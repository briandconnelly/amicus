"""The §6 envelope shape: invariants pydantic enforces and the published schemas encode."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from amicus import __version__
from amicus.schemas import envelope as e
from amicus.schemas.fingerprint import FINGERPRINT, JSON_SCHEMA_DIALECT


def test_repair_next_step_is_symbolic_and_optionals_default_none():
    r = e.Repair(next_step="poll_job_status")
    assert (r.tool, r.arguments, r.alternative) == (None, None, None)
    with pytest.raises(ValidationError):
        e.Repair(next_step="not_a_step")


def test_errorinfo_requires_temporary_and_retry_after_ms_in_schema():
    schema = e.ErrorInfo.model_json_schema()
    assert "temporary" in schema["required"]
    assert "retry_after_ms" in schema["required"]
    assert "backend" in schema["properties"]


def test_errorinfo_non_temporary_forbids_retry_after_ms():
    with pytest.raises(ValidationError):
        e.ErrorInfo(code="internal_error", message="x", temporary=False, retry_after_ms=5)
    with pytest.raises(ValidationError):
        e.ErrorInfo(code="backend_rate_limited", message="x", temporary=True, retry_after_ms=-1)
    ok = e.ErrorInfo(
        code="backend_rate_limited", message="x", backend="codex", temporary=True, retry_after_ms=1
    )
    assert ok.backend == "codex"


def test_errorinfo_rejects_unknown_code_and_malformed_backend_id():
    with pytest.raises(ValidationError):
        e.ErrorInfo(code="codex_not_found", message="x", temporary=False, retry_after_ms=None)
    # `backend` is an open lowercase identifier (third-party plugins carry their own id),
    # not the v1 enum; only the shape is validated.
    with pytest.raises(ValidationError):
        e.ErrorInfo(
            code="internal_error",
            message="x",
            backend="Not-An-Id",
            temporary=False,
            retry_after_ms=None,
        )
    assert (
        e.ErrorInfo(
            code="internal_error", message="x", backend="fake", temporary=False, retry_after_ms=None
        ).backend
        == "fake"
    )


def test_errordetail_field_and_fields_are_exclusive_and_value_is_absent():
    assert "value" not in e.ErrorDetail.model_fields
    assert e.ErrorDetail(field="question").field == "question"
    assert e.ErrorDetail(fields=["a", "b"]).fields == ["a", "b"]
    with pytest.raises(ValidationError):
        e.ErrorDetail(field="a", fields=["a", "b"])
    with pytest.raises(ValidationError):
        e.ErrorDetail(fields=[])
    with pytest.raises(ValidationError):
        e.ErrorDetail(fields=["a", "a"])
    assert "minItems" in json.dumps(e.ErrorDetail.model_json_schema()["properties"]["fields"])


def test_meta_defaults_and_identity():
    m = e.Meta()
    assert m.cwd is None and m.backend is None
    assert m.fingerprint == FINGERPRINT
    assert m.server_version == __version__
    assert len(m.request_id) == 32
    assert m.elapsed_ms == 0 and m.truncated is False
    with pytest.raises(ValidationError):
        e.Meta(backend="Not-An-Id")
    with pytest.raises(ValidationError):
        e.Meta(unknown_key=1)


def test_meta_field_names_are_the_documented_set():
    assert list(e.Meta.model_fields) == [
        "backend",
        "cwd",
        "workspace_source",
        "workspace_warning",
        "roots_source",
        "model",
        "reasoning_effort",
        "timeout_seconds",
        "elapsed_ms",
        "command_exit_code",
        "session_id",
        "truncated",
        "truncation_hint",
        "compat_warnings",
        "security_warnings",
        "redacted_paths",
        "usage",
        "context_summary",
        "job_id",
        "job_kind",
        "task_id",
        "idempotency_replayed",
        "backend_details",
        "request_id",
        "fingerprint",
        "server_version",
    ]


def test_usage_carries_cache_fields():
    u = e.Usage(input_tokens=1, cached_input_tokens=2, cache_creation_input_tokens=3)
    assert (u.cached_input_tokens, u.cache_creation_input_tokens) == (2, 3)
    assert u.total_tokens is None


def test_error_envelope_schema_is_hardened():
    s = e.ERROR_ENVELOPE_SCHEMA
    assert s["$schema"] == JSON_SCHEMA_DIALECT
    assert "ok" in s["required"]
    info = s["$defs"]["ErrorInfo"]
    assert info["if"] == {"properties": {"temporary": {"const": False}}, "required": ["temporary"]}
    assert info["then"] == {"properties": {"retry_after_ms": {"const": None}}}
    # The offending-value policy is disclosed on the envelope resource ([6.offending-value]).
    assert "details.value" in s["description"]


def test_result_meta_schema_carries_dialect_and_delivered_shape_rule():
    s = e.RESULT_META_SCHEMA
    assert s["$schema"] == JSON_SCHEMA_DIALECT
    assert "backend" in s["properties"]
    assert "null-valued keys" in s["description"]


def test_dump_success_retains_nulls():
    class Model(e.SuccessBase):
        tool: str = "amicus_consult"
        summary: str = "s"

    out = e.dump_success(Model(meta=e.Meta()))
    assert out["ok"] is True
    assert "cwd" in out["meta"] and out["meta"]["cwd"] is None
