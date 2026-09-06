"""The single delivery chokepoint: detail, slimming, validation, lifecycle-state errors."""

from __future__ import annotations

from amicus.errors import error_envelope
from amicus.jobs import delivery
from amicus.schemas.envelope import Meta, dump_success
from amicus.schemas.fingerprint import FINGERPRINT, RESULT_FORMAT
from amicus.schemas.results import ConsultResult, RawResponse

_JOB = "0" * 32


def _stored_success(text="RAW", **meta_fields):
    meta = Meta(backend="codex", cwd="/repo", model="m", session_id="s", **meta_fields)
    meta.fingerprint = "old/fingerprint"
    return dump_success(
        ConsultResult(
            summary="s", raw_response=RawResponse(text=text, session_id="s", model="m"), meta=meta
        )
    )


def _rec(status="done", fmt=RESULT_FORMAT, **extra):
    return {"status": status, "extra": {"result_format": fmt}, "poll_after_ms": 1500, **extra}


def test_apply_detail_and_slim_meta():
    env = _stored_success()
    assert delivery.apply_detail(dict(env), "full")["raw_response"]["text"] == "RAW"
    summary = delivery.apply_detail(dict(env), "summary")
    assert summary["raw_response"]["text"] is None and summary["summary"] == "s"
    slim = delivery.slim_meta(dict(env))
    assert (
        "usage" not in slim["meta"]
        and slim["meta"]["elapsed_ms"] == 0
        and slim["meta"]["model"] == "m"
    )
    err = error_envelope("timeout", "t", Meta())
    assert (
        delivery.slim_meta(dict(err)) == err and delivery.apply_detail(dict(err), "summary") == err
    )


def test_done_success_is_validated_stamped_and_slimmed():
    env, delivered = delivery.finished_job_envelope(
        _rec(), _stored_success(), _JOB, "consult", Meta(), "summary", None
    )
    assert delivered and env["ok"] is True
    assert env["meta"]["job_id"] == _JOB and env["meta"]["fingerprint"] == FINGERPRINT
    assert "usage" not in env["meta"] and env["raw_response"]["text"] is None


def test_done_success_of_the_wrong_kind_or_format_is_not_delivered():
    env, delivered = delivery.finished_job_envelope(
        _rec(), _stored_success(), _JOB, "delegate", Meta(), "full", None
    )
    assert (
        not delivered and env["error"]["code"] == "internal_error" and env["meta"]["job_id"] == _JOB
    )
    env, delivered = delivery.finished_job_envelope(
        _rec(fmt=RESULT_FORMAT + 1), _stored_success(), _JOB, "delegate", Meta(), "full", None
    )
    assert (
        not delivered
        and env["error"]["code"] == "job_result_incompatible"
        and "result_format" in env["error"]["message"]
    )
    env, delivered = delivery.finished_job_envelope(
        _rec(), {"ok": True, "tool": "amicus_consult"}, _JOB, "unknown_kind", Meta(), "full", None
    )
    assert not delivered and env["error"]["code"] == "internal_error"


def test_done_error_is_validated_and_keeps_the_producer_version():
    stored = error_envelope("nonzero_exit", "boom\x1b[31m", Meta(backend="codex", cwd="/repo"))
    stored["meta"]["server_version"] = "0.0.1"
    env, delivered = delivery.finished_job_envelope(
        _rec(), stored, _JOB, "consult", Meta(), "full", None
    )
    assert delivered and env["ok"] is False and env["error"]["code"] == "nonzero_exit"
    assert env["meta"]["job_id"] == _JOB and env["meta"]["server_version"] == "0.0.1"
    assert "\x1b" not in env["error"]["message"] and env["meta"]["fingerprint"] == FINGERPRINT
    env, delivered = delivery.finished_job_envelope(
        _rec(), {"ok": False, "error": {"code": "nope"}}, _JOB, "consult", Meta(), "full", None
    )
    assert not delivered and env["error"]["code"] == "internal_error"


def test_lifecycle_states():
    env, delivered = delivery.finished_job_envelope(
        _rec("running"), None, _JOB, "consult", Meta(), "full", "/repo"
    )
    assert (
        not delivered
        and env["error"]["code"] == "job_running"
        and env["error"]["retry_after_ms"] == 1500
    )
    assert env["error"]["repair"]["tool"] == "amicus_job_status" and env["error"]["repair"][
        "arguments"
    ] == {"job_id": _JOB, "workspace_root": "/repo"}
    for state, code in (
        ("cancelled", "job_cancelled"),
        ("timeout", "job_timeout"),
        ("failed", "job_failed"),
    ):
        env, delivered = delivery.finished_job_envelope(
            _rec(state), None, _JOB, "consult", Meta(), "full", None
        )
        assert (
            not delivered
            and env["error"]["code"] == code
            and env["error"]["repair"].get("arguments") is None
        )


def test_done_with_an_unreadable_payload_is_distinct_from_a_failed_job():
    env, delivered = delivery.finished_job_envelope(
        _rec("done"), None, _JOB, "consult", Meta(), "full", None
    )
    assert (
        not delivered
        and env["error"]["code"] == "job_failed"
        and env["error"]["message"] == "The job finished but its stored result could not be read."
    )
    assert env["error"]["repair"].get("arguments") is None


def test_stored_presentation_is_sanitized_only_when_a_control_char_is_present():
    env = _stored_success()
    env["summary"] = "a\x07b"
    env["findings"] = [{"title": "t\x07", "severity": "medium", "file": "f\x07.py"}]
    out, _ = delivery.finished_job_envelope(_rec(), env, _JOB, "consult", Meta(), "full", None)
    assert out["summary"] == "ab" and out["findings"][0]["title"] == "t"
    assert out["findings"][0]["file"] == "f\x07.py"  # a machine field is never repaired


def test_a_coerced_field_in_the_stored_payload_is_not_delivered():
    env = _stored_success()
    env["meta"]["elapsed_ms"] = "1"  # lax validation would coerce this; strict must not
    out, delivered = delivery.finished_job_envelope(
        _rec(), env, _JOB, "consult", Meta(), "full", None
    )
    assert not delivered and out["error"]["code"] == "internal_error"
    assert out["meta"]["job_id"] == _JOB


def test_a_genuine_stored_success_still_delivers():
    out, delivered = delivery.finished_job_envelope(
        _rec(), _stored_success(), _JOB, "consult", Meta(), "full", None
    )
    assert delivered and out["ok"] is True and out["meta"]["job_id"] == _JOB
