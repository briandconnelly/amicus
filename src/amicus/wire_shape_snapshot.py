"""Canonical snapshot of the DELIVERED (wire) success-envelope surface (ported from
codex-in-claude #334/#400). Rendered by driving the REAL chokepoint,
`jobs.delivery.finished_job_envelope`, so the fixture stays blind to nothing the wiring does.
Representative metas populate their producible optionals (a null optional is already absent
on the wire, so a regression deleting a populated key must have somewhere to show); the
no-changes delegate stays sparse so the omission itself remains visible."""

from __future__ import annotations

import json
from typing import Any

from amicus.errors import make_error, serialize_error
from amicus.jobs.delivery import finished_job_envelope
from amicus.orchestration.workspace import workspace_warning_for
from amicus.schemas.envelope import (
    ContextSummary,
    ErrorResult,
    InstructionsFingerprint,
    Meta,
    Usage,
    dump_success,
)
from amicus.schemas.fingerprint import FINGERPRINT, RESULT_FORMAT
from amicus.schemas.results import ConsultResult, DelegateResult, RawResponse, ReviewResult

_FINGERPRINT_SENTINEL = "<fingerprint>"
_VERSION_SENTINEL = "0.0.0"
_REQUEST_ID_SENTINEL = "0" * 32
_JOB_ID_SENTINEL = "0" * 32


def _meta(**optional: Any) -> Meta:
    meta = Meta(backend="codex", cwd="/repo", timeout_seconds=1, elapsed_ms=1, **optional)
    meta.fingerprint = _FINGERPRINT_SENTINEL
    meta.server_version = _VERSION_SENTINEL
    meta.request_id = _REQUEST_ID_SENTINEL
    return meta


def _populated(**extra: Any) -> Meta:
    fields: dict[str, Any] = {
        "workspace_source": "param",
        "roots_source": "client",
        "model": "a-model",
        "reasoning_effort": "high",
        "instructions_append": InstructionsFingerprint(sha256="a" * 64, bytes=5),
        "command_exit_code": 0,  # a POPULATED FALSY optional: slimming keys on `is None`
        "session_id": "sess-1",
        "usage": Usage(input_tokens=1, output_tokens=2, total_tokens=6, cached_input_tokens=3),
        "backend_details": {"isolation": "inherit"},
    }
    fields.update(extra)
    return _meta(**fields)


def _raw() -> RawResponse:
    return RawResponse(text="RAW MODEL TEXT", session_id="sess-1", model="a-model")


def _stored_envelopes() -> dict[str, dict[str, Any]]:
    return {
        "consult": dump_success(ConsultResult(summary="s", raw_response=_raw(), meta=_populated())),
        "review": dump_success(
            ReviewResult(
                summary="s",
                verdict="pass",
                confidence="high",
                review_status="completed",
                context_summary=ContextSummary(files_changed=1, lines_added=2, lines_removed=3),
                raw_response=_raw(),
                meta=_populated(
                    context_summary=ContextSummary(files_changed=1, lines_added=2, lines_removed=3)
                ),
            )
        ),
        # The states the branch review cannot hold at once: a cwd-resolved workspace and a
        # truncated diff, so every producible optional is populated SOMEWHERE.
        "review_commit_truncated": dump_success(
            ReviewResult(
                summary="s",
                verdict="unknown",
                confidence="low",
                review_status="completed",
                raw_response=_raw(),
                meta=_populated(
                    workspace_source="cwd",
                    workspace_warning=workspace_warning_for("cwd", "/repo"),
                    truncated=True,
                    truncation_hint="diff exceeded the byte cap; narrow the scope with paths",
                    redacted_paths=[".env"],
                    security_warnings=["baseline warning"],
                    compat_warnings=["--model"],
                ),
            )
        ),
        "delegate_no_changes": dump_success(
            DelegateResult(summary="s", diff=None, raw_response=_raw(), meta=_meta())
        ),
    }


_KIND_BY_NAME = {
    "consult": "consult",
    "review": "review_changes",
    "review_commit_truncated": "review_changes",
    "delegate_no_changes": "delegate",
}


def _deliver(stored: dict[str, Any], name: str, detail: str) -> dict[str, Any]:
    rec = {"status": "done", "extra": {"result_format": RESULT_FORMAT}}
    envelope, delivered = finished_job_envelope(
        rec,
        json.loads(json.dumps(stored)),
        _JOB_ID_SENTINEL,
        _KIND_BY_NAME[name],
        _meta(),
        detail,
        None,
    )
    if not delivered:
        raise AssertionError(f"{name}: the chokepoint refused to deliver the payload")
    if envelope["meta"].get("fingerprint") != FINGERPRINT:
        raise AssertionError(f"{name}: the chokepoint did not stamp meta.fingerprint")
    envelope["meta"]["fingerprint"] = _FINGERPRINT_SENTINEL
    return envelope


_POLL_AFTER_MS_SENTINEL = 500
# result_format the chokepoint reads today; a stored record claiming a DIFFERENT value
# (never None, never the current one) is what makes `_unreadable` report
# job_result_incompatible instead of internal_error.
_INCOMPATIBLE_RESULT_FORMAT = RESULT_FORMAT + 1


def _lifecycle_envelope(
    rec: dict[str, Any],
    payload: dict[str, Any] | None,
    kind: str,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    envelope, _delivered = finished_job_envelope(
        rec, payload, _JOB_ID_SENTINEL, kind, _meta(), "summary", workspace_root
    )
    if envelope["meta"].get("fingerprint") == FINGERPRINT:
        envelope["meta"]["fingerprint"] = _FINGERPRINT_SENTINEL
    return envelope


def _lifecycle_envelopes() -> dict[str, dict[str, Any]]:
    """The non-`done`-success outcomes `finished_job_envelope` produces: the four
    still-in-flight/terminal-without-a-result states, a `done` record whose stored
    payload IS an error envelope (passthrough), and a `done` record whose payload
    fails its kind's schema under a result_format the chokepoint no longer reads."""
    running = _lifecycle_envelope(
        {"status": "running", "poll_after_ms": _POLL_AFTER_MS_SENTINEL},
        None,
        "consult",
        workspace_root="/repo",
    )
    cancelled = _lifecycle_envelope({"status": "cancelled"}, None, "consult")
    timeout = _lifecycle_envelope({"status": "timeout"}, None, "consult")
    failed = _lifecycle_envelope({"status": "failed"}, None, "consult")

    stored_error = serialize_error(
        ErrorResult(
            error=make_error("nonzero_exit", "the backend command exited nonzero", backend="codex"),
            meta=_meta(),
        )
    )
    done_error = _lifecycle_envelope(
        {"status": "done", "extra": {"result_format": RESULT_FORMAT}},
        json.loads(json.dumps(stored_error)),
        "consult",
    )

    mismatched_payload = dump_success(ConsultResult(summary="s", raw_response=_raw(), meta=_meta()))
    done_incompatible = _lifecycle_envelope(
        {"status": "done", "extra": {"result_format": _INCOMPATIBLE_RESULT_FORMAT}},
        json.loads(json.dumps(mismatched_payload)),
        "review_changes",
    )

    return {
        "running": running,
        "cancelled": cancelled,
        "timeout": timeout,
        "failed": failed,
        "done_error": done_error,
        "done_incompatible": done_incompatible,
    }


def build_snapshot() -> dict[str, Any]:
    stored = _stored_envelopes()
    return {
        "delivered": {
            detail: {name: _deliver(env, name, detail) for name, env in stored.items()}
            for detail in ("summary", "full")
        },
        "omitted_meta_keys": {
            name: sorted(set(env["meta"]) - set(_deliver(env, name, "summary")["meta"]))
            for name, env in stored.items()
        },
        "lifecycle": _lifecycle_envelopes(),
    }


def render() -> str:
    return json.dumps(build_snapshot(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.stdout.write(render())
