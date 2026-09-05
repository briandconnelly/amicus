"""codex argv build, probes, and failure classification (ported from tests/test_codex.py)."""

from __future__ import annotations

import tomllib

import pytest
from pontonier.conventions.preflight import FlagSupport
from pontonier.core import worktree
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun

from amicus.backends.codex import cli, contract
from amicus.backends.codex import config as cc
from amicus.schemas import instructions as ins

_ALL_FLAGS = FlagSupport(
    supported=frozenset(contract.ALWAYS_SEND_FLAGS | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
_NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)
_EFFORT_KEY = contract.MODEL_REASONING_EFFORT_CONFIG_KEY


def _build(**kw):
    base = dict(
        codex_bin="/CODEX",
        cwd="/repo",
        sandbox="read-only",
        isolation="inherit",
        output_last_message_path="/TMP/last.txt",
        flag_support=_ALL_FLAGS,
    )
    base.update(kw)
    return cli.build_exec_command(**base)


def _disabled(cmd):
    return [cmd[i + 1] for i, t in enumerate(cmd) if t == contract.DISABLE_FEATURE_FLAG]


def test_build_core_and_ordering():
    cmd, dropped = _build(model="gpt-5.4")
    assert cmd[0] == "/CODEX" and cmd[1] == "exec" and "--json" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--cd") + 1] == "/repo"
    assert cmd[cmd.index("--output-last-message") + 1] == "/TMP/last.txt"
    assert "--ephemeral" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5.4"
    assert cmd[-1] == contract.STDIN_PROMPT and dropped == []
    assert _disabled(cmd) == ["remote_plugin", "sleep_tool"]
    assert contract.STRICT_CONFIG_FLAG not in cmd  # no -c override rides a default consult


@pytest.mark.parametrize("isolation", cc.VALID_ISOLATIONS)
@pytest.mark.parametrize("sandbox", contract.VALID_SANDBOXES)
def test_workspace_write_pins_exactly(sandbox, isolation):
    cmd, _ = _build(sandbox=sandbox, isolation=isolation)
    for pin in (
        "sandbox_workspace_write.network_access=false",
        "sandbox_workspace_write.writable_roots=[]",
    ):
        pairs = [i for i in range(len(cmd) - 1) if cmd[i] == "-c" and cmd[i + 1] == pin]
        assert len(pairs) == (1 if sandbox == "workspace-write" else 0)
    assert (contract.STRICT_CONFIG_FLAG in cmd) == (sandbox == "workspace-write")
    if isolation == "ignore-rules":
        assert "--ignore-user-config" in cmd and "--ignore-rules" in cmd


def test_help_gating_drops_model_but_never_effort():
    cmd, dropped = _build(model="gpt-5.4", reasoning_effort="xhigh", flag_support=_NO_MODEL)
    assert "--model" not in cmd and "gpt-5.4" not in cmd and dropped == ["--model"]
    assert f'{_EFFORT_KEY}="xhigh"' in cmd


@pytest.mark.parametrize(
    ("value", "token"),
    [
        ("high", f'{_EFFORT_KEY}="high"'),
        ("", f'{_EFFORT_KEY}=""'),
        ("true", f'{_EFFORT_KEY}="true"'),
        ('"high"', f'{_EFFORT_KEY}="\\"high\\""'),
        ("high\U0001f600", f'{_EFFORT_KEY}="high\U0001f600"'),
    ],
)
def test_effort_is_toml_string_encoded_and_round_trips(value, token):
    cmd, _ = _build(reasoning_effort=value)
    assert cmd[cmd.index(token) - 1] == "-c"
    assert tomllib.loads(f"v = {token.partition('=')[2]}")["v"] == value
    assert contract.STRICT_CONFIG_FLAG in cmd


def test_developer_instructions_are_composed_once_and_encoded():
    cmd, _ = _build(developer_instructions="Focus on locking.")
    token = next(t for t in cmd if t.startswith(f"{contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY}="))
    assert cmd[cmd.index(token) - 1] == "-c"
    assert tomllib.loads(f"v = {token.partition('=')[2]}")["v"] == ins.compose("Focus on locking.")
    cmd, _ = _build(developer_instructions=None)
    assert not any(contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY in t for t in cmd)


def test_extra_args_ride_after_plugin_tokens_and_arm_strict_config():
    cmd, _ = _build(extra_args=("-c", "model_provider=x"), reasoning_effort="low")
    assert cmd.index(f'{_EFFORT_KEY}="low"') < cmd.index("model_provider=x") < cmd.index("-")
    assert all(i < cmd.index("model_provider=x") for i, t in enumerate(cmd) if t == "--disable")
    assert contract.STRICT_CONFIG_FLAG in cmd
    cmd, _ = _build(extra_args=("-p", "work"))
    assert contract.STRICT_CONFIG_FLAG not in cmd


def test_strict_config_not_armed_by_a_flag_shaped_model_value():
    cmd, _ = _build(model="-c")
    assert contract.STRICT_CONFIG_FLAG not in cmd


def test_schema_and_skip_git_repo_check():
    cmd, _ = _build(output_schema_path="/TMP/s.json", skip_git_repo_check=True)
    assert cmd[cmd.index("--output-schema") + 1] == "/TMP/s.json" and "--skip-git-repo-check" in cmd


def test_plugin_config_keys_for_mirrors_the_builder():
    assert (
        cli.plugin_config_keys_for(
            sandbox="read-only", reasoning_effort=None, developer_instructions=None
        )
        == frozenset()
    )
    keys = cli.plugin_config_keys_for(
        sandbox="workspace-write", reasoning_effort="high", developer_instructions="x"
    )
    assert keys == contract.PLUGIN_OWNED_CONFIG_KEYS


# --- probes -------------------------------------------------------------------------------------


def test_codex_version_and_login_status(monkeypatch):
    monkeypatch.setattr(
        cli.runtime,
        "run_sync_capture",
        lambda cmd, timeout_seconds, **k: CommandRun("codex-cli 0.153.4\n", "", 0, 1, False),
    )
    assert cli.codex_version("/CODEX") == "codex-cli 0.153.4"
    monkeypatch.setattr(
        cli.runtime,
        "run_sync_capture",
        lambda cmd, timeout_seconds, **k: CommandRun("Logged in using ChatGPT", "", 0, 1, False),
    )
    assert cli.login_status("/CODEX") == (True, "Codex reports an authenticated session (ChatGPT).")
    monkeypatch.setattr(
        cli.runtime,
        "run_sync_capture",
        lambda cmd, timeout_seconds, **k: CommandRun("", "", 1, 1, False),
    )
    assert cli.login_status("/CODEX")[0] is False
    monkeypatch.setattr(
        cli.runtime,
        "run_sync_capture",
        lambda cmd, timeout_seconds, **k: CommandRun("", BINARY_NOT_FOUND, 127, 1, False),
    )
    assert cli.codex_version("/CODEX") is None and cli.login_status("/CODEX") == (None, None)


def test_version_display_bounds_and_sanitizes():
    assert cli.version_display("codex-cli 0.153.4") == "codex-cli 0.153.4"
    assert cli.version_display("0.\x07153.0") == "0.153.0"
    assert cli.version_display("\x07\x1b") is None and cli.version_display(None) is None
    long = "v" * 500
    shown = cli.version_display(long) or ""
    assert len(shown) == 200 and shown.endswith("…[truncated]")


# --- classify_failure ----------------------------------------------------------------------------


def _classify(run, **kw):
    base = dict(
        last_message=None,
        events=None,
        extra_args=cc.ExtraArgs(),
        reasoning_effort=None,
        sanitize=None,
        plugin_config_keys=frozenset(),
    )
    base.update(kw)
    return cli.classify_failure(run, **base)


def test_classify_binary_missing_and_timeout():
    assert _classify(CommandRun("", BINARY_NOT_FOUND, 127, 1, False)).code == "codex_not_found"
    out = _classify(CommandRun("", TIMED_OUT, -9, 1, True))
    assert out.code == "timeout" and out.repair is None
    out = _classify(CommandRun("", TIMED_OUT, -9, 1, True, capture_failed=True))
    assert out.code == "timeout" and out.repair is not None and "capture" in out.detail


def test_classify_auth_drift_rate_limit_and_ordering():
    assert _classify(CommandRun("", "not logged in", 1, 1, False)).code == "codex_auth_required"
    assert (
        _classify(CommandRun("", "error: unexpected argument '--zap' found", 2, 1, False)).code
        == "cli_contract_changed"
    )
    out = _classify(CommandRun("", "429 Too Many Requests, Retry-After: 5", 1, 1, False))
    assert out.code == "codex_rate_limited" and out.retry_after_ms == 5000
    out = _classify(CommandRun("", "rate limit reached", 1, 1, False))
    assert out.retry_after_ms == contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
    assert (
        _classify(CommandRun("", "unauthorized; rate limit", 1, 1, False)).code
        == "codex_auth_required"
    )
    assert (
        _classify(CommandRun("", "invalid value; rate limit", 1, 1, False)).code
        == "cli_contract_changed"
    )
    assert (
        _classify(
            CommandRun("", "", 1, 1, False), events='{"type":"error","message":"401 unauthorized"}'
        ).code
        == "codex_auth_required"
    )


def test_classify_nonzero_generic_sanitizes_before_truncating():
    secret = "sk-" + "c" * 32
    out = _classify(CommandRun("", "x" * 290 + f" token={secret}", 1, 1, False))
    assert (
        out.code == "nonzero_exit" and secret not in out.detail and "codex exited 1" in out.detail
    )
    out = _classify(CommandRun("", "boom\x1b[31m", 1, 1, False, capture_failed=True))
    assert "\x1b" not in out.detail and "capture failed" in out.detail


def test_classify_sanitize_relativizes_worktree_paths(tmp_path):
    wt = str(tmp_path / "amicus-wt-x" / "tree")
    aliases = worktree.path_aliases(wt)
    out = _classify(
        CommandRun("", f"fatal: cannot open {wt}/f.py", 1, 1, False),
        sanitize=lambda t: worktree.sanitize_echo_prose(t, aliases) or "",
    )
    assert wt not in out.detail and "./f.py" in out.detail


def test_classify_effort_rejection_only_when_effort_sent():
    stderr = "[ReasoningEffortParam] [reasoning.effort] [invalid_enum_value] Invalid value: 'zz'"
    out = _classify(CommandRun("", stderr, 1, 1, False), reasoning_effort="zz")
    assert out.code == "invalid_reasoning_effort" and out.details == {"field": "reasoning_effort"}
    assert _classify(CommandRun("", stderr, 1, 1, False)).code == "cli_contract_changed"


def test_classify_attributes_drift_to_operator_extra_args_when_named():
    ea = cc.parse_extra_args("-p work")
    out = _classify(
        CommandRun("", "error: unexpected argument '--profile' found", 2, 1, False), extra_args=ea
    )
    assert (
        out.code == "extra_args_rejected" and out.repair is not None and "--profile" in out.detail
    )
    out = _classify(
        CommandRun("", "error: unexpected argument '--sandbox' found", 2, 1, False), extra_args=ea
    )
    assert out.code == "cli_contract_changed"
    # A bare `-c` rejection stays drift when the plugin itself emitted a -c pair.
    ea = cc.parse_extra_args("-c model_provider=x")
    out = _classify(
        CommandRun("", "error: unexpected argument '-c' found", 2, 1, False),
        extra_args=ea,
        reasoning_effort="high",
    )
    assert out.code == "cli_contract_changed"
    out = _classify(
        CommandRun("", "error: unexpected argument '-c' found", 2, 1, False), extra_args=ea
    )
    assert out.code == "extra_args_rejected"


def test_strict_config_attribution():
    override = (
        "Error loading config.toml: unknown configuration field `model_reasoning_effort` "
        "in -c/--config override\n"
    )
    assert _classify(CommandRun("", override, 1, 1, False)).code == "cli_contract_changed"
    op = (
        "Error loading config.toml: unknown configuration field `model_provider` "
        "in -c/--config override\n"
    )
    assert (
        _classify(
            CommandRun("", op, 1, 1, False), extra_args=cc.parse_extra_args("-c model_provider=x")
        ).code
        == "extra_args_rejected"
    )
    assert _classify(CommandRun("", op, 1, 1, False)).code == "cli_contract_changed"
    in_file = (
        "Error loading config.toml:\n/h/.codex/config.toml:3:1: unknown configuration field `zzz`\n"
    )
    out = _classify(CommandRun("", in_file + "\n401", 1, 1, False))  # beats the auth matcher
    assert (
        out.code == "user_config_rejected"
        and "zzz" in out.detail
        and "/h/.codex/config.toml:3" in out.detail
    )
    profile = (
        "Error loading config.toml:\n"
        "/h/.codex/work.config.toml:3:1: unknown configuration field `zzz`\n"
    )
    assert (
        _classify(
            CommandRun("", profile, 1, 1, False), extra_args=cc.parse_extra_args("-p work")
        ).code
        == "extra_args_rejected"
    )


def test_retired_and_invalid_value_attribution():
    retired = "Error: approval_policy = untrusted is no longer supported; remove this setting\n"
    out = _classify(CommandRun("", retired, 1, 1, False))
    assert out.code == "user_config_rejected" and "untrusted" in out.detail
    ea = cc.parse_extra_args("-c model_provider=x -p work")
    out = _classify(
        CommandRun(
            "",
            "Error: model_provider = zz is no longer supported; remove this setting\n",
            1,
            1,
            False,
        ),
        extra_args=ea,
    )
    assert out.code == "extra_args_rejected"
    out = _classify(CommandRun("", retired, 1, 1, False), extra_args=ea)
    assert (
        out.code == "user_config_rejected" and "work" in out.detail
    )  # profile ambiguity disclosed
    invalid = (
        'Error loading config.toml: invalid type: string "yes", expected a boolean\n'
        "in `sandbox_workspace_write.network_access`\n\n"
    )
    assert _classify(CommandRun("", invalid, 1, 1, False)).code == "user_config_rejected"
    assert (
        _classify(
            CommandRun("", invalid, 1, 1, False),
            plugin_config_keys=frozenset({"sandbox_workspace_write.network_access"}),
        ).code
        == "cli_contract_changed"
    )
    assert "yes" not in _classify(CommandRun("", invalid, 1, 1, False)).detail
