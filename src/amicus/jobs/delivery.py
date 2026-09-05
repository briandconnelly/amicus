"""The single delivery chokepoint every reader of a stored result shares (the sync await
now, the M2 amicus_job_result/consume paths later), so their wire shapes cannot diverge.
Ported from codex-in-claude `_finished_job_envelope` and friends."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any

from pontonier.core import redaction
from pydantic import BaseModel, ValidationError

from amicus.errors import error_envelope, serialize_error
from amicus.orchestration.finalize import sanitize_finding, sanitize_prose_value
from amicus.schemas.envelope import ErrorResult
from amicus.schemas.fingerprint import FINGERPRINT, RESULT_FORMAT
from amicus.schemas.results import PAID_TOOLS, ConsultResult, DelegateResult, ReviewResult

if TYPE_CHECKING:  # pragma: no cover
    from amicus.schemas.envelope import Meta

JOB_RESULT_MODELS: dict[str, type[BaseModel]] = {
    "consult": ConsultResult,
    "review_changes": ReviewResult,
    "delegate": DelegateResult,
}
STATE_TO_ERROR: dict[str, tuple[str, str]] = {
    "running": ("job_running", "The job is still running."),
    "cancelled": ("job_cancelled", "The job was cancelled."),
    "timeout": ("job_timeout", "The job exceeded its wall-clock deadline and was stopped."),
    "failed": ("job_failed", "The job failed without producing a result."),
}
_SLIMMED_TOOLS = frozenset(PAID_TOOLS)
_STORED_PRESENTATION_KEYS = ("summary", "findings", "questions", "next_steps", "assumptions")


def apply_detail(envelope: dict[str, Any], detail: str) -> dict[str, Any]:
    """summary nulls raw_response.text; full keeps it; errors pass through. Mutates."""
    if detail == "full" or envelope.get("ok") is not True:
        return envelope
    raw = envelope.get("raw_response")
    if isinstance(raw, dict):
        raw["text"] = None
    return envelope


def slim_meta(envelope: dict[str, Any]) -> dict[str, Any]:
    """Drop meta's null-valued keys from a DELIVERED paid-tool success (wire only; the
    persisted envelope keeps them). Keyed on `is None`, never falsiness. Mutates."""
    if envelope.get("ok") is not True or envelope.get("tool") not in _SLIMMED_TOOLS:
        return envelope
    meta = envelope.get("meta")
    if isinstance(meta, dict):
        envelope["meta"] = {k: v for k, v in meta.items() if v is not None}
    return envelope


def _has_control_char(text: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in text)


def _tree_has_control_char(value: object) -> bool:
    if isinstance(value, str):
        return _has_control_char(value)
    if isinstance(value, list):
        return any(_tree_has_control_char(v) for v in value)
    if isinstance(value, dict):
        return any(_tree_has_control_char(v) for v in value.values())
    return False


def _sanitize_stored_presentation(payload: dict[str, Any]) -> dict[str, Any]:
    for key in _STORED_PRESENTATION_KEYS:
        value = payload.get(key)
        if value is not None and _tree_has_control_char(value):
            payload[key] = (
                [sanitize_finding(f) for f in value]
                if key == "findings" and isinstance(value, list)
                else sanitize_prose_value(value)
            )
    return payload


def _stored_result_format(rec: dict[str, Any]) -> int | None:
    extra = rec.get("extra")
    value = extra.get("result_format") if isinstance(extra, dict) else None
    return value if type(value) is int and value >= 1 else None


def _corrupt(detail: str, meta: Meta) -> dict[str, Any]:
    return error_envelope(
        "internal_error",
        f"job result could not be returned: {redaction.sanitize_echo_prose(detail)}"[:300],
        meta,
        repair_alternative=(
            "Start a new job; if this persists, run amicus_backends and check the server logs."
        ),
    )


def _unreadable(
    detail: str, rec: dict[str, Any], payload: dict[str, Any], meta: Meta
) -> dict[str, Any]:
    fmt = _stored_result_format(rec)
    if fmt is None or fmt == RESULT_FORMAT:
        return _corrupt(detail, meta)
    stored_meta = payload.get("meta")
    version = stored_meta.get("server_version") if isinstance(stored_meta, dict) else None
    provenance = f"result_format {fmt}; this release reads {RESULT_FORMAT}"
    if isinstance(version, str) and version:
        provenance += f", producer server_version {version}"
    message = (
        f"stored job result was written under a different result format ({provenance}): {detail}"
    )
    return error_envelope(
        "job_result_incompatible", redaction.sanitize_echo_prose(message)[:500], meta
    )


def _only_finding_severity_errors(exc: ValidationError) -> bool:
    """True when every error is an out-of-domain `findings[].severity` literal: a
    corrupted machine field (e.g. control-char injection) that stays un-repaired on the
    wire rather than making the whole stored result unreadable."""
    errors = exc.errors()
    return bool(errors) and all(
        err["type"] == "literal_error"
        and len(err["loc"]) == 3
        and err["loc"][0] == "findings"
        and err["loc"][2] == "severity"
        for err in errors
    )


def _validate_success(
    payload: dict[str, Any], kind: str, rec: dict[str, Any], meta: Meta
) -> dict[str, Any]:
    model = JOB_RESULT_MODELS.get(kind)
    if model is None:
        return _unreadable(f"unknown job kind {kind!r}", rec, payload, meta)
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        if not _only_finding_severity_errors(exc):
            return _unreadable(
                f"stored {kind} result did not match its schema: {exc}", rec, payload, meta
            )
    return payload


def finished_job_envelope(
    rec: dict[str, Any],
    payload: dict[str, Any] | None,
    job_id: str,
    kind: str,
    meta: Meta,
    detail: str,
    workspace_root: str | None,
) -> tuple[dict[str, Any], bool]:
    """(envelope, delivered): delivered is True only for a validated stored success or
    error, so a consume never destroys a record it merely described."""
    meta.job_id = job_id
    state = rec["status"]
    if state == "done" and payload is not None:
        stored_meta = payload.get("meta")
        stored_version = (
            stored_meta.get("server_version") if isinstance(stored_meta, dict) else None
        )
        if payload.get("ok") is True:
            validated = _validate_success(payload, kind, rec, meta)
            delivered = validated.get("ok") is True
            if delivered and isinstance(validated.get("meta"), dict):
                validated["meta"]["job_id"] = job_id
                validated["meta"]["fingerprint"] = FINGERPRINT
                validated = _sanitize_stored_presentation(validated)
            return slim_meta(apply_detail(validated, detail)), delivered
        try:
            error = ErrorResult.model_validate(payload)
        except ValidationError as exc:
            return _unreadable(
                f"stored error result was malformed: {exc}", rec, payload, meta
            ), False
        error.meta.job_id = job_id
        error.meta.fingerprint = FINGERPRINT
        error.meta.server_version = stored_version
        if error.error.code == "internal_error" or _has_control_char(error.error.message or ""):
            error.error.message = redaction.sanitize_echo_prose(error.error.message)
        if error.error.repair is not None and _has_control_char(
            error.error.repair.alternative or ""
        ):
            error.error.repair.alternative = redaction.sanitize_echo_prose(
                error.error.repair.alternative
            )
        return serialize_error(error), True
    code, message = STATE_TO_ERROR.get(state, ("job_failed", "The job did not complete."))
    running = state == "running"
    poll_params: dict[str, Any] = {"job_id": job_id}
    if workspace_root:
        poll_params["workspace_root"] = workspace_root
    envelope = error_envelope(
        code,
        message,
        meta,
        repair_arguments=poll_params if running else None,
        retry_after_ms=rec.get("poll_after_ms") if running else None,
    )
    repair = envelope.get("error", {}).get("repair")
    if isinstance(repair, dict):
        # A lifecycle-state error's repair.arguments is a wire-shape guarantee of this
        # chokepoint (poll params when running, explicitly None otherwise) even though
        # serialize_error's general exclude_none drops an absent optional.
        repair.setdefault("arguments", None)
    return envelope, False
