"""Shared failure classifier: precedence order, hook-first, retry-after parsing."""

from __future__ import annotations

from tests.sdk.conftest import make_run
from tests.sdk.test_contract import make_contract

from amicus.sdk.backend import classify
from amicus.sdk.backend.contract import FailureSignatures
from amicus.sdk.backend.protocol import ClassifiedFailure, RunOutcome, RunRequest
from amicus.sdk.core import runtime

SIGS = FailureSignatures(
    auth=(r"please log in",),
    contract_drift=(r"unknown option",),
    invalid_model=(r"unknown model",),
    rate_limited=(r"rate limited",),
    retry_after_ms=r"retry in (\d+) ms",
)

CONTRACT = make_contract(failure_signatures=SIGS)
REQUEST = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)


def _outcome(stderr: str = "", exit_code: int = 1, timed_out: bool = False) -> RunOutcome:
    return RunOutcome(run=make_run(stderr=stderr, exit_code=exit_code, timed_out=timed_out))


def _classify(outcome: RunOutcome, hook=None) -> ClassifiedFailure:
    return classify.classify(CONTRACT, outcome, REQUEST, detail="detail", backend_hook=hook)


def test_binary_missing_wins():
    out = RunOutcome(run=make_run(stderr=runtime.BINARY_NOT_FOUND, exit_code=127))
    assert _classify(out).code == "fake_not_found"


def test_timeout():
    assert _classify(_outcome(timed_out=True)).code == "timeout"


def test_contract_drift_beats_auth():
    # A drifted CLI can also print auth-looking noise; drift must win so the
    # repair steers to the plugin, not to a pointless login.
    out = _outcome(stderr="error: unknown option '--x'\nplease log in")
    assert _classify(out).code == "cli_contract_changed"


def test_auth_beats_rate_limit():
    out = _outcome(stderr="please log in — rate limited")
    assert _classify(out).code == "fake_auth_required"


def test_rate_limited_with_retry_after():
    c = _classify(_outcome(stderr="rate limited; retry in 2500 ms"))
    assert c.code == "fake_rate_limited"
    assert c.retry_after_ms == 2500


def test_invalid_model():
    assert _classify(_outcome(stderr="unknown model 'zap'")).code == "invalid_model"


def test_fallback_nonzero_exit():
    assert _classify(_outcome(stderr="something else broke")).code == "nonzero_exit"


def test_hook_runs_first_and_wins():
    def hook(outcome, request):
        return ClassifiedFailure(code="budget_exceeded", detail="from envelope")

    c = _classify(_outcome(stderr="please log in"), hook=hook)
    assert c.code == "budget_exceeded"


def test_hook_none_falls_through():
    c = _classify(_outcome(stderr="please log in"), hook=lambda o, r: None)
    assert c.code == "fake_auth_required"


def test_parse_retry_after_edge_cases():
    assert classify.parse_retry_after_ms(None, "retry in 5 ms") is None
    assert classify.parse_retry_after_ms(r"retry in (\d+) ms", "no match") is None
    assert classify.parse_retry_after_ms(r"retry in (-?\d+) ms", "retry in -5 ms") is None
    assert classify.parse_retry_after_ms(r"retry in (\d+) ms", "retry in 100 ms") == 100
