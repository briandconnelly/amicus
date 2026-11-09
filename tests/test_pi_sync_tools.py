"""End to end, spend-free: MCP client -> sync tool -> detached worker -> real pi plugin ->
the fake pi executable -> delivered envelope."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.registry import BackendRegistry

MODEL = "openrouter/moonshotai/kimi-k3"


@pytest.fixture
def app(tmp_path, fake_pi, monkeypatch):
    monkeypatch.setenv("AMICUS_PI_BIN", str(fake_pi))
    monkeypatch.setenv("AMICUS_PI_MODEL", MODEL)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_PI_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_PI_STDIN_FILE", str(tmp_path / "stdin.txt"))
    for key in (
        "FAKE_PI_EXIT",
        "FAKE_PI_STDERR",
        "FAKE_PI_ANSWER",
        "FAKE_PI_WRITE",
        "FAKE_PI_EVENTS",
        "FAKE_PI_AUTH",
        "FAKE_PI_MODELS",
        "FAKE_PI_VERSION",
        "FAKE_PI_HELP_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    return server.create_app(settings, registry)


def _invocations(tmp_path):
    path = tmp_path / "argv.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _runs(tmp_path):
    return [argv for argv in _invocations(tmp_path) if "-p" in argv]


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


async def test_consult_returns_the_answer_with_usage_and_keeps_the_prompt_off_argv(
    app, tmp_path, repo
):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "pi",
                "question": "why is the sky blue?",
                "workspace_root": str(repo),
                "instructions_append": "Focus on locking.",
            },
        )
    body = res.structured_content
    assert res.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    meta = body["meta"]
    assert meta["backend"] == "pi" and meta["job_id"]
    assert meta["usage"] is not None
    stdin = (tmp_path / "stdin.txt").read_text()
    assert "why is the sky blue?" in stdin and "Focus on locking." in stdin
    [argv] = _runs(tmp_path)
    assert "why is the sky blue?" not in json.dumps(argv)
    assert "Focus on locking." not in json.dumps(argv)
    assert argv[argv.index("--model") + 1] == MODEL


async def test_review_changes_returns_structured_findings(app, repo, monkeypatch):
    (repo / "a.py").write_text("x = 2\n")
    monkeypatch.setenv(
        "FAKE_PI_ANSWER",
        json.dumps(
            {
                "summary": "One issue",
                "verdict": "fail",
                "confidence": "high",
                "findings": [
                    {
                        "title": "Bad constant",
                        "severity": "high",
                        "file": "a.py",
                        "line": 1,
                        "evidence": "x = 2",
                    }
                ],
                "questions": [],
                "assumptions": [],
                "next_steps": [],
            }
        ),
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_review_changes", {"backend": "pi", "workspace_root": str(repo)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["review_status"] == "completed"
    assert body["meta"]["backend"] == "pi" and body["verdict"] == "fail"
    [finding] = body["findings"]
    assert finding["title"] == "Bad constant" and finding["severity"] == "high"
    assert finding["file"] == "a.py"


async def test_delegate_returns_the_diff_of_the_written_file(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_PI_WRITE", "b.py")
    monkeypatch.setenv("FAKE_PI_ANSWER", "Added b.py.")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate", {"backend": "pi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["summary"] == "Added b.py."
    assert "+written by fake pi" in body["diff"]
    assert not (repo / "b.py").exists()
    [argv] = _runs(tmp_path)
    assert "add b.py" not in json.dumps(argv)
    assert "add b.py" in (tmp_path / "stdin.txt").read_text()


async def test_a_call_with_no_model_is_refused_before_any_run(app, tmp_path, repo, monkeypatch):
    monkeypatch.delenv("AMICUS_PI_MODEL")
    settings = config.settings()  # the fixture's app captured the model at build time
    app = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "pi", "question": "why?", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert res.is_error is True and body["ok"] is False
    err = body["error"]
    assert err["backend"] == "pi" and err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "model" and "AMICUS_PI_MODEL" in err["message"]
    # The success tests positively exercise `_runs`, so an empty list is a real absence.
    assert _runs(tmp_path) == []


async def test_an_error_stop_reason_at_exit_zero_is_an_auth_failure(
    app, tmp_path, repo, monkeypatch
):
    assistant = {
        "role": "assistant",
        "content": [],
        "stopReason": "error",
        "errorMessage": "401 Unauthorized: invalid api key",
    }
    events = [
        {"type": "agent_start"},
        {"type": "message_end", "message": assistant},
        {"type": "agent_end", "messages": [assistant]},
    ]
    monkeypatch.setenv("FAKE_PI_EVENTS", "".join(json.dumps(e) + "\n" for e in events))
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "pi", "question": "why?", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert res.is_error is True and body["ok"] is False
    assert body["error"]["code"] == "backend_auth_required"
    assert body["error"]["backend"] == "pi"
    assert len(_runs(tmp_path)) == 1  # the failure came from the stream, not a pre-spawn refusal


async def test_a_length_stop_withholds_the_cut_off_answer(app, tmp_path, repo, monkeypatch):
    """A structured answer cut off by the output-token limit can still parse; it must not be
    delivered as an ok result."""
    answer = json.dumps({"summary": "Looks fine", "verdict": "pass", "confidence": "high"})
    assistant = {
        "role": "assistant",
        "content": [{"type": "text", "text": answer}],
        "stopReason": "length",
    }
    events = [
        {"type": "agent_start"},
        {"type": "message_end", "message": assistant},
        {"type": "agent_end", "messages": [assistant]},
    ]
    monkeypatch.setenv("FAKE_PI_EVENTS", "".join(json.dumps(e) + "\n" for e in events))
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "pi", "question": "why?", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert res.is_error is True and body["ok"] is False
    assert body["error"]["code"] == "answer_unavailable"
    assert body["error"]["details"]["reason"] == "stream_truncated"
    assert "Looks fine" not in json.dumps(body)
    assert len(_runs(tmp_path)) == 1


async def test_an_unauthenticated_pi_refuses_before_any_run_and_is_reported(
    app, tmp_path, repo, monkeypatch
):
    monkeypatch.setenv(
        "FAKE_PI_AUTH", '{"status":"not_ready","provider":"openrouter","authType":"api_key"}'
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "pi", "question": "why?", "workspace_root": str(repo)},
            raise_on_error=False,
        )
        backends = await c.call_tool("amicus_backends", {"backend": "pi"})
    body = res.structured_content
    assert res.is_error is True and body["ok"] is False
    assert body["error"]["code"] == "backend_auth_required" and body["error"]["backend"] == "pi"
    # The success tests positively exercise `_runs`, so an empty list is a real absence.
    assert _runs(tmp_path) == []
    [entry] = backends.structured_content["backends"]
    assert entry["status"]["authenticated"] is False


async def test_pi_absent_from_path_is_backend_not_found(tmp_path, repo, monkeypatch):
    """No AMICUS_PI_BIN and no pi on PATH: the call reports backend_not_found, not a model
    error: the spawn of the bare `pi` literal fails as binary-missing."""
    import shutil

    bindir = tmp_path / "bin"
    bindir.mkdir()
    git = shutil.which("git")
    assert git is not None
    (bindir / "git").symlink_to(git)
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.delenv("AMICUS_PI_BIN")
    monkeypatch.setenv("AMICUS_PI_MODEL", MODEL)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    app = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "pi", "question": "why?", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert res.is_error is True and body["ok"] is False
    assert body["error"]["code"] == "backend_not_found" and body["error"]["backend"] == "pi"
