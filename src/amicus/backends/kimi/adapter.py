"""KimiBackend: the behavior half of the Kimi contract on the pontonier lifecycle (ported
from moonbridge `backend.py`, with the fixes the amicus spec names: the classifier gets the
last message and the site sanitizer; finalize carries cache tokens; the pre-spend effort
gate is the adapter's own; empty answers are an outcome inspection)."""

from __future__ import annotations

import contextlib
import os
import shutil
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, ExecResult, PreparedRun, RepairHint
from pontonier.core import runtime, worktree

from amicus.backends.kimi import cli, contract, models, normalize
from amicus.backends.kimi import config as kimi_config
from amicus.backends.kimi.binary import BinaryNotFoundError
from amicus.schemas import instructions
from amicus.schemas.params import reasoning_effort_shape_error

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    from pontonier.backend.protocol import RunOutcome, RunRequest
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.kimi.binary import KimiBinary
    from amicus.backends.kimi.config import KimiConfig
    from amicus.backends.kimi.models import KimiModels

_INSTRUCTION_KINDS = frozenset({"consult", "review_changes"})
EMPTY_RESPONSE_DETAIL = (
    "Kimi completed without producing an answer: no answer file and no assistant text in "
    "the event stream."
)


class KimiBackend:
    def __init__(
        self, config: KimiConfig, binary: KimiBinary, help_probe: HelpProbe, models: KimiModels
    ) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe
        self._models = models

    # --- resolution the adapter and the classifier must agree on ----------------------------
    def _model(self, request: RunRequest) -> str | None:
        return request.model or self._config.model

    def _effort(self, request: RunRequest) -> str | None:
        # Exact-None precedence: an explicit "" is the caller's value.
        if request.reasoning_effort is not None:
            return request.reasoning_effort
        return self._config.reasoning_effort

    @staticmethod
    def _read_only(request: RunRequest) -> bool:
        # Fail closed: the agent file is the only thing making a kimi consult
        # read-only, so only the explicit write posture drops it.
        if request.access is not None:
            return request.access != contract.SANDBOX_WORKSPACE_WRITE
        return request.kind != "delegate"

    @staticmethod
    def _answer(outcome: RunOutcome) -> str | None:
        answer = (outcome.artifact_texts.get("answer") or "").strip()
        return answer or normalize.extract_final_message(outcome.events or outcome.run.stdout)

    def _effort_refusal(self, detail: str, allowed: tuple[str, ...]) -> ClassifiedFailure:
        return ClassifiedFailure(
            code="invalid_reasoning_effort",
            detail=detail,
            details={"field": "reasoning_effort", "allowed_values": list(allowed)},
            repair=RepairHint(
                next_step="correct_arguments",
                tool="amicus_models",
                alternative=(
                    f"Pass one of: {', '.join(allowed)} — or omit reasoning_effort to use the "
                    "model's default. amicus_models lists each alias's declared efforts. "
                    "Refused locally (zero spend): kimi ignores an unrecognized effort instead "
                    "of rejecting it, so the run would silently use the default while the "
                    "result claimed otherwise."
                ),
            ),
        )

    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        # ORDER MATTERS: shape, then the catalog (it decides alone when it names the alias),
        # then the fallback vocabulary ONLY when the catalog is silent. Compare the EXACT
        # value prepare() will send: normalizing here would validate a string the run never
        # uses. See ADR 0009.
        effort = self._effort(request)
        if effort is not None:
            reason = reasoning_effort_shape_error(effort)
            if reason is not None:
                return ClassifiedFailure(
                    code="invalid_reasoning_effort",
                    detail=f"the requested reasoning_effort {reason}.",
                    details={"field": "reasoning_effort"},
                )
            supported = models.supported_efforts_for(self._model(request), self._models.read())
            # An alias declaring an explicitly empty supportEfforts is treated the same as
            # an absent/unusable one (supported == ()), so the fallback vocabulary decides.
            if supported:
                if effort not in supported:
                    return self._effort_refusal(
                        "the requested reasoning_effort is not one this model declares.",
                        supported,
                    )
            elif effort not in contract.REASONING_EFFORT_FALLBACK_VOCABULARY:
                return self._effort_refusal(
                    "the requested reasoning_effort matches no known kimi effort level.",
                    tuple(sorted(contract.REASONING_EFFORT_FALLBACK_VOCABULARY)),
                )
        if request.access is not None and request.access not in (
            contract.SANDBOX_READ_ONLY,
            contract.SANDBOX_WORKSPACE_WRITE,
        ):
            return ClassifiedFailure(
                code="invalid_arguments",
                detail="the requested access posture is not one kimi supports.",
                details={"field": "access"},
            )
        raw = request.instructions_append
        if raw is not None and request.kind not in _INSTRUCTION_KINDS:
            return ClassifiedFailure(
                code="invalid_arguments",
                detail=(
                    f"instructions_append is not accepted for kind {request.kind!r}: only "
                    "consult and review_changes carry caller instructions (delegate edits files)."
                ),
                details={"field": "instructions_append"},
            )
        if raw is not None:
            text = instructions.normalize(raw)
            if text is None:
                return ClassifiedFailure(
                    code="invalid_arguments",
                    detail="instructions_append is blank after normalization.",
                    details={"field": "instructions_append"},
                )
            boundary = instructions.boundary_error(text)
            if boundary is not None:
                return ClassifiedFailure(
                    code="invalid_arguments",
                    detail=f"instructions_append {boundary[0]}",
                    details={"field": "instructions_append"},
                )
        return None

    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest) -> AsyncIterator[PreparedRun]:
        """Stage the out-of-workspace handshake dir (prompt file; read-only agent profile or
        answer file), the argv pointer, and the effort/output-format environment; tear the
        dir down on exit, so the answer file must be read inside the context."""
        if (invalid := self.validate_request(request)) is not None:
            raise ValueError(invalid.detail)
        resolved_bin = self._binary.resolve()
        if resolved_bin is None:
            raise BinaryNotFoundError(
                "the kimi binary could not be resolved; refusing to spawn a PATH-searched fallback."
            )
        read_only = self._read_only(request)
        prompt_text = request.prompt
        caller = instructions.normalize(request.instructions_append)
        if caller is not None:
            prompt_text = instructions.compose(caller) + "\n\n" + prompt_text
        if request.schema is not None:
            prompt_text += cli.schema_instruction(request.schema)
        isolation = request.isolation or self._config.isolation
        handshake_dir = cli.create_handshake_dir()
        try:
            paths = cli.write_handshake(handshake_dir, prompt_text, read_only=read_only)
            cmd, dropped = cli.build_exec_command(
                kimi_bin=resolved_bin,
                read_only=read_only,
                prompt_pointer=cli.build_prompt_pointer(paths, read_only=read_only),
                model=self._model(request),
                agent_file_path=paths.get("agent"),
                skills_dir=kimi_config.skills_dir_for(isolation, self._config.state_dir),
                flag_support=self._help_probe.flag_support(),
            )
            yield PreparedRun(
                argv=tuple(cmd),
                env=cli.build_run_env(
                    self.scrub_env(dict(os.environ), request.config_mode), self._effort(request)
                ),
                cwd=request.cwd,
                stdin_text=None,  # kimi ignores stdin
                orphan_marker=request.cwd
                if len(request.cwd) >= runtime.MIN_ORPHAN_MARKER_LENGTH
                else None,
                artifacts=tuple(paths.values()),
                # Only the answer file is an artifact the loop reads back; the prompt and
                # agent files are inputs, and the loop's reader is the hardened one.
                artifact_paths={"answer": paths["answer"]} if "answer" in paths else {},
                dropped_flags=tuple(dropped),
            )
        finally:
            shutil.rmtree(handshake_dir, ignore_errors=True)

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        answer = self._answer(outcome) or ""
        events = outcome.events or outcome.run.stdout
        usage, session_id = normalize.parse_event_metadata(events)
        structured = normalize.parse_structured(answer) if request.schema is not None else None
        return ExecResult(answer=answer, structured=structured, usage=usage, session_id=session_id)

    def inspect_outcome(
        self,
        outcome: RunOutcome,
        request: RunRequest,  # noqa: ARG002
    ) -> ClassifiedFailure | None:
        """A zero-exit run with no answer is `empty_response`: kimi has no
        --output-last-message, so a read-only run's only answer channel is the stream, and
        a success whose summary says "no message" would launder that into a result."""
        run = outcome.run
        if run.exit_code != 0 or run.timed_out or run.binary_missing:
            return None
        if self._answer(outcome):
            return None
        return ClassifiedFailure(code="empty_response", detail=EMPTY_RESPONSE_DETAIL)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        aliases = request.sanitize_aliases
        sanitize = (lambda t: worktree.sanitize_echo_prose(t, aliases) or "") if aliases else None
        return cli.classify_failure(
            outcome.run,
            last_message=self._answer(outcome),
            events=outcome.events or outcome.run.stdout or None,
            reasoning_effort=self._effort(request),
            sanitize=sanitize,
        )

    def list_models(self) -> tuple[str, ...]:
        return tuple(m.slug for m in self._models.read().models)

    def auth_probe(self) -> bool | None:
        binary = self._binary.resolve()
        if binary is None:
            return None
        return cli.login_status(binary)[0]

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:  # noqa: ARG002
        # kimi inherits the caller's environment: the provider credentials in the user's
        # config are what authenticate the run; kimi has no config modes.
        return env
