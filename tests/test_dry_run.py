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
from amicus.tools._resolve import FREE_MARKER


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
        "access": "toolless",
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


def _without(body: dict, *keys: str) -> dict:
    return {k: v for k, v in body.items() if k not in keys}


def _with_tool_const(schema: dict, name: str) -> dict:
    swapped = json.loads(json.dumps(schema))
    for branch in swapped.get("anyOf", [swapped]):
        if "tool" in branch.get("properties", {}):
            branch["properties"]["tool"]["const"] = name
    return swapped


async def test_the_deprecated_alias_is_the_same_preview_under_its_old_name(app, repo):
    """#98, [9.rename]: amicus_dry_run keeps its arguments and its result for the window.
    Only `tool` differs, and it names the tool the caller actually called."""
    (repo / "a.py").write_text("x = 2\n")
    args = {"backend": "codex", "workspace_root": str(repo), "reasoning_effort": "high"}
    async with Client(app) as c:
        listed = {t.name: t for t in await c.list_tools()}
        new = (await c.call_tool("amicus_review_changes_dry_run", args)).structured_content
        old = (await c.call_tool("amicus_dry_run", args)).structured_content
        bad = await c.call_tool("amicus_dry_run", {"backend": "codex"}, raise_on_error=False)
    alias, replacement = listed["amicus_dry_run"], listed["amicus_review_changes_dry_run"]
    assert alias.input_schema == replacement.input_schema
    assert alias.annotations == replacement.annotations
    # The outputSchemas differ in exactly the `tool` const; the inequality is the known
    # positive that makes the swapped comparison mean something.
    assert alias.output_schema != replacement.output_schema
    assert alias.output_schema == _with_tool_const(replacement.output_schema, "amicus_dry_run")
    assert (new["tool"], old["tool"]) == ("amicus_review_changes_dry_run", "amicus_dry_run")
    Draft202012Validator(replacement.output_schema).validate(new)
    Draft202012Validator(alias.output_schema).validate(old)
    assert new["would_call_model"] is True
    assert _without(old, "tool", "meta") == _without(new, "tool", "meta")
    assert _without(old["meta"], "request_id") == _without(new["meta"], "request_id")
    assert bad.structured_content["error"]["code"] == "invalid_workspace_root"


async def test_only_the_alias_is_deprecated_and_its_marker_names_a_live_tool(app):
    """[9.tier-metadata] puts the marker on the record itself and the same facts in the
    capability summary; [9.deprecation-marker] makes its presence the signal. So exactly one
    tool record and one capability row carry it, identically, on both detail levels, and
    no resource or template does. The description repeats it because a host may never show
    _meta to the model."""
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
    assert set(marked) == {"amicus_dry_run"}
    marker = marked["amicus_dry_run"]
    assert set(marker) == {"since", "removal_at_or_after", "replaced_by", "migration"}
    assert all("deprecation" not in meta[LIFECYCLE_META_KEY] for meta in others)
    for detail, detail_rows in rows.items():
        assert len(detail_rows) == len(listed), detail
        carried = {row["name"]: row["deprecation"] for row in detail_rows if row["deprecation"]}
        assert carried == {"amicus_dry_run": marker}, detail
    assert marker["replaced_by"] in listed and marker["replaced_by"] not in marked
    description = listed["amicus_dry_run"].description or ""
    assert description.startswith(FREE_MARKER)
    assert f"Deprecated: use {marker['replaced_by']}" in description
    assert marker["removal_at_or_after"] in description


async def test_a_marker_without_a_successor_keeps_its_null_on_the_capability_row(app, monkeypatch):
    """[9.deprecation-marker] fixes the field set, so a deprecation with no successor carries
    `replaced_by: null` on its amicus_capabilities row as well as in its lifecycle _meta.
    The shipped alias has a successor, so this patches in one that has none: the row is
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
