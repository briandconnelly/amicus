"""pi argv, child environment, free probes and the failure classifier."""

from __future__ import annotations

import pytest

from amicus.backends.pi import cli, contract
from amicus.sdk.core.runtime import BINARY_NOT_FOUND, CommandRun


def _argv(**kw):
    base = dict(pi_bin="/PI", read_only=True, model="openrouter/m", thinking=None)
    base.update(kw)
    return cli.build_exec_command(**base)


def test_read_only_argv():
    argv = _argv()
    assert argv[0] == "/PI"
    assert argv[1 : 1 + len(contract.RUN_FLAGS)] == list(contract.RUN_FLAGS)
    assert argv[argv.index("--tools") + 1] == "read,grep,find,ls"
    assert argv[argv.index("--system-prompt") + 1] == contract.PI_SYSTEM_PROMPT
    assert argv[argv.index("--append-system-prompt") + 1] == ""
    assert argv[argv.index("--model") + 1] == "openrouter/m"
    assert "--thinking" not in argv and "--no-session" in argv and "--no-approve" in argv


def test_write_argv_has_bash_and_thinking():
    argv = _argv(read_only=False, thinking="high")
    assert argv[argv.index("--tools") + 1] == "read,bash,edit,write,grep,find,ls"
    assert argv[argv.index("--thinking") + 1] == "high"


def test_run_env_sets_and_drops():
    base = {"PI_CODING_AGENT_SESSION_DIR": "/x", "OPENROUTER_API_KEY": "k"}
    env = cli.build_run_env(base)
    assert env["PI_TELEMETRY"] == "0" and env["PI_SKIP_VERSION_CHECK"] == "1"
    assert "PI_CODING_AGENT_SESSION_DIR" not in env
    assert env["OPENROUTER_API_KEY"] == "k"
    assert "PI_TELEMETRY" not in base and "PI_CODING_AGENT_SESSION_DIR" in base


def _probe(monkeypatch, *, stdout="", stderr="", exit_code=0, timed_out=False, missing=False):
    calls: list[list[str]] = []

    def fake(cmd, **kw):
        calls.append(list(cmd))
        if missing:
            return CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
        return CommandRun(stdout, stderr, exit_code, 1, timed_out)

    monkeypatch.setattr(cli.runtime, "run_sync_capture", fake)
    return calls


def test_version_probe(monkeypatch):
    _probe(monkeypatch, stdout="1.5.0\n")
    assert cli.pi_version("/PI") == "1.5.0"
    _probe(monkeypatch, missing=True)
    assert cli.pi_version("/PI") is None
    _probe(monkeypatch, stdout="1.5.0", exit_code=1)
    assert cli.pi_version("/PI") is None
    assert cli.version_display("1.5.0\x1b[0m") == "1.5.0"
    assert cli.version_display(None) is None


_R = '{"status":"ready","provider":"openrouter","authType":"oauth"}'
_NR = '{"status":"not_ready","provider":"anthropic","reason":"credentials_not_configured"}'
_UNRES = '{"status":"invalid","provider":"nosuch/zzz-model","reason":"invalid_state"}'
_INV = '{"status":"invalid","provider":"openrouter","reason":"invalid_state"}'


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (dict(stdout=_R), "ready"),
        (dict(stdout=_NR, exit_code=1), "not_ready"),
        (dict(stdout=_UNRES, exit_code=2), "unresolved"),
        (dict(stdout=_INV, exit_code=2), "not_ready"),
        (dict(stdout='{"status":"weird"}'), "unknown"),
        (dict(stdout="[1]"), "unknown"),
        (dict(stderr="kaboom", exit_code=1), "unknown"),
        (dict(stdout="garbage", exit_code=0), "unknown"),
        (dict(timed_out=True, exit_code=-1), "unknown"),
        (dict(missing=True), "unknown"),
    ],
)
def test_auth_status_maps_every_outcome(monkeypatch, kw, expected):
    calls = _probe(monkeypatch, **kw)
    assert cli.auth_status("/PI", "nosuch/zzz-model") == expected
    argv = calls[0]
    assert argv == ["/PI", *contract.AUTH_CHECK_ARGS, "--model", "nosuch/zzz-model"]
    assert "--credentials" not in argv


@pytest.mark.parametrize("model", [None, ""])
def test_auth_status_without_model_spawns_nothing(monkeypatch, model):
    calls = _probe(monkeypatch, stdout='{"status":"ready"}')
    assert cli.auth_status("/PI", model) == "unknown"
    assert calls == []


# --- classification ------------------------------------------------------------------------


def _run(stdout="", stderr="", exit_code=1, timed_out=False, missing=False):
    if missing:
        return CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
    return CommandRun(stdout, stderr, exit_code, 12, timed_out)


def _classify(run, **kw):
    base = dict(error_message=None, sanitize=None)
    base.update(kw)
    return cli.classify_failure(run, **base)


def test_classifier_reads_the_exit_zero_error_message():
    f = _classify(_run(exit_code=0), error_message="401 Unauthorized")
    assert f.code == "pi_auth_required"


def test_binary_missing_and_timeout():
    assert _classify(_run(missing=True)).code == "pi_not_found"
    assert _classify(_run(timed_out=True, exit_code=-1)).code == "timeout"


def test_drift_beats_auth():
    f = _classify(_run(stderr="Error: Unknown option: --x 401 unauthorized"))
    assert f.code == "cli_contract_changed"


def test_rate_limit_uses_parsed_and_default_backoff():
    f = _classify(_run(exit_code=0), error_message="429 retry-after: 2s")
    assert f.code == "pi_rate_limited" and f.retry_after_ms == 2000
    g = _classify(_run(exit_code=0), error_message="429 Too Many Requests")
    assert g.retry_after_ms == contract.RATE_LIMIT_DEFAULT_BACKOFF_MS


def test_invalid_model():
    f = _classify(_run(exit_code=0), error_message='Model "x/y" not found')
    assert f.code == "invalid_model" and f.details == {"field": "model"}
    assert f.repair is not None and f.repair.tool == "amicus_models"


def test_generic_detail_is_sanitized_before_the_cut():
    secret = "sk-" + "c" * 32
    f = _classify(_run(stderr=f"boom token={secret}", exit_code=3))
    assert f.code == "nonzero_exit" and secret not in f.detail and "pi exited 3" in f.detail
    straddling = "x" * 280 + f" token={secret}"
    g = _classify(_run(stderr=straddling, exit_code=2))
    assert "sk-cccc" not in g.detail and secret not in g.detail and len(g.detail) <= 320
    h = _classify(
        _run(stderr="failed at /wt/abc/src/a.py", exit_code=2),
        sanitize=lambda t: t.replace("/wt/abc/", "./"),
    )
    assert "/wt/abc" not in h.detail and "./src/a.py" in h.detail
    assert _classify(_run(stderr="\x1b[31mred\x1b[0m", exit_code=2)).detail.endswith("red")
    assert _classify(_run(exit_code=2), error_message="oops").detail.endswith("oops")
