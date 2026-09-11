"""End to end, spend-free: MCP client → sync tool → detached worker → real claude plugin →
the fake claude executable → delivered envelope, a recoverable job record, and the discovery
tools reading the same fake. The rule-18 carrier assertions live here: the caller's text is on
stdin, never on argv."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.backends.claude import adversarial
from amicus.jobs import lifecycle
from amicus.registry import BackendRegistry

STRUCTURED_CRITIQUE = json.dumps(
    {
        "summary": "The plan ignores retries",
        "verdict": "concerns",
        "confidence": "high",
        "findings": [],
        "questions": ["What happens on a dropped message?"],
        "assumptions": [],
        "next_steps": ["decide the retry policy"],
    }
)


@pytest.fixture
def app(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("AMICUS_CLAUDE_BIN", str(fake_claude))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_CLAUDE_PROMPT_FILE", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    for key in (
        "FAKE_CLAUDE_EXIT",
        "FAKE_CLAUDE_STDERR",
        "FAKE_CLAUDE_ANSWER",
        "FAKE_CLAUDE_STDOUT",
        "FAKE_CLAUDE_SLEEP",
        "FAKE_CLAUDE_AUTH_EXIT",
        "FAKE_CLAUDE_HELP_OMIT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    return server.create_app(settings, registry)


def _runs(tmp_path):
    """The recorded `-p` invocations (probes excluded)."""
    if not (tmp_path / "argv.jsonl").exists():
        return []
    lines = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    return [line for line in lines if "-p" in line["argv"]]


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


async def test_consult_end_to_end_with_the_stdin_carrier(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "why?",
                "workspace_root": str(repo),
                "instructions_append": "Focus on locking.",
                "model": "sonnet",
                "reasoning_effort": "low",
                "backend_options": {"access": "readonly", "max_budget_usd": 0.5},
            },
        )
    body = res.structured_content
    assert res.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    meta = body["meta"]
    assert meta["backend"] == "claude" and meta["job_id"] and meta["session_id"] == "sess-fake"
    assert meta["usage"]["cost_usd"] == 0.0123 and meta["usage"]["cached_input_tokens"] == 10
    assert meta["backend_details"] == {
        "config_mode": "inherit",
        "access": "readonly",
        "max_budget_usd": 0.5,
    }
    assert meta["model"] == "sonnet" and meta["reasoning_effort"] == "low"
    assert meta["instructions_append"]["bytes"] == 17 and "Focus on locking" not in json.dumps(body)
    assert meta.get("security_warnings", []) == []
    prompt = (tmp_path / "prompt.txt").read_text()
    assert "Focus on locking." in prompt and "## Question\nwhy?" in prompt
    assert prompt.startswith("You are assisting another coding agent")
    assert adversarial.critic_stance("TestHost") in prompt and "# Required output format" in prompt
    [run] = _runs(tmp_path)
    argv = run["argv"]
    assert "Focus on locking." not in " ".join(argv) and "why?" not in " ".join(argv)
    assert argv[argv.index("--append-system-prompt") + 1] == adversarial.CRITIC_GUARDRAILS
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "low" and "--strict-mcp-config" in argv
    assert run["has_api_key"] is False and run["cwd"] == str(repo.resolve())
    store = lifecycle.job_store(config.settings())
    rec, payload = store.result_payload(str(repo.resolve()), meta["job_id"])
    assert rec["status"] == "done" and rec["extra"]["backend"] == "claude"
    spec_text = (store._job_dir(str(repo.resolve()), meta["job_id"]) / "spec.json").read_text()
    assert "why?" not in spec_text and "Focus on locking" not in spec_text


async def test_consult_outside_a_repo_runs_directly(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "claude", "question": "q", "workspace_root": str(tmp_path)},
        )
    body = res.structured_content
    assert body["ok"] is True and body["meta"]["security_warnings"] == []
    assert _runs(tmp_path)[0]["cwd"] == str(tmp_path.resolve())


async def test_review_and_adversarial_end_to_end(app, tmp_path, repo, monkeypatch):
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes",
            {"backend": "claude", "workspace_root": str(repo), "focus": "types"},
        )
        monkeypatch.setenv("FAKE_CLAUDE_ANSWER", STRUCTURED_CRITIQUE)
        critique = await c.call_tool(
            "amicus_adversarial_review",
            {
                "backend": "claude",
                "target": "Ship without retries.",
                "evidence": "The queue is at-most-once.",
                "scope": "working_tree",
                "workspace_root": str(repo),
            },
        )
        plain = await c.call_tool(
            "amicus_adversarial_review",
            {
                "backend": "claude",
                "target": "Ship without retries.",
                "workspace_root": str(tmp_path),
            },
        )
    rb = review.structured_content
    assert rb["ok"] is True and rb["review_status"] == "completed" and rb["verdict"] == "unknown"
    assert "focused" in rb["summary"] and rb["meta"]["context_summary"]["files_changed"] == 1
    cb = critique.structured_content
    assert cb["ok"] is True and cb["tool"] == "amicus_adversarial_review"
    assert cb["verdict"] == "concerns" and cb["review_status"] == "completed"
    assert cb["context_summary"]["files_changed"] == 1 and cb["questions"]
    pb = plain.structured_content
    assert pb["ok"] is True and pb["context_summary"] is None and pb["meta"]["job_id"]
    prompt = (tmp_path / "prompt.txt").read_text()  # the last run's prompt
    assert "## Target (untrusted data)\nShip without retries." in prompt
    assert "## Attached changes" not in prompt
    assert "independent critique of TestHost's work" in prompt
    argvs = [r["argv"] for r in _runs(tmp_path)]
    assert len(argvs) == 3 and all("Ship without retries." not in " ".join(a) for a in argvs)
    assert "--safe-mode" not in argvs[0]
    for argv, body in zip(argvs[1:], (cb, pb), strict=True):
        assert "--safe-mode" in argv
        assert body["meta"]["backend_details"]["config_mode"] == "safe"
        assert adversarial.OUTPUT_GUARDRAILS in argv[argv.index("--append-system-prompt") + 1]


@pytest.mark.parametrize("explicit", [None, "inherit", "bare"])
async def test_adversarial_async_mode_survives_job_handoff(app, tmp_path, monkeypatch, explicit):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("FAKE_CLAUDE_ANSWER", STRUCTURED_CRITIQUE)
    options = {} if explicit is None else {"config_mode": explicit}
    expected = explicit or "safe"
    async with Client(app) as c:
        body = (
            await c.call_tool(
                "amicus_adversarial_review_async",
                {
                    "backend": "claude",
                    "target": "Ship without retries.",
                    "workspace_root": str(tmp_path),
                    "backend_options": options,
                },
            )
        ).structured_content
    assert body["ok"] is True
    assert body["meta"]["backend_details"]["config_mode"] == expected
    store = lifecycle.job_store(server.state_of(app).settings)
    async with asyncio.timeout(15):
        while True:
            record = store.status(str(tmp_path), body["job_id"])
            assert record is not None
            if record["status"] != "running":
                break
            await asyncio.sleep(0.02)
    _, result = store.result_payload(str(tmp_path), body["job_id"])
    assert result["ok"] is True
    assert result["meta"]["backend_details"]["config_mode"] == expected
    [run] = _runs(tmp_path)
    assert ("--safe-mode" in run["argv"]) == (expected == "safe")
    assert ("--bare" in run["argv"]) == (expected == "bare")


async def test_adversarial_with_an_empty_scope_is_not_run_without_spawning(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_adversarial_review",
            {
                "backend": "claude",
                "target": "t",
                "scope": "working_tree",
                "workspace_root": str(repo),
            },
        )
    body = res.structured_content
    assert body["ok"] is True and body["review_status"] == "not_run"
    assert body["verdict"] == "unknown"
    assert _runs(tmp_path) == []


async def test_zero_exit_failure_envelopes_are_errors(app, tmp_path, monkeypatch):
    budget = json.dumps(
        {
            "type": "result",
            "subtype": "error_max_budget_usd",
            "is_error": True,
            "result": "Budget stop threshold reached.",
            "session_id": "sess-b",
            "total_cost_usd": 0.004,
            "usage": {"input_tokens": 20, "output_tokens": 0},
        }
    )
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", budget)
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "claude", "question": "q", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert res.is_error is True and body["ok"] is False
    err = body["error"]
    assert err["code"] == "budget_exceeded" and err["temporary"] is False
    assert err["backend"] == "claude"
    assert err["repair"]["next_step"] == "reduce_input"
    assert "max_budget_usd" in err["repair"]["alternative"]
    assert err["details"]["field"] == "backend_options.max_budget_usd"
    assert body["meta"]["command_exit_code"] == 0
    assert body["meta"]["usage"]["cost_usd"] == 0.004
    assert body["meta"]["session_id"] == "sess-b"
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", "not json")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "claude", "question": "q", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    assert res.structured_content["error"]["code"] == "invalid_json"


async def test_timeout_is_not_retryable_and_points_at_a_new_job(
    pinned_claude_bin, monkeypatch, tmp_path
):
    """The first repair_overrides entry, through the loop in-process (the sync deadline floor
    is 10 s, so a real timed-out fake would make this suite slow; the differential's `timeout`
    case pins the code/temporary pair against the sibling, this pins amicus's repair)."""
    from pontonier.core.runtime import TIMED_OUT
    from tests.support import claudefixtures as cf

    from amicus.orchestration import run as run_mod
    from amicus.request import RunSpec

    plugin, _ = cf.make_backend()
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        cf.scripted_run_async(stdout="", stderr=TIMED_OUT, exit_code=-9, timed_out=True),
    )
    spec = RunSpec(
        backend="claude",
        kind="consult",
        tool="amicus_consult",
        cwd=str(tmp_path),
        workspace_source="param",
        roots_source="client",
        host_name="TestHost",
        timeout_seconds=10,
        options={"config_mode": "inherit", "access": "toolless", "max_budget_usd": 1.0},
        question="q",
    )
    out = await run_mod.run_request(spec, plugin)
    err = out["error"]
    assert out["ok"] is False and err["code"] == "timeout" and err["temporary"] is False
    assert err["retry_after_ms"] is None
    assert err["repair"]["next_step"] == "start_new_job"
    assert err["repair"].get("tool") is None
    assert "amicus_consult_async" in err["repair"]["alternative"]
    assert "MAY" in err["message"]


async def test_hook_warning_reaches_meta(app, tmp_path, repo):
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text('{"hooks": {"PreToolUse": []}}')
    async with Client(app) as c:
        inherit = await c.call_tool(
            "amicus_consult", {"backend": "claude", "question": "q", "workspace_root": str(repo)}
        )
        safe = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "q",
                "workspace_root": str(repo),
                "backend_options": {"config_mode": "safe"},
            },
        )
    [warning] = inherit.structured_content["meta"]["security_warnings"]
    assert "hooks" in warning and ".claude/settings.json" in warning
    assert safe.structured_content["meta"]["security_warnings"] == []
    assert "--safe-mode" in _runs(tmp_path)[1]["argv"]


async def test_bare_without_a_key_is_refused_pre_spend(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "q",
                "workspace_root": str(tmp_path),
                "backend_options": {"config_mode": "bare"},
            },
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "api_key_missing" and err["temporary"] is False
    assert err["repair"]["next_step"] == "correct_config"
    assert err["repair"]["tool"] == "amicus_backends"
    assert _runs(tmp_path) == []


async def test_bare_with_a_key_keeps_it_and_login_modes_strip_it(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    async with Client(app) as c:
        await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "q",
                "workspace_root": str(tmp_path),
                "backend_options": {"config_mode": "bare"},
            },
        )
        await c.call_tool(
            "amicus_consult",
            {"backend": "claude", "question": "q", "workspace_root": str(tmp_path)},
        )
    bare, inherit = _runs(tmp_path)
    assert bare["has_api_key"] is True and "--bare" in bare["argv"]
    assert inherit["has_api_key"] is False and "--bare" not in inherit["argv"]


async def test_invalid_effort_and_budget_are_refused_pre_spend(app, tmp_path):
    async with Client(app) as c:
        effort = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "q",
                "workspace_root": str(tmp_path),
                "reasoning_effort": "ultra",
            },
            raise_on_error=False,
        )
        budget = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "q",
                "workspace_root": str(tmp_path),
                "backend_options": {"max_budget_usd": 50},
            },
            raise_on_error=False,
        )
    e = effort.structured_content["error"]
    assert e["code"] == "invalid_reasoning_effort"
    assert e["details"]["allowed_values"] == ["low", "medium", "high", "xhigh", "max"]
    assert e["repair"]["tool"] == "amicus_models"
    b = budget.structured_content["error"]
    assert b["code"] == "invalid_arguments"
    assert b["details"]["field"] == "backend_options.max_budget_usd"
    assert _runs(tmp_path) == []


async def test_discovery_reads_the_fake(app, monkeypatch):
    async with Client(app) as c:
        backends = (await c.call_tool("amicus_backends", {"backend": "claude"})).structured_content
        models = (await c.call_tool("amicus_models", {"backend": "claude"})).structured_content
        dry = await c.call_tool(
            "amicus_dry_run", {"backend": "claude", "workspace_root": "/tmp"}, raise_on_error=False
        )
    entry = backends["backends"][0]
    assert entry["id"] == "claude" and entry["available"] is True
    assert entry["status"]["installed"] is True
    assert entry["status"]["authenticated"] is True
    assert entry["status"]["version"] == "2.1.263 (Claude Code)"
    assert entry["status"]["warnings"] == []
    assert set(entry["features"]) == {"adversarial_review", "usage_accounting"}
    assert entry["effects"]["paid_calls_destructive"] is True
    by_name = {o["name"]: o for o in entry["options"]}
    assert by_name["config_mode"]["allowed_values"] == ["inherit", "scoped", "safe", "bare"]
    assert by_name["config_mode"]["default"] is None  # The default varies by verb.
    assert by_name["max_budget_usd"]["default"] == 1.0
    assert "stdin" in entry["carriers"] and "Anthropic" in entry["egress"]
    assert models["source"] == "static" and models["models"][0]["slug"] == "opus"
    assert dry.structured_content["error"]["code"] in (
        "not_a_git_repo",
        "invalid_workspace_root",
        "workspace_outside_roots",
    )
    monkeypatch.setenv("FAKE_CLAUDE_AUTH_EXIT", "1")
    monkeypatch.setenv("FAKE_CLAUDE_HELP_OMIT", "--safe-mode")
    async with Client(app) as c:
        drifted = (await c.call_tool("amicus_backends", {"backend": "claude"})).structured_content
    status = drifted["backends"][0]["status"]
    assert status["authenticated"] is False
    assert any("--safe-mode" in w for w in status["warnings"])


async def test_delegate_is_feature_gated_and_never_spawns(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {"backend": "claude", "task": "t", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert res.structured_content["error"]["code"] == "feature_unsupported"
    assert _runs(tmp_path) == []


async def test_dry_run_previews_the_review_without_spawning(app, tmp_path, repo):
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_dry_run",
            {"backend": "claude", "workspace_root": str(repo)},
        )
    body = res.structured_content
    assert body["ok"] is True
    assert body["would_call_model"] is True
    assert body["meta"]["backend_details"]["config_mode"] == "inherit"
    assert body["prompt_bytes"] > 0
    assert body["prompt_bytes"] >= len(adversarial.critic_stance("TestHost").encode("utf-8"))
    assert _runs(tmp_path) == []
