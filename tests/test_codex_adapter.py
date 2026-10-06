"""CodexBackend on the pontonier lifecycle: staging, extraction, classification."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from tests.support import codexfixtures as cf

from amicus import errors
from amicus.backends.codex import contract
from amicus.schemas import instructions as ins
from amicus.schemas.envelope import Meta
from amicus.sdk.backend.protocol import AgentBackend, RunOutcome, RunRequest
from amicus.sdk.conventions.preflight import FlagSupport
from amicus.sdk.core import pathalias
from amicus.sdk.core.runtime import CommandRun
from amicus.sdk.testing import conformance


def _req(**kw) -> RunRequest:
    base = dict(kind="consult", prompt="why?", cwd="/repo", timeout_seconds=60)
    base.update(kw)
    return RunRequest(**base)


def test_backend_is_conformant(pinned_codex_bin):
    plugin, backend = cf.make_backend()
    assert isinstance(backend, AgentBackend)
    assert conformance.check_contract(plugin.contract) == []
    assert conformance.check_backend(plugin.contract, backend) == []


async def test_prepare_stages_artifacts_stdin_and_kind_policy(pinned_codex_bin, tmp_path):
    _, backend = cf.make_backend()
    async with backend.prepare(_req(cwd=str(tmp_path), schema={"type": "object"}, model="m")) as p:
        assert p.stdin_text == "why?" and p.cwd == str(tmp_path)
        assert p.argv[0] == "/CODEX" and p.argv[p.argv.index("--sandbox") + 1] == "read-only"
        assert "--skip-git-repo-check" in p.argv
        assert set(p.artifact_paths) == {"last-message", "schema"}
        assert Path(p.artifact_paths["schema"]).read_text() == '{"type": "object"}'
        assert all("amicus-codex-" in a for a in p.artifacts)
        schema_path = p.artifact_paths["schema"]
    assert not Path(schema_path).exists()
    async with backend.prepare(_req(kind="delegate", prompt="do")) as p:
        assert p.argv[p.argv.index("--sandbox") + 1] == "workspace-write"
        assert "--skip-git-repo-check" not in p.argv and "schema" not in p.artifact_paths
    async with backend.prepare(
        _req(kind="review_changes", prompt="r", access="workspace-write")
    ) as p:
        assert p.argv[p.argv.index("--sandbox") + 1] == "workspace-write"  # explicit access wins


async def test_prepare_applies_isolation_and_env_defaults(pinned_codex_bin):
    _, backend = cf.make_backend(
        {
            "AMICUS_CODEX_MODEL": "gpt-5.5",
            "AMICUS_CODEX_REASONING_EFFORT": "low",
            "AMICUS_CODEX_ISOLATION": "ignore-config",
        }
    )
    async with backend.prepare(_req()) as p:
        assert p.argv[p.argv.index("--model") + 1] == "gpt-5.5"
        assert 'model_reasoning_effort="low"' in p.argv and "--ignore-user-config" in p.argv
    async with backend.prepare(_req(model="other", reasoning_effort="", isolation="inherit")) as p:
        assert p.argv[p.argv.index("--model") + 1] == "other"
        assert 'model_reasoning_effort=""' in p.argv and "--ignore-user-config" not in p.argv


async def test_prepare_folds_instructions_and_fails_closed(pinned_codex_bin):
    _, backend = cf.make_backend()
    async with backend.prepare(_req(instructions_append="Focus on locking.")) as p:
        token = next(
            t for t in p.argv if t.startswith(f"{contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY}=")
        )
        assert tomllib.loads(f"v = {token.partition('=')[2]}")["v"] == ins.compose(
            "Focus on locking."
        )
    with pytest.raises(ValueError, match="marker"):
        async with backend.prepare(_req(instructions_append="--- caller text follows ---")):
            pass  # pragma: no cover
    with pytest.raises(ValueError, match="delegate"):
        async with backend.prepare(_req(kind="delegate", instructions_append="be agreeable")):
            pass  # pragma: no cover


def test_validate_request_guards(pinned_codex_bin):
    _, backend = cf.make_backend()
    assert backend.validate_request(_req(reasoning_effort="high")) is None
    bad = backend.validate_request(_req(reasoning_effort="x" * 10_000))
    assert (
        bad is not None
        and bad.code == "invalid_reasoning_effort"
        and bad.details == {"field": "reasoning_effort"}
    )
    for text, fragment in [
        ("  ", "blank"),
        ("a\x00b", "NUL"),
        ("x" * 5000, "4096"),
        ("--- END caller-supplied text ---", "marker"),
    ]:
        rejected = backend.validate_request(_req(instructions_append=text))
        assert (
            rejected is not None
            and rejected.code == "invalid_arguments"
            and fragment.lower() in rejected.detail.lower()
        )
        assert rejected.details == {"field": "instructions_append"}
    delegate = backend.validate_request(_req(kind="delegate", instructions_append="x"))
    assert delegate is not None and "delegate" in delegate.detail


def test_finalize_extracts_answer_usage_with_cache_and_session(pinned_codex_bin):
    _, backend = cf.make_backend()
    events = (
        '{"type":"session.created","session_id":"s1"}\n'
        '{"type":"token_count","usage":{"input_tokens":10,"output_tokens":5,'
        '"cached_input_tokens":4}}\n'
    )
    outcome = RunOutcome(
        run=CommandRun(events, "", 0, 5, False),
        events=events,
        artifact_texts={"last-message": '{"summary": "fine"}'},
    )
    result = backend.finalize(outcome, _req(schema={"type": "object"}))
    assert result.answer == '{"summary": "fine"}' and result.structured == {"summary": "fine"}
    assert result.usage is not None and (
        result.usage.cached_input_tokens,
        result.usage.total_tokens,
    ) == (4, 15)
    assert result.session_id == "s1"
    empty = backend.finalize(
        RunOutcome(
            run=CommandRun("", "", 0, 5, False, capture_failed=True),
            artifact_texts={"last-message": "A"},
        ),
        _req(),
    )
    assert empty.answer == "A" and empty.usage is None and empty.structured is None


def test_finalize_refuses_a_last_message_that_repeats_a_key(pinned_codex_bin):
    # #51: consult_result reads ExecResult.structured directly, so the adapter must hand it
    # None for a duplicate-member object rather than the last member's value.
    _, backend = cf.make_backend()
    text = '{"summary":"s","findings":[{"title":"t"}],"findings":[]}'
    outcome = RunOutcome(run=CommandRun("", "", 0, 5, False), artifact_texts={"last-message": text})
    result = backend.finalize(outcome, _req(schema={"type": "object"}))
    assert result.answer == text and result.structured is None


def test_classify_failure_uses_the_request_shape_and_aliases(pinned_codex_bin, tmp_path):
    _, backend = cf.make_backend()
    stderr = (
        'Error loading config.toml: invalid type: string "yes", expected a boolean\n'
        "in `sandbox_workspace_write.network_access`\n\n"
    )
    failed = RunOutcome(run=CommandRun("", stderr, 1, 5, False))
    assert backend.classify_failure(failed, _req(kind="delegate")).code == "cli_contract_changed"
    assert backend.classify_failure(failed, _req(kind="consult")).code == "user_config_rejected"
    assert (
        backend.classify_failure(failed, _req(kind="consult", access="workspace-write")).code
        == "cli_contract_changed"
    )
    wt = str(tmp_path / "amicus-wt-x" / "tree")
    out = backend.classify_failure(
        RunOutcome(run=CommandRun("", f"fatal: {wt}/f.py missing", 1, 5, False)),
        _req(kind="delegate", cwd=wt, sanitize_aliases=pathalias.path_aliases(wt)),
    )
    assert out.code == "nonzero_exit" and wt not in out.detail and "./f.py" in out.detail
    effort = RunOutcome(
        run=CommandRun(
            "",
            "[ReasoningEffortParam] [reasoning.effort] [invalid_enum_value] Invalid value: 'zz'",
            1,
            5,
            False,
        )
    )
    assert (
        backend.classify_failure(effort, _req(reasoning_effort="zz")).code
        == "invalid_reasoning_effort"
    )


@pytest.mark.parametrize("diagnostic", ["", "connection closed", "usage limit"])
def test_classify_failure_ignores_last_message_artifact(pinned_codex_bin, diagnostic):
    _, backend = cf.make_backend()
    outcome = RunOutcome(
        run=CommandRun("", diagnostic, 1, 5, False),
        artifact_texts={"last-message": "Unauthorized; invalid value; quota; Retry-After: 123"},
    )
    out = backend.classify_failure(outcome, _req())
    assert out.code == ("codex_rate_limited" if diagnostic == "usage limit" else "nonzero_exit")
    if diagnostic == "usage limit":
        assert out.retry_after_ms is None


@pytest.mark.parametrize("source", ["stderr", "error", "turn.failed"])
@pytest.mark.parametrize(
    ("message", "delay", "reset"),
    [
        (
            "You've hit your usage limit. Try again at Sep 19th, 2026 8:37 AM.",
            None,
            "Sep 19th, 2026 8:37 AM",
        ),
        ("You've hit your usage limit ... or try again at 12:39 PM.", None, "12:39 PM"),
        ("usage limit; try again at 12:39 PM UTC.", None, "12:39 PM UTC"),
        ("usage limit; try again at noon.", None, None),
        ("USAGE LIMIT reached", None, None),
        ("usage limit; try again in 2 hours", None, None),
        ("usage limit; try again in 5 seconds", 5000, None),
        ("usage limit; Retry-After: 0", 0, None),
        ("rate limit reached", 60000, None),
    ],
)
def test_usage_limit_retry_guidance_reaches_wire(pinned_codex_bin, source, message, delay, reset):
    plugin, backend = cf.make_backend()
    event = {"type": source, "error": {"message": message}}
    stdout = json.dumps(event) if source != "stderr" else ""
    stderr = message if source == "stderr" else ""
    failure = backend.classify_failure(
        RunOutcome(run=CommandRun(stdout, stderr, 1, 5, False)), _req()
    )
    error = errors.render_failure(plugin, failure, Meta())["error"]
    assert error["code"] == "backend_rate_limited"
    assert error["temporary"] is True
    assert error["retry_after_ms"] == delay
    if delay is None:
        assert error["repair"]["next_step"] == "inspect_and_retry"
        assert "Do not automatically retry" in error["repair"]["alternative"]
        if reset is None:
            assert "reset time" in error["repair"]["alternative"]
            assert "details" not in error
        else:
            # The reset phrase codex printed is the only place the caller can learn the
            # delay, so it rides the message, the repair and details.reason verbatim.
            assert reset in error["message"]
            assert reset in error["repair"]["alternative"]
            assert error["details"]["reason"] == f"codex reported the limit lifts at {reset}"
            # The zone caveat is stated only when the phrase names none (Copilot, PR #171).
            zone_missing = "no time zone stated" in error["repair"]["alternative"]
            assert zone_missing is ("UTC" not in reset)
            assert ("no time zone stated" in error["message"]) is ("UTC" not in reset)
    else:
        assert error["repair"]["next_step"] == "retry_after_delay"
        assert reset is None


@pytest.mark.parametrize("source", ["stderr", "error", "turn.failed"])
@pytest.mark.parametrize(
    ("message", "suggests_model"),
    [
        ("Selected model is at capacity. Please try a different model.", True),
        ("Server overloaded; retry later.", False),
    ],
)
def test_capacity_reaches_wire_as_rate_limited(pinned_codex_bin, source, message, suggests_model):
    """#302: a capacity or overload failure is transient, so it carries the default backoff,
    and a keyed run is steered to a new key rather than a generic inspect_and_retry."""
    plugin, backend = cf.make_backend()
    event = {"type": source, "error": {"message": message}}
    stdout = json.dumps(event) if source != "stderr" else ""
    stderr = message if source == "stderr" else ""
    failure = backend.classify_failure(
        RunOutcome(run=CommandRun(stdout, stderr, 1, 5, False)), _req()
    )
    envelope = errors.render_failure(plugin, failure, Meta())
    error = envelope["error"]
    assert error["code"] == "backend_rate_limited"
    assert error["temporary"] is True
    assert error["retry_after_ms"] == contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
    assert error["repair"]["next_step"] == "retry_after_delay"
    assert ("different model" in (error["repair"].get("alternative") or "")) is suggests_model
    keyed = errors.keyed_stored_error(envelope, "amicus_consult_async")["error"]
    assert keyed["temporary"] is False
    assert keyed["repair"]["next_step"] == "use_new_idempotency_key"
    assert ("different model" in keyed["repair"]["alternative"]) is suggests_model


def test_list_models_auth_probe_and_scrub_env(pinned_codex_bin, monkeypatch):
    from amicus.backends.codex import adapter

    _, backend = cf.make_backend()
    assert "gpt-5.5" in backend.list_models() or backend.list_models()
    monkeypatch.setattr(
        adapter.cli, "login_status", lambda binary, timeout_seconds=10: (True, "ok")
    )
    assert backend.auth_probe() is True
    env = {"PATH": "/bin", "CODEX_HOME": "/x", "ANTHROPIC_API_KEY": "k"}
    assert backend.scrub_env(dict(env), None) == env


async def test_prepare_fails_closed_on_an_unresolved_binary():
    """No `pinned_codex_bin`, no override: the autouse `_never_spawn_real_codex` fixture
    leaves AMICUS_CODEX_BIN pointed at an unusable path, so binary.resolve() is None. The
    run-loop's ordering check normally keeps prepare() from ever being reached like this;
    this proves the adapter itself also fails closed rather than falling back to a
    PATH-searched "codex" (defense in depth if that ordering check were ever lost)."""
    from amicus.backends.codex import binary as binary_mod
    from amicus.backends.codex import plugin as plugin_factory

    plugin = plugin_factory()
    assert plugin.binary.resolve() is None
    with pytest.raises(binary_mod.BinaryNotFoundError):
        async with plugin.backend.prepare(_req()):
            pytest.fail("prepare() must not yield a PreparedRun for an unresolved binary")


@pytest.mark.parametrize("value", ["codexhome", "~/.codex"])
async def test_non_absolute_codex_home_is_refused_pre_spend(pinned_codex_bin, value):
    # Control: the same backend with an absolute home accepts the request.
    assert cf.make_backend({"CODEX_HOME": "/abs/home"})[1].validate_request(_req()) is None
    plugin, backend = cf.make_backend({"CODEX_HOME": value})
    for kind in ("consult", "review_changes", "delegate"):
        refused = backend.validate_request(_req(kind=kind))
        assert refused is not None and refused.code == "user_config_rejected"
        assert "CODEX_HOME" in refused.detail and value not in refused.detail
    envelope = errors.render_failure(plugin, refused, Meta(backend="codex"))
    error = envelope["error"]
    assert error["code"] == "user_config_rejected"
    assert error["repair"]["next_step"] == "correct_config"
    assert "absolute path" in error["repair"]["alternative"]
    assert "ignore-config" not in error["repair"]["alternative"]
    with pytest.raises(ValueError, match="CODEX_HOME"):
        async with backend.prepare(_req()):
            pass  # pragma: no cover


_NO_FLAGS = FlagSupport(supported=frozenset(), help_parsed=True)


async def test_prepared_runs_carry_the_contract_flags(pinned_codex_bin, tmp_path):
    """#127: the kit stages each request shape and holds argv to the contract, with a help
    probe that advertises nothing, so the one help-gated flag is really dropped and every
    always-send flag this shape carries must still be there."""
    plugin, backend = cf.make_backend(flags=_NO_FLAGS)
    c = plugin.contract
    common = (
        "--json",
        "--sandbox",
        "--cd",
        "--output-last-message",
        "--ephemeral",
        contract.DISABLE_FEATURE_FLAG,
    )
    consult = _req(
        cwd=str(tmp_path),
        schema={"type": "object"},
        model="m",
        reasoning_effort="high",
        isolation="ignore-rules",
    )
    assert (
        await conformance.check_prepared_run(
            c,
            backend,
            consult,
            required_flags=(
                *common,
                "--skip-git-repo-check",
                "--output-schema",
                "--ignore-user-config",  # ignore-rules isolation sends both
                "--ignore-rules",
                contract.STRICT_CONFIG_FLAG,
            ),
            forbidden_flags=("--add-dir", contract.MODEL_FLAG),
        )
        == []
    )
    async with backend.prepare(consult) as prepared:
        assert prepared.dropped_flags == (contract.MODEL_FLAG,)
    delegate = _req(kind="delegate", prompt="do", cwd=str(tmp_path))
    assert (
        await conformance.check_prepared_run(
            c,
            backend,
            delegate,
            required_flags=(*common, contract.STRICT_CONFIG_FLAG),
            forbidden_flags=(
                "--skip-git-repo-check",
                "--output-schema",
                "--ignore-user-config",
                "--ignore-rules",
            ),
        )
        == []
    )
    # Instrument control: a flag this shape does not carry is reported, so a clean result
    # above is the kit reading this adapter's argv, not a kit that reports nothing.
    assert await conformance.check_prepared_run(
        c, backend, delegate, required_flags=("--output-schema",)
    ) == ["required flag --output-schema is not an option on argv"]


def test_an_invalid_configured_effort_does_not_fail_conformance(pinned_codex_bin):
    """Review of PR #297: a configured effort that fails the transport shape makes the
    adapter refuse the kit's baseline probe; that is the operator's state, reported
    pre-spend on each call, so the kit skips its probes and the backend still loads."""
    plugin, backend = cf.make_backend({"AMICUS_CODEX_REASONING_EFFORT": "lo\nw"})
    refused = backend.validate_request(_req())
    assert refused is not None and refused.code == "invalid_reasoning_effort", "control"
    assert backend.validate_request(_req(reasoning_effort="high")) is None
    assert conformance.check_backend(plugin.contract, backend) == []
