"""The async poll hint keeps growing past pontonier's 10 s ceiling (#95).

pontonier 0.9.0 computes `poll_after_ms` as min(max(base, elapsed), 10000), so a job that
runs for minutes is polled every ten seconds for almost its whole life. amicus sizes its own
ceiling; every site that hands the hint to a client must agree on it."""

from __future__ import annotations

import pytest

from amicus.jobs.polling import poll_hint_ms


def _rec(status: str, elapsed_ms: int) -> dict:
    # pontonier's own capped hint rides every status dict; the helper must not echo it.
    return {"status": status, "elapsed_ms": elapsed_ms, "poll_after_ms": 10000}


@pytest.mark.parametrize(
    ("elapsed_s", "want_ms"),
    [
        (0, 1000),  # never below the base
        (1, 1000),
        (5, 5000),  # "wait about as long as it has already run"
        (10, 10000),
        (20, 20000),  # pontonier stops at 10000
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
