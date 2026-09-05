"""CodexBackend: the behavior half of the Codex contract on the pontonier lifecycle
(ported from codex-in-claude `backend.py`). Since the sibling's re-plumb this adapter IS
the hot path; amicus runs it from `orchestration.run`."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, ExecResult, PreparedRun, Usage
from pontonier.core import worktree

from amicus.backends.codex import cli, contract, normalize
from amicus.backends.codex.config import reasoning_effort_shape_error, sandbox_for_kind
from amicus.backends.codex.models import CodexModels
from amicus.schemas import instructions

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    from pontonier.backend.protocol import RunOutcome, RunRequest
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.codex.binary import CodexBinary
    from amicus.backends.codex.config import CodexConfig

TEMP_PREFIX = "amicus-codex-"
_INSTRUCTION_KINDS = frozenset({"consult", "review_changes"})


class CodexBackend:
    def __init__(self, config: CodexConfig, binary: CodexBinary, help_probe: HelpProbe) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe

    # --- resolution the adapter and the classifier must agree on ----------------------------
    def _sandbox(self, request: RunRequest) -> str:
        return request.access or sandbox_for_kind(request.kind)

    def _isolation(self, request: RunRequest) -> str:
        return request.isolation or self._config.isolation

    def _model(self, request: RunRequest) -> str | None:
        return request.model or self._config.model

    def _effort(self, request: RunRequest) -> str | None:
        # Exact-None precedence: an explicit "" is the caller's value.
        if request.reasoning_effort is not None:
            return request.reasoning_effort
        return self._config.reasoning_effort

    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        effort = self._effort(request)
        if effort is not None:
            reason = reasoning_effort_shape_error(effort)
            if reason is not None:
                return ClassifiedFailure(
                    code="invalid_reasoning_effort",
                    detail=f"the requested reasoning_effort {reason}.",
                    details={"field": "reasoning_effort"},
                )
        raw = request.instructions_append
        if raw is not None and request.kind not in _INSTRUCTION_KINDS:
            return ClassifiedFailure(
                code="invalid_arguments",
                detail=(
                    f"instructions_append is not accepted for kind {request.kind!r}: only "
                    "consult and review_changes carry a caller developer turn (delegate edits "
                    "files)."
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
        # Fail closed for a direct caller that skipped validate_request.
        if (invalid := self.validate_request(request)) is not None:
            raise ValueError(invalid.detail)
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp:
            last_msg_path = str(Path(tmp) / "last-message.txt")
            schema_path: str | None = None
            if request.schema is not None:
                schema_path = str(Path(tmp) / "schema.json")
                Path(schema_path).write_text(json.dumps(request.schema), encoding="utf-8")
            cmd, dropped = cli.build_exec_command(
                codex_bin=self._binary.resolve() or contract.CODEX_BIN,
                cwd=request.cwd,
                sandbox=self._sandbox(request),
                isolation=self._isolation(request),
                output_last_message_path=last_msg_path,
                model=self._model(request),
                reasoning_effort=self._effort(request),
                developer_instructions=instructions.normalize(request.instructions_append),
                output_schema_path=schema_path,
                # Consult is read-only Q&A: repo membership is irrelevant.
                skip_git_repo_check=request.kind == "consult",
                extra_args=self._config.extra_args.tokens,
                flag_support=self._help_probe.flag_support(),
            )
            yield PreparedRun(
                argv=tuple(cmd),
                env=self.scrub_env(dict(os.environ), request.config_mode),
                cwd=request.cwd,
                stdin_text=request.prompt,
                artifacts=tuple(p for p in (last_msg_path, schema_path) if p),
                artifact_paths={
                    name: path
                    for name, path in (("last-message", last_msg_path), ("schema", schema_path))
                    if path
                },
                dropped_flags=tuple(dropped),
            )

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        answer = outcome.artifact_texts.get("last-message") or ""
        usage, session_id = normalize.parse_event_metadata(outcome.events)
        structured = normalize.parse_structured(answer) if request.schema is not None else None
        return ExecResult(
            answer=answer,
            structured=structured,
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                cached_input_tokens=usage.cached_input_tokens,
            )
            if usage is not None
            else None,
            session_id=session_id,
        )

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        aliases = request.sanitize_aliases
        sanitize = (lambda t: worktree.sanitize_echo_prose(t, aliases) or "") if aliases else None
        effort = self._effort(request)
        return cli.classify_failure(
            outcome.run,
            last_message=outcome.artifact_texts.get("last-message"),
            events=outcome.events or None,
            extra_args=self._config.extra_args,
            reasoning_effort=effort,
            sanitize=sanitize,
            plugin_config_keys=cli.plugin_config_keys_for(
                sandbox=self._sandbox(request),
                reasoning_effort=effort,
                developer_instructions=instructions.normalize(request.instructions_append),
            ),
        )

    def list_models(self) -> tuple[str, ...]:
        return tuple(m.slug for m in CodexModels(self._config).read().models)

    def auth_probe(self) -> bool | None:
        binary = self._binary.resolve()
        if binary is None:
            return None
        return cli.login_status(binary)[0]

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:  # noqa: ARG002
        # Codex inherits the caller's environment: auth rides $CODEX_HOME, and connector
        # suppression is argv (`--disable remote_plugin`), not env.
        return env
