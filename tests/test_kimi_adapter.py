"""KimiBackend on the pontonier lifecycle: staging, the effort gate, extraction, the empty
answer inspection, and classification with the site sanitizer."""

from __future__ import annotations

from pathlib import Path

import pytest
from pontonier.backend.protocol import AgentBackend, OutcomeInspector, RunOutcome, RunRequest
from pontonier.core.runtime import CommandRun
from pontonier.testing import conformance
from tests.support import kimifixtures as kf

from amicus.backends.kimi import cli, contract
from amicus.schemas import instructions as ins

STRUCTURED = '{"summary": "Looks fine", "verdict": "pass", "confidence": "high", "findings": []}'
EVENTS = (
    '{"role":"meta","type":"system.version","version":"0.41.0"}\n'
    '{"role":"assistant","content":"from the stream"}\n'
    '{"role":"meta","type":"session.resume_hint","session_id":"session_x"}\n'
)


def _req(**kw) -> RunRequest:
    base = dict(kind="consult", prompt="why?", cwd="/repo/some/where", timeout_seconds=60)
    base.update(kw)
    return RunRequest(**base)


def test_backend_is_conformant(pinned_kimi_bin):
    plugin, backend = kf.make_backend()
    assert isinstance(backend, AgentBackend) and isinstance(backend, OutcomeInspector)
    assert conformance.check_contract(plugin.contract) == []
    assert conformance.check_backend(plugin.contract, backend) == []


def test_a_perturbed_backend_fails_conformance(pinned_kimi_bin):
    plugin, backend = kf.make_backend()

    class AcceptsAnything(type(backend)):  # type: ignore[misc]
        def validate_request(self, request):
            return None

    loose = AcceptsAnything(backend._config, backend._binary, backend._help_probe, backend._models)
    assert any(
        "bogus reasoning_effort" in v for v in conformance.check_backend(plugin.contract, loose)
    )

    class Raises(type(backend)):  # type: ignore[misc]
        def inspect_outcome(self, outcome, request):
            raise RuntimeError("boom")

    bad = Raises(backend._config, backend._binary, backend._help_probe, backend._models)
    assert any(
        "inspect_outcome raised" in v for v in conformance.check_backend(plugin.contract, bad)
    )


async def test_prepare_stages_a_read_only_run(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend({"AMICUS_STATE_DIR": str(tmp_path / "state")})
    async with backend.prepare(_req(cwd=str(tmp_path), schema={"type": "object"}, model="k3")) as p:
        assert p.stdin_text is None and p.cwd == str(tmp_path) and p.orphan_marker == str(tmp_path)
        assert p.argv[0] == "/KIMI" and p.argv[1] == "--prompt"
        agent = p.argv[p.argv.index("--agent-file") + 1]
        assert Path(agent).read_text() == cli.read_only_agent_document()
        assert p.argv[p.argv.index("--model") + 1] == "k3" and "--skills-dir" not in p.argv
        pointer = p.argv[2]
        prompt_path = pointer.split("Read the file ", 1)[1].split(" and follow", 1)[0]
        text = Path(prompt_path).read_text()
        assert text.startswith("why?") and "# Required output format" in text
        assert contract.HANDSHAKE_DIR_PREFIX in prompt_path and str(tmp_path) not in prompt_path
        assert p.artifact_paths == {} and all(
            contract.HANDSHAKE_DIR_PREFIX in a for a in p.artifacts
        )
        assert p.env["KIMI_MODEL_OUTPUT_FORMAT"] == "stream-json"
        assert "KIMI_MODEL_THINKING_EFFORT" not in p.env
    assert not Path(prompt_path).exists()


async def test_prepare_stages_a_delegate_run_and_applies_env_defaults(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend(
        {
            "AMICUS_KIMI_MODEL": "k3",
            "AMICUS_KIMI_REASONING_EFFORT": "low",
            "AMICUS_KIMI_ISOLATION": "ignore-skills",
            "AMICUS_STATE_DIR": str(tmp_path / "state"),
        }
    )
    async with backend.prepare(_req(kind="delegate", prompt="do", cwd=str(tmp_path))) as p:
        assert "--agent-file" not in p.argv and "answer" in p.artifact_paths
        assert p.artifact_paths["answer"].endswith(contract.ANSWER_FILE_NAME)
        assert p.argv[p.argv.index("--model") + 1] == "k3"
        assert p.argv[p.argv.index("--skills-dir") + 1] == str(tmp_path / "state" / "empty-skills")
        assert p.env["KIMI_MODEL_THINKING_EFFORT"] == "low"
        assert "write your final answer to" in p.argv[2]
    async with backend.prepare(
        _req(kind="delegate", prompt="do", cwd=str(tmp_path), access="read-only")
    ) as p:
        assert "--agent-file" in p.argv  # explicit access wins


async def test_prepare_prepends_composed_instructions(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend()
    async with backend.prepare(
        _req(cwd=str(tmp_path), instructions_append="Focus on locking.")
    ) as p:
        prompt_path = p.argv[2].split("Read the file ", 1)[1].split(" and follow", 1)[0]
        text = Path(prompt_path).read_text()
    assert text.startswith(ins.compose("Focus on locking.")) and text.endswith("why?")


async def test_prepare_help_gates_model_and_fails_closed(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend(flags=kf.NO_MODEL)
    async with backend.prepare(_req(cwd=str(tmp_path), model="k3")) as p:
        assert "--model" not in p.argv and p.dropped_flags == ("--model",)
    with pytest.raises(ValueError):
        async with backend.prepare(_req(cwd=str(tmp_path), reasoning_effort="bogus-level")):
            pass  # pragma: no cover
    _, unresolved = kf.make_backend({"AMICUS_KIMI_BIN": str(tmp_path / "missing")})
    from amicus.backends.kimi.binary import BinaryNotFoundError

    with pytest.raises(BinaryNotFoundError):
        async with unresolved.prepare(_req(cwd=str(tmp_path))):
            pass  # pragma: no cover


def test_validate_request_catalog_first_then_fallback_then_fail_open(pinned_kimi_bin):
    _, catalog = kf.make_backend(catalog=kf.K3)
    assert catalog.validate_request(_req(model="k3", reasoning_effort="high")) is None
    refused = catalog.validate_request(_req(model="k3", reasoning_effort="xhigh"))
    assert refused is not None and refused.code == "invalid_reasoning_effort"
    assert refused.details == {
        "field": "reasoning_effort",
        "allowed_values": ["low", "medium", "high"],
    }
    assert refused.repair is not None and refused.repair.tool == "amicus_models"
    assert catalog.validate_request(_req(model="unlisted", reasoning_effort="xhigh")) is None
    # A live catalog that does not list the alias: kimi will reject the alias itself
    # (invalid_model), so no effort verdict is issued here — fail open, no vocabulary check.
    assert catalog.validate_request(_req(model="unlisted", reasoning_effort="nope")) is None
    # A listed alias with no effort metadata is "cannot tell": the vocabulary decides.
    assert catalog.validate_request(_req(model="bare", reasoning_effort="max")) is None
    assert catalog.validate_request(_req(model="bare", reasoning_effort="nope")) is not None
    _, silent = kf.make_backend(catalog=kf.SILENT)
    assert silent.validate_request(_req(reasoning_effort="xhigh")) is None
    # Silent catalog: nothing authoritative, so the vocabulary decides even for a named alias.
    assert silent.validate_request(_req(model="unlisted", reasoning_effort="nope")) is not None
    fallback = silent.validate_request(_req(reasoning_effort="not-a-real-effort-level"))
    assert fallback is not None and fallback.details["allowed_values"] == sorted(
        contract.REASONING_EFFORT_FALLBACK_VOCABULARY
    )
    assert silent.validate_request(_req(reasoning_effort=" HIGH ")) is not None  # exact value
    assert silent.validate_request(_req()) is None
    shape = silent.validate_request(_req(reasoning_effort="x" * 200))
    assert shape is not None and "exceeds" in shape.detail
    _, from_env = kf.make_backend({"AMICUS_KIMI_REASONING_EFFORT": "zzz"})
    assert from_env.validate_request(_req()) is not None
    assert from_env.validate_request(_req(reasoning_effort="low")) is None


def test_validate_request_refuses_an_unexpected_access_posture(pinned_kimi_bin):
    _, backend = kf.make_backend()
    for bad in ("readonly", "toolless", "garbage"):
        refused = backend.validate_request(_req(access=bad))
        assert refused is not None and refused.code == "invalid_arguments"
        assert refused.details == {"field": "access"}
        assert bad not in refused.detail
    assert backend.validate_request(_req(access=contract.SANDBOX_READ_ONLY)) is None
    assert backend.validate_request(_req(access=contract.SANDBOX_WORKSPACE_WRITE)) is None
    assert backend.validate_request(_req(access=None)) is None


def test_read_only_fails_closed_on_an_unexpected_access_posture(pinned_kimi_bin):
    from amicus.backends.kimi.adapter import KimiBackend

    assert KimiBackend._read_only(_req(access="garbage")) is True
    assert KimiBackend._read_only(_req(access=contract.SANDBOX_WORKSPACE_WRITE)) is False
    assert KimiBackend._read_only(_req(access=contract.SANDBOX_READ_ONLY)) is True


def test_validate_request_instructions_rules(pinned_kimi_bin):
    _, backend = kf.make_backend()
    bad_kind = backend.validate_request(_req(kind="delegate", instructions_append="x"))
    assert bad_kind is not None and bad_kind.details == {"field": "instructions_append"}
    blank = backend.validate_request(_req(instructions_append="   "))
    assert blank is not None and "blank" in blank.detail
    assert backend.validate_request(_req(instructions_append="Focus.")) is None


def _outcome(stdout=EVENTS, answer=None, exit_code=0, stderr="", timed_out=False):
    texts = {"answer": answer} if answer is not None else {}
    return RunOutcome(
        run=CommandRun(stdout, stderr, exit_code, 5, timed_out), events=stdout, artifact_texts=texts
    )


def test_finalize_prefers_the_answer_file_and_carries_cache_tokens(pinned_kimi_bin):
    _, backend = kf.make_backend()
    usage_line = (
        '{"type":"token_count","usage":'
        '{"input_tokens":10,"output_tokens":2,"cached_input_tokens":8}}\n'
    )
    res = backend.finalize(_outcome(stdout=EVENTS + usage_line, answer="  from the file  "), _req())
    assert res.answer == "from the file" and res.session_id == "session_x"
    assert (
        res.usage is not None
        and res.usage.cached_input_tokens == 8
        and res.usage.total_tokens == 12
    )
    stream = backend.finalize(_outcome(), _req())
    assert stream.answer == "from the stream" and stream.usage is None and stream.structured is None
    structured = backend.finalize(_outcome(answer=STRUCTURED), _req(schema={"type": "object"}))
    assert structured.structured == {
        "summary": "Looks fine",
        "verdict": "pass",
        "confidence": "high",
        "findings": [],
    }


def test_inspect_outcome_flags_only_a_zero_exit_run_without_an_answer(pinned_kimi_bin):
    _, backend = kf.make_backend()
    empty = backend.inspect_outcome(
        _outcome(stdout='{"role":"meta","type":"system.version"}\n'), _req()
    )
    assert empty is not None and empty.code == "empty_response"
    assert backend.inspect_outcome(_outcome(), _req()) is None
    assert backend.inspect_outcome(_outcome(stdout="", answer="x"), _req()) is None
    assert backend.inspect_outcome(_outcome(stdout="", exit_code=1), _req()) is None
    assert (
        backend.inspect_outcome(_outcome(stdout="", timed_out=True, exit_code=-9), _req()) is None
    )


def test_classify_failure_uses_the_stream_message_and_the_site_sanitizer(pinned_kimi_bin):
    _, backend = kf.make_backend()
    auth = backend.classify_failure(
        _outcome(stdout='{"role":"assistant","content":"invalid api key"}\n', exit_code=2), _req()
    )
    assert auth.code == "kimi_auth_required"
    secret = "sk-" + "c" * 32
    out = _outcome(
        stdout="", stderr="x" * 290 + f" token={secret} at /wt/abc/src/a.py", exit_code=2
    )
    plain = backend.classify_failure(out, _req(sanitize_aliases=("/wt/abc",)))
    assert (
        plain.code == "nonzero_exit"
        and "sk-c" not in plain.detail
        and "/wt/abc" not in plain.detail
    )


def test_list_models_and_auth_probe(pinned_kimi_bin, monkeypatch):
    _, backend = kf.make_backend(catalog=kf.K3)
    assert backend.list_models() == ("k3", "bare")
    monkeypatch.setattr(cli, "login_status", lambda binary, timeout_seconds=10: (True, "ok"))
    assert backend.auth_probe() is True
    _, unresolved = kf.make_backend({"AMICUS_KIMI_BIN": "/definitely/not/here"})
    assert unresolved.auth_probe() is None
    assert backend.scrub_env({"A": "1"}, None) == {"A": "1"}
