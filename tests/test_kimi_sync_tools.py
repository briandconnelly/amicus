"""End to end, spend-free: MCP client → sync tool → detached worker → real kimi plugin →
the fake kimi executable → delivered envelope, a recoverable job record, and the discovery
tools reading the same fake."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.orchestration.isolation import NO_REPO_WARNING
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_kimi, monkeypatch):
    monkeypatch.setenv("AMICUS_KIMI_BIN", str(fake_kimi))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_KIMI_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_KIMI_PROMPT_FILE", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in (
        "FAKE_KIMI_EXIT",
        "FAKE_KIMI_STDERR",
        "FAKE_KIMI_ANSWER",
        "FAKE_KIMI_WRITE",
        "FAKE_KIMI_EVENTS",
        "FAKE_KIMI_PROVIDERS",
        "FAKE_KIMI_SLEEP",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    return server.create_app(settings, registry)


def _runs(tmp_path):
    """The recorded `--prompt` invocations (probes excluded)."""
    if not (tmp_path / "argv.jsonl").exists():
        return []
    lines = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    return [line for line in lines if "--prompt" in line["argv"]]


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


async def test_consult_end_to_end_in_a_repo(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "why?",
                "workspace_root": str(repo),
                "instructions_append": "Focus on locking.",
                "model": "k3",
                "reasoning_effort": "high",
            },
        )
    body = res.structured_content
    assert res.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    meta = body["meta"]
    assert meta["backend"] == "kimi" and meta["job_id"] and meta["session_id"] == "session-fake"
    assert meta.get("usage") is None and meta["backend_details"] == {"isolation": "inherit"}
    assert NO_REPO_WARNING not in meta.get("security_warnings", []) and meta["model"] == "k3"
    assert meta["instructions_append"]["bytes"] == 17 and "Focus on locking" not in json.dumps(body)
    prompt = (tmp_path / "prompt.txt").read_text()
    assert "Focus on locking." in prompt and "## Question\nwhy?" in prompt
    assert "TestHost" in prompt and "# Required output format" in prompt
    [run] = _runs(tmp_path)
    argv = run["argv"]
    assert argv[0] == "--prompt" and "--agent-file" in argv and "--add-dir" not in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--model") + 1] == "k3"
    assert run["env"] == {
        "KIMI_MODEL_THINKING_EFFORT": "high",
        "KIMI_MODEL_OUTPUT_FORMAT": "stream-json",
    }
    store = lifecycle.job_store(config.settings())
    rec, payload = store.result_payload(str(repo.resolve()), meta["job_id"])
    assert rec["status"] == "done" and rec["extra"]["backend"] == "kimi"
    spec_text = (store._job_dir(str(repo.resolve()), meta["job_id"]) / "spec.json").read_text()
    assert "why?" not in spec_text
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert listed.strip().count("\n") == 0


async def test_consult_outside_a_repo_runs_in_an_empty_dir_with_a_warning(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(tmp_path)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["meta"]["security_warnings"] == [NO_REPO_WARNING]


async def test_review_and_delegate_end_to_end(app, tmp_path, repo, monkeypatch):
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes", {"backend": "kimi", "workspace_root": str(repo)}
        )
    body = review.structured_content
    assert body["ok"] is True
    assert body["review_status"] == "completed" and body["verdict"] == "pass"
    assert body["meta"]["context_summary"]["files_changed"] == 1
    monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "Added b.py.")
    async with Client(app) as c:
        delegate = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = delegate.structured_content
    assert body["ok"] is True and body["summary"] == "Added b.py."
    assert "+written by fake kimi" in body["diff"]
    assert not (repo / "b.py").exists() and (repo / "a.py").read_text() == "x = 2\n"
    argv = _runs(tmp_path)[-1]["argv"]
    assert "--agent-file" not in argv and "write your final answer to" in argv[1]


async def test_empty_answer_is_an_empty_response_error(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert res.is_error is True
    err = res.structured_content["error"]
    assert err["code"] == "empty_response" and err["backend"] == "kimi"
    assert res.structured_content["meta"]["command_exit_code"] == 0


async def test_unsupported_effort_is_refused_before_spend(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "q",
                "workspace_root": str(repo),
                "model": "k3",
                "reasoning_effort": "xhigh",
            },
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_reasoning_effort" and err["temporary"] is False
    assert err["details"]["allowed_values"] == ["low", "medium", "high"]
    assert err["repair"]["tool"] == "amicus_models"
    assert _runs(tmp_path) == []
    async with Client(app) as c:
        ok = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "q",
                "workspace_root": str(repo),
                "model": "unlisted",
                "reasoning_effort": "xhigh",
            },
        )
    assert ok.structured_content["ok"] is True  # fail open on an unlisted alias
    assert _runs(tmp_path)[-1]["env"]["KIMI_MODEL_THINKING_EFFORT"] == "xhigh"


async def test_failures_are_classified_and_recorded(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_EXIT", "1")
    monkeypatch.setenv("FAKE_KIMI_STDERR", "Error: 401 Unauthorized")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "backend_auth_required" and err["backend"] == "kimi"
    assert err["temporary"] is False
    assert res.structured_content["meta"]["command_exit_code"] == 1
    monkeypatch.setenv(
        "FAKE_KIMI_STDERR",
        'error: failed to run prompt: Model "zz" is not configured in config.toml.',
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo), "model": "zz"},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_model" and err["details"]["field"] == "model"
    assert err["repair"]["tool"] == "amicus_models"


async def test_discovery_tools_read_the_fake(app, tmp_path, repo):
    async with Client(app) as c:
        backends = await c.call_tool("amicus_backends", {"backend": "kimi"})
        models = await c.call_tool("amicus_models", {"backend": "kimi"})
        dry = await c.call_tool("amicus_dry_run", {"backend": "kimi", "workspace_root": str(repo)})
    [entry] = backends.structured_content["backends"]
    assert entry["available"] is True and entry["status"] == {
        "installed": True,
        "version": "0.41.0",
        "authenticated": True,
        "warnings": [],
    }
    assert entry["features"] == ["delegate", "empty_response_detection", "model_validation"]
    assert {o["name"] for o in entry["options"]} == {"isolation"}
    assert entry["options"][0]["allowed_values"] == ["inherit", "ignore-skills"]
    assert "handshake" in entry["carriers"] and "Kimi provider" in entry["egress"]
    body = models.structured_content
    assert body["source"] == "live" and [m["slug"] for m in body["models"]] == ["k3"]
    assert body["models"][0]["supported_reasoning_efforts"] == ["low", "medium", "high"]
    assert dry.structured_content["ok"] is True
    assert dry.structured_content["meta"]["backend"] == "kimi"
    assert _runs(tmp_path) == []
