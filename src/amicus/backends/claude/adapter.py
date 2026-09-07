"""ClaudeBackend: the behavior half of the Claude contract on the pontonier lifecycle (ported
from claude-in-codex `backend.py`, with the fixes the amicus spec names: the zero-exit
envelope is an outcome inspection; usage carries the cache counters; timeout is not
retryable; the caller's instructions ride stdin, never argv)."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, ExecResult, PreparedRun, RepairHint
from pontonier.core import worktree

from amicus.backends.claude import adversarial, cli, contract, normalize
from amicus.backends.claude import config as claude_config
from amicus.backends.claude.binary import BinaryNotFoundError
from amicus.schemas import instructions
from amicus.schemas.structured import schema_instruction

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator, Callable

    from pontonier.backend.protocol import RunOutcome, RunRequest
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.claude.binary import ClaudeBinary
    from amicus.backends.claude.config import ClaudeConfig

_INSTRUCTION_KINDS = frozenset({"consult", "review_changes"})
PERMISSION_DENIED_NO_ANSWER_DETAIL = (
    "claude was denied the tools it requested and produced no answer."
)


class ClaudeBackend:
    def __init__(self, config: ClaudeConfig, binary: ClaudeBinary, help_probe: HelpProbe) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe

    # --- resolution the adapter, the classifier and the status probe must agree on ----------
    def _config_mode(self, request: RunRequest) -> str:
        return request.config_mode or self._config.config_mode

    def _access(self, request: RunRequest) -> str:
        return request.access or self._config.access

    def _model(self, request: RunRequest) -> str | None:
        return request.model or self._config.model

    def _effort(self, request: RunRequest) -> str:
        # Exact-None precedence: an explicit "" is the caller's value.
        if request.reasoning_effort is not None:
            return request.reasoning_effort
        return self._config.reasoning_effort

    def _budget(self, request: RunRequest) -> float:
        return request.budget_usd if request.budget_usd is not None else self._config.max_budget_usd

    @staticmethod
    def _sanitizer(request: RunRequest) -> Callable[[str], str] | None:
        aliases = request.sanitize_aliases
        if not aliases:
            return None
        return lambda text: worktree.sanitize_echo_prose(text, aliases) or ""

    @staticmethod
    def _invalid(detail: str, field: str) -> ClassifiedFailure:
        return ClassifiedFailure(code="invalid_arguments", detail=detail, details={"field": field})

    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        """Every refusal here is zero spend. The tool boundary already validates the wire
        vocabulary; this mirrors it so a direct adapter caller cannot spend on a value the
        tools would refuse, and adds the two checks only the adapter can make (the resolved
        effort, and bare mode's key)."""
        if request.extra_args:
            return self._invalid("extra_args accepts no descriptors on this backend.", "extra_args")
        effort = self._effort(request)
        if effort not in contract.VALID_EFFORTS:
            return ClassifiedFailure(
                code="invalid_reasoning_effort",
                detail=f"reasoning_effort must be one of {', '.join(contract.VALID_EFFORTS)}.",
                details={
                    "field": "reasoning_effort",
                    "allowed_values": list(contract.VALID_EFFORTS),
                },
                repair=RepairHint(
                    next_step="use_allowed_value",
                    tool="amicus_models",
                    alternative=(
                        f"Pass one of: {', '.join(contract.VALID_EFFORTS)} — or omit "
                        "reasoning_effort for the configured default. Refused locally (zero "
                        "spend): claude rejects an unknown level at arg-parse."
                    ),
                ),
            )
        mode = self._config_mode(request)
        if mode not in contract.CONFIG_MODES:
            return self._invalid(
                f"config_mode must be one of {', '.join(contract.CONFIG_MODES)}.",
                "backend_options.config_mode",
            )
        if self._access(request) not in contract.ACCESS_MODES:
            return self._invalid(
                f"access must be one of {', '.join(contract.ACCESS_MODES)}.",
                "backend_options.access",
            )
        budget = self._budget(request)
        if not (contract.MIN_BUDGET_USD <= budget <= contract.MAX_BUDGET_USD):
            return self._invalid(
                f"max_budget_usd must be between {contract.MIN_BUDGET_USD} and "
                f"{contract.MAX_BUDGET_USD} USD.",
                "backend_options.max_budget_usd",
            )
        if mode == "bare" and not claude_config.api_key_present():
            return ClassifiedFailure(
                code="api_key_missing",
                detail="config_mode=bare runs only on ANTHROPIC_API_KEY, which is unset.",
                retryable=False,
                details={"field": "backend_options.config_mode"},
                repair=RepairHint(
                    next_step="correct_config",
                    tool="amicus_backends",
                    alternative=(
                        "Set ANTHROPIC_API_KEY for the server process, or use "
                        "backend_options.config_mode inherit/scoped/safe after `claude /login`. "
                        "No model call was made."
                    ),
                ),
            )
        raw = request.instructions_append
        if raw is not None and request.kind not in _INSTRUCTION_KINDS:
            return self._invalid(
                f"instructions_append is not accepted for kind {request.kind!r}: only consult "
                "and review_changes carry caller instructions (the adversarial critic's stance "
                "is fixed).",
                "instructions_append",
            )
        if raw is not None:
            text = instructions.normalize(raw)
            if text is None:
                return self._invalid(
                    "instructions_append is blank after normalization.", "instructions_append"
                )
            boundary = instructions.boundary_error(text)
            if boundary is not None:
                return self._invalid(f"instructions_append {boundary[0]}", "instructions_append")
        return None

    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest) -> AsyncIterator[PreparedRun]:
        """Stage the invocation: constant argv (guardrails, mode/access flags, budget, the
        help-gated effort/model), a per-mode scrubbed environment, and the prompt over stdin
        with any caller instructions composed in front of it. No file artifacts: answer, cost
        and session id all arrive in the stdout envelope."""
        if (invalid := self.validate_request(request)) is not None:
            raise ValueError(invalid.detail)
        resolved_bin = self._binary.resolve()
        if resolved_bin is None:
            raise BinaryNotFoundError(
                "the claude binary could not be resolved; refusing to spawn a PATH-searched "
                "fallback."
            )
        prompt_text = request.prompt
        caller = instructions.normalize(request.instructions_append)
        if caller is not None:
            prompt_text = instructions.compose(caller) + "\n\n" + prompt_text
        if request.schema is not None:
            prompt_text += schema_instruction(request.schema)
        mode = self._config_mode(request)
        cmd, dropped = cli.build_command(
            claude_bin=resolved_bin,
            config_mode=mode,
            access=self._access(request),
            system_prompt=adversarial.CRITIC_GUARDRAILS,
            max_budget_usd=self._budget(request),
            effort=self._effort(request),
            model=self._model(request),
            flag_support=self._help_probe.flag_support(),
        )
        yield PreparedRun(
            argv=tuple(cmd),
            env=self.scrub_env(dict(os.environ), mode),
            cwd=request.cwd,
            stdin_text=prompt_text,
            dropped_flags=tuple(dropped),
        )

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        """A tolerant read of the envelope, whatever it says about success (the loop calls this
        before inspection so a failure keeps its usage). The workspace hook scan rides
        `warnings`: the loop copies them onto meta.security_warnings."""
        env = normalize.parse_envelope(outcome.run.stdout) or {}
        answer = normalize.extract_answer(env)
        structured = normalize.parse_structured(answer) if request.schema is not None else None
        return ExecResult(
            answer=answer,
            structured=structured,
            usage=normalize.extract_usage(env),
            session_id=normalize.extract_session_id(env),
            warnings=tuple(
                claude_config.hook_security_warnings(request.cwd, self._config_mode(request))
            ),
        )

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        """What the exit status cannot reveal: claude exits 0 with `is_error`/a non-success
        `subtype`, with no JSON envelope at all, or with denials and no answer. A failed
        process is classify_failure's job."""
        run = outcome.run
        if run.exit_code != 0 or run.timed_out or run.binary_missing:
            return None
        env = normalize.parse_envelope(run.stdout)
        if env is None:
            return ClassifiedFailure(code="invalid_json", detail=cli.INVALID_JSON_DETAIL)
        if normalize.is_failure_envelope(env):
            return cli.classify_envelope(
                env,
                stderr=run.stderr,
                config_mode=self._config_mode(request),
                sanitize=self._sanitizer(request),
            )
        if not normalize.extract_answer(env).strip() and normalize.extract_denials(env):
            return ClassifiedFailure(
                code="claude_permission_error",
                detail=PERMISSION_DENIED_NO_ANSWER_DETAIL,
                retryable=False,
                details={"field": "backend_options.access"},
                repair=RepairHint(
                    next_step="correct_arguments", tool=None, alternative=cli.PERMISSION_REPAIR
                ),
                usage=normalize.extract_usage(env),
            )
        return None

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        return cli.classify_failure(
            outcome.run, config_mode=self._config_mode(request), sanitize=self._sanitizer(request)
        )

    def list_models(self) -> tuple[str, ...]:
        return tuple(slug for slug, _name, _kind in contract.KNOWN_MODELS)

    def auth_probe(self) -> bool | None:
        binary = self._binary.resolve()
        if binary is None:
            return None
        return cli.auth_status(binary, self._config.config_mode)

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        return cli.scrub_env(env, config_mode)
