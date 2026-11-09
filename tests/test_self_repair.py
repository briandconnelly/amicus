"""#444: a `correct_arguments` repair names the tool that failed, on every path that builds an
envelope, through the real MCP call path: the call boundary, the pre-spend checks, the review
gather (sync, dry run, _async through amicus_job_result, and a keyed replay), and no repair
echoes a prompt input (rule 18)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.orchestration import gitdiff
from amicus.registry import BackendRegistry

# A literal of this test's own (rule 18): it must reach no repair, message or mirror.
SENTINEL = "SENTINEL-444-do-not-echo"


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    for key in ("FAKE_CODEX_EXIT", "FAKE_CODEX_STDERR", "FAKE_CODEX_ANSWER", "FAKE_CODEX_SLEEP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "t@t.co"),
        ("config", "user.name", "t"),
    ):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)
    (r / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=r, check=True, capture_output=True)
    return r


def _error(res):
    """The error, after checking the result is an MCP error whose text mirrors it."""
    assert res.is_error is True
    body = res.structured_content
    assert json.loads(res.content[0].text) == body
    return body["error"]


async def _call(c, tool, args):
    return _error(await c.call_tool(tool, args, raise_on_error=False))


async def test_a_boundary_failure_on_a_lookup_tool_names_that_tool(app):
    """The issue's first row: amicus_models is a lookup tool, and its own invalid backend
    used to be completed as a lookup, find no backend, and lose its tool."""
    async with Client(app) as c:
        err = await _call(c, "amicus_models", {"backend": "gemini"})
    assert err["code"] == "invalid_arguments"
    assert err["repair"]["next_step"] == "correct_arguments"
    assert err["repair"]["tool"] == "amicus_models" and "arguments" not in err["repair"]


async def test_a_boundary_failure_on_a_job_tool_names_that_tool(app, tmp_path):
    async with Client(app) as c:
        err = await _call(
            c,
            "amicus_job_status",
            {"job_id": "a" * 32, "workspace_root": str(tmp_path), "wait_seconds": 99},
        )
        cursor = await _call(
            c, "amicus_job_list", {"workspace_root": str(tmp_path), "cursor": "not-a-cursor"}
        )
        missing = await _call(
            c, "amicus_job_status", {"job_id": "a" * 32, "workspace_root": str(tmp_path)}
        )
    assert err["code"] == "invalid_arguments" and err["repair"]["tool"] == "amicus_job_status"
    assert cursor["code"] == "invalid_arguments" and cursor["repair"]["tool"] == "amicus_job_list"
    # job_not_found is a lookup, not a self-repair, and keeps its complete call.
    assert missing["code"] == "job_not_found"
    assert missing["repair"]["tool"] == "amicus_job_list"
    assert missing["repair"]["arguments"] == {"workspace_root": str(tmp_path)}


async def test_a_rejected_backend_option_on_a_dry_run_names_the_dry_run(app, repo):
    async with Client(app) as c:
        err = await _call(
            c,
            "amicus_review_changes_dry_run",
            {
                "backend": "codex",
                "workspace_root": str(repo),
                "backend_options": {"access": "readonly"},
            },
        )
    assert err["code"] == "invalid_arguments"
    assert err["repair"]["tool"] == "amicus_review_changes_dry_run"


# (case, the arguments that make the gather refuse, the code)
_GATHER_REFUSALS = [
    ("base", {"scope": "branch", "base": "no-such-ref"}, "invalid_base"),
    ("commit", {"scope": "commit", "commit": "no-such-commit"}, "invalid_commit"),
    ("paths", {"paths": ["../outside"]}, "invalid_paths"),
]


@pytest.mark.parametrize(
    ("case", "args", "code"), _GATHER_REFUSALS, ids=[c[0] for c in _GATHER_REFUSALS]
)
@pytest.mark.parametrize("tool", ["amicus_review_changes_dry_run", "amicus_review_changes"])
async def test_a_gather_refusal_names_the_tool_that_gathered(app, repo, tool, case, args, code):
    """The review gather runs in process for a dry run and in the worker for the paid
    call; both name the tool that was called. The focus is a prompt input and is echoed
    nowhere."""
    (repo / "a.py").write_text("x = 2\n")
    call = {"backend": "codex", "workspace_root": str(repo), "focus": SENTINEL, **args}
    async with Client(app) as c:
        res = await c.call_tool(tool, call, raise_on_error=False)
    err = _error(res)
    assert err["code"] == code, case
    assert err["repair"]["next_step"] == "correct_arguments"
    assert err["repair"]["tool"] == tool and "arguments" not in err["repair"], case
    assert SENTINEL not in json.dumps(res.structured_content)
    assert SENTINEL not in res.content[0].text


async def _job_result(c, store, cwd, job_id):
    deadline = time.monotonic() + 15
    while store.status(str(cwd), job_id)["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    return await c.call_tool(
        "amicus_job_result", {"job_id": job_id, "workspace_root": str(cwd)}, raise_on_error=False
    )


async def test_an_async_refusal_stored_by_the_worker_names_the_async_tool(app, repo):
    """The repair is built where the envelope is, before the job stores it, so a fetch
    returns the _async tool's own repair, not the job-read tool's."""
    store = lifecycle.job_store(server.state_of(app).settings)
    call = {
        "backend": "codex",
        "workspace_root": str(repo),
        "scope": "commit",
        "commit": "no-such-commit",
        "focus": SENTINEL,
    }
    async with Client(app) as c:
        started = (await c.call_tool("amicus_review_changes_async", call)).structured_content
        res = await _job_result(c, store, repo, started["job_id"])
    err = _error(res)
    assert err["code"] == "invalid_commit"
    assert err["repair"]["tool"] == "amicus_review_changes_async"
    assert SENTINEL not in json.dumps(res.structured_content)


async def test_a_keyed_replay_carries_the_same_self_repair(app, repo):
    call = {
        "backend": "codex",
        "workspace_root": str(repo),
        "scope": "commit",
        "commit": "no-such-commit",
        "idempotency_key": "k-444",
    }
    async with Client(app) as c:
        first = await _call(c, "amicus_review_changes", call)
        replay = await _call(c, "amicus_review_changes", call)
    assert first["code"] == replay["code"] == "invalid_commit"
    assert first["repair"] == replay["repair"]
    assert replay["repair"]["tool"] == "amicus_review_changes"


async def test_an_unknown_scope_is_refused_at_the_boundary(app, repo):
    """`scope` is a closed literal, so the call boundary refuses an unknown one before the
    gather's defensive invalid_scope can."""
    async with Client(app) as c:
        err = await _call(
            c,
            "amicus_review_changes_dry_run",
            {"backend": "codex", "workspace_root": str(repo), "scope": "everything"},
        )
    assert err["code"] == "invalid_arguments" and err["details"]["field"] == "scope"
    assert err["repair"]["tool"] == "amicus_review_changes_dry_run"


async def test_the_defensive_invalid_scope_names_the_tool_too(app, repo, monkeypatch):
    def refuse(*_a, **_k):
        raise gitdiff.InvalidScopeError("invalid scope: injected")

    monkeypatch.setattr(gitdiff, "gather_diff", refuse)
    async with Client(app) as c:
        err = await _call(
            c, "amicus_review_changes_dry_run", {"backend": "codex", "workspace_root": str(repo)}
        )
    assert err["code"] == "invalid_scope"
    assert err["repair"]["tool"] == "amicus_review_changes_dry_run"
    assert err["details"]["allowed_values"]


async def test_a_workspace_error_still_carries_no_repair(app, tmp_path):
    async with Client(app) as c:
        err = await _call(
            c,
            "amicus_review_changes_dry_run",
            {"backend": "codex", "workspace_root": str(tmp_path / "nowhere")},
        )
    assert err["code"] == "invalid_workspace_root" and "repair" not in err


@pytest.mark.parametrize(
    ("tool", "field"),
    [("amicus_consult", "question"), ("amicus_delegate_dry_run", "task")],
)
async def test_a_boundary_repair_never_echoes_a_prompt_input(app, repo, tool, field):
    """An unknown key's correction is unique, but the surviving prompt input cannot be
    echoed, so the repair names the tool and carries no arguments."""
    call = {"backend": "codex", "workspace_root": str(repo), field: SENTINEL, "bogus": 1}
    async with Client(app) as c:
        res = await c.call_tool(tool, call, raise_on_error=False)
    err = _error(res)
    assert err["code"] == "invalid_arguments"
    assert err["repair"]["tool"] == tool and "arguments" not in err["repair"]
    assert SENTINEL not in json.dumps(res.structured_content)
    assert SENTINEL not in res.content[0].text
