"""The async poll hint keeps growing past the ten seconds pontonier stopped at (#95).

pontonier 0.9.0 computed `poll_after_ms` as min(max(base, elapsed), 10000), so a job that
ran for minutes was polled every ten seconds for almost its whole life. amicus sizes its own
ceiling; every site that hands the hint to a client must agree on it."""

from __future__ import annotations

import time

import pytest

from amicus.jobs.polling import poll_hint_ms
from amicus.jobs.store import MAX_POLL_AFTER_MS, JobStore


def _rec(status: str, elapsed_ms: int) -> dict:
    # A hint rides every status dict; the helper recomputes it from elapsed_ms rather than
    # echoing the record — an echo would answer 10000 for every row below.
    return {"status": status, "elapsed_ms": elapsed_ms, "poll_after_ms": 10000}


@pytest.mark.parametrize(
    ("elapsed_s", "want_ms"),
    [
        (0, 1000),  # never below the base
        (1, 1000),
        (5, 5000),  # "wait about as long as it has already run"
        (10, 10000),
        (20, 20000),  # pontonier stopped at 10000
        (30, 30000),
        (60, 30000),  # amicus's own ceiling
        (240, 30000),
    ],
)
def test_a_running_job_hint_grows_past_ten_seconds(elapsed_s, want_ms):
    assert poll_hint_ms(_rec("running", elapsed_s * 1000)) == want_ms


@pytest.mark.parametrize("status", ["done", "failed", "cancelled", "timeout"])
def test_a_terminal_job_has_no_hint(status):
    assert poll_hint_ms(_rec(status, 240_000)) is None


def test_the_store_and_the_hint_share_one_ceiling(tmp_path):
    """#118 folded amicus's ceiling into the store, so there is no second constant left to
    drift from. A four-minute-old running record gets 30 s out of the store itself, and
    `poll_hint_ms` recomputes the same number; before the fold the store stopped at 10 s and
    only the hint grew past it. Pin the literal, not just the agreement: two constants read
    from each other agree at any value."""
    assert MAX_POLL_AFTER_MS == 30_000
    store = JobStore(root=tmp_path, ttl_seconds=60, max_seconds=600, max_count=10)
    rec = store._status_dict(
        tmp_path, {"job_id": "j", "started_epoch": time.time() - 240}, "running"
    )
    assert rec["poll_after_ms"] == 30_000
    assert poll_hint_ms(rec) == rec["poll_after_ms"]
