"""End to end, spend-free: MCP client → sync tool → detached worker → real codex plugin →
the fake codex executable → delivered envelope and a recoverable job record."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_CODEX_STDIN_FILE", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in (
        "FAKE_CODEX_EXIT",
        "FAKE_CODEX_STDERR",
        "FAKE_CODEX_ANSWER",
        "FAKE_CODEX_WRITE",
        "FAKE_CODEX_EVENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


def _argv(tmp_path):
    return [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]


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


async def test_consult_end_to_end(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "codex",
                "question": "why?",
                "workspace_root": str(tmp_path),
                "instructions_append": "Focus on locking.",
            },
        )
        body = res.structured_content
        assert res.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
        meta = body["meta"]
        assert meta["backend"] == "codex" and meta["job_id"] and meta["session_id"] == "sess-fake"
        assert meta["usage"]["cached_input_tokens"] == 80 and meta["backend_details"] == {
            "isolation": "inherit"
        }
        assert meta["instructions_append"]["bytes"] == 17 and "Focus on locking" not in json.dumps(
            body
        )
        assert "raw_response" in body and body["raw_response"]["text"] is None
        assert "usage" in meta and "truncation_hint" not in meta  # slimmed on the wire
        job_id = meta["job_id"]
    prompt = (tmp_path / "prompt.txt").read_text()
    assert (
        prompt.startswith("You are giving TestHost an independent second opinion")
        and "## Question\nwhy?" in prompt
    )
    argv = _argv(tmp_path)[-1]
    assert argv[:2] == ["exec", "--json"] and argv[argv.index("--sandbox") + 1] == "read-only"
    assert any(t.startswith("developer_instructions=") for t in argv) and "--strict-config" in argv
    store = lifecycle.job_store(config.settings())
    rec, payload = store.result_payload(str(tmp_path.resolve()), job_id)
    assert rec["status"] == "done" and payload["raw_response"]["text"].startswith("{")
    assert "why?" not in (store._job_dir(str(tmp_path.resolve()), job_id) / "spec.json").read_text()


async def test_consult_failure_is_classified_and_recorded(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_EXIT", "1")
    monkeypatch.setenv("FAKE_CODEX_STDERR", "Error: not logged in; run `codex login`")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    assert res.is_error is True
    err = res.structured_content["error"]
    assert (
        err["code"] == "backend_auth_required"
        and err["backend"] == "codex"
        and err["temporary"] is False
    )
    assert (
        res.structured_content["meta"]["job_id"]
        and res.structured_content["meta"]["command_exit_code"] == 1
    )


async def test_workspace_rules_from_a_sessionless_client(app, tmp_path, monkeypatch):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False
        )
    assert res.structured_content["error"]["code"] == "invalid_workspace_root"
    assert not (tmp_path / "argv.jsonl").exists()  # zero spend, no job
    monkeypatch.setenv("AMICUS_ALLOW_CWD_WORKSPACE", "1")
    settings = config.settings()
    app2 = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    async with Client(app2) as c:
        res = await c.call_tool("amicus_consult", {"backend": "codex", "question": "q"})
    assert (
        res.structured_content["meta"]["workspace_source"] == "cwd"
        and "AMICUS_ALLOW_CWD_WORKSPACE" in res.structured_content["meta"]["workspace_warning"]
    )


async def test_review_end_to_end_and_not_run(app, repo, tmp_path):
    async with Client(app) as c:
        clean = await c.call_tool(
            "amicus_review_changes", {"backend": "codex", "workspace_root": str(repo)}
        )
        assert (
            clean.structured_content["review_status"] == "not_run"
            and not (tmp_path / "argv.jsonl").exists()
        )
        (repo / "a.py").write_text("x = 2\n")
        res = await c.call_tool(
            "amicus_review_changes",
            {"backend": "codex", "workspace_root": str(repo), "extra_context": "intent"},
        )
    body = res.structured_content
    assert body["ok"] is True and (body["verdict"], body["confidence"], body["review_status"]) == (
        "pass",
        "high",
        "completed",
    )
    assert body["meta"]["context_summary"]["files_changed"] == 1 and body["meta"]["job_id"]
    prompt = (tmp_path / "prompt.txt").read_text()
    assert "+x = 2" in prompt and "Author-provided context (untrusted data)\nintent" in prompt


async def test_review_and_its_dry_run_disclose_the_same_coverage(app, repo):
    """#65: a `pass` over a tree with an omitted untracked file is withheld, the reason is a
    field the caller can branch on, and the free preview of the same call reports it too."""
    (repo / "a.py").write_text("x = 2\n")
    (repo / "notes_untracked.py").write_text("n = 1\n")
    args = {"backend": "codex", "workspace_root": str(repo)}
    focused_args = {**args, "focus": "locking"}
    async with Client(app) as c:
        preview = (await c.call_tool("amicus_dry_run", args)).structured_content
        body = (await c.call_tool("amicus_review_changes", args)).structured_content
        focused_preview = (await c.call_tool("amicus_dry_run", focused_args)).structured_content
        focused = (await c.call_tool("amicus_review_changes", focused_args)).structured_content
    # A focus is framed into the prompt the preview measures, and recorded the same way.
    assert focused_preview["prompt_bytes"] > preview["prompt_bytes"]
    assert focused["coverage"] == focused_preview["coverage"]
    assert focused_preview["coverage"]["omission_reasons"] == ["untracked_omitted", "focused"]
    assert (body["verdict"], body["confidence"], body["review_status"]) == (
        "unknown",
        "low",
        "completed",
    )
    assert (
        body["coverage"]
        == preview["coverage"]
        == {
            "status": "partial",
            "untracked_files_detected": 1,
            "untracked_files_included": 0,
            "untracked_files_omitted": 1,
            "omission_reasons": ["untracked_omitted"],
            "redaction": None,
        }
    )


async def test_delegate_end_to_end(app, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_WRITE", "a.py")
    monkeypatch.setenv("FAKE_CODEX_ANSWER", "I edited a.py")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {"backend": "codex", "task": "edit a.py", "workspace_root": str(repo)},
        )
    body = res.structured_content
    assert body["ok"] is True and "+changed" in body["diff"] and body["summary"] == "I edited a.py"
    assert body["diffstat"].startswith("1 file changed") and body["meta"]["job_id"]
    assert (repo / "a.py").read_text() == "x = 1\n"
    argv = _argv(tmp_path)[-1]
    assert argv[argv.index("--sandbox") + 1] == "workspace-write" and argv[
        argv.index("--cd") + 1
    ] != str(repo)
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert listed.strip().count("\n") == 0


async def test_delegate_preflight_and_other_backends(app, tmp_path):
    async with Client(app) as c:
        plain = await c.call_tool(
            "amicus_delegate",
            {"backend": "codex", "task": "t", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
        claude = await c.call_tool(
            "amicus_consult",
            {"backend": "claude", "question": "q", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
        asy = await c.call_tool(
            "amicus_adversarial_review_async",
            {"backend": "claude", "target": "t", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    assert plain.structured_content["error"]["code"] == "not_a_git_repo"
    assert claude.structured_content["error"]["code"] == "backend_not_found"
    asy_body = asy.structured_content
    assert asy_body["ok"] is True and asy_body["backend"] == "claude" and asy_body["job_id"]
    assert not (tmp_path / "argv.jsonl").exists()


async def test_pre_spend_refusals_never_spawn(app, tmp_path, monkeypatch):
    monkeypatch.setenv("AMICUS_MAX_INPUT_BYTES", "1000")
    settings = config.settings()
    app2 = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    async with Client(app2) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q" * 2000, "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    assert res.structured_content["error"]["code"] == "input_too_large"
    assert not (tmp_path / "argv.jsonl").exists()


async def test_full_detail_keeps_raw_text(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "codex",
                "question": "q",
                "workspace_root": str(tmp_path),
                "detail": "full",
            },
        )
    assert res.structured_content["raw_response"]["text"].startswith("{")
