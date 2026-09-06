"""kimi -p staging and classification: the read-only guarantee, the handshake, the pointer,
the free probes, and the classifier's precedence and sanitization."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pontonier.conventions.preflight import FlagSupport
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun

from amicus.backends.kimi import cli, contract

ALL = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)
RO = {"prompt": "/T/prompt.md", "agent": "/T/readonly-agent.md"}
RW = {"prompt": "/T/prompt.md", "answer": "/T/answer.md"}


def _cmd(**kw):
    base = dict(
        kimi_bin="/KIMI",
        read_only=True,
        prompt_pointer=cli.build_prompt_pointer(RO, read_only=True),
        agent_file_path=RO["agent"],
        flag_support=ALL,
    )
    base.update(kw)
    return cli.build_exec_command(**base)


# --- argv --------------------------------------------------------------------------------


def test_read_only_without_an_agent_file_raises_rather_than_degrading():
    with pytest.raises(ValueError, match="agent file"):
        _cmd(agent_file_path=None)


def test_read_only_sends_the_agent_file_and_it_is_never_help_gated():
    cmd, dropped = _cmd(flag_support=FlagSupport(supported=frozenset(), help_parsed=True))
    assert cmd[cmd.index("--agent-file") + 1] == RO["agent"] and dropped == []
    assert "--agent-file" not in contract.HELP_GATED_FLAGS


def test_argv_shape_and_never_sent_flags():
    cmd, dropped = _cmd(model="k3", skills_dir="/T/empty-skills")
    assert (
        cmd[0] == "/KIMI"
        and cmd[1] == "--prompt"
        and cmd[3:5] == ["--output-format", "stream-json"]
    )
    assert (
        cmd[cmd.index("--model") + 1] == "k3"
        and cmd[cmd.index("--skills-dir") + 1] == "/T/empty-skills"
    )
    assert dropped == []
    assert contract.ADD_DIR_FLAG not in cmd
    assert not set(contract.PROMPT_MODE_INCOMPATIBLE_FLAGS) & set(cmd)


def test_model_and_skills_dir_are_help_gated_with_their_values():
    cmd, dropped = _cmd(model="k3", skills_dir="/T/s", flag_support=NO_MODEL)
    assert "--model" not in cmd and "k3" not in cmd and "/T/s" not in cmd
    assert dropped == ["--skills-dir", "--model"]
    fail_open, dropped2 = _cmd(model="k3", flag_support=FlagSupport(frozenset(), help_parsed=False))
    assert "--model" in fail_open and dropped2 == []


def test_an_oversized_pointer_is_refused():
    with pytest.raises(ValueError, match="argv prompt exceeds"):
        _cmd(prompt_pointer="x" * (contract.MAX_ARGV_PROMPT_CHARS + 1))


def test_delegate_argv_has_no_agent_file():
    cmd, _ = _cmd(
        read_only=False,
        prompt_pointer=cli.build_prompt_pointer(RW, read_only=False),
        agent_file_path=None,
    )
    assert "--agent-file" not in cmd and "/T/answer.md" in cmd[2]


# --- env ---------------------------------------------------------------------------------


def test_run_env_pins_the_output_format_and_sets_effort_only_when_given():
    env = cli.build_run_env({"HOME": "/h", "KIMI_MODEL_OUTPUT_FORMAT": "text"}, "high")
    assert env["KIMI_MODEL_THINKING_EFFORT"] == "high" and env["HOME"] == "/h"
    assert env["KIMI_MODEL_OUTPUT_FORMAT"] == "stream-json"
    assert "KIMI_MODEL_THINKING_EFFORT" not in cli.build_run_env({}, None)


# --- the read-only agent and the handshake ------------------------------------------------


def test_the_read_only_agent_document_grants_only_the_three_tools():
    doc = cli.read_only_agent_document()
    assert doc.startswith("---\nname: amicus-readonly\n")
    tools_block = doc.split("tools:\n", 1)[1].split("---", 1)[0]
    assert [line.strip("- ").strip() for line in tools_block.strip().splitlines()] == list(
        contract.READ_ONLY_AGENT_TOOLS
    )
    assert "Bash" not in doc and "Write" not in doc


def test_handshake_files_for_each_tier_are_private_and_outside_the_repo(tmp_path):
    run_dir = cli.create_handshake_dir()
    try:
        assert Path(run_dir).name.startswith(contract.HANDSHAKE_DIR_PREFIX)
        assert not (Path(run_dir) / ".git").exists() and str(tmp_path) not in run_dir
        ro = cli.write_handshake(run_dir, "PROMPT", read_only=True)
        assert set(ro) == {"prompt", "agent"}
        assert Path(ro["prompt"]).read_text() == "PROMPT"
        assert Path(ro["agent"]).read_text() == cli.read_only_agent_document()
        assert stat.S_IMODE(Path(ro["prompt"]).stat().st_mode) == 0o600
        rw = cli.write_handshake(cli.create_handshake_dir(), "P", read_only=False)
        assert set(rw) == {"prompt", "answer"} and not Path(rw["answer"]).exists()
    finally:
        import shutil

        shutil.rmtree(run_dir, ignore_errors=True)


def test_handshake_refuses_to_follow_a_planted_symlink(tmp_path):
    run_dir = tmp_path / "hs"
    run_dir.mkdir()
    target = tmp_path / "elsewhere.md"
    (run_dir / contract.PROMPT_FILE_NAME).symlink_to(target)
    with pytest.raises(FileExistsError):
        cli.write_handshake(str(run_dir), "PROMPT", read_only=True)
    assert not target.exists()


def test_prompt_pointers_stay_small_and_name_the_files():
    ro = cli.build_prompt_pointer(RO, read_only=True)
    rw = cli.build_prompt_pointer(RW, read_only=False)
    assert RO["prompt"] in ro and RW["answer"] not in ro
    assert RW["prompt"] in rw and RW["answer"] in rw
    assert len(ro) < 300 and len(rw) < 300


def test_schema_instruction_names_the_schema():
    text = cli.schema_instruction({"type": "object"})
    assert text.startswith("\n\n# Required output format") and '"type": "object"' in text


# --- probes ------------------------------------------------------------------------------


def _probe(monkeypatch, stdout="", stderr="", exit_code=0, timed_out=False, missing=False):
    def fake(cmd, timeout_seconds, **k):
        if missing:
            return CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
        return CommandRun(stdout, stderr, exit_code, 1, timed_out)

    monkeypatch.setattr(cli.runtime, "run_sync_capture", fake)


def test_version_probe(monkeypatch):
    _probe(monkeypatch, stdout="0.41.0\n")
    assert cli.kimi_version("/KIMI") == "0.41.0"
    _probe(monkeypatch, missing=True)
    assert cli.kimi_version("/KIMI") is None
    assert cli.version_display("0.41.0\x1b[0m") == "0.41.0"


def test_login_status_counts_providers_and_never_echoes_them(monkeypatch):
    payload = '{"providers": {"p": {"apiKey": "sk-secret", "baseUrl": "https://x"}}, "models": {}}'
    _probe(monkeypatch, stdout=payload)
    ok, detail = cli.login_status("/KIMI")
    assert ok is True and detail == "Kimi reports 1 configured provider(s)."
    _probe(monkeypatch, stdout='{"providers": {}}')
    assert cli.login_status("/KIMI") == (
        False,
        "Kimi has no configured provider; run `kimi login`.",
    )
    _probe(monkeypatch, stdout="garbage")
    assert cli.login_status("/KIMI") == (None, None)
    _probe(monkeypatch, exit_code=1)
    assert cli.login_status("/KIMI")[0] is False
    _probe(monkeypatch, missing=True)
    assert cli.login_status("/KIMI") == (None, None)
    _probe(monkeypatch, stdout="[1, 2]")
    assert cli.login_status("/KIMI")[0] is True


# --- classification ------------------------------------------------------------------------


def _run(stdout="", stderr="", exit_code=1, timed_out=False):
    return CommandRun(stdout, stderr, exit_code, 12, timed_out)


def _classify(run, **kw):
    base = dict(last_message=None, events=None, reasoning_effort=None, sanitize=None)
    base.update(kw)
    return cli.classify_failure(run, **base)


def test_missing_binary_and_timeout():
    assert _classify(_run(stderr=BINARY_NOT_FOUND, exit_code=127)).code == "kimi_not_found"
    assert _classify(_run(stderr=TIMED_OUT, exit_code=-9, timed_out=True)).code == "timeout"


def test_invalid_model_blames_the_argument_but_an_unresolved_default_does_not():
    f = _classify(
        _run(stderr='error: failed to run prompt: Model "x" is not configured in config.toml.')
    )
    assert f.code == "invalid_model" and f.details == {"field": "model"}
    assert f.repair is not None and f.repair.tool == "amicus_models"
    g = _classify(
        _run(
            stderr=(
                "error: failed to run prompt: model foo does not resolve to a configured provider"
            )
        )
    )
    assert g.code == "invalid_model" and g.details is None
    assert (
        g.repair is not None
        and g.repair.next_step == "correct_config"
        and "default_model" in (g.repair.alternative or "")
    )


def test_model_prose_discussing_the_failure_is_not_invalid_model():
    events = (
        '{"role":"assistant","content":"the alias does not resolve to a configured provider"}\n'
    )
    f = _classify(_run(stdout=events, exit_code=3), events=events, last_message="x")
    assert f.code == "nonzero_exit"


def test_drift_auth_and_rate_limit_precedence():
    assert _classify(_run(stderr="error: unknown option '--zap'")).code == "cli_contract_changed"
    assert (
        _classify(_run(stderr="Cannot combine --prompt with --yolo.")).code
        == "cli_contract_changed"
    )
    assert _classify(_run(stderr="401 Unauthorized")).code == "kimi_auth_required"
    rate = _classify(_run(stderr="429 Too Many Requests; retry-after: 5"))
    assert rate.code == "kimi_rate_limited" and rate.retry_after_ms == 5000
    assert (
        _classify(_run(stderr="rate limit reached")).retry_after_ms
        == contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
    )
    assert _classify(_run(stderr="rate limit; retry-after: 0")).retry_after_ms == 0
    both = _classify(_run(stderr="error: unknown option '--x' (429 rate limit)"))
    assert both.code == "cli_contract_changed"
    assert (
        _classify(
            _run(stderr='error: unknown option; Model "x" is not configured in config.toml')
        ).code
        == "cli_contract_changed"
    )
    from_events = '{"type":"turn.failed","message":"rate limit reached; try again in 2 seconds"}\n'
    assert _classify(_run(stdout=from_events), events=from_events).retry_after_ms == 2000


def test_auth_is_also_detected_in_the_last_message():
    assert _classify(_run(exit_code=2), last_message="invalid api key").code == "kimi_auth_required"


def test_generic_failures_are_bounded_and_sanitized_before_truncation():
    secret = "sk-" + "c" * 32
    f = _classify(_run(stderr=f"boom token={secret}", exit_code=3))
    assert f.code == "nonzero_exit" and secret not in f.detail and "kimi exited 3" in f.detail
    straddling = "x" * 280 + f" token={secret}"
    g = _classify(_run(stderr=straddling, exit_code=2))
    assert "sk-cccc" not in g.detail and secret not in g.detail and len(g.detail) <= 320
    h = _classify(
        _run(stderr="failed at /wt/abc/src/a.py", exit_code=2),
        sanitize=lambda t: t.replace("/wt/abc/", "./"),
    )
    assert "/wt/abc" not in h.detail and "./src/a.py" in h.detail
    assert _classify(_run(stderr="\x1b[31mred\x1b[0m", exit_code=2)).detail.endswith("red")
