"""One serializer for the §6 envelope; pontonier rules are defaults, plugins override."""

from __future__ import annotations

import pytest
from pontonier.backend.protocol import ClassifiedFailure, RepairHint
from pontonier.backend.protocol import Usage as PUsage
from pontonier.conventions.envelope import RepairRule
from tests.support import fakeplugin

from amicus import errors
from amicus.schemas.codes import ERROR_CODES
from amicus.schemas.envelope import ErrorDetail, ErrorResult, InvalidArgument, Meta


def test_repair_table_covers_the_whole_catalog_and_no_more():
    table = errors.repair_table()
    assert set(table) == set(ERROR_CODES)
    assert table["backend_not_found"].next_step == "install_backend"
    assert table["not_implemented"].tool == "amicus_capabilities"
    assert "amicus_backends" in table["backend_unavailable"].alternative
    # Prose overrides name amicus tools, never a sibling's.
    assert "amicus_consult_async" in table["timeout"].alternative
    assert "codex" not in table["invalid_arguments"].alternative


def test_plugin_overrides_win_per_code_and_local_codes_are_added():
    plugin = fakeplugin.make_plugin(
        repair_overrides={
            "fake_auth_required": RepairRule("authenticate", None, False, "Run `fake login`.")
        },
        local_codes={"fake_only": RepairRule("inspect_and_retry", None, True, "fake-only")},
    )
    table = errors.repair_table(plugin)
    assert table["backend_auth_required"].alternative == "Run `fake login`."
    assert table["fake_only"].alternative == "fake-only"
    assert errors.repair_table()["backend_auth_required"].alternative != "Run `fake login`."


def test_make_error_derives_repair_and_temporary_from_the_table():
    info = errors.make_error("job_running", "still running", retry_after_ms=500)
    assert info.temporary is True and info.retry_after_ms == 500
    assert info.repair is not None
    assert info.repair.next_step == "poll_job_status" and info.repair.tool == "amicus_job_status"
    info = errors.make_error("invalid_scope", "bad", retry_after_ms=500)
    assert info.temporary is False and info.retry_after_ms is None
    info = errors.make_error("invalid_scope", "bad", temporary=True, retry_after_ms=5)
    assert info.retry_after_ms == 5


def test_make_error_repair_tool_three_states():
    keep = errors.make_error("job_not_found", "m")
    assert keep.repair is not None and keep.repair.tool == "amicus_job_list"
    cleared = errors.make_error("job_not_found", "m", repair_tool=None)
    assert cleared.repair is not None and cleared.repair.tool is None
    named = errors.make_error("job_not_found", "m", repair_tool="amicus_job_status")
    assert named.repair is not None and named.repair.tool == "amicus_job_status"


def test_invalid_arguments_requires_the_list_and_derives_details():
    with pytest.raises(ValueError, match="non-empty invalid_arguments"):
        errors.make_error("invalid_arguments", "m")
    with pytest.raises(ValueError, match="derived"):
        errors.make_error(
            "invalid_arguments",
            "m",
            details=ErrorDetail(field="x"),
            invalid_arguments=[InvalidArgument(field="x", reason="r")],
        )
    info = errors.make_error(
        "invalid_arguments",
        "m",
        invalid_arguments=[InvalidArgument(field="x", reason="r", allowed_values=["a"])],
    )
    assert info.details == ErrorDetail(field="x", reason="r", allowed_values=["a"])


def test_serialize_strips_none_but_keeps_retry_after_ms():
    info = errors.make_error("internal_error", "m", backend="codex")
    out = errors.serialize_error(ErrorResult(error=info, meta=Meta()))
    assert out["ok"] is False
    assert out["error"]["retry_after_ms"] is None
    assert "details" not in out["error"]
    assert out["error"]["backend"] == "codex"
    assert "cwd" not in out["meta"]
    assert errors.serialize_error_info(info)["code"] == "internal_error"
    no_backend = errors.make_error("internal_error", "m")
    assert errors.serialize_error_info(no_backend)["backend"] is None


def test_error_envelope_helper():
    out = errors.error_envelope("not_implemented", "later", Meta(), backend="kimi")
    assert out["error"]["code"] == "not_implemented" and out["error"]["backend"] == "kimi"


def test_render_failure_generalizes_minted_codes_and_names_the_backend():
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(code="fake_rate_limited", detail="slow down", retry_after_ms=250)
    out = errors.render_failure(plugin, failure, Meta())
    err = out["error"]
    assert err["code"] == "backend_rate_limited" and err["backend"] == "fake"
    assert err["temporary"] is True and err["retry_after_ms"] == 250
    assert err["repair"]["next_step"] == "retry_after_delay"


def test_render_failure_honors_retryable_details_repair_and_usage():
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(
        code="timeout",
        detail="deadline",
        retryable=False,
        details={"field": "timeout_seconds", "reason": "exceeded"},
        repair=RepairHint(next_step="reduce_input", tool="amicus_consult", alternative="shrink"),
        usage=PUsage(input_tokens=3, cost_usd=0.5),
    )
    out = errors.render_failure(plugin, failure, Meta())
    err = out["error"]
    assert err["temporary"] is False and err["retry_after_ms"] is None
    assert err["details"] == {
        "field": "timeout_seconds",
        "reason": "exceeded",
        "field_withheld": False,
    }
    assert err["repair"] == {
        "next_step": "reduce_input",
        "tool": "amicus_consult",
        "alternative": "shrink",
    }
    assert out["meta"]["usage"]["input_tokens"] == 3 and out["meta"]["usage"]["cost_usd"] == 0.5


def test_render_failure_maps_an_uncataloged_code_to_internal_error_with_the_detail():
    plugin = fakeplugin.make_plugin()
    out = errors.render_failure(plugin, ClassifiedFailure(code="mystery", detail="d"), Meta())
    assert out["error"]["code"] == "internal_error"
    assert "mystery" in out["error"]["message"] and "d" in out["error"]["message"]


def test_render_failure_tolerates_bad_details():
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(
        code="nonzero_exit", detail="d", details={"field": "a", "fields": ["b"]}
    )
    out = errors.render_failure(plugin, failure, Meta())
    assert out["error"]["details"] == {"reason": "field=a fields=['b']", "field_withheld": False}
