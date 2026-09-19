"""amicus_review_changes_dry_run / amicus_delegate_dry_run: free previews that fail where the
paid call would, and the deprecated amicus_dry_run alias (#98)."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server
from amicus.registry import BackendRegistry
from amicus.schemas.envelope import META_ALWAYS_PRESENT
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY
from amicus.schemas.results import ToolDeprecation
from amicus.tools import _meta


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.co")
    _git(r, "config", "user.name", "t")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


async def _schema(c, name):
    return next(t for t in await c.list_tools() if t.name == name).output_schema


async def test_dry_run_previews_the_review(app, repo):
    async with Client(app) as c:
        clean = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "codex", "workspace_root": str(repo)}
        )
        body = clean.structured_content
        assert (
            body["ok"] is True and body["would_call_model"] is False and body["prompt_bytes"] == 0
        )
        (repo / "a.py").write_text("x = 2\n")
        res = await c.call_tool(
            "amicus_review_changes_dry_run",
            {
                "backend": "codex",
                "workspace_root": str(repo),
                "reasoning_effort": "high",
                "backend_options": {"isolation": "ignore-rules"},
            },
        )
        body = res.structured_content
        Draft202012Validator(await _schema(c, "amicus_review_changes_dry_run")).validate(body)
        # #47: a free tool's success is as sparse on the wire as a delivered paid one, on
        # both carriers, and the always-present core survives the slimming.
        for env in (body, json.loads(res.content[0].text)):
            assert [k for k, v in env["meta"].items() if v is None] == []
            assert set(env["meta"]) >= set(META_ALWAYS_PRESENT)
    assert (
        body["would_call_model"] is True
        and body["prompt_bytes"] > 100
        and body["scope"] == "working_tree"
    )
    assert body["context_summary"]["files_changed"] == 1 and body["backend_options"] == {
        "isolation": "ignore-rules"
    }
    assert body["reasoning_effort"] == "high" and body["workspace"]["cwd"] == str(repo.resolve())
    assert any("amicus_review_changes_async" in w for w in body["warnings"])
    assert body["meta"]["backend"] == "codex"


async def test_dry_run_fails_where_the_review_would(app, tmp_path, repo):
    async with Client(app) as c:
        bad_base = await c.call_tool(
            "amicus_review_changes_dry_run",
            {"backend": "codex", "workspace_root": str(repo), "scope": "branch", "base": "nope"},
            raise_on_error=False,
        )
        no_ws = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "codex"}, raise_on_error=False
        )
        claude = await c.call_tool(
            "amicus_review_changes_dry_run",
            {"backend": "claude", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert bad_base.structured_content["error"]["code"] == "invalid_base"
    assert no_ws.structured_content["error"]["code"] == "invalid_workspace_root"
    body = claude.structured_content
    # The `repo` fixture has no uncommitted changes, so this mirrors the codex clean-repo
    # case above (test_dry_run_previews_the_review), which also asserts would_call_model is False.
    assert body["ok"] is True and body["would_call_model"] is False
    assert body["backend_options"] == {
        "config_mode": "inherit",
        "access": "readonly",
        "max_budget_usd": 1.0,
    }


async def test_dry_run_discloses_what_the_paid_review_would_omit(app, repo):
    """#65: the free preview says, machine-readably, that an untracked file would be skipped,
    both when the tracked change would still be reviewed and when nothing else would be."""
    (repo / "notes_untracked.py").write_text("n = 1\n")
    omitted = {
        "status": "partial",
        "untracked_files_detected": 1,
        "untracked_files_included": 0,
        "untracked_files_omitted": 1,
        "omission_reasons": ["untracked_omitted"],
        "redaction": None,
    }
    async with Client(app) as c:
        schema = await _schema(c, "amicus_review_changes_dry_run")
        untracked_only = (
            await c.call_tool(
                "amicus_review_changes_dry_run", {"backend": "codex", "workspace_root": str(repo)}
            )
        ).structured_content
        (repo / "a.py").write_text("x = 2\n")
        with_tracked = (
            await c.call_tool(
                "amicus_review_changes_dry_run", {"backend": "codex", "workspace_root": str(repo)}
            )
        ).structured_content
        included = (
            await c.call_tool(
                "amicus_review_changes_dry_run",
                {"backend": "codex", "workspace_root": str(repo), "untracked": "include"},
            )
        ).structured_content
    for body in (untracked_only, with_tracked, included):
        Draft202012Validator(schema).validate(body)
    assert untracked_only["would_call_model"] is False and untracked_only["coverage"] == omitted
    assert with_tracked["would_call_model"] is True and with_tracked["coverage"] == omitted
    assert included["coverage"] == {
        "status": "complete",
        "untracked_files_detected": 1,
        "untracked_files_included": 1,
        "untracked_files_omitted": 0,
        "omission_reasons": [],
        "redaction": None,
    }


async def test_dry_run_reports_the_input_cap_the_paid_call_enforces(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AMICUS_MAX_INPUT_BYTES", "123457")
    settings = config.settings()
    capped = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    async with Client(capped) as c:
        body = (
            await c.call_tool(
                "amicus_review_changes_dry_run", {"backend": "codex", "workspace_root": str(repo)}
            )
        ).structured_content
    assert body["max_input_bytes"] == 123457


async def test_delegate_dry_run(app, repo, tmp_path):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate_dry_run",
            {"backend": "codex", "task": "do it", "workspace_root": str(repo)},
        )
        body = res.structured_content
        Draft202012Validator(await _schema(c, "amicus_delegate_dry_run")).validate(body)
        plain = await c.call_tool(
            "amicus_delegate_dry_run",
            {"backend": "codex", "task": "do it", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    assert (
        body["ok"] is True
        and body["task_bytes"] == 5
        and body["worktree"] == {"baseline_ref": head, "prefix": "amicus-wt-"}
    )
    assert body["backend_options"] == {"isolation": "inherit"} and body["warnings"] == []
    assert plain.structured_content["error"]["code"] == "not_a_git_repo"


async def _marked(app):
    """(tool records carrying a marker, resource/template metas, capability rows by detail)."""
    async with Client(app) as c:
        listed = {t.name: t for t in await c.list_tools()}
        others = [r.meta for r in await c.list_resources()]
        others += [t.meta for t in await c.list_resource_templates()]
        rows = {
            detail: (
                await c.call_tool("amicus_capabilities", {"detail": detail})
            ).structured_content["tool_details"]
            for detail in ("summary", "full")
        }
    marked = {
        name: tool.meta[LIFECYCLE_META_KEY]["deprecation"]
        for name, tool in listed.items()
        if "deprecation" in tool.meta[LIFECYCLE_META_KEY]
    }
    return listed, marked, others, rows


async def test_no_tool_is_deprecated_since_the_alias_was_removed(app):
    """`amicus_dry_run` was the one deprecated tool (#98), removed at the end of its window
    (#204, ADR 0028). [9.deprecation-marker] makes a marker's PRESENCE the signal, so with
    nothing deprecated no record and no capability row carries one. The test below is what
    makes this absence mean something."""
    listed, marked, others, rows = await _marked(app)
    assert "amicus_dry_run" not in listed and "amicus_review_changes_dry_run" in listed
    assert marked == {}
    assert all("deprecation" not in meta[LIFECYCLE_META_KEY] for meta in others)
    for detail, detail_rows in rows.items():
        assert len(detail_rows) == len(listed), detail
        assert [row["name"] for row in detail_rows if row["deprecation"]] == [], detail


async def test_a_deprecated_tool_would_carry_its_marker_on_both_carriers(monkeypatch, tmp_path):
    """The mechanism outlives its first user. [9.tier-metadata] puts the marker on the record
    itself and the same facts in the capability summary, so exactly one tool record and one
    capability row carry it, identically, on both detail levels, and no resource or template
    does. The entry is synthetic, and the app is built AFTER it is patched in, because a
    record's lifecycle _meta is fixed at registration."""
    monkeypatch.setitem(
        _meta.DEPRECATED_TOOLS,
        "amicus_models",
        ToolDeprecation(
            since="0.5.0",
            removal_at_or_after="0.7.0",
            replaced_by="amicus_backends",
            migration="m",
        ),
    )
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    settings = config.settings()
    patched = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    listed, marked, others, rows = await _marked(patched)
    assert set(marked) == {"amicus_models"}
    marker = marked["amicus_models"]
    assert set(marker) == {"since", "removal_at_or_after", "replaced_by", "migration"}
    assert all("deprecation" not in meta[LIFECYCLE_META_KEY] for meta in others)
    for detail, detail_rows in rows.items():
        carried = {row["name"]: row["deprecation"] for row in detail_rows if row["deprecation"]}
        assert carried == {"amicus_models": marker}, detail
    assert marker["replaced_by"] in listed and marker["replaced_by"] not in marked


async def test_a_marker_without_a_successor_keeps_its_null_on_the_capability_row(app, monkeypatch):
    """[9.deprecation-marker] fixes the field set, so a deprecation with no successor carries
    `replaced_by: null` on its amicus_capabilities row as well as in its lifecycle _meta.
    Nothing ships deprecated today, so this patches in an entry with no successor: the row is
    dumped with exclude_none, which would drop the null, and only the restamp from the
    lifecycle source keeps it (Copilot's review of #99)."""
    monkeypatch.setitem(
        _meta.DEPRECATED_TOOLS,
        "amicus_models",
        ToolDeprecation(
            since="0.3.0", removal_at_or_after="0.5.0", replaced_by=None, migration="m"
        ),
    )
    expected = {
        "since": "0.3.0",
        "removal_at_or_after": "0.5.0",
        "replaced_by": None,
        "migration": "m",
    }
    async with Client(app) as c:
        for detail in ("summary", "full"):
            rows = (
                await c.call_tool("amicus_capabilities", {"detail": detail})
            ).structured_content["tool_details"]
            row = next(r for r in rows if r["name"] == "amicus_models")
            assert row["deprecation"] == expected, detail
