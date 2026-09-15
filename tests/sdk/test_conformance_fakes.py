"""Three fake adapters — smoke validation of the frozen protocol.

Each fake models one real backend's mechanics, exercising the variation points
the protocol was shaped around:

* CodexLike — stdin prompt, structured output via an argv flag, answer from a
  last-message file, sandbox flag isolation, env-based connector suppression.
* KimiLike  — argv-pointer + handshake file (prompt too big for argv), answer
  from stream events, prompt-appended schema, generated read-only agent file,
  MANDATORY pre-spend effort validation (upstream silently ignores bad values).
* ClaudeLike — stdin prompt, answer from a stdout JSON envelope, config-mode
  env scrubbing, envelope-aware failure classification via the backend hook.

These are smoke checks: they prove the protocol CAN express all three shapes.
They are not the compatibility authority — the ``amicus.sdk.backend`` module
docstring is, including which changes its freeze treats as breaking. Read it
before changing anything these fakes implement.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path

import pytest
from tests.sdk.conftest import make_run
from tests.sdk.test_contract import make_contract

from amicus.sdk.backend import classify
from amicus.sdk.backend.contract import FailureSignatures, IsolationPolicy, Limits, ModelCatalog
from amicus.sdk.backend.protocol import (
    AgentBackend,
    ClassifiedFailure,
    ExecResult,
    PreparedRun,
    RunOutcome,
    RunRequest,
    Usage,
)
from amicus.sdk.testing import conformance


def _jsonl(events: str) -> list[dict]:
    """Tolerant JSONL parse, as real normalize layers do: bad lines degrade."""
    out = []
    for line in events.splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                out.append(parsed)
    return out


# ------------------------------------------------------------------ CodexLike


CODEX_CONTRACT = make_contract(
    backend_id="codexlike",
    env_prefix="CODEXLIKE_",
    exec_argv_prefix=("exec",),
    structured_output="argv_flag",
    isolation_policy=IsolationPolicy.SANDBOX_FLAG,
    needs_orphan_sweep=False,
    effort_silently_ignored_upstream=False,
    effort_validation="shape_only",
    supported_features=frozenset({"delegate", "transfer", "usage_accounting"}),
    usage_event_markers=("token_count",),
    model_catalog=ModelCatalog(
        strategy="cache_with_static_fallback",
        model_identifier_authority="advisory",
        effort_metadata_authority="advisory",
    ),
)


class CodexLikeBackend:
    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        return None  # upstream rejects bad values loudly; nothing to pre-empt

    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest):
        outdir = tempfile.mkdtemp(prefix="codexlike-")
        last_message = str(Path(outdir) / "last-message.txt")
        argv = ["fakecli", "exec", "--sandbox", "read-only", "--output-last-message", last_message]
        if request.schema is not None:
            schema_path = Path(outdir) / "schema.json"
            schema_path.write_text(json.dumps(request.schema))
            argv += ["--output-schema", str(schema_path)]
        try:
            yield PreparedRun(
                argv=tuple(argv),
                env={"DISABLED_FEATURES": "remote_plugin"},
                cwd=request.cwd,
                stdin_text=request.prompt,
                artifacts=(last_message,),
            )
        finally:
            import shutil

            shutil.rmtree(outdir, ignore_errors=True)

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        answer = outcome.artifact_texts.get("last-message", "")
        structured = None
        if request.schema is not None:
            with contextlib.suppress(json.JSONDecodeError):
                structured = json.loads(answer)
        usage = None
        for event in _jsonl(outcome.events):
            if event.get("type") == "token_count":
                usage = Usage(total_tokens=event.get("total"))
        return ExecResult(answer=answer, structured=structured, usage=usage)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        return classify.classify(CODEX_CONTRACT, outcome, request, detail="sanitized")

    def list_models(self) -> tuple[str, ...]:
        return ("model-a", "model-b")  # bundled fallback

    def auth_probe(self) -> bool | None:
        return True

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        return {**env, "DISABLED_FEATURES": "remote_plugin"}


# ------------------------------------------------------------------- KimiLike


KIMI_CONTRACT = make_contract(
    backend_id="kimilike",
    env_prefix="KIMILIKE_",
    structured_output="prompt_append",
    isolation_policy=IsolationPolicy.WORKTREE_ALL_TIERS,
    needs_orphan_sweep=True,
    effort_silently_ignored_upstream=True,
    effort_validation="token_floor_plus_catalog",
    supported_features=frozenset({"delegate", "model_validation", "empty_response_detection"}),
    limits=Limits(
        max_argv_prompt_chars=8_000,
        handshake_dir_name=".kimilike",
        answer_file_name="answer.md",
    ),
)

_VALID_EFFORTS = ("low", "medium", "high")


class KimiLikeBackend:
    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        # Upstream silently ignores a bad effort and exits 0 — validating here
        # is the only protection against paying for a default-effort answer.
        if request.reasoning_effort is not None and request.reasoning_effort not in _VALID_EFFORTS:
            return ClassifiedFailure(
                code="invalid_reasoning_effort",
                detail=f"effort must be one of {_VALID_EFFORTS}",
            )
        return None

    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest):
        # Prompt is argv-only upstream and argv has a hard cap, so the real
        # prompt goes to a handshake file OUTSIDE the workspace and argv carries
        # a short pointer. Read-only is a generated agent profile, staged in the
        # same step — the two are inseparable, which is why prepare() is one call.
        handshake_dir = tempfile.mkdtemp(prefix="kimilike-handshake-")
        prompt_path = Path(handshake_dir) / "prompt.md"
        body = request.prompt
        if request.schema is not None:
            body += "\n\nRespond with JSON matching:\n" + json.dumps(request.schema)
        prompt_path.write_text(body)
        agent_path = Path(handshake_dir) / "readonly-agent.md"
        agent_path.write_text("tools: [Read, Glob, Grep]\n")
        pointer = f"Read the file {prompt_path} and follow it exactly"
        assert len(pointer) <= 8_000
        env = {"KIMILIKE_MODEL_THINKING_EFFORT": request.reasoning_effort or "medium"}
        try:
            yield PreparedRun(
                argv=("fakecli", "--prompt", pointer, "--agent-file", str(agent_path)),
                env=env,
                cwd=request.cwd,
                stdin_text=None,  # stdin is ignored upstream
                orphan_marker=request.cwd,
                artifacts=(str(prompt_path), str(agent_path)),
            )
        finally:
            import shutil

            shutil.rmtree(handshake_dir, ignore_errors=True)

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        answer = ""
        for event in _jsonl(outcome.events):
            if event.get("role") == "assistant":
                answer = event.get("content", "")
        structured = None
        if request.schema is not None:
            with contextlib.suppress(json.JSONDecodeError):
                structured = json.loads(answer)
        # No usage events in prompt mode — never estimate.
        return ExecResult(answer=answer, structured=structured, usage=None)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        if outcome.run.exit_code == 0 and not any(
            e.get("role") == "assistant" for e in _jsonl(outcome.events)
        ):
            return ClassifiedFailure(code="empty_response", detail="no assistant event")
        return classify.classify(KIMI_CONTRACT, outcome, request, detail="sanitized")

    def list_models(self) -> tuple[str, ...]:
        return ("alias-1",)  # live probe result; authoritative for identifiers

    def auth_probe(self) -> bool | None:
        return None  # probe cannot answer without leaking provider config

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        return dict(env)  # no-op


# ----------------------------------------------------------------- ClaudeLike


CLAUDE_CONTRACT = make_contract(
    backend_id="claudelike",
    env_prefix="CLAUDELIKE_",
    exec_argv_prefix=("-p",),
    structured_output="argv_flag",
    isolation_policy=IsolationPolicy.TOOL_ALLOWLIST,
    needs_orphan_sweep=False,
    effort_silently_ignored_upstream=False,
    supported_features=frozenset(),
    failure_signatures=FailureSignatures(auth=(r"login required",)),
)


class ClaudeLikeBackend:
    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        return None

    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest):
        argv = ["fakecli", "-p", "--output-format", "json"]
        if request.access == "readonly":
            argv += ["--tools", "Read,Grep,Glob"]
        yield PreparedRun(
            argv=tuple(argv),
            env=self.scrub_env({}, request.config_mode),
            cwd=request.cwd,
            stdin_text=request.prompt,
        )

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        envelope = json.loads(outcome.run.stdout)
        return ExecResult(
            answer=envelope.get("result", ""),
            usage=Usage(cost_usd=envelope.get("total_cost_usd")),
            session_id=envelope.get("session_id"),
        )

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        # Envelope-aware: the stdout JSON names failure states the stderr
        # regexes cannot see. Hook first, shared skeleton as fallback.
        def hook(o: RunOutcome, r: RunRequest) -> ClassifiedFailure | None:
            with contextlib.suppress(json.JSONDecodeError):
                envelope = json.loads(o.run.stdout)
                if envelope.get("subtype") == "error_budget_exceeded":
                    return ClassifiedFailure(code="nonzero_exit", detail="budget exceeded")
            return None

        return classify.classify(
            CLAUDE_CONTRACT, outcome, request, detail="sanitized", backend_hook=hook
        )

    def list_models(self) -> tuple[str, ...]:
        return ("static-model",)

    def auth_probe(self) -> bool | None:
        return False

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        scrubbed = {k: v for k, v in env.items() if k != "PROVIDER_API_KEY"}
        if config_mode == "bare":
            return dict(env)  # bare mode NEEDS the key
        return scrubbed


# -------------------------------------------------------------------- checks

FAKES = [
    (CODEX_CONTRACT, CodexLikeBackend()),
    (KIMI_CONTRACT, KimiLikeBackend()),
    (CLAUDE_CONTRACT, ClaudeLikeBackend()),
]


@pytest.mark.parametrize("contract,backend", FAKES, ids=["codexlike", "kimilike", "claudelike"])
def test_fake_is_structurally_conformant(contract, backend):
    assert isinstance(backend, AgentBackend)


@pytest.mark.parametrize("contract,backend", FAKES, ids=["codexlike", "kimilike", "claudelike"])
def test_fake_passes_conformance(contract, backend):
    assert conformance.check_contract(contract) == []
    assert conformance.check_backend(contract, backend) == []


def test_effort_conformance_catches_missing_validation():
    """Negative control: a Kimi-shaped backend WITHOUT pre-spend effort
    validation must fail conformance — this is the invariant that prevents
    paying for silently-default-effort answers."""

    class Lax(KimiLikeBackend):
        def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
            return None

    violations = conformance.check_backend(KIMI_CONTRACT, Lax())
    assert any("pre-spend" in v for v in violations)


async def test_codexlike_lifecycle():
    backend = CodexLikeBackend()
    request = RunRequest(
        kind="consult", prompt="q?", cwd=".", timeout_seconds=10, schema={"type": "object"}
    )
    async with backend.prepare(request) as prepared:
        assert prepared.stdin_text == "q?"  # prompt over stdin, never argv
        assert "--output-schema" in prepared.argv
        last_message = prepared.artifacts[0]
        assert Path(prepared.argv[prepared.argv.index("--output-last-message") + 1]) == Path(
            last_message
        )
        schema_path = Path(prepared.argv[prepared.argv.index("--output-schema") + 1])
        assert schema_path.exists()
    assert not schema_path.exists()  # context exit cleaned staged artifacts

    outcome = RunOutcome(
        run=make_run(exit_code=0),
        events='{"type": "token_count", "total": 42}\nnot json — must degrade\n',
        artifact_texts={"last-message": '{"summary": "fine"}'},
    )
    result = backend.finalize(outcome, request)
    assert result.structured == {"summary": "fine"}
    assert result.usage.total_tokens == 42


async def test_kimilike_lifecycle():
    backend = KimiLikeBackend()
    big_prompt = "x" * 100_000  # far past the argv cap
    request = RunRequest(kind="consult", prompt=big_prompt, cwd="/tmp/ws", timeout_seconds=10)
    async with backend.prepare(request) as prepared:
        assert prepared.stdin_text is None
        pointer = prepared.argv[prepared.argv.index("--prompt") + 1]
        assert len(pointer) < 8_000  # argv carries a pointer, not the prompt
        prompt_path = Path(prepared.artifacts[0])
        assert prompt_path.read_text().startswith("xxx")
        assert "/tmp/ws" not in str(prompt_path)  # handshake staged OUTSIDE the workspace
        assert prepared.orphan_marker == "/tmp/ws"
    assert not prompt_path.exists()

    outcome = RunOutcome(
        run=make_run(exit_code=0),
        events='{"role": "assistant", "content": "the answer"}\n',
    )
    result = backend.finalize(outcome, request)
    assert result.answer == "the answer"
    assert result.usage is None  # no usage events; never estimated


def test_kimilike_empty_response_detection():
    backend = KimiLikeBackend()
    request = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)
    outcome = RunOutcome(run=make_run(exit_code=0), events="")
    assert backend.classify_failure(outcome, request).code == "empty_response"


def test_kimilike_rejects_bad_effort_before_spend():
    backend = KimiLikeBackend()
    request = RunRequest(
        kind="consult", prompt="q", cwd=".", timeout_seconds=10, reasoning_effort="ultra"
    )
    rejected = backend.validate_request(request)
    assert rejected is not None
    assert rejected.code == "invalid_reasoning_effort"


async def test_claudelike_lifecycle():
    backend = ClaudeLikeBackend()
    request = RunRequest(
        kind="consult",
        prompt="q?",
        cwd=".",
        timeout_seconds=10,
        access="readonly",
        config_mode="scoped",
    )
    async with backend.prepare(request) as prepared:
        assert prepared.stdin_text == "q?"
        assert "--tools" in prepared.argv
        assert "PROVIDER_API_KEY" not in prepared.env

    envelope = json.dumps(
        {"result": "hi", "total_cost_usd": 0.03, "session_id": "s-1", "subtype": "success"}
    )
    result = backend.finalize(RunOutcome(run=make_run(stdout=envelope)), request)
    assert result.answer == "hi"
    assert result.usage.cost_usd == 0.03
    assert result.session_id == "s-1"


def test_claudelike_envelope_aware_classification():
    backend = ClaudeLikeBackend()
    request = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)
    envelope = json.dumps({"subtype": "error_budget_exceeded"})
    out = RunOutcome(run=make_run(stdout=envelope, stderr="login required", exit_code=1))
    # The envelope hook wins over the stderr auth regex.
    assert backend.classify_failure(out, request).detail == "budget exceeded"


def test_claudelike_bare_mode_keeps_key():
    backend = ClaudeLikeBackend()
    env = {"PROVIDER_API_KEY": "k", "PATH": "/bin"}
    assert "PROVIDER_API_KEY" in backend.scrub_env(env, "bare")
    assert "PROVIDER_API_KEY" not in backend.scrub_env(env, "scoped")
