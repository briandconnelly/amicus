"""One serializer for the §6 envelope; pontonier rules are defaults, plugins override."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from tests.support import fakeplugin

from amicus import errors
from amicus.schemas.codes import ERROR_CODES
from amicus.schemas.envelope import ErrorDetail, ErrorResult, InvalidArgument, Meta
from amicus.sdk.backend.protocol import ClassifiedFailure, RepairHint
from amicus.sdk.backend.protocol import Usage as PUsage
from amicus.sdk.conventions.envelope import RepairRule


def test_repair_table_covers_the_whole_catalog_and_no_more():
    table = errors.repair_table()
    assert set(table) == set(ERROR_CODES)
    assert table["backend_not_found"].next_step == "install_backend"
    assert table["backend_unavailable"].tool == "amicus_backends"
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


def test_make_error_with_a_plugin_uses_its_table_and_backend_id():
    plugin = fakeplugin.make_plugin(
        repair_overrides={
            "fake_auth_required": RepairRule("authenticate", None, False, "Run `fake login`.")
        },
        local_codes={"fake_only": RepairRule("inspect_and_retry", None, True, "fake-only")},
    )
    info = errors.make_error("backend_auth_required", "m", plugin=plugin)
    assert info.backend == "fake"
    assert info.repair is not None and info.repair.alternative == "Run `fake login`."
    # An explicit backend wins over the plugin's id.
    assert (
        errors.make_error("internal_error", "m", backend="codex", plugin=plugin).backend == "codex"
    )


def test_make_error_derives_repair_and_temporary_from_the_table():
    info = errors.make_error("job_running", "still running", retry_after_ms=500)
    assert info.temporary is True and info.retry_after_ms == 500
    assert info.repair is not None
    assert info.repair.next_step == "poll_job_status" and info.repair.tool == "amicus_job_status"
    info = errors.make_error("invalid_scope", "bad", retry_after_ms=500)
    assert info.temporary is False and info.retry_after_ms is None
    info = errors.make_error("invalid_scope", "bad", temporary=True, retry_after_ms=5)
    assert info.retry_after_ms == 5


def test_workspace_codes_carry_no_repair():
    # Issue #42: no call can mint the caller's intended absolute directory, so the envelope
    # names the field (details, candidate_roots) and omits repair rather than ship prose.
    for code in ("invalid_workspace_root", "workspace_outside_roots"):
        assert errors.make_error(code, "m").repair is None
        payload = errors.error_envelope(code, "m", Meta())
        assert "repair" not in payload["error"]


def _input_schema(tool: str) -> dict:
    fixture = Path(__file__).parent / "fixtures" / "manifest_snapshot.all.json"
    record = next(t for t in json.loads(fixture.read_text())["tools"] if t["name"] == tool)
    return record.get("inputSchema") or record["input_schema"]


@pytest.mark.parametrize(
    ("code", "backend", "tool", "arguments"),
    [
        ("invalid_model", "codex", "amicus_models", {"backend": "codex"}),
        ("invalid_reasoning_effort", "kimi", "amicus_models", {"backend": "kimi"}),
        ("backend_unavailable", "claude", "amicus_backends", {"backend": "claude"}),
        ("api_key_missing", "claude", "amicus_backends", {"backend": "claude"}),
        ("backend_unavailable", None, "amicus_backends", {}),
    ],
)
def test_lookup_repairs_carry_a_complete_call(code, backend, tool, arguments):
    # Issue #42: a repair routed to a lookup names the call that makes it, not only the
    # tool; amicus_models requires backend, so a tool-only repair there is not callable.
    info = errors.make_error(code, "m", backend=backend)
    assert info.repair is not None
    assert (info.repair.tool, info.repair.arguments) == (tool, arguments)
    Draft202012Validator(_input_schema(tool)).validate(arguments)


def test_render_failure_completes_a_lookup_repair():
    plugin = fakeplugin.make_plugin("codex")
    from_table = ClassifiedFailure(code="invalid_model", detail="no")
    hinted = ClassifiedFailure(
        code="invalid_model",
        detail="no",
        repair=RepairHint(next_step="use_allowed_value", tool="amicus_models", alternative="x"),
    )
    for failure in (from_table, hinted):
        repair = errors.render_failure(plugin, failure, Meta())["error"]["repair"]
        assert (repair["tool"], repair["arguments"]) == ("amicus_models", {"backend": "codex"})


def test_lookup_repairs_never_name_a_backend_the_lookup_rejects():
    # Codex review of #42: a third-party plugin id is a valid error.backend but not a value
    # the lookup tools' closed `backend` enum accepts, so completing with it would mint a
    # call its own tool rejects. amicus_backends falls back to the unfiltered call.
    plugin = fakeplugin.make_plugin()
    unavailable = errors.render_failure(
        plugin, ClassifiedFailure(code="backend_unavailable", detail="no"), Meta()
    )["error"]["repair"]
    assert (unavailable["tool"], unavailable["arguments"]) == ("amicus_backends", {})
    Draft202012Validator(_input_schema("amicus_backends")).validate(unavailable["arguments"])
    # amicus_models cannot be called without a backend it accepts, so naming it would be a
    # dead route (Copilot review of #42): the repair stays a symbolic next step, no tool.
    model = errors.render_failure(
        plugin, ClassifiedFailure(code="invalid_model", detail="no"), Meta()
    )["error"]["repair"]
    assert model["next_step"] == "use_allowed_value"
    assert "tool" not in model and "arguments" not in model
    bare = errors.make_error("invalid_reasoning_effort", "m").repair
    assert bare is not None and (bare.tool, bare.arguments) == (None, None)


@pytest.mark.parametrize(
    ("tool", "hinted", "expected"),
    [
        ("amicus_models", {"backend": "kimi"}, ("amicus_models", {"backend": "kimi"})),
        ("amicus_models", {}, (None, None)),
        ("amicus_models", {"backend": "fake"}, (None, None)),
        ("amicus_models", {"backend": "kimi", "x": 1}, (None, None)),
        ("amicus_backends", {"backend": "kimi"}, ("amicus_backends", {"backend": "kimi"})),
        ("amicus_backends", {}, ("amicus_backends", {})),
        ("amicus_backends", {"backend": "fake"}, ("amicus_backends", {})),
        ("amicus_backends", {"x": 1}, ("amicus_backends", {})),
    ],
)
def test_an_explicit_lookup_call_is_kept_only_in_a_shape_its_tool_accepts(tool, hinted, expected):
    # Codex's second review of #42: a plugin's own RepairHint arguments reach the envelope
    # too, so the closed-backend guard applies to them, not only to completed calls.
    hint = RepairHint(next_step="use_allowed_value", tool=tool, arguments=hinted, alternative="x")
    failure = ClassifiedFailure(code="invalid_model", detail="no", repair=hint)
    repair = errors.render_failure(fakeplugin.make_plugin(), failure, Meta())["error"]["repair"]
    assert (repair.get("tool"), repair.get("arguments")) == expected
    if expected[0] is not None:
        Draft202012Validator(_input_schema(expected[0])).validate(expected[1])


def test_render_failure_keeps_workspace_codes_repair_free():
    # Codex review of #42: the omission is the code's, whichever path renders it.
    plugin = fakeplugin.make_plugin("codex")
    hint = RepairHint(next_step="correct_arguments", tool="amicus_consult", alternative="x")
    for code in sorted(errors.NO_CORRECTIVE_CALL):
        for failure in (
            ClassifiedFailure(code=code, detail="no"),
            ClassifiedFailure(code=code, detail="no", repair=hint),
        ):
            assert "repair" not in errors.render_failure(plugin, failure, Meta())["error"]


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


def test_serialize_error_mirrors_meta_request_id_onto_error():
    info = errors.make_error("internal_error", "m")
    meta = Meta()
    out = errors.serialize_error(ErrorResult(error=info, meta=meta))
    assert out["error"]["request_id"] == out["meta"]["request_id"] == meta.request_id


def test_error_envelope_helper():
    out = errors.error_envelope("feature_unsupported", "later", Meta(), backend="kimi")
    assert out["error"]["code"] == "feature_unsupported" and out["error"]["backend"] == "kimi"


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


def test_the_timeout_rule_is_never_temporary_for_any_backend():
    """#245 / ADR 0039: one contract for the deadline timeout whatever the backend. The
    identical synchronous call spends again and will likely hit the same deadline."""
    for plugin in (None, fakeplugin.make_plugin()):
        rule = errors.repair_table(plugin)["timeout"]
        assert rule.temporary is False and rule.next_step == "start_new_job"
        assert rule.tool is None
        assert "NEW paid run" in rule.alternative
        assert "amicus_delegate_async" in rule.alternative
    info = errors.make_error("timeout", "t", retry_after_ms=500)
    assert info.temporary is False and info.retry_after_ms is None
    assert info.repair is not None and info.repair.next_step == "start_new_job"


def test_async_twin_for_names_the_verbs_async_tool():
    assert errors.async_twin_for("consult") == "amicus_consult_async"
    assert errors.async_twin_for("review_changes") == "amicus_review_changes_async"
    assert errors.async_twin_for("adversarial_review") == "amicus_adversarial_review_async"
    assert errors.async_twin_for("delegate") == "amicus_delegate_async"
    assert errors.async_twin_for(None) is None
    assert errors.async_twin_for("not_a_verb") is None


def test_render_failure_names_the_twin_on_a_classified_timeout():
    """A backend-classified CLI timeout is the same condition as the server deadline: the
    repair names the verb's _async twin and carries no arguments (rule 18)."""
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(code="timeout", detail="deadline")
    err = errors.render_failure(plugin, failure, Meta(), kind="review_changes")["error"]
    assert err["temporary"] is False and err["retry_after_ms"] is None
    assert err["repair"]["next_step"] == "start_new_job"
    assert err["repair"]["tool"] == "amicus_review_changes_async"
    assert "arguments" not in err["repair"]
    # Without a kind no tool is named, and a non-timeout code is untouched.
    assert errors.render_failure(plugin, failure, Meta())["error"]["repair"].get("tool") is None
    other = ClassifiedFailure(code="nonzero_exit", detail="x")
    assert (
        errors.render_failure(plugin, other, Meta(), kind="consult")["error"]["repair"].get("tool")
        is None
    )
    # A timeout that carries its own repair (codex's capture-failed retry-once hint) is not
    # overridden with the async twin: naming a different tool would contradict its next_step.
    own_repair = ClassifiedFailure(
        code="timeout",
        detail="d",
        retryable=True,
        repair=RepairHint(next_step="retry_after_delay", alternative="once"),
    )
    own_out = errors.render_failure(plugin, own_repair, Meta(), kind="consult")["error"]
    assert own_out["repair"].get("tool") is None
    assert own_out["repair"]["next_step"] == "retry_after_delay"
