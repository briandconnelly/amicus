"""Argv construction (constant text only), per-mode env scrubbing, the free probes, and the
classifier: envelope branch first, sanitize before truncate, timeout not retryable."""

from __future__ import annotations

import json
import subprocess

import pytest
from pontonier.conventions.preflight import FlagSupport
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun
from tests.support import claudefixtures as cf

from amicus.backends.claude import cli, contract

ALL = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | {"--effort", "--disallowed-tools"}),
    help_parsed=True,
)
UNPARSED = FlagSupport(supported=frozenset(), help_parsed=False)
SECRET = "sk-" + "c" * 32


def _build(**kw):
    base = dict(
        claude_bin="/CLAUDE",
        config_mode="inherit",
        access="toolless",
        system_prompt="GUARDRAILS",
        max_budget_usd=1.0,
        effort="xhigh",
        model=None,
        flag_support=ALL,
    )
    base.update(kw)
    return cli.build_command(**base)


def test_config_mode_flags_match_the_sibling_byte_for_byte():
    assert cli.config_mode_flags("inherit") == [
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]
    assert cli.config_mode_flags("scoped") == [
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-session-persistence",
    ]
    assert cli.config_mode_flags("safe") == [
        "--safe-mode",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]
    assert cli.config_mode_flags("bare") == [
        "--bare",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]
    with pytest.raises(ValueError, match="config_mode"):
        cli.config_mode_flags("yolo")


def test_access_flags():
    assert cli.access_flags("toolless") == ["--tools", ""]
    assert cli.access_flags("readonly") == [
        "--tools",
        "Read,Grep,Glob",
        "--disallowed-tools",
        "Edit,Write,NotebookEdit,Bash",
    ]
    with pytest.raises(ValueError, match="access"):
        cli.access_flags("full")


def test_build_command_default_shape_carries_only_constant_text():
    cmd, dropped = _build()
    assert dropped == []
    assert cmd[:5] == ["/CLAUDE", "-p", "--output-format", "json", "--no-chrome"]
    assert cmd[cmd.index("--append-system-prompt") + 1] == "GUARDRAILS"
    assert cmd[cmd.index("--max-budget-usd") + 1] == "1.0"
    assert cmd[cmd.index("--effort") + 1] == "xhigh"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--model" not in cmd and "--disallowed-tools" not in cmd
    for flag in contract.ALWAYS_SEND_FLAGS:
        if flag in ("--setting-sources", "--bare", "--safe-mode"):
            continue  # mode-specific
        assert flag in cmd, flag


def test_build_command_model_effort_and_readonly():
    cmd, dropped = _build(model="sonnet", effort="low", access="readonly", config_mode="scoped")
    assert dropped == [] and cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--effort") + 1] == "low"
    assert cmd[cmd.index("--disallowed-tools") + 1] == "Edit,Write,NotebookEdit,Bash"
    assert cmd[cmd.index("--setting-sources") + 1] == "project"
    none, _ = _build(effort=None)
    assert "--effort" not in none


def test_help_gating_drops_a_flag_with_its_value_and_never_rescans_the_value():
    cmd, dropped = _build(model="--effort", flag_support=NO_MODEL)
    assert dropped == ["--model"] and "--model" not in cmd
    assert cmd.count("--effort") == 1 and cmd[cmd.index("--effort") + 1] == "xhigh"
    kept, dropped = _build(model="sonnet", flag_support=UNPARSED)
    assert dropped == [] and kept[kept.index("--model") + 1] == "sonnet"  # fails open


def test_scrub_env_strips_direct_credentials_in_login_modes_only():
    env = {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t", "PATH": "/bin"}
    for mode in ("inherit", "scoped", "safe"):
        assert cli.scrub_env(env, mode) == {"PATH": "/bin"}, mode
    assert cli.scrub_env(env, "bare") == env
    assert cli.scrub_env(env, "bare") is not env


def test_version_display_is_bounded_and_ansi_free():
    assert cli.version_display("\x1b[32m2.1.263 (Claude Code)\x1b[0m") == "2.1.263 (Claude Code)"
    assert cli.version_display("x" * 400) == "x" * 300
    assert cli.version_display(None) is None and cli.version_display("\x1b[0m") is None


def test_auth_status_is_exit_code_only_and_mode_aware(monkeypatch):
    seen: list[dict] = []

    def fake_run(cmd, **kw):
        seen.append({"cmd": cmd, "env": kw.get("env")})
        return subprocess.CompletedProcess(cmd, 0, "Logged in as someone@example.com", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert cli.auth_status("/CLAUDE", "inherit") is True
    assert seen[0]["cmd"] == ["/CLAUDE", "auth", "status", "--text"]
    assert "ANTHROPIC_API_KEY" not in seen[0]["env"]
    assert cli.auth_status("/CLAUDE", "bare") is True and seen[1]["env"]["ANTHROPIC_API_KEY"] == "k"
    monkeypatch.setattr(
        cli.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "")
    )
    assert cli.auth_status("/CLAUDE", "inherit") is False

    def boom(cmd, **kw):
        raise OSError("nope")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    assert cli.auth_status("/CLAUDE", "inherit") is None


def _run(stdout="", stderr="", exit_code=1, timed_out=False):
    return CommandRun(stdout, stderr, exit_code, 12, timed_out)


def _envelope(result, subtype="error", is_error=True, **extra):
    body = {"type": "result", "subtype": subtype, "is_error": is_error, "result": result}
    body.update(extra)
    return json.dumps(body)


def test_binary_missing_and_timeout():
    missing = cli.classify_failure(
        _run(stderr=BINARY_NOT_FOUND, exit_code=127), config_mode="inherit", sanitize=None
    )
    assert missing.code == "claude_not_found" and missing.detail == cli.NOT_FOUND_DETAIL
    timeout = cli.classify_failure(
        _run(stderr=TIMED_OUT, exit_code=-9, timed_out=True), config_mode="inherit", sanitize=None
    )
    assert timeout.code == "timeout" and timeout.retryable is False
    assert timeout.repair is not None and timeout.repair.next_step == "start_new_job"
    assert timeout.repair.tool is None and "MAY" in timeout.detail


@pytest.mark.parametrize(
    "result, code, retryable, field",
    [
        ("Not logged in · Please run /login", "claude_auth_required", None, None),
        ("Invalid API key.", "api_key_invalid", None, None),
        ("Authentication required.", "claude_auth_required", None, None),
        (
            "Budget stop threshold reached.",
            "budget_exceeded",
            False,
            "backend_options.max_budget_usd",
        ),
        (
            "Permission denied for tool Read.",
            "claude_permission_error",
            False,
            "backend_options.access",
        ),
        ("Rate limited; try later.", "claude_rate_limited", None, None),
        ("error: unknown option '--effort'", "cli_contract_changed", None, None),
        ("the model declined to answer", "nonzero_exit", False, None),
        ("", "nonzero_exit", False, None),
    ],
)
def test_classify_envelope_branches(result, code, retryable, field):
    env = json.loads(_envelope(result, total_cost_usd=0.004, usage={"input_tokens": 20}))
    failure = cli.classify_envelope(env, stderr="", config_mode="inherit", sanitize=None)
    assert failure.code == code
    assert failure.retryable is retryable
    assert (failure.details or {}).get("field") == field
    assert failure.usage is not None and failure.usage.cost_usd == 0.004
    if code == "nonzero_exit":
        assert failure.detail.startswith("claude reported an error: ")
        assert (result or "error") in failure.detail


def test_classify_envelope_is_error_with_subtype_success_and_the_author_is_not_auth():
    env = json.loads(_envelope("Rate limited; try later.", subtype="success"))
    assert (
        cli.classify_envelope(env, stderr="", config_mode="inherit", sanitize=None).code
        == "claude_rate_limited"
    )
    env = json.loads(_envelope("The author's approach fails on empty input."))
    failure = cli.classify_envelope(env, stderr="", config_mode="inherit", sanitize=None)
    assert failure.code == "nonzero_exit" and "author" in failure.detail


def test_classify_envelope_repairs_are_mode_aware():
    env = json.loads(_envelope("Not logged in"))
    inherit = cli.classify_envelope(env, stderr="", config_mode="inherit", sanitize=None)
    bare = cli.classify_envelope(env, stderr="", config_mode="bare", sanitize=None)
    assert inherit.repair is not None and "/login" in (inherit.repair.alternative or "")
    assert bare.repair is not None and "ANTHROPIC_API_KEY" in (bare.repair.alternative or "")
    assert inherit.repair.next_step == "authenticate" and bare.repair.next_step == "authenticate"


def test_api_key_repair_names_the_placeholder_when_the_host_did_not_expand_it(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "${ANTHROPIC_API_KEY}")
    assert "placeholder" in cli.api_key_repair_for("bare")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "Set a valid ANTHROPIC_API_KEY" in cli.api_key_repair_for("bare")
    assert "does not rely on ANTHROPIC_API_KEY" in cli.api_key_repair_for("inherit")


def test_classify_failure_routes_a_failure_envelope_on_any_exit_code():
    run = _run(stdout=_envelope("Budget stop threshold reached."), exit_code=1)
    assert cli.classify_failure(run, config_mode="inherit", sanitize=None).code == "budget_exceeded"


def test_classify_failure_reads_a_budget_stop_by_its_subtype_alone():
    """A real budget stop carries no `result` text, only the subtype (#73); it classified as
    nonzero_exit while the budget pattern was word-bounded."""
    run = _run(stdout=cf.budget_stop_envelope(total_cost_usd=1.66), exit_code=1)
    failure = cli.classify_failure(run, config_mode="inherit", sanitize=None)
    assert failure.code == "budget_exceeded"
    assert failure.details == {"field": "backend_options.max_budget_usd"}
    assert failure.usage is not None and failure.usage.cost_usd == 1.66


@pytest.mark.parametrize(
    "stderr, code",
    [
        ("Not logged in. Please run /login", "claude_auth_required"),
        ("Error: invalid API key", "api_key_invalid"),
        ("stopped: budget exhausted", "budget_exceeded"),
        ("429 Too Many Requests", "claude_rate_limited"),
        ("error: unknown option '--zap'", "cli_contract_changed"),
        ("segfault", "nonzero_exit"),
    ],
)
def test_classify_failure_generic_branches(stderr, code):
    failure = cli.classify_failure(
        _run(stderr=stderr, exit_code=2), config_mode="inherit", sanitize=None
    )
    assert failure.code == code
    if code == "nonzero_exit":
        assert failure.detail == "claude exited 2: segfault" and failure.retryable is None
    if code == "claude_rate_limited":
        assert failure.retry_after_ms is None


def test_generic_branch_sanitizes_before_the_cut_and_applies_the_site_sanitizer():
    straddling = "x" * 280 + f" token={SECRET}"
    failure = cli.classify_failure(
        _run(stderr=straddling, exit_code=2), config_mode="inherit", sanitize=None
    )
    assert SECRET not in failure.detail and "sk-cccc" not in failure.detail
    assert len(failure.detail) <= len("claude exited 2: ") + 300
    aliased = cli.classify_failure(
        _run(stderr="failed reading /wt/abc/src/a.py", exit_code=2),
        config_mode="inherit",
        sanitize=lambda t: t.replace("/wt/abc", "<worktree>"),
    )
    assert "/wt/abc" not in aliased.detail and "<worktree>/src/a.py" in aliased.detail
    ansi = cli.classify_failure(
        _run(stderr="\x1b[31mboom\x1b[0m", exit_code=2), config_mode="inherit", sanitize=None
    )
    assert ansi.detail == "claude exited 2: boom"


def test_envelope_result_text_is_sanitized_before_it_is_echoed():
    env = json.loads(_envelope("the model declined: " + "y" * 190 + f" key={SECRET}"))
    failure = cli.classify_envelope(env, stderr="", config_mode="inherit", sanitize=None)
    assert SECRET not in failure.detail and "sk-cccc" not in failure.detail
