"""amicus_review_changes_dry_run / amicus_delegate_dry_run: free previews that fail where the
paid call would, and the deprecation marker's carriers, which outlive the amicus_dry_run
alias they were built for (#98, removed by #204)."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server, tools
from amicus.registry import BackendRegistry
from amicus.schemas.envelope import META_ALWAYS_PRESENT
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY
from amicus.schemas.results import ToolDeprecation
from amicus.tools import _meta
from amicus.tools._resolve import FREE_MARKER, PAID_MARKER


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


async def test_delegate_dry_run_names_a_workspace_that_vanished_after_resolution(
    app, repo, monkeypatch
):
    """#248: prepare_run's own delegate preflight (`worktree.ensure_repo_with_head`) can
    pass while the directory still exists, and the directory can then vanish before
    `worktree.plan()`'s later git calls run inside the dry-run tool itself; that is
    invalid_workspace_root, reason not_a_directory for an explicit workspace_root, not
    worktree_error. Patches `_git_ok` (used by plan() after its own
    `_ensure_repo_with_head` check, but never by the preflight) rather than plan() or
    `_ensure_repo_with_head` itself, so this exercises the fix under test —
    worktree.plan() translating the vanished cwd to WorkspaceMissingError, and dry_run.py
    mapping that to invalid_workspace_root — rather than the earlier, already-fixed
    preflight path."""
    import shutil

    from amicus.tools import dry_run

    def vanish(repo_path, *_args, **_kwargs):
        shutil.rmtree(repo_path)
        raise FileNotFoundError(2, "No such file or directory", repo_path)

    monkeypatch.setattr(dry_run.worktree, "_git_ok", vanish)
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate_dry_run",
            {"backend": "codex", "task": "do it", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_workspace_root"
    assert err["details"]["reason"] == "not_a_directory"
    assert "repair" not in err


async def test_delegate_dry_run_maps_not_a_git_repo_found_after_the_preflight(
    app, repo, monkeypatch
):
    """#248: the preflight's own `worktree.ensure_repo_with_head` check can pass, and
    `worktree.plan()`'s later `_git_ok` call can still raise `NotAGitRepoError` (e.g. a
    race that turns the directory into a non-repo between the two checks); the dry-run
    tool's own `except worktree.NotAGitRepoError` clause — added alongside the
    WorkspaceMissingError one in this fix, but previously untested because
    `test_delegate_dry_run`'s `not_a_git_repo` case is caught by the earlier preflight
    and never reaches this clause — must map it to not_a_git_repo with
    details.field=workspace_root, not let it escape as an unstructured error."""
    from amicus.tools import dry_run

    def not_a_repo(*_args, **_kwargs):
        raise dry_run.worktree.NotAGitRepoError("workspace is not a git repository")

    monkeypatch.setattr(dry_run.worktree, "_git_ok", not_a_repo)
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate_dry_run",
            {"backend": "codex", "task": "do it", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "not_a_git_repo"
    assert err["details"]["field"] == "workspace_root"


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


def _registration_problems(table, descriptions, groups):
    """ADR 0028's two promises for any deprecated tool: it sits last in its cost group, and
    its description leads with the deprecation, because a host may never show `_meta` to the
    model. Plain data in, so the rule can be shown to fire without a deprecated tool."""
    problems = []
    for name, deprecation in table.items():
        group = next((g for g in groups if name in g), None)
        if group is None or name not in descriptions:
            problems.append(f"{name}: not registered")
            continue
        live = [n for n in group if n not in table]
        if group[: len(live)] != tuple(live):
            problems.append(f"{name}: not last in its cost group")
        lead = "Deprecated: " + (
            f"use {deprecation.replaced_by}" if deprecation.replaced_by else "no replacement"
        )
        before, found, _ = descriptions[name].partition(lead)
        if not found or before.strip() not in ("", FREE_MARKER, PAID_MARKER):
            problems.append(f"{name}: description does not lead with {lead!r}")
    return problems


async def test_a_deprecated_tool_sits_last_in_its_group_and_says_so_first(app):
    """Nothing is deprecated since #204, so the rule is first shown to pass a well-placed
    entry and to fail a misplaced one, an unannounced one and an unregistered one; only then
    is its silence on the real table worth anything."""
    async with Client(app) as c:
        real = {t.name: t.description for t in await c.list_tools()}
    groups = (tools.ACTIVE_TOOLS, tools.FREE_TOOLS, tools.JOB_TOOLS)
    entry = ToolDeprecation(
        since="0.5.0", removal_at_or_after="0.7.0", replaced_by="amicus_backends", migration="m"
    )
    good = {**real, "amicus_old": f"{FREE_MARKER} Deprecated: use amicus_backends. Lists backends."}
    good_groups = (tools.ACTIVE_TOOLS, (*tools.FREE_TOOLS, "amicus_old"), tools.JOB_TOOLS)
    assert _registration_problems({"amicus_old": entry}, good, good_groups) == []
    first = (tools.ACTIVE_TOOLS, ("amicus_old", *tools.FREE_TOOLS), tools.JOB_TOOLS)
    assert _registration_problems({"amicus_old": entry}, good, first) == [
        "amicus_old: not last in its cost group"
    ]
    quiet = {
        **real,
        "amicus_old": f"{FREE_MARKER} Lists backends. Deprecated: use amicus_backends.",
    }
    assert len(_registration_problems({"amicus_old": entry}, quiet, good_groups)) == 1
    assert _registration_problems({"amicus_old": entry}, real, groups) == [
        "amicus_old: not registered"
    ]
    assert _registration_problems(_meta.DEPRECATED_TOOLS, real, groups) == []


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


async def test_every_focus_states_its_cap_and_points_long_text_to_extra_context(app, repo):
    # Issue #268: the cap is in the prose, not only maxLength, and an over-long focus is
    # told where the supporting detail belongs on every tool that declares focus.
    async with Client(app) as c:
        focused = [t for t in await c.list_tools() if "focus" in t.input_schema["properties"]]
        res = await c.call_tool(
            "amicus_review_changes_dry_run",
            {"backend": "codex", "workspace_root": str(repo), "focus": "x" * 501},
            raise_on_error=False,
        )
    assert len(focused) == 5
    for tool in focused:
        props = tool.input_schema["properties"]
        assert "at most 500 characters" in props["focus"]["description"], tool.name
        assert "extra_context" in props["focus"]["description"], tool.name
        assert "extra_context" in props, tool.name
    alternative = res.structured_content["error"]["repair"]["alternative"]
    assert "keep focus to a short concern (at most 500 characters)" in alternative
    assert "move the supporting detail to extra_context" in alternative


# --- #439: a dry run runs the backend's pre-spend validation -------------------------------

PI_MODEL = "openrouter/moonshotai/kimi-k3"
_NO_THINKING_MODELS = (
    "provider    model                     context  max-out  thinking  images\n"
    "openrouter  moonshotai/kimi-k3        1.0M     943.7K   no        yes\n"
)


def _pi_registry(
    tmp_path, fake_pi, monkeypatch, *, model: str | None = PI_MODEL, models: str | None = None
):
    """(app, registry) on the fake pi, as tests/test_pi_sync_tools.py builds it. The catalog
    is set before the registry loads: its conformance check validates, and the adapter
    remembers each model's catalog row for the probe TTL."""
    from amicus.jobs import lifecycle

    monkeypatch.setenv("AMICUS_PI_BIN", str(fake_pi))
    if model is None:
        monkeypatch.delenv("AMICUS_PI_MODEL", raising=False)
    else:
        monkeypatch.setenv("AMICUS_PI_MODEL", model)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_PI_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_PI_STDIN_FILE", str(tmp_path / "stdin.txt"))
    for key in ("FAKE_PI_EXIT", "FAKE_PI_EVENTS", "FAKE_PI_AUTH", "FAKE_PI_MODELS"):
        monkeypatch.delenv(key, raising=False)
    if models is not None:
        monkeypatch.setenv("FAKE_PI_MODELS", models)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    return server.create_app(settings, registry), registry


def _pi_runs(tmp_path):
    """The fake pi's model invocations (`-p` runs); its free probes are not recorded."""
    path = tmp_path / "argv.jsonl"
    if not path.exists():
        return []
    return [a for a in map(json.loads, path.read_text().splitlines()) if "-p" in a]


def _reason_field(details):
    """The field of a backend detail that ErrorDetail could not hold whole: pi's invalid_model
    adds `catalog`, so render_failure folds the pairs into `reason` ("field=model ...")."""
    reason = details.get("reason") or ""
    return next((t.removeprefix("field=") for t in reason.split() if t.startswith("field=")), None)


# (case, the env/args it needs, the code and field both the dry run and the paid tool return)
_PI_REFUSALS = [
    ("missing_model", {"model": None}, {}, "invalid_arguments", "model"),
    (
        "unlisted_model",
        {},
        {"model": "openrouter/nobody/nothing"},
        "invalid_model",
        "model",
    ),
    (
        "unsupported_effort",
        {"models": _NO_THINKING_MODELS},
        {"reasoning_effort": "high"},
        "invalid_reasoning_effort",
        "reasoning_effort",
    ),
]
_PAIRS = [
    ("amicus_review_changes_dry_run", "amicus_review_changes", {}),
    ("amicus_delegate_dry_run", "amicus_delegate", {"task": "add b.py"}),
]


@pytest.mark.parametrize(("dry", "paid", "extra"), _PAIRS, ids=["review", "delegate"])
@pytest.mark.parametrize(
    ("case", "setup", "args", "code", "field"), _PI_REFUSALS, ids=[c[0] for c in _PI_REFUSALS]
)
async def test_a_pi_dry_run_refuses_exactly_where_the_paid_call_does(
    tmp_path, repo, fake_pi, monkeypatch, dry, paid, extra, case, setup, args, code, field
):
    """#439: the refusal travels the real paid path (MCP -> worker -> the fake pi), and the
    dry run returns the same code and field, with no model run on either side."""
    app, _ = _pi_registry(
        tmp_path,
        fake_pi,
        monkeypatch,
        model=setup.get("model", PI_MODEL),
        models=setup.get("models"),
    )
    (repo / "a.py").write_text("x = 2\n")  # a review with nothing to send never validates
    call = {"backend": "pi", "workspace_root": str(repo), **extra, **args}
    async with Client(app) as c:
        dry_res = await c.call_tool(dry, call, raise_on_error=False)
        paid_res = await c.call_tool(paid, call, raise_on_error=False)
    dry_err = dry_res.structured_content["error"]
    paid_err = paid_res.structured_content["error"]
    assert dry_res.is_error is True and paid_res.is_error is True
    assert dry_err["code"] == paid_err["code"] == code, case
    assert dry_err["details"] == paid_err["details"], case
    assert field in (dry_err["details"].get("field"), _reason_field(dry_err["details"])), case
    assert dry_err["backend"] == "pi" and json.loads(dry_res.content[0].text) == (
        dry_res.structured_content
    )
    assert _pi_runs(tmp_path) == []


async def test_a_valid_pi_model_previews_and_the_model_runs_are_recorded(
    tmp_path, repo, fake_pi, monkeypatch
):
    """The positive control for the refusal tests above: a listed model previews ok, and the
    `-p` recorder they read empty does see a paid run."""
    app, _ = _pi_registry(tmp_path, fake_pi, monkeypatch)
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "pi", "workspace_root": str(repo)}
        )
        delegate = await c.call_tool(
            "amicus_delegate_dry_run",
            {"backend": "pi", "task": "add b.py", "workspace_root": str(repo)},
        )
        assert _pi_runs(tmp_path) == []
        await c.call_tool(
            "amicus_consult", {"backend": "pi", "question": "why?", "workspace_root": str(repo)}
        )
    assert review.structured_content["ok"] is True
    assert review.structured_content["would_call_model"] is True
    assert review.structured_content["model"] == PI_MODEL
    assert delegate.structured_content["ok"] is True
    assert len(_pi_runs(tmp_path)) == 1


async def test_a_clean_tree_pi_preview_without_a_model_does_not_validate(
    tmp_path, repo, fake_pi, monkeypatch
):
    """A review with nothing to send never reaches the backend on the paid path, so its
    preview says so and does not turn the missing model into a refusal."""
    app, registry = _pi_registry(tmp_path, fake_pi, monkeypatch, model=None)
    backend = registry.get("pi").backend
    calls = []
    real = backend.validate_request

    def spy(request):
        calls.append(request)
        return real(request)

    monkeypatch.setattr(backend, "validate_request", spy)
    async with Client(app) as c:
        clean = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "pi", "workspace_root": str(repo)}
        )
        assert calls == []
        (repo / "a.py").write_text("x = 2\n")
        dirty = await c.call_tool(
            "amicus_review_changes_dry_run",
            {"backend": "pi", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = clean.structured_content
    assert body["ok"] is True and body["would_call_model"] is False and body["model"] is None
    # The spy is live: the same preview over a dirty tree reaches it and is refused.
    assert len(calls) == 1
    assert dirty.structured_content["error"]["code"] == "invalid_arguments"


async def test_a_refused_dry_run_starts_nothing(tmp_path, repo, fake_pi, monkeypatch):
    """The dry call alone: no worktree, no backend.prepare, no job record, no model run."""
    from amicus.jobs import lifecycle
    from amicus.orchestration import isolation

    app, registry = _pi_registry(tmp_path, fake_pi, monkeypatch)
    backend = registry.get("pi").backend

    def forbidden(*_a, **_k):
        raise AssertionError("a dry run must not reach this")

    monkeypatch.setattr(backend, "prepare", forbidden)
    monkeypatch.setattr(lifecycle, "start_job", forbidden)
    monkeypatch.setattr(isolation, "select_site", forbidden)
    monkeypatch.setattr(dry_run_mod().worktree, "create", forbidden, raising=False)
    (repo / "a.py").write_text("x = 2\n")
    call = {"backend": "pi", "workspace_root": str(repo), "model": "openrouter/nobody/nothing"}
    async with Client(app) as c:
        review = await c.call_tool("amicus_review_changes_dry_run", call, raise_on_error=False)
        delegate = await c.call_tool(
            "amicus_delegate_dry_run", {**call, "task": "add b.py"}, raise_on_error=False
        )
    assert review.structured_content["error"]["code"] == "invalid_model"
    assert delegate.structured_content["error"]["code"] == "invalid_model"
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert len(worktrees) == 1
    state = tmp_path / "state"
    assert not [p for p in state.rglob("*") if p.name in ("meta.json", "result.json")]
    assert _pi_runs(tmp_path) == []


def dry_run_mod():
    from amicus.tools import dry_run

    return dry_run


def _app(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


async def test_a_codex_dry_run_refuses_a_relative_codex_home(tmp_path, repo, monkeypatch):
    app = _app(tmp_path, monkeypatch, CODEX_HOME="relative/codex-home")
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes_dry_run",
            {"backend": "codex", "workspace_root": str(repo)},
            raise_on_error=False,
        )
        delegate = await c.call_tool(
            "amicus_delegate_dry_run",
            {"backend": "codex", "task": "do it", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert review.structured_content["error"]["code"] == "user_config_rejected"
    assert delegate.structured_content["error"]["code"] == "user_config_rejected"


async def test_a_claude_dry_run_refuses_bare_mode_without_a_key(tmp_path, repo, monkeypatch):
    app = _app(tmp_path, monkeypatch, ANTHROPIC_API_KEY=None)
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_review_changes_dry_run",
            {
                "backend": "claude",
                "workspace_root": str(repo),
                "backend_options": {"config_mode": "bare"},
            },
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "api_key_missing"
    assert err["details"]["field"] == "backend_options.config_mode"


async def test_a_kimi_dry_run_refuses_an_unknown_effort(tmp_path, repo, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes_dry_run",
            {"backend": "kimi", "workspace_root": str(repo), "reasoning_effort": "turbo"},
            raise_on_error=False,
        )
        delegate = await c.call_tool(
            "amicus_delegate_dry_run",
            {
                "backend": "kimi",
                "task": "do it",
                "workspace_root": str(repo),
                "reasoning_effort": "turbo",
            },
            raise_on_error=False,
        )
    assert review.structured_content["error"]["code"] == "invalid_reasoning_effort"
    assert delegate.structured_content["error"]["code"] == "invalid_reasoning_effort"


_PARITY_FIELDS = (
    "kind",
    "prompt",
    "schema",
    "timeout_seconds",
    "model",
    "reasoning_effort",
    "access",
    "config_mode",
    "isolation",
    "budget_usd",
    "instructions_append",
)
_PARITY_CASES = [
    (
        "codex",
        "amicus_review_changes_dry_run",
        "amicus_review_changes",
        {
            "model": "gpt-test",
            "reasoning_effort": "high",
            "instructions_append": "Be terse.",
            "backend_options": {"isolation": "ignore-rules"},
        },
    ),
    (
        "claude",
        "amicus_review_changes_dry_run",
        "amicus_review_changes",
        {
            "model": "opus-test",
            "reasoning_effort": "high",
            "backend_options": {"config_mode": "safe", "max_budget_usd": 2.5},
        },
    ),
    (
        "codex",
        "amicus_delegate_dry_run",
        "amicus_delegate",
        {
            "task": "add b.py",
            "model": "gpt-test",
            "reasoning_effort": "low",
            "backend_options": {"isolation": "ignore-rules"},
        },
    ),
]


@pytest.mark.parametrize(
    ("backend", "dry", "paid", "args"),
    _PARITY_CASES,
    ids=["codex-review", "claude-review", "codex-delegate"],
)
async def test_a_dry_run_validates_the_request_the_paid_call_would(
    tmp_path, repo, monkeypatch, backend, dry, paid, args
):
    """The paid path runs in a worker process, so it is driven here in process: run_sync is
    replaced by run_request itself, and both sides hand their RunRequest to a recorder that
    refuses, so nothing runs."""
    from amicus.jobs import lifecycle
    from amicus.orchestration import run as run_mod
    from amicus.sdk.backend.protocol import ClassifiedFailure

    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    app = server.create_app(settings, registry)
    seen = []

    def record(request):
        seen.append(request)
        return ClassifiedFailure(code="invalid_arguments", detail="recorded")

    monkeypatch.setattr(registry.get(backend).backend, "validate_request", record)

    async def in_process(_store, spec, _meta, plugin, **_kw):
        return await run_mod.run_request(spec, plugin)

    monkeypatch.setattr(lifecycle, "run_sync", in_process)
    (repo / "a.py").write_text("x = 2\n")
    call = {"backend": backend, "workspace_root": str(repo), **args}
    async with Client(app) as c:
        dry_res = await c.call_tool(dry, call, raise_on_error=False)
        paid_res = await c.call_tool(paid, call, raise_on_error=False)
    assert dry_res.structured_content["error"]["message"] == "recorded"
    assert paid_res.structured_content["error"]["message"] == "recorded"
    dry_req, paid_req = seen
    for field in _PARITY_FIELDS:
        assert getattr(dry_req, field) == getattr(paid_req, field), field
    assert dry_req.model == args["model"] and dry_req.reasoning_effort == args["reasoning_effort"]
