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


def test_openrouter_batch_model_is_refused_before_any_probe():
    calls: list = []
    backend = pf.make_backend(calls=calls)
    failure = backend.validate_request(_req(model="openrouter/z-ai/glm-5.3:batch"))
    assert failure is not None and failure.code == "invalid_model"
    assert failure.details is not None and failure.details["catalog"] == "batch_only"
    assert "batch" in failure.detail
    assert calls == []


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


def test_a_missing_binary_skips_the_catalog_so_the_run_reports_not_found():
    """No AMICUS_PI_BIN and no pi on PATH: the binary resolves to the bare literal, the auth
    probe's spawn is binary-missing, and validation steps aside so the run itself reports
    pi_not_found rather than a model error with a dead-end repair."""
    calls: list = []
    backend = pf.make_backend(auth="missing", calls=calls)
    assert backend.validate_request(_req()) is None
    assert calls == [("auth", "/PI", pf.MODEL)]  # the catalog is never asked
    # A missing binary is transient (it may be installed next), so it is not remembered.
    assert backend.validate_request(_req()) is None
    assert calls == [("auth", "/PI", pf.MODEL)] * 2


@pytest.mark.parametrize(
    "environ", [{"AMICUS_PI_BIN": "/definitely/not/here"}, {}], ids=["bad_override", "missing"]
)
def test_an_unprobed_binary_still_runs_the_free_checks(environ):
    """Skipping the probes must not skip the checks that need none: the conformance kit at
    registry load refuses a backend that accepts a bogus effort, which would report pi as
    backend_unavailable instead of letting the run report backend_not_found."""
    calls: list = []
    backend = pf.make_backend({**environ, "AMICUS_PI_MODEL": pf.MODEL}, auth="missing", calls=calls)
    assert conformance.check_backend(contract.CONTRACT, backend) == []
    for effort in ("not-a-level", "high\n"):
        failure = backend.validate_request(_req(reasoning_effort=effort))
        assert failure is not None and failure.code == "invalid_reasoning_effort"
    failure = backend.validate_request(_req(access="danger-full-access"))
    assert failure is not None and failure.code == "invalid_arguments"
    assert all(call[0] == "auth" for call in calls)  # the catalog is never asked


def test_pi_absent_from_path_validates_clean_through_the_real_probe(monkeypatch, tmp_path):
    """The same, end to end through the real resolver and auth probe: PATH holds no pi."""
    spawned: list = []

    def missing(cmd, timeout_seconds, **kwargs):
        spawned.append(cmd)
        return CommandRun("", runtime.BINARY_NOT_FOUND, 127, 0, False)

    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.config import load_config
    from amicus.backends.pi.models import PiModels
    from amicus.sdk.conventions.preflight import HelpProbe

    monkeypatch.setattr(runtime, "run_sync_capture", missing)
    monkeypatch.setenv("PATH", str(tmp_path))
    cfg = load_config({})
    binary = PiBinary(cfg)
    backend = adapter.PiBackend(
        cfg,
        binary,
        HelpProbe(help_argv=("pi", *contract.HELP_ARGS), probe_cwd=lambda: "/probe-cwd"),
        PiModels(cfg, binary),
    )
    assert binary.resolve() == contract.PI_BIN
    assert backend.validate_request(_req()) is None
    assert [cmd[1:3] for cmd in spawned] == [["auth", "check"]]  # no --list-models
    assert backend.auth_probe() is None


@pytest.mark.parametrize("model", ["-h", "--list-models", "@notes.md", "@"])
def test_a_flag_or_file_shaped_model_is_refused_before_any_probe(model):
    """The model is spliced into the probes' argv as a bare token, where pi would read a
    leading "-" as a flag and a leading "@" as a file argument."""
    calls: list = []
    backend = pf.make_backend(calls=calls)
    failure = backend.validate_request(_req(model=model))
    assert failure is not None and failure.code == "invalid_model"
    assert failure.details is not None and failure.details["field"] == "model"
    assert failure.repair is not None and failure.repair.tool == "amicus_models"
    assert len(model) == 1 or model not in failure.detail  # never echoed
    assert calls == []
    configured = pf.make_backend({"AMICUS_PI_MODEL": f"{model}/x"}, calls=calls)
    refused = configured.validate_request(_req(model=None))
    assert refused is not None and refused.code == "invalid_model"
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
        {"model": "--help"},
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


def test_a_capture_loss_outranks_a_length_stop():
    """When amicus's capture also lost output, that is the account to give: the stream
    amicus holds cannot vouch that the length stop was the run's last word."""
    backend = pf.make_backend()
    stdout = pf.stream("partial", stop="length") + "[output truncated]\n"
    run = CommandRun(stdout, "", 0, 5, False, stdout_truncated=True)
    assert backend.finalize(RunOutcome(run=run, events=stdout), _req()).answer_loss == "truncated"
    run = CommandRun(stdout, "", 0, 5, False, stdout_capture_failed=True)
    loss = backend.finalize(RunOutcome(run=run, events=stdout), _req()).answer_loss
    assert loss == "capture_failed"


@pytest.mark.parametrize(
    ("text", "schema"),
    [("a prose answer cut off mid-sent", None), ('{"summary": "ok", "findings": []}', {})],
    ids=["prose", "structured"],
)
def test_a_length_stop_marks_the_model_output_limit(text, schema):
    """pi reports a response cut off by the output-token limit as stopReason "length": the
    answer, even one that parses as complete JSON, is not the whole answer (Ruling 16), and
    the loss is the model's limit rather than amicus's capture cap (#425)."""
    req = _req(schema={"type": "object"}) if schema is not None else _req()
    backend = pf.make_backend()
    cut = backend.finalize(_outcome(pf.stream(text, stop="length")), req)
    assert cut.answer_loss == "model_output_limit"
    whole = backend.finalize(_outcome(pf.stream(text, stop="stop")), req)
    assert whole.answer_loss is None
    assert backend.inspect_outcome(_outcome(pf.stream(text, stop="length")), req) is None


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
    failure = backend.inspect_outcome(_outcome(other), _req())
    assert failure is not None
    assert failure.detail == "pi stopped with reason 'error': upstream exploded"


def test_an_aborted_stop_at_exit_zero_names_the_stop_reason():
    failure = pf.make_backend().inspect_outcome(_outcome(pf.stream(None, stop="aborted")), _req())
    assert failure is not None and failure.code == "nonzero_exit"
    assert failure.detail == (
        "pi stopped with reason 'aborted' and wrote no error message and nothing to stderr."
    )


@pytest.mark.parametrize("stop", [["x"], {"x": 1}])
def test_a_non_string_stop_reason_with_an_answer_is_a_normal_result(stop):
    """#438: an unhashable stopReason crashed inspect_outcome, so the worker reported
    internal_error and lost a usable answer."""
    backend = pf.make_backend()
    outcome = _outcome(pf.stream("hi", stopReason=stop))
    assert backend.inspect_outcome(outcome, _req()) is None
    assert backend.finalize(outcome, _req()).answer == "hi"


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
        adapter.cli,
        "auth_status",
        lambda binary, model, cwd=None: seen.append((binary, model, cwd)) or "ready",
    )
    assert adapter._auth_status("/PI", pf.MODEL, cwd="/probe") == "ready"
    assert seen == [("/PI", pf.MODEL, "/probe")]


def test_scrub_env_applies_the_run_environment():
    env = pf.make_backend().scrub_env({"PI_CODING_AGENT_SESSION_DIR": "/x", "HOME": "/h"}, None)
    assert env == {"HOME": "/h", "PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1"}


# --- Ruling 7: the stop reason, not the message, is the failure signal ------------------------


@pytest.mark.parametrize("message", [None, "  "])
def test_error_stop_without_a_message_is_a_failure_even_with_partial_text(message):
    extra = {} if message is None else {"errorMessage": message}
    stdout = pf.stream("partial answer", stop="error", **extra)
    failure = pf.make_backend().inspect_outcome(_outcome(stdout), _req())
    assert failure is not None and failure.code == "nonzero_exit"


def test_aborted_stop_is_a_failure():
    stdout = pf.stream("partial answer", stop="aborted")
    failure = pf.make_backend().inspect_outcome(_outcome(stdout), _req())
    assert failure is not None and failure.code != "empty_response"


def test_error_stop_with_no_text_is_not_empty_response():
    stdout = pf.stream(None, stop="error")
    failure = pf.make_backend().inspect_outcome(_outcome(stdout), _req())
    assert failure is not None and failure.code == "nonzero_exit"


@pytest.mark.parametrize(("stop", "exit_code"), [("error", 0), ("aborted", 0), ("stop", 1)])
def test_a_failure_detail_never_echoes_the_stream(stop, exit_code):
    """The stream echoes the user message, so with no errorMessage and no stderr the detail
    must not fall back to stdout (rule 18)."""
    user = pf.line(
        {
            "type": "message_end",
            "message": {"role": "user", "content": [{"type": "text", "text": "SENTINEL-Q"}]},
        }
    )
    stdout = pf.SESSION + user + pf.assistant_end("partial", stop=stop)
    backend = pf.make_backend()
    failure = backend.classify_failure(_outcome(stdout, exit_code=exit_code), _req())
    assert failure.code == "nonzero_exit" and "SENTINEL" not in failure.detail
    with_stderr = _outcome(stdout, stderr="provider said no", exit_code=exit_code)
    assert "provider said no" in backend.classify_failure(with_stderr, _req()).detail


# --- Ruling 6: the per-call probes are cached for HELP_CACHE_TTL_SECONDS, by model -----------

OTHER = "openrouter/moonshotai/kimi-k3.1-pro"
_TABLE = (
    "provider    model                     context  max-out  thinking  images\n"
    "openrouter  moonshotai/kimi-k3        1.0M     943.7K   yes       yes\n"
    "openrouter  moonshotai/kimi-k3.1-pro  1.0M     943.7K   yes       yes\n"
)


def _spawning_backend(monkeypatch, *, auth_out: str = '{"status":"ready"}', list_exit: int = 0):
    """A backend whose probes run the real cli/models code over a counting spawn seam."""
    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.config import load_config
    from amicus.backends.pi.models import PiModels
    from amicus.sdk.conventions.preflight import HelpProbe

    spawned: list[tuple[str, str]] = []

    def fake(cmd, timeout_seconds, **kwargs):
        if cmd[1:3] == ["auth", "check"]:
            spawned.append(("auth", cmd[cmd.index("--model") + 1]))
            return CommandRun(auth_out, "", 0, 1, False)
        assert cmd[1] == "--list-models", cmd
        spawned.append(("lookup", cmd[2]))
        return CommandRun(_TABLE if list_exit == 0 else "", "", list_exit, 1, False)

    monkeypatch.setattr(runtime, "run_sync_capture", fake)
    cfg = load_config({"AMICUS_PI_BIN": "/PI"})
    binary = PiBinary(cfg)
    binary.resolve = lambda: "/PI"  # type: ignore[method-assign]
    backend = adapter.PiBackend(
        cfg,
        binary,
        HelpProbe(help_argv=("/PI", *contract.HELP_ARGS), probe_cwd=lambda: "/probe-cwd"),
        PiModels(cfg, binary),
    )
    return backend, spawned


def test_repeated_validation_of_one_model_probes_once(monkeypatch):
    backend, spawned = _spawning_backend(monkeypatch)
    assert backend.validate_request(_req()) is None
    assert backend.validate_request(_req(reasoning_effort="high")) is None
    assert spawned == [("auth", pf.MODEL), ("lookup", pf.MODEL)]
    assert backend.validate_request(_req(model=OTHER)) is None
    assert spawned[2:] == [("auth", OTHER), ("lookup", OTHER)]


def test_conformance_at_load_spawns_each_probe_once(monkeypatch):
    from amicus.backends.pi.config import load_config

    backend, spawned = _spawning_backend(monkeypatch)
    configured = adapter.PiBackend(
        load_config({"AMICUS_PI_BIN": "/PI", "AMICUS_PI_MODEL": pf.MODEL}),
        backend._binary,
        backend._help_probe,
        backend._models,
    )
    assert conformance.check_backend(contract.CONTRACT, configured) == []
    assert spawned == [("auth", pf.MODEL), ("lookup", pf.MODEL)]


def test_the_cache_expires_after_the_ttl(monkeypatch):
    from amicus.backends.pi.models import HELP_CACHE_TTL_SECONDS

    backend, spawned = _spawning_backend(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])
    assert backend.validate_request(_req()) is None
    clock[0] += HELP_CACHE_TTL_SECONDS - 1
    assert backend.validate_request(_req()) is None
    assert len(spawned) == 2
    clock[0] += 2
    assert backend.validate_request(_req()) is None
    assert len(spawned) == 4


def test_an_unknown_auth_state_is_not_cached(monkeypatch):
    backend, spawned = _spawning_backend(monkeypatch, auth_out="not json")
    assert backend.validate_request(_req()) is None
    assert backend.validate_request(_req()) is None
    # The lookup that followed the unknown auth state was cached; the auth state was not.
    assert spawned == [("auth", pf.MODEL), ("lookup", pf.MODEL), ("auth", pf.MODEL)]


def test_an_unreadable_catalog_is_not_cached(monkeypatch):
    backend, spawned = _spawning_backend(monkeypatch, list_exit=1)
    for _ in range(2):
        failure = backend.validate_request(_req())
        assert failure is not None and failure.details["catalog"] == "unreadable"
    assert spawned == [("auth", pf.MODEL), ("lookup", pf.MODEL), ("lookup", pf.MODEL)]


def test_the_memo_is_bounded_by_distinct_models(monkeypatch):
    backend, spawned = _spawning_backend(monkeypatch)
    monkeypatch.setattr(adapter, "_PROBE_CACHE_MAX_MODELS", 2)
    for model in (pf.MODEL, OTHER, "openrouter/x/y"):
        backend.validate_request(_req(model=model))
    assert set(backend._auth_memo) == {"openrouter/x/y"}
    assert set(backend._lookup_memo) == {"openrouter/x/y"}
    spawned.clear()
    assert backend.validate_request(_req()) is None  # forgotten, so probed again
    assert spawned == [("auth", pf.MODEL), ("lookup", pf.MODEL)]


def test_a_model_past_a_truncated_listing_is_checked_by_its_own_lookup(monkeypatch):
    """#443: the listing amicus_models shows stops at MAX_ENTRIES, but validate_request asks
    pi about the exact model, so a row past the cut is accepted and its efforts enforced."""
    from amicus.backends.pi import models as pi_models
    from amicus.plugin import ModelEntry

    header = "provider    model     context  max-out  thinking  images"
    filler = [f"filler      m{i:04d}     1K       1K       yes       no" for i in range(1100)]
    late = "late        plain     1K       1K       no        no"

    def probe(_binary, *terms, cwd):
        rows = [*filler, late]
        if terms:
            rows = [r for r in rows if terms[0] in "/".join(r.split()[:2])]
        return "\n".join([header, *rows]) + "\n"

    monkeypatch.setattr(pi_models, "_probe", probe)
    monkeypatch.setattr(pi_models, "probe_cwd", lambda _cfg: "/probe-cwd")
    backend = pf.make_backend()
    real = pi_models.PiModels(backend._config, backend._binary)
    backend._models = real
    listing = real.read()
    assert listing.truncated is True
    assert "late/plain" not in {e.slug for e in listing.models}
    assert real.lookup("late/plain") == ModelEntry(
        slug="late/plain", supported_reasoning_efforts=("off",)
    )
    assert backend.validate_request(_req(model="late/plain")) is None
    refused = backend.validate_request(_req(model="late/plain", reasoning_effort="high"))
    assert refused is not None and refused.code == "invalid_reasoning_effort"
    assert refused.details == {"field": "reasoning_effort", "allowed_values": ["off"]}
