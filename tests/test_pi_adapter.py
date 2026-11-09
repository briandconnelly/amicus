"""PiBackend on the SDK lifecycle: the pre-spend model and effort gate (fail closed), the
stdin-only prompt, the tool tier, and reading an exit-0 run that may still be a failure."""

from __future__ import annotations

import pytest
from tests.support import pifixtures as pf

from amicus.backends.pi import adapter, contract
from amicus.backends.pi.binary import BinaryNotFoundError
from amicus.plugin import ModelListing
from amicus.schemas import instructions as ins
from amicus.sdk.backend.protocol import AgentBackend, OutcomeInspector, RunOutcome, RunRequest
from amicus.sdk.core import runtime
from amicus.sdk.core.runtime import CommandRun
from amicus.sdk.testing import conformance


def _req(**kw) -> RunRequest:
    base = dict(
        kind="consult", prompt="why?", cwd="/repo/some/where", timeout_seconds=60, model=pf.MODEL
    )
    base.update(kw)
    return RunRequest(**base)


def _outcome(stdout: str = "", stderr: str = "", exit_code: int = 0) -> RunOutcome:
    return RunOutcome(run=CommandRun(stdout, stderr, exit_code, 5, False), events=stdout)


@pytest.fixture(autouse=True)
def _no_spawn(monkeypatch):
    """Every probe in these tests is pinned; a spawn would mean a seam was missed."""

    def refuse(*args, **kwargs):  # pragma: no cover - reaching it fails the test
        raise AssertionError(f"unexpected spawn: {args!r}")

    monkeypatch.setattr(runtime, "run_sync_capture", refuse)


def test_backend_is_conformant():
    backend = pf.make_backend()
    assert isinstance(backend, AgentBackend) and isinstance(backend, OutcomeInspector)
    assert conformance.check_backend(contract.CONTRACT, backend) == []
    configured = pf.make_backend({"AMICUS_PI_MODEL": pf.MODEL})
    assert conformance.check_backend(contract.CONTRACT, configured) == []


# --- validate_request ------------------------------------------------------------------------


def test_no_model_anywhere_is_refused_pre_spend():
    calls: list = []
    backend = pf.make_backend(calls=calls)
    failure = backend.validate_request(_req(model=None))
    assert failure is not None and failure.code == "invalid_arguments"
    assert failure.details == {"field": "model"}
    assert failure.repair is not None and failure.repair.tool == "amicus_models"
    assert "AMICUS_PI_MODEL" in (failure.repair.alternative or "")
    assert calls == []


def test_configured_model_is_used_when_the_call_omits_one():
    calls: list = []
    backend = pf.make_backend({"AMICUS_PI_MODEL": pf.MODEL}, calls=calls)
    assert backend.validate_request(_req(model=None)) is None
    assert calls == [("auth", "/PI", pf.MODEL), ("lookup", pf.MODEL)]


def test_unauthenticated_provider_is_auth_required_not_invalid_model():
    calls: list = []
    backend = pf.make_backend(auth="not_ready", calls=calls)
    failure = backend.validate_request(_req())
    assert failure is not None and failure.code == "pi_auth_required"
    assert failure.repair is not None and failure.repair.next_step == "authenticate"
    assert contract.LOGIN_HINT in (failure.repair.alternative or "")
    assert "amicus_backends" in (failure.repair.alternative or "")
    assert calls == [("auth", "/PI", pf.MODEL)]  # the catalog is never asked


def test_unresolvable_model_is_invalid_model():
    backend = pf.make_backend(auth="unresolved")
    failure = backend.validate_request(_req(model="nosuch/zzz"))
    assert failure is not None and failure.code == "invalid_model"
    assert failure.details is not None and failure.details["field"] == "model"


def test_unknown_auth_state_falls_through_to_the_catalog():
    calls: list = []
    backend = pf.make_backend(auth="unknown", calls=calls)
    assert backend.validate_request(_req()) is None
    assert ("lookup", pf.MODEL) in calls


def test_fuzzy_model_is_refused_as_invalid_model():
    backend = pf.make_backend()
    failure = backend.validate_request(_req(model="moonshotai/kimi-k3"))
    assert failure is not None and failure.code == "invalid_model"
    assert failure.details is not None and failure.details["catalog"] == "no_exact_row"


def test_unreadable_catalog_fails_closed():
    backend = pf.make_backend(catalog="unreadable")
    failure = backend.validate_request(_req())
    assert failure is not None and failure.code == "invalid_model"
    assert failure.details is not None and failure.details["catalog"] == "unreadable"


def test_unresolvable_binary_skips_the_probes():
    calls: list = []
    backend = pf.make_backend({"AMICUS_PI_BIN": "/definitely/not/here"}, calls=calls)
    assert backend.validate_request(_req()) is None
    assert calls == []


def test_effort_outside_model_set_is_refused():
    backend = pf.make_backend()
    failure = backend.validate_request(_req(model=pf.NO_THINKING, reasoning_effort="high"))
    assert failure is not None and failure.code == "invalid_reasoning_effort"
    assert failure.details == {"field": "reasoning_effort", "allowed_values": ["off"]}
    assert backend.validate_request(_req(model=pf.NO_THINKING, reasoning_effort="off")) is None
    assert backend.validate_request(_req(reasoning_effort="xhigh")) is None


def test_configured_effort_is_validated_too():
    backend = pf.make_backend({"AMICUS_PI_REASONING_EFFORT": "high"})
    failure = backend.validate_request(_req(model=pf.NO_THINKING))
    assert failure is not None and failure.code == "invalid_reasoning_effort"


@pytest.mark.parametrize("effort", ["", "HIGH ", "high\n", "x" * 200])
def test_malformed_effort_is_refused(effort):
    failure = pf.make_backend().validate_request(_req(reasoning_effort=effort))
    assert failure is not None and failure.code == "invalid_reasoning_effort"


def test_unknown_access_and_misplaced_instructions_are_refused():
    backend = pf.make_backend()
    bad_access = backend.validate_request(_req(access="danger-full-access"))
    assert bad_access is not None and bad_access.details == {"field": "access"}
    misplaced = backend.validate_request(_req(kind="delegate", instructions_append="x"))
    assert misplaced is not None and misplaced.details == {"field": "instructions_append"}
    blank = backend.validate_request(_req(instructions_append="   "))
    assert blank is not None and blank.details == {"field": "instructions_append"}
    unsafe = backend.validate_request(_req(instructions_append="a\x00b"))
    assert unsafe is not None and unsafe.details == {"field": "instructions_append"}


# --- prepare -------------------------------------------------------------------------------


async def test_prompt_rides_stdin_and_argv_carries_no_input(tmp_path):
    backend = pf.make_backend()
    request = _req(
        prompt="SENTINEL-Q",
        instructions_append="SENTINEL-I",
        cwd=str(tmp_path),
        schema={"type": "object"},
    )
    async with backend.prepare(request) as prep:
        assert "SENTINEL-Q" in prep.stdin_text and "SENTINEL-I" in prep.stdin_text
        assert not any("SENTINEL" in a for a in prep.argv)
        assert prep.stdin_text.startswith(ins.compose("SENTINEL-I") + "\n\nSENTINEL-Q")
        assert "# Required output format" in prep.stdin_text
        assert prep.argv[prep.argv.index("--system-prompt") + 1] == contract.PI_SYSTEM_PROMPT
        assert prep.argv[0] == "/PI" and prep.argv[prep.argv.index("--model") + 1] == pf.MODEL
        assert "--thinking" not in prep.argv
        assert prep.artifacts == () and prep.staging_dir is None
        assert prep.cwd == str(tmp_path) and prep.orphan_marker == str(tmp_path)


async def test_short_cwd_gets_no_orphan_marker():
    async with pf.make_backend().prepare(_req(cwd="/r")) as prep:
        assert prep.orphan_marker is None


async def test_delegate_gets_write_tools_and_consult_does_not(tmp_path):
    backend = pf.make_backend()

    async def tools(**kw) -> str:
        async with backend.prepare(_req(cwd=str(tmp_path), **kw)) as prep:
            return prep.argv[prep.argv.index("--tools") + 1]

    assert await tools(kind="delegate") == ",".join(contract.WRITE_TOOLS)
    assert await tools(kind="consult") == ",".join(contract.READ_ONLY_TOOLS)
    assert await tools(kind="review_changes") == ",".join(contract.READ_ONLY_TOOLS)
    assert await tools(kind="delegate", access="read-only") == ",".join(contract.READ_ONLY_TOOLS)
    assert await tools(kind="consult", access="workspace-write") == ",".join(contract.WRITE_TOOLS)


async def test_effort_and_env_reach_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", "/elsewhere")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    backend = pf.make_backend({"AMICUS_PI_REASONING_EFFORT": "low"})
    async with backend.prepare(_req(cwd=str(tmp_path))) as prep:
        assert prep.argv[prep.argv.index("--thinking") + 1] == "low"
        assert prep.env["PI_TELEMETRY"] == "0" and prep.env["PI_SKIP_VERSION_CHECK"] == "1"
        assert "PI_CODING_AGENT_SESSION_DIR" not in prep.env
        assert prep.env["OPENROUTER_API_KEY"] == "k"
    async with backend.prepare(_req(cwd=str(tmp_path), reasoning_effort="high")) as prep:
        assert prep.argv[prep.argv.index("--thinking") + 1] == "high"


async def test_prepare_refuses_invalid_requests_and_an_unresolved_binary(tmp_path):
    for bad in (
        {"model": None},
        {"reasoning_effort": "high\n"},
        {"access": "danger-full-access"},
    ):
        with pytest.raises(ValueError):
            async with pf.make_backend().prepare(_req(cwd=str(tmp_path), **bad)):
                pass  # pragma: no cover
    unresolved = pf.make_backend({"AMICUS_PI_BIN": "/definitely/not/here"})
    with pytest.raises(BinaryNotFoundError):
        async with unresolved.prepare(_req(cwd=str(tmp_path))):
            pass  # pragma: no cover


# --- reading the outcome -------------------------------------------------------------------


def test_finalize_reads_answer_usage_and_session():
    result = pf.make_backend().finalize(_outcome(pf.stream("the answer")), _req())
    assert result.answer == "the answer" and result.session_id == "sess-1"
    assert result.usage is not None and result.usage.input_tokens == 10
    assert result.structured is None and result.warnings == () and result.answer_loss is None


def test_finalize_parses_structured_output_when_asked():
    stdout = pf.stream('{"summary": "ok", "findings": []}')
    result = pf.make_backend().finalize(_outcome(stdout), _req(schema={"type": "object"}))
    assert result.structured == {"summary": "ok", "findings": []}


def test_finalize_marks_a_truncated_stream():
    backend = pf.make_backend()
    after = pf.stream("partial") + "[output truncated]\n"
    run = CommandRun(after, "", 0, 5, False, stdout_truncated=True)
    assert backend.finalize(RunOutcome(run=run, events=after), _req()).answer_loss == "truncated"
    before = "[output truncated]\n" + pf.stream("whole")
    run = CommandRun(before, "", 0, 5, False, stdout_truncated=True)
    assert backend.finalize(RunOutcome(run=run, events=before), _req()).answer_loss is None


def test_clamped_thinking_level_warns():
    backend = pf.make_backend()
    outcome = _outcome(pf.stream("ok", thinking="high"))
    result = backend.finalize(outcome, _req(reasoning_effort="xhigh"))
    assert result.warnings == (
        "pi ran at thinking level 'high', not the requested 'xhigh'; the model does not "
        "support the requested level.",
    )
    assert backend.finalize(outcome, _req(reasoning_effort="high")).warnings == ()
    assert backend.finalize(outcome, _req()).warnings == ()  # nothing requested


def test_exit_zero_error_stop_reason_is_a_failure_not_a_result():
    backend = pf.make_backend()
    stdout = pf.stream(None, stop="error", errorMessage="401 Unauthorized: bad key")
    failure = backend.inspect_outcome(_outcome(stdout), _req())
    assert failure is not None and failure.code == "pi_auth_required"
    other = pf.stream(None, stop="error", errorMessage="upstream exploded")
    failure = backend.inspect_outcome(_outcome(other, exit_code=1), _req())
    assert failure is not None and failure.code == "nonzero_exit"
    assert "upstream exploded" in failure.detail


def test_empty_zero_exit_run_is_empty_response():
    backend = pf.make_backend()
    failure = backend.inspect_outcome(_outcome(pf.stream(None)), _req())
    assert failure is not None and failure.code == "empty_response"
    assert backend.inspect_outcome(_outcome(""), _req()) is not None
    assert backend.inspect_outcome(_outcome(pf.stream("hi")), _req()) is None
    assert backend.inspect_outcome(_outcome("", exit_code=1), _req()) is None


def test_classify_failure_reads_the_stream_error_and_sanitizes(tmp_path):
    backend = pf.make_backend()
    wt = str(tmp_path / "wt")
    stdout = pf.stream(None, stop="error", errorMessage=f"boom in {wt}/x.py")
    failure = backend.classify_failure(_outcome(stdout, exit_code=1), _req(sanitize_aliases=(wt,)))
    assert failure.code == "nonzero_exit" and wt not in failure.detail
    missing = RunOutcome(run=CommandRun("", runtime.BINARY_NOT_FOUND, 127, 0, False))
    assert backend.classify_failure(missing, _req()).code == "pi_not_found"
    drift = _outcome("", stderr="error: unknown option '--tools'", exit_code=1)
    assert backend.classify_failure(drift, _req()).code == "cli_contract_changed"


# --- the remaining lifecycle -------------------------------------------------------------


def test_list_models_reads_the_catalog():
    assert pf.make_backend().list_models() == (pf.MODEL, pf.NO_THINKING)
    empty = pf.make_backend(catalog=ModelListing(models=(), source="none"))
    assert empty.list_models() == ()


@pytest.mark.parametrize(
    ("state", "expected"),
    [("ready", True), ("not_ready", False), ("unresolved", False), ("unknown", None)],
)
def test_auth_probe_maps_the_configured_model(state, expected):
    calls: list = []
    backend = pf.make_backend({"AMICUS_PI_MODEL": pf.MODEL}, auth=state, calls=calls)
    assert backend.auth_probe() is expected
    assert calls == [("auth", "/PI", pf.MODEL)]


def test_auth_probe_without_a_binary_is_unknown():
    backend = pf.make_backend({"AMICUS_PI_BIN": "/definitely/not/here"})
    assert backend.auth_probe() is None


def test_auth_status_seam_reaches_the_cli_at_call_time(monkeypatch):
    seen = []
    monkeypatch.setattr(
        adapter.cli, "auth_status", lambda binary, model: seen.append((binary, model)) or "ready"
    )
    assert adapter._auth_status("/PI", pf.MODEL) == "ready"
    assert seen == [("/PI", pf.MODEL)]


def test_scrub_env_applies_the_run_environment():
    env = pf.make_backend().scrub_env({"PI_CODING_AGENT_SESSION_DIR": "/x", "HOME": "/h"}, None)
    assert env == {"HOME": "/h", "PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1"}
