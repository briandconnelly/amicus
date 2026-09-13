"""The verb x backend parameter matrix from the spec, written before any schema."""

from __future__ import annotations

import pytest

from amicus.schemas import params as p

ALL = frozenset({"consult", "review_changes", "adversarial_review", "delegate"})


def test_matrix_matches_the_spec_table():
    assert p.PARAM_MATRIX["backend"] == ALL
    for name in ("workspace_root", "model", "reasoning_effort", "backend_options"):
        assert p.PARAM_MATRIX[name] == ALL, name
    assert p.PARAM_MATRIX["timeout_seconds"] == ALL
    assert p.PARAM_MATRIX["detail"] == ALL
    assert p.PARAM_MATRIX["idempotency_key"] == ALL
    assert p.PARAM_MATRIX["extra_context"] == {"consult", "review_changes", "adversarial_review"}
    assert p.PARAM_MATRIX["instructions_append"] == {"consult", "review_changes"}
    for name in ("scope", "base", "commit", "paths", "untracked", "focus"):
        assert p.PARAM_MATRIX[name] == {"review_changes", "adversarial_review"}, name
    assert p.PARAM_MATRIX["target"] == {"adversarial_review"}
    assert p.PARAM_MATRIX["evidence"] == {"adversarial_review"}
    assert p.PARAM_MATRIX["task"] == {"delegate"}
    assert p.PARAM_MATRIX["question"] == {"consult"}
    assert set(p.PARAM_MATRIX) == {
        "backend",
        "workspace_root",
        "model",
        "reasoning_effort",
        "timeout_seconds",
        "detail",
        "idempotency_key",
        "extra_context",
        "instructions_append",
        "scope",
        "base",
        "commit",
        "paths",
        "untracked",
        "focus",
        "target",
        "evidence",
        "task",
        "question",
        "backend_options",
    }


def test_sync_and_async_splits():
    assert {"timeout_seconds", "detail"} == p.SYNC_ONLY_PARAMS
    # Every parameter the matrix grants a verb is on both members of its pair except the
    # two sync-only wait controls; idempotency_key left this set in #66 (ADR 0020).
    assert frozenset() == p.ASYNC_ONLY_PARAMS
    assert p.expected_params("amicus_consult") == {
        "backend",
        "question",
        "workspace_root",
        "extra_context",
        "instructions_append",
        "model",
        "reasoning_effort",
        "timeout_seconds",
        "detail",
        "idempotency_key",
        "backend_options",
    }
    assert p.expected_params("amicus_consult_async") == {
        "backend",
        "question",
        "workspace_root",
        "extra_context",
        "instructions_append",
        "model",
        "reasoning_effort",
        "idempotency_key",
        "backend_options",
    }
    assert p.expected_params("amicus_delegate_async") == {
        "backend",
        "task",
        "workspace_root",
        "model",
        "reasoning_effort",
        "idempotency_key",
        "backend_options",
    }
    assert "instructions_append" not in p.expected_params("amicus_adversarial_review")
    assert "instructions_append" not in p.expected_params("amicus_delegate")


def test_required_sets():
    assert p.expected_required("amicus_consult") == {"backend", "question"}
    assert p.expected_required("amicus_review_changes") == {"backend"}
    assert p.expected_required("amicus_adversarial_review") == {"backend", "target"}
    assert p.expected_required("amicus_delegate_async") == {"backend", "task"}


def test_tool_verb_covers_the_eight_paid_tools():
    assert set(p.TOOL_VERB) == {
        "amicus_consult",
        "amicus_consult_async",
        "amicus_review_changes",
        "amicus_review_changes_async",
        "amicus_adversarial_review",
        "amicus_adversarial_review_async",
        "amicus_delegate",
        "amicus_delegate_async",
    }
    assert p.TOOL_VERB["amicus_review_changes_async"] == ("review_changes", True)


def test_unknown_tool_raises():
    with pytest.raises(KeyError):
        p.expected_params("amicus_nope")


def test_parameter_contracts_have_summary_and_full_and_point_at_the_resource():
    assert set(p.PARAMETER_CONTRACTS) == {
        "idempotency_key",
        "extra_context",
        "instructions_append",
        "reasoning_effort",
        "backend_options",
        "workspace_root",
    }
    for c in p.PARAMETER_CONTRACTS.values():
        assert c.summary and c.full
        assert p.PARAMS_RESOURCE_URI in c.summary
        assert len(c.summary) < len(c.full)
    body = p.params_resource_body()
    assert set(body["params"]) == set(p.PARAMETER_CONTRACTS)


# The inline copy of a contract is paid once per tool that declares the parameter (up
# to fifteen times per tools/list), so it is a one-line summary plus the pointer; the
# rest lives at amicus://params (issue #41). The ceiling is a ratchet, not a target.
SUMMARY_CEILING_BYTES = 200

# What an agent needs at SELECTION time, before it has read amicus://params: a safety or
# applicability fact that must stay inline whether or not the full text also carries it,
# because dropping it from the summary drops it from the wire. Pinned as substrings so a
# rewording that keeps the fact passes and one that loses it fails.
SELECTION_TIME_FACTS: dict[str, tuple[str, ...]] = {
    "workspace_root": ("sessionless", "must pass"),
    "idempotency_key": ("reusing", "different arg"),
    "extra_context": ("UNTRUSTED", "secrets"),
    "instructions_append": ("UNTRUSTED", "grants no tools", "secrets", "4096"),
    "reasoning_effort": ("amicus_models",),
    "backend_options": ("key or value", "pre-spend"),
}


@pytest.mark.parametrize("name", sorted(SELECTION_TIME_FACTS))
def test_parameter_summary_is_one_line_and_keeps_its_selection_time_facts(name):
    summary = p.PARAMETER_CONTRACTS[name].summary
    assert len(summary.encode("utf-8")) <= SUMMARY_CEILING_BYTES, (name, len(summary))
    for fact in SELECTION_TIME_FACTS[name]:
        assert fact.lower() in summary.lower(), (name, fact)


def test_selection_time_facts_cover_every_contract():
    assert set(SELECTION_TIME_FACTS) == set(p.PARAMETER_CONTRACTS)


def test_timeout_bounds_and_pattern():
    assert (p.MIN_TIMEOUT_SECONDS, p.MAX_TIMEOUT_SECONDS) == (10, 600)
    assert p.CONTROL_CHAR_FREE_PATTERN == r"^[^\x00-\x1F\x7F-\x9F]*$"
