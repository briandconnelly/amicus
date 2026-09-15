"""Sync/async pair-parity kit."""

from __future__ import annotations

from amicus.sdk.testing import pair_parity

SYNC = {
    "properties": {
        "question": {"type": "string"},
        "model": {"type": "string"},
    },
    "required": ["question"],
}

ASYNC_OK = {
    "properties": {
        "question": {"type": "string"},
        "model": {"type": "string"},
        "idempotency_key": {"type": "string"},
    },
    "required": ["question"],
}


def test_matching_pair_passes():
    assert pair_parity.check_pair("consult", SYNC, "consult_async", ASYNC_OK) == []


def test_async_missing_param_flagged():
    bad = {"properties": {"question": {"type": "string"}}, "required": ["question"]}
    violations = pair_parity.check_pair("consult", SYNC, "consult_async", bad)
    assert any("lacks" in v for v in violations)


def test_async_unexpected_extra_flagged():
    bad = {
        "properties": {**ASYNC_OK["properties"], "surprise": {"type": "string"}},
        "required": ["question"],
    }
    violations = pair_parity.check_pair("consult", SYNC, "consult_async", bad)
    assert any("surprise" in v for v in violations)


def test_type_drift_flagged():
    bad = {
        "properties": {**ASYNC_OK["properties"], "model": {"type": "integer"}},
        "required": ["question"],
    }
    violations = pair_parity.check_pair("consult", SYNC, "consult_async", bad)
    assert any("'model' differs" in v for v in violations)


def test_requiredness_drift_flagged():
    bad = {"properties": ASYNC_OK["properties"], "required": ["question", "model"]}
    violations = pair_parity.check_pair("consult", SYNC, "consult_async", bad)
    assert any("required sets differ" in v for v in violations)


def test_async_only_required_key_is_allowed():
    ok = {"properties": ASYNC_OK["properties"], "required": ["question", "idempotency_key"]}
    assert pair_parity.check_pair("consult", SYNC, "consult_async", ok) == []


def test_check_pairs_reports_unknown_tools():
    tools = {"consult": SYNC}
    violations = pair_parity.check_pairs(tools, (("consult", "consult_async"),))
    assert any("unknown tool 'consult_async'" in v for v in violations)


def test_check_pairs_runs_all_pairs():
    tools = {"consult": SYNC, "consult_async": ASYNC_OK}
    assert pair_parity.check_pairs(tools, (("consult", "consult_async"),)) == []
