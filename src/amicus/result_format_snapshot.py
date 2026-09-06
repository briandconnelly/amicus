"""Canonical snapshot of the persisted result-format surface (ported from codex-in-claude
#305): the envelope models' schemas (wording stripped, release variables pinned) and
representative envelopes through the REAL writers, pinning the null-retention asymmetry
between dump_success (nulls kept) and serialize_error (nulls dropped)."""

from __future__ import annotations

import json
from typing import Any

from amicus.errors import make_error, serialize_error
from amicus.schemas.envelope import ErrorResult, InstructionsFingerprint, Meta, dump_success
from amicus.schemas.fingerprint import FINGERPRINT, RESULT_FORMAT
from amicus.schemas.results import ConsultResult, DelegateResult, ReviewResult

_ENVELOPE_MODELS = (ConsultResult, ReviewResult, DelegateResult, ErrorResult)
_FINGERPRINT_SENTINEL = "<fingerprint>"
_VERSION_SENTINEL = "0.0.0"
_REQUEST_ID_SENTINEL = "0" * 32


_FIELD_NAME_CONTAINERS = ("properties", "$defs")


def _normalize_schema(node: Any, *, in_field_map: bool = False) -> Any:
    """Strip `description` and pin the fingerprint default — but never at the immediate
    child level of a `properties` or `$defs` map, whose keys are field/definition NAMES
    (a field could itself be named `description`), not schema keywords."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if in_field_map:
                out[key] = _normalize_schema(value)
                continue
            if key == "description":
                continue
            if key == "default" and value == FINGERPRINT:
                out[key] = _FINGERPRINT_SENTINEL
                continue
            out[key] = _normalize_schema(value, in_field_map=key in _FIELD_NAME_CONTAINERS)
        return out
    if isinstance(node, list):
        return [_normalize_schema(v) for v in node]
    return node


def _meta(**fields: Any) -> Meta:
    meta = Meta(backend="codex", cwd="/repo", timeout_seconds=1, elapsed_ms=1, **fields)
    meta.fingerprint = _FINGERPRINT_SENTINEL
    meta.server_version = _VERSION_SENTINEL
    meta.request_id = _REQUEST_ID_SENTINEL
    return meta


def build_snapshot() -> dict[str, Any]:
    serialized = {
        "consult_success": dump_success(ConsultResult(summary="s", meta=_meta())),
        "review_success": dump_success(
            ReviewResult(
                summary="s",
                verdict="pass",
                confidence="high",
                review_status="completed",
                meta=_meta(instructions_append=InstructionsFingerprint(sha256="a" * 64, bytes=5)),
            )
        ),
        "delegate_success": dump_success(DelegateResult(summary="s", diff=None, meta=_meta())),
        "error": serialize_error(
            ErrorResult(error=make_error("internal_error", "m"), meta=_meta())
        ),
        # A backend-local code outside the sample above, so an ErrorCode change shows in the
        # persisted bytes and not only in the schemas view.
        "error_user_config_rejected": serialize_error(
            ErrorResult(
                error=make_error("user_config_rejected", "m", backend="codex"),
                meta=_meta(command_exit_code=1),
            )
        ),
    }
    return {
        "result_format": RESULT_FORMAT,
        "schemas": {m.__name__: _normalize_schema(m.model_json_schema()) for m in _ENVELOPE_MODELS},
        "serialized": serialized,
    }


def render() -> str:
    return json.dumps(build_snapshot(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.stdout.write(render())
