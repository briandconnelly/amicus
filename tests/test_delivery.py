"""The single delivery chokepoint: detail, slimming, validation, lifecycle-state errors."""

from __future__ import annotations

from typing import get_args

from amicus.errors import error_envelope
from amicus.jobs import delivery
from amicus.jobs.store import DiscardOutcome as StoreDiscardOutcome
from amicus.schemas.envelope import ConsumeDisposition, DiscardOutcome, Meta, dump_success
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
    # A real store record carries elapsed_ms beside pontonier's hint; the job_running hint
    # is derived from it (#95), so 1500 ms elapsed is a 1500 ms hint.
    return {
        "status": status,
        "extra": {"result_format": fmt},
        "elapsed_ms": 1500,
        "poll_after_ms": 1500,
        **extra,
    }


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


def test_job_running_retry_follows_the_grown_poll_hint():
    # retry_after_ms matches amicus_job_status's own hint, not the record's stale one (#95).
    rec = _rec("running", elapsed_ms=240_000, poll_after_ms=10000)
    env, delivered = delivery.finished_job_envelope(
        rec, None, _JOB, "consult", Meta(), "full", "/repo"
    )
    assert not delivered and env["error"]["retry_after_ms"] == 30000


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


def test_a_stored_result_from_another_format_is_never_delivered_as_current():
    """A payload written before a field existed still validates, because the new field
    has a default - so validation alone cannot catch it and the format must be checked
    FIRST. Delivering it would answer a question the producing release never asked: a
    defaulted `findings_diagnostics: null` would assert "nothing was lost" about a run
    that never measured loss (issue #38)."""
    env, delivered = delivery.finished_job_envelope(
        _rec(fmt=RESULT_FORMAT - 1), _stored_success(), _JOB, "consult", Meta(), "full", None
    )
    assert not delivered
    assert env["error"]["code"] == "job_result_incompatible"
    assert "result_format" in env["error"]["message"]


def test_a_stored_result_with_no_recorded_format_is_not_delivered_either():
    env, delivered = delivery.finished_job_envelope(
        {"status": "done", "extra": {}, "poll_after_ms": 1500},
        _stored_success(),
        _JOB,
        "consult",
        Meta(),
        "full",
        None,
    )
    assert not delivered and env["error"]["code"] == "job_result_incompatible"


def test_the_format_gate_covers_a_stored_error_too():
    """The format stamps the RECORD, not one branch of it."""
    stored = error_envelope("timeout", "t", Meta(backend="codex"))
    env, delivered = delivery.finished_job_envelope(
        _rec(fmt=RESULT_FORMAT - 1), stored, _JOB, "consult", Meta(), "full", None
    )
    assert not delivered and env["error"]["code"] == "job_result_incompatible"


def test_the_wire_outcomes_are_exactly_the_stores():
    """A new pontonier outcome must fail here, not validate as a value amicus never names."""
    assert set(get_args(DiscardOutcome)) == {o.value for o in StoreDiscardOutcome}


def test_attach_consume_disposition_maps_every_discard_outcome():
    for outcome in StoreDiscardOutcome:
        for root in (None, "/repo"):
            env = delivery.attach_consume_disposition({"ok": True, "meta": {}}, outcome, _JOB, root)
            got = env["meta"]["consume"]
            assert got["discard_outcome"] == outcome.value
            if outcome in (StoreDiscardOutcome.REMOVED, StoreDiscardOutcome.MISSING):
                assert got == {"discard_outcome": outcome.value}, "the record is gone"
                continue
            arguments = {"job_id": _JOB}
            if root is not None:
                arguments["workspace_root"] = root
            assert got["follow_up"] == {
                "next_step": "inspect_and_retry",
                "tool": "amicus_job_status",
                "arguments": arguments,
                "alternative": delivery.CONSUME_FOLLOW_UP,
            }


def test_consumable_state_names_what_a_consume_may_delete():
    """A done record only once delivered (a corrupt or incompatible one is kept), and every
    terminal-error record in the state it was read in (#126); a running job never."""
    assert delivery.consumable_state("done", True) == "done"
    assert delivery.consumable_state("done", False) is None
    assert delivery.consumable_state("running", False) is None
    for state in ("failed", "cancelled", "timeout"):
        assert delivery.consumable_state(state, False) == state
    # Every state that has a terminal error, except running, is one a consume may delete.
    assert set(delivery.STATE_TO_ERROR) - {"running"} == delivery.TERMINAL_ERROR_STATES


def test_consume_is_never_persisted_and_a_stored_copy_never_reaches_a_plain_read():
    meta = Meta(consume=ConsumeDisposition(discard_outcome="removed"))
    assert meta.consume is not None, "control: the field is set on the model"
    assert "consume" not in dump_success(ConsultResult(summary="s", meta=meta))["meta"]
    assert "consume" not in error_envelope("timeout", "t", meta)["meta"]
    stored = _stored_success()
    stored["meta"]["consume"] = {"discard_outcome": "removed"}
    env, delivered = delivery.finished_job_envelope(
        _rec(), stored, _JOB, "consult", Meta(), "summary", None
    )
    assert delivered, "control: a stored copy validates, so only the scrub removes it"
    assert "consume" not in env["meta"]
