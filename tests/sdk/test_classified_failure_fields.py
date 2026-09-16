"""``ClassifiedFailure.retryable`` / ``details`` / ``repair`` (#24; background
briandconnelly/claude-in-codex#145): defaulted machine
fields so an adapter that already computes them (Claude's ``ErrorInfo`` carries repair,
details and retryable) can hand them to a generic consumer instead of dropping them.
``None`` on any of them means "the backend expressed no opinion; apply your defaults" —
it is never a claim."""

from __future__ import annotations

import dataclasses

import pytest

from amicus.sdk.backend import CONTRACT_API_VERSION
from amicus.sdk.backend.protocol import ClassifiedFailure, RepairHint, Usage
from amicus.sdk.conventions.envelope import REPAIR_STEPS


def test_new_fields_default_to_none_and_keep_the_freeze():
    failure = ClassifiedFailure(code="timeout", detail="d")
    assert failure.retryable is None
    assert failure.details is None
    assert failure.repair is None
    assert failure.usage is None
    assert CONTRACT_API_VERSION == 1


def test_positional_construction_is_unchanged():
    failure = ClassifiedFailure("nonzero_exit", "d", 250)
    assert (failure.code, failure.detail, failure.retry_after_ms) == ("nonzero_exit", "d", 250)
    names = [f.name for f in dataclasses.fields(ClassifiedFailure)]
    assert names == [
        "code",
        "detail",
        "retry_after_ms",
        "retryable",
        "details",
        "repair",
        "usage",
    ]


def test_repair_hint_is_a_frozen_next_action():
    hint = RepairHint(next_step="authenticate")
    assert (hint.tool, hint.arguments, hint.alternative) == (None, None, None)
    full = RepairHint(
        next_step="authenticate",
        tool="amicus_backends",
        arguments={"backend": "claude"},
        alternative="Run `claude /login` and retry.",
    )
    assert full.arguments == {"backend": "claude"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        full.next_step = "other"  # type: ignore[misc]


def test_repair_hint_speaks_the_shared_repair_vocabulary():
    # One vocabulary: a hint uses the same symbols RepairRule does, so a consumer
    # whose serializer maps REPAIR_STEPS can never meet a step it has no wire value for.
    for step in REPAIR_STEPS:
        assert RepairHint(next_step=step).next_step == step
    with pytest.raises(ValueError, match="unknown repair step 'raise_timeout'"):
        RepairHint(next_step="raise_timeout")


def test_usage_rides_a_failure():
    # A zero-exit error envelope still reports what the run cost; the field keeps it.
    failure = ClassifiedFailure(code="nonzero_exit", detail="d", usage=Usage(cost_usd=0.42))
    assert failure.usage is not None
    assert failure.usage.cost_usd == 0.42
