"""PiBackend: the behavior half of the pi contract on the SDK lifecycle.

Three things set it apart from kimi's adapter. The model check fails closed: pi sends an
unknown id anyway, so a model the catalog cannot vouch for is refused before spending. The
prompt rides stdin and nothing is staged on disk. And a provider failure exits 0, so the
outcome inspector reads the stream's final `stopReason` whatever the exit code."""

from __future__ import annotations

import contextlib
import os
import time
from typing import TYPE_CHECKING, Literal

from amicus.backends.pi import cli, contract, normalize
from amicus.backends.pi.binary import BinaryNotFoundError
from amicus.backends.pi.models import HELP_CACHE_TTL_SECONDS
from amicus.schemas import instructions
from amicus.schemas.params import reasoning_effort_shape_error
from amicus.schemas.structured import schema_instruction
from amicus.sdk.backend.protocol import (
    ClassifiedFailure,
    ExecResult,
    PreparedRun,
    RepairHint,
    stream_answer_loss,
)
from amicus.sdk.core import pathalias, runtime

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncGenerator, Callable

    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.cli import AuthStatus
    from amicus.backends.pi.config import PiConfig
    from amicus.backends.pi.models import PiModels
    from amicus.plugin import ModelEntry
    from amicus.sdk.backend.protocol import RunOutcome, RunRequest
    from amicus.sdk.conventions.preflight import HelpProbe

_INSTRUCTION_KINDS = frozenset({"consult", "review_changes"})
# Distinct models a backend remembers probe outcomes for; past it the memo starts over, so a
# caller cycling through model strings cannot grow it without bound.
_PROBE_CACHE_MAX_MODELS = 64
EMPTY_RESPONSE_DETAIL = (
    "pi completed without producing an answer: the event stream holds no assistant text and "
    "no error."
)


def _auth_status(binary: str, model: str | None) -> AuthStatus:
    # Resolved through the module at call time, so a test that patches cli.auth_status
    # reaches a backend built before the patch.
    return cli.auth_status(binary, model)


def _invalid_model(detail: str, catalog: str) -> ClassifiedFailure:
    return ClassifiedFailure(
        code="invalid_model",
        detail=detail,
        details={"field": "model", "catalog": catalog},
        repair=RepairHint(
            next_step="correct_arguments",
            tool="amicus_models",
            alternative=(
                "Pass an exact provider/id that amicus_models lists for pi. Refused locally "
                "(zero spend): pi sends a model id it does not know to the provider anyway."
            ),
        ),
    )


class PiBackend:
    def __init__(
        self, config: PiConfig, binary: PiBinary, help_probe: HelpProbe, models: PiModels
    ) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe
        self._models = models
        self._auth_status: Callable[[str, str | None], AuthStatus] = _auth_status
        # validate_request's two probes, remembered per model for HELP_CACHE_TTL_SECONDS, as
        # the catalog read is: the conformance check at registry load validates several
        # requests for one model, and each would otherwise spawn both probes again.
        self._auth_memo: dict[str, tuple[float, AuthStatus]] = {}
        self._lookup_memo: dict[str, tuple[float, ModelEntry | None]] = {}

    # --- per-call probes, memoized by model ---------------------------------------------------
    @staticmethod
    def _make_room(memo: dict, model: str) -> None:
        if model not in memo and len(memo) >= _PROBE_CACHE_MAX_MODELS:
            memo.clear()

    def _cached_auth(self, binary: str, model: str) -> AuthStatus:
        """`pi auth check` for `model`; an "unknown" outcome is transient and not remembered."""
        now = time.monotonic()
        hit = self._auth_memo.get(model)
        if hit is not None and now - hit[0] < HELP_CACHE_TTL_SECONDS:
            return hit[1]
        status = self._auth_status(binary, model)
        if status != "unknown":
            self._make_room(self._auth_memo, model)
            self._auth_memo[model] = (now, status)
        return status

    def _cached_lookup(self, model: str) -> ModelEntry | Literal["unreadable"] | None:
        """The catalog row for `model`; an unreadable catalog is transient and not remembered,
        as PiModels.read does not cache a failed probe."""
        now = time.monotonic()
        hit = self._lookup_memo.get(model)
        if hit is not None and now - hit[0] < HELP_CACHE_TTL_SECONDS:
            return hit[1]
        result = self._models.lookup(model)
        if result != "unreadable":
            self._make_room(self._lookup_memo, model)
            self._lookup_memo[model] = (now, result)
        return result

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
        # Fail closed: the tool allowlist is the only thing making a pi consult read-only,
        # so only the explicit write posture, or a delegate with none set, drops it.
        if request.access is not None:
            return request.access != contract.SANDBOX_WORKSPACE_WRITE
        return request.kind != "delegate"

    @staticmethod
    def _events(outcome: RunOutcome) -> str:
        return outcome.events or outcome.run.stdout

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
                    "model's default. amicus_models lists each model's declared efforts. "
                    "Refused locally (zero spend): pi clamps an effort the model lacks "
                    "instead of rejecting it, so the run would use another level than asked."
                ),
            ),
        )

    # --- pre-spend validation -----------------------------------------------------------------
    def _missing_model(self) -> ClassifiedFailure:
        return ClassifiedFailure(
            code="invalid_arguments",
            detail=(
                "no pi model was given: pass `model` as an exact provider/id, or set "
                "AMICUS_PI_MODEL. pi's own default comes from ambient settings and fuzzy "
                "matching, so amicus does not rely on it."
            ),
            details={"field": "model"},
            repair=RepairHint(
                next_step="correct_arguments",
                tool="amicus_models",
                alternative=(
                    "Pass `model` as one of the provider/id values amicus_models lists for "
                    "pi, or set AMICUS_PI_MODEL in the server's environment."
                ),
            ),
        )

    def _auth_required(self) -> ClassifiedFailure:
        return ClassifiedFailure(
            code="pi_auth_required",
            detail="pi reports the model's provider is not authenticated.",
            details={"field": "model"},
            repair=RepairHint(
                next_step="authenticate",
                tool="amicus_backends",
                alternative=f"{contract.LOGIN_HINT} Then rerun amicus_backends.",
            ),
        )

    def _shape_refusal(self, request: RunRequest) -> ClassifiedFailure | None:
        effort = self._effort(request)
        reason = reasoning_effort_shape_error(effort) if effort is not None else None
        if reason is None:
            return None
        return ClassifiedFailure(
            code="invalid_reasoning_effort",
            detail=f"the requested reasoning_effort {reason}.",
            details={"field": "reasoning_effort"},
        )

    def _local_refusal(self, request: RunRequest) -> ClassifiedFailure | None:
        """The checks after the effort that need no probe: access and caller instructions."""
        if request.access is not None and request.access not in (
            contract.SANDBOX_READ_ONLY,
            contract.SANDBOX_WORKSPACE_WRITE,
        ):
            return ClassifiedFailure(
                code="invalid_arguments",
                detail="the requested access posture is not one pi supports.",
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

    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        # ORDER MATTERS. The model comes first, since nothing can be checked without one.
        # An unresolvable binary skips the probes, so the run reports backend_not_found
        # rather than a model error. `pi auth check` goes before the catalog because
        # `--list-models` hides every model of a provider with no credentials: asked first,
        # the catalog would call an unauthenticated model invalid. Auth "unknown" does not
        # block; the catalog then decides, and fails closed. See the M9 design.
        model = self._model(request)
        if not model:
            return self._missing_model()
        binary = self._binary.resolve()
        if binary is None:
            return None
        auth = self._cached_auth(binary, model)
        if auth == "unresolved":
            return _invalid_model("pi cannot resolve that model's provider.", "unresolved")
        if auth == "not_ready":
            return self._auth_required()
        entry = self._cached_lookup(model)
        if entry == "unreadable":
            return _invalid_model(
                "pi's model catalog could not be read, so the model cannot be vouched for.",
                "unreadable",
            )
        if entry is None:
            return _invalid_model(
                "pi's model catalog has no row that matches the model exactly.", "no_exact_row"
            )
        if (shape := self._shape_refusal(request)) is not None:
            return shape
        effort = self._effort(request)
        if effort is not None:
            allowed = entry.supported_reasoning_efforts or contract.EFFORTS
            if effort not in allowed:
                return self._effort_refusal(
                    "the requested reasoning_effort is not one this model supports.", allowed
                )
        return self._local_refusal(request)

    # --- the run ---------------------------------------------------------------------------
    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest) -> AsyncGenerator[PreparedRun]:
        """Build the argv and environment. Nothing is staged on disk: the composed prompt is
        the run's stdin, and argv carries no prompt input. The probing checks are
        validate_request's, which the orchestration runs first; prepare repeats only the
        free ones, so a run does not ask pi about its model twice."""
        model = self._model(request)
        if not model:
            raise ValueError(self._missing_model().detail)
        invalid = self._shape_refusal(request) or self._local_refusal(request)
        if invalid is not None:
            raise ValueError(invalid.detail)
        resolved_bin = self._binary.resolve()
        if resolved_bin is None:
            raise BinaryNotFoundError(
                "the pi binary could not be resolved; refusing to spawn a PATH-searched fallback."
            )
        prompt_text = request.prompt
        caller = instructions.normalize(request.instructions_append)
        if caller is not None:
            prompt_text = instructions.compose(caller) + "\n\n" + prompt_text
        if request.schema is not None:
            prompt_text += schema_instruction(request.schema)
        cmd = cli.build_exec_command(
            pi_bin=resolved_bin,
            read_only=self._read_only(request),
            model=model,
            thinking=self._effort(request),
        )
        yield PreparedRun(
            argv=tuple(cmd),
            env=self.scrub_env(dict(os.environ), request.config_mode),
            cwd=request.cwd,
            stdin_text=prompt_text,
            orphan_marker=request.cwd
            if len(request.cwd) >= runtime.MIN_ORPHAN_MARKER_LENGTH
            else None,
        )

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        events = self._events(outcome)
        answer = normalize.extract_final_message(events) or ""
        usage, session_id = normalize.parse_event_metadata(events)
        structured = normalize.parse_structured(answer) if request.schema is not None else None
        warnings: tuple[str, ...] = ()
        requested = self._effort(request)
        actual = normalize.thinking_level(events)
        if requested is not None and actual is not None and actual != requested:
            warnings = (
                f"pi ran at thinking level {actual!r}, not the requested {requested!r}; the "
                "model does not support the requested level.",
            )
        return ExecResult(
            answer=answer,
            structured=structured,
            usage=usage,
            session_id=session_id,
            warnings=warnings,
            answer_loss=stream_answer_loss(
                outcome.run, lost_after_answer=normalize.lost_after_final_message(events)
            ),
        )

    def _classify(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        aliases = request.sanitize_aliases
        sanitize = (lambda t: pathalias.sanitize_echo_prose(t, aliases) or "") if aliases else None
        return cli.classify_failure(
            outcome.run,
            error_message=normalize.final_error(self._events(outcome)),
            sanitize=sanitize,
        )

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        """A provider failure exits 0 after pi's own retries, so a final assistant message
        whose `stopReason` is "error" or "aborted" is classified whatever the exit code and
        whether or not it carries an `errorMessage`: any text before it is a partial answer.
        A zero-exit run with no answer text is `empty_response`: a success with nothing in it
        would launder the loss into a result."""
        if normalize.failed_stop(self._events(outcome)) is not None:
            return self._classify(outcome, request)
        run = outcome.run
        if run.exit_code != 0 or run.timed_out or run.binary_missing:
            return None
        if normalize.extract_final_message(self._events(outcome)):
            return None
        return ClassifiedFailure(code="empty_response", detail=EMPTY_RESPONSE_DETAIL)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        return self._classify(outcome, request)

    # --- discovery --------------------------------------------------------------------------
    def list_models(self) -> tuple[str, ...]:
        return tuple(m.slug for m in self._models.read().models)

    def auth_probe(self) -> bool | None:
        binary = self._binary.resolve()
        if binary is None:
            return None
        status = self._auth_status(binary, self._config.model)
        if status == "ready":
            return True
        if status in ("not_ready", "unresolved"):
            return False
        return None

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:  # noqa: ARG002
        # pi inherits the caller's environment: provider credentials and PI_CODING_AGENT_DIR
        # are what authenticate the run. pi has no config modes.
        return cli.build_run_env(env)
