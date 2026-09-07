"""Construction and serialization of the error envelope (ADR 0005).

pontonier's `repair_rules()` are the defaults, minted with a neutral vocabulary so the
four per-backend codes come out as `backend_*`; amicus-local codes and prose overrides
sit on top; a plugin's `local_codes` are added and its `repair_overrides` win per code.
`render_failure` turns a backend's ClassifiedFailure into the wire envelope, honoring the
0.9.0 machine fields (`retryable`, `details`, `repair`, `usage`)."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from pontonier.conventions.envelope import BackendErrorVocabulary, RepairRule, repair_rules
from pydantic import ValidationError

from amicus.schemas.codes import ERROR_CODES, generalize_code
from amicus.schemas.envelope import (
    ErrorDetail,
    ErrorInfo,
    ErrorResult,
    InvalidArgument,
    Meta,
    Repair,
    Usage,
)

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.backend.protocol import ClassifiedFailure

    from amicus.plugin import BackendPlugin

NEUTRAL_VOCABULARY = BackendErrorVocabulary(
    backend_id="backend",
    display_name="the backend",
    install_hint=(
        "Install the CLI of the backend named in error.backend, then rerun amicus_backends."
    ),
    login_hint=(
        "Log in to the CLI of the backend named in error.backend, then rerun amicus_backends."
    ),
    status_tool="amicus_backends",
)
_FEATURES = frozenset({"model_validation", "empty_response_detection"})

_LOCAL_RULES: dict[str, RepairRule] = {
    "not_implemented": RepairRule(
        "update_plugin",
        "amicus_capabilities",
        False,
        "This tool's backend has not landed in this amicus release; amicus_capabilities "
        "lists what is implemented. Update amicus when the backend ships.",
    ),
    "backend_unavailable": RepairRule(
        "inspect_and_retry",
        "amicus_backends",
        False,
        "The backend failed to load; amicus_backends reports the reason. Fix it or pick "
        "another backend.",
    ),
    "feature_unsupported": RepairRule(
        "use_allowed_value",
        "amicus_backends",
        False,
        "This backend does not support this verb; amicus_backends lists each backend's "
        "features. Pick a backend that declares it.",
    ),
    "user_config_rejected": RepairRule(
        "correct_config",
        None,
        False,
        "The backend CLI refused to start because of a key or value in the user's own CLI "
        "config; fix that setting (the message names it), then retry. No model call was made.",
    ),
    "budget_exceeded": RepairRule(
        "reduce_input",
        None,
        False,
        "The backend stopped at its best-effort spend cap; raise backend_options.max_budget_usd "
        "or narrow the request, then retry (a retry spends again).",
    ),
    "claude_permission_error": RepairRule(
        "correct_arguments",
        None,
        False,
        "The backend was denied a tool it requested; use backend_options.access='toolless' or "
        "grant read-only access, then retry.",
    ),
    "api_key_invalid": RepairRule(
        "authenticate",
        "amicus_backends",
        False,
        "The provider rejected the API key; fix it or use a login mode, then rerun "
        "amicus_backends.",
    ),
    "api_key_missing": RepairRule(
        "correct_config",
        "amicus_backends",
        False,
        "This config_mode needs an API key the server process does not have; set it or pick a "
        "login mode. No model call was made.",
    ),
}

# Prose that must name amicus tools rather than a sibling's.
_PROSE_OVERRIDES: dict[str, str] = {
    "invalid_arguments": (
        "Check each tool's inputSchema (tools/list) or amicus_capabilities, then retry."
    ),
    "timeout": (
        "Retrying the same synchronous call will likely time out again. Prefer the matching "
        "async tool (amicus_consult_async / amicus_review_changes_async / "
        "amicus_adversarial_review_async / amicus_delegate_async), then poll "
        "amicus_job_status and fetch amicus_job_result. Otherwise narrow the task or raise "
        "timeout_seconds."
    ),
    "resource_not_found": (
        "List the available resource URIs via the MCP resources/list method (or "
        "amicus_capabilities), then retry with an exact URI."
    ),
    "job_not_found": "Call amicus_job_list to recover known job_ids in this workspace.",
    "job_running": "Poll amicus_job_status until result_available, honoring poll_after_ms.",
}
_TOOL_OVERRIDES: dict[str, str] = {
    "job_not_found": "amicus_job_list",
    "job_running": "amicus_job_status",
    "invalid_reasoning_effort": "amicus_models",
    "invalid_model": "amicus_models",
}


def repair_table(plugin: BackendPlugin | None = None) -> dict[str, RepairRule]:
    rules = dict(repair_rules(NEUTRAL_VOCABULARY, _FEATURES))
    rules.update(_LOCAL_RULES)
    for code, prose in _PROSE_OVERRIDES.items():
        rules[code] = dataclasses.replace(rules[code], alternative=prose)
    for code, tool in _TOOL_OVERRIDES.items():
        rules[code] = dataclasses.replace(rules[code], tool=tool)
    if plugin is not None:
        rules.update(plugin.local_codes)
        for code, rule in plugin.repair_overrides.items():
            rules[generalize_code(code, plugin.backend_id)] = rule
    return rules


class _KeepTableTool:
    __slots__ = ()


KEEP_TABLE_TOOL = _KeepTableTool()


def make_error(
    code: str,
    message: str,
    *,
    backend: str | None = None,
    plugin: BackendPlugin | None = None,
    retry_after_ms: int | None = None,
    temporary: bool | None = None,
    repair_next_step: str | None = None,
    repair_tool: str | _KeepTableTool | None = KEEP_TABLE_TOOL,
    repair_arguments: dict[str, Any] | None = None,
    repair_alternative: str | None = None,
    details: ErrorDetail | None = None,
    invalid_arguments: list[InvalidArgument] | None = None,
    limit_bytes: int | None = None,
    actual_bytes: int | None = None,
    candidate_roots: list[str] | None = None,
) -> ErrorInfo:
    """Build the envelope for `code`, deriving the symbolic repair from the table.
    `repair_tool` has three states: omitted keeps the table's tool, a string overrides
    it, explicit None clears it. An `invalid_arguments` envelope must carry the list and
    `details` is always derived from its first entry."""
    if code == "invalid_arguments":
        if not invalid_arguments:
            raise ValueError(
                "make_error: an invalid_arguments envelope must carry a non-empty "
                "invalid_arguments list"
            )
        if details is not None:
            raise ValueError(
                "make_error: `details` is derived from invalid_arguments[0]; do not supply it"
            )
        first = invalid_arguments[0]
        details = ErrorDetail(
            field=first.field,
            reason=first.reason,
            allowed_values=first.allowed_values,
            field_withheld=first.field_withheld,
        )
    rule = repair_table(plugin)[code]
    next_step = repair_next_step or rule.next_step
    tool = rule.tool if isinstance(repair_tool, _KeepTableTool) else repair_tool
    is_temp = rule.temporary if temporary is None else temporary
    backend_id = backend if backend is not None else (plugin.backend_id if plugin else None)
    return ErrorInfo(
        code=code,  # ty: ignore[invalid-argument-type]  # validated by pydantic against the catalog
        message=message,
        backend=backend_id,
        temporary=is_temp,
        retry_after_ms=retry_after_ms if is_temp else None,
        repair=Repair(
            next_step=next_step,  # ty: ignore[invalid-argument-type]
            tool=tool,
            arguments=repair_arguments,
            alternative=repair_alternative or rule.alternative,
        ),
        details=details,
        invalid_arguments=invalid_arguments,
        limit_bytes=limit_bytes,
        actual_bytes=actual_bytes,
        candidate_roots=candidate_roots,
    )


def serialize_error_info(error: ErrorInfo) -> dict[str, Any]:
    """Strip absent optionals but ALWAYS keep `retry_after_ms` and `backend` (§6 wants
    both keys, and `backend` is a required-nullable wire field)."""
    payload = error.model_dump(mode="json", exclude_none=True)
    payload.setdefault("retry_after_ms", None)
    payload.setdefault("backend", None)
    return payload


def serialize_error(result: ErrorResult) -> dict[str, Any]:
    """Serialize the envelope, then mirror `meta.request_id` onto `error.request_id`
    when the error carries none, so both carriers always agree on one request id."""
    payload = result.model_dump(mode="json", exclude_none=True)
    payload["error"] = serialize_error_info(result.error)
    payload["error"].setdefault("request_id", payload["meta"]["request_id"])
    return payload


def error_envelope(code: str, message: str, meta: Meta, **kwargs: Any) -> dict[str, Any]:
    return serialize_error(ErrorResult(error=make_error(code, message, **kwargs), meta=meta))


def _detail_from(raw: dict[str, Any] | None) -> ErrorDetail | None:
    if not raw:
        return None
    try:
        return ErrorDetail.model_validate(raw)
    except ValidationError:
        return ErrorDetail(reason=" ".join(f"{k}={v}" for k, v in raw.items())[:300])


def render_failure(plugin: BackendPlugin, failure: ClassifiedFailure, meta: Meta) -> dict[str, Any]:
    """The wire envelope for a backend's classified failure. Minted codes are
    generalized; an uncataloged code is reported as internal_error with the original
    code and detail in the message; `retryable` overrides the rule's `temporary`; a
    backend-supplied repair wins over the table; usage from a failed run is kept."""
    table = repair_table(plugin)
    code = generalize_code(failure.code, plugin.backend_id)
    message = failure.detail
    if code not in table or code not in ERROR_CODES:
        message = f"{failure.code}: {failure.detail}"
        code = "internal_error"
    rule = table[code]
    temporary = rule.temporary if failure.retryable is None else failure.retryable
    if failure.repair is not None:
        repair = Repair(
            next_step=failure.repair.next_step,  # ty: ignore[invalid-argument-type]
            tool=failure.repair.tool,
            arguments=failure.repair.arguments,
            alternative=failure.repair.alternative or rule.alternative,
        )
    else:
        repair = Repair(
            next_step=rule.next_step,  # ty: ignore[invalid-argument-type]
            tool=rule.tool,
            alternative=rule.alternative,
        )
    if failure.usage is not None:
        meta = meta.model_copy(update={"usage": Usage(**dataclasses.asdict(failure.usage))})
    info = ErrorInfo(
        code=code,  # ty: ignore[invalid-argument-type]
        message=message,
        backend=plugin.backend_id,
        temporary=temporary,
        retry_after_ms=failure.retry_after_ms if temporary else None,
        repair=repair,
        details=_detail_from(failure.details),
    )
    return serialize_error(ErrorResult(error=info, meta=meta))
