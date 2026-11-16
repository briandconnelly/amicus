"""pi's amicus-enforced spend cap (#454): the stream probe, its wiring into a run, the
failure it maps to, and the AMICUS_PI_MAX_BUDGET_USD default."""

from __future__ import annotations

import sys

import pytest
from tests.support import pifixtures as pf

from amicus.backends.pi import budget, cli
from amicus.backends.pi import config as pc
from amicus.backends.pi.options import options_for
from amicus.sdk.backend.protocol import RunOutcome, RunRequest
from amicus.sdk.core import runtime, streamcap
from amicus.sdk.core.runtime import CommandRun


def _end(stop: str, cost: float | None = 0.4, *, from_provider: bool = True) -> str:
    usage = pf.usage()
    usage["cost"] = {} if cost is None else {"total": cost, "totalFromProvider": from_provider}
    return pf.assistant_end("x", stop=stop, usage=usage)


def _req(**kw) -> RunRequest:
    base = dict(kind="consult", prompt="q", cwd="/repo/some/where", timeout_seconds=60)
    base.update(model=pf.MODEL, **kw)
    return RunRequest(**base)


# --- the probe -----------------------------------------------------------------------------


def test_probe_stops_only_before_another_model_call():
    probe = budget.SpendProbe(1.0)
    assert probe(_end("toolUse", 0.6)) is None
    assert probe(_end("toolUse", 0.5)) == budget.BUDGET
    assert probe.spent_usd == pytest.approx(1.1)


def test_probe_lets_a_terminal_message_through_even_over_the_cap():
    probe = budget.SpendProbe(0.1)
    assert probe(_end("stop", 3.0)) is None
    for stop in ("error", "aborted"):
        assert budget.SpendProbe(0.1)(_end(stop, 3.0)) is None


def test_an_error_stop_is_let_through_but_its_retry_is_gated():
    """pi retries a retryable error itself and announces it with auto_retry_start (#454 review)."""
    probe = budget.SpendProbe(0.5)
    assert probe(_end("error", 0.6)) is None
    assert probe(pf.line({"type": "auto_retry_start", "attempt": 1})) == budget.BUDGET
    unpriced = budget.SpendProbe(5.0)
    assert unpriced(_end("error", None)) is None
    assert unpriced(pf.line({"type": "auto_retry_start"})) == budget.UNVERIFIABLE


def test_compaction_is_gated_and_its_spend_counted():
    probe = budget.SpendProbe(1.0)
    assert probe(_end("toolUse", 0.5)) is None
    assert probe(pf.line({"type": "compaction_start", "reason": "threshold"})) is None
    usage = {"cost": {"total": 0.6, "totalFromProvider": True}}
    end = {"type": "compaction_end", "reason": "threshold", "result": {"usage": usage}}
    assert probe(pf.line(end)) is None
    assert probe.spent_usd == pytest.approx(1.1)
    assert probe(pf.line({"type": "compaction_start", "reason": "overflow"})) == budget.BUDGET


def test_unpriced_compaction_fails_closed_and_a_failed_one_counts_nothing():
    probe = budget.SpendProbe(5.0)
    assert probe(pf.line({"type": "compaction_end", "result": None, "aborted": True})) is None
    assert not probe.unverified
    unpriced = {"type": "compaction_end", "result": {"usage": {"cost": {"total": 0.1}}}}
    assert probe(pf.line(unpriced)) is None
    assert probe(_end("toolUse", 0.01)) == budget.UNVERIFIABLE


@pytest.mark.parametrize("stop", ["toolUse", "length", "pending", "deferred", "something-new"])
def test_any_non_terminal_stop_counts_as_continuing(stop):
    assert budget.SpendProbe(0.1)(_end(stop, 0.2)) == budget.BUDGET


@pytest.mark.parametrize(
    "line",
    [
        _end("toolUse", 0.01, from_provider=False),
        _end("toolUse", None),
        pf.line(
            {
                "type": "message_end",
                "message": {"role": "assistant", "stopReason": "toolUse"},
            }
        ),
    ],
)
def test_unverifiable_cost_fails_closed_before_the_next_call(line):
    assert budget.SpendProbe(5.0)(line) == budget.UNVERIFIABLE


def test_unverifiable_cost_on_the_final_message_does_not_stop():
    assert budget.SpendProbe(5.0)(_end("stop", 0.01, from_provider=False)) is None


def test_an_earlier_unverifiable_message_stops_a_later_continuation():
    probe = budget.SpendProbe(5.0)
    assert probe(_end("toolUse", None)) == budget.UNVERIFIABLE
    fresh = budget.SpendProbe(5.0)
    fresh.unverified = True
    assert fresh(_end("toolUse", 0.01)) == budget.UNVERIFIABLE


def _raw_cost_end(total: str) -> str:
    """A toolUse message_end whose cost total is the JSON token `total`, which Python's
    parser reads where a strict one would not (`NaN`, `Infinity`)."""
    return (
        '{"type":"message_end","message":{"role":"assistant","stopReason":"toolUse",'
        f'"usage":{{"cost":{{"total":{total},"totalFromProvider":true}}}}}}}}'
    )


@pytest.mark.parametrize("total", ["NaN", "Infinity", "-Infinity", "-5.0", "1e999"])
def test_a_cost_that_is_not_a_finite_non_negative_number_fails_closed(total):
    """A NaN total made every later comparison false and a negative one refunded the cap,
    so either let the run continue past it."""
    probe = budget.SpendProbe(0.05)
    assert probe(_raw_cost_end(total)) == budget.UNVERIFIABLE
    assert probe.spent_usd == 0.0
    assert probe(_end("toolUse", 10.0)) == budget.UNVERIFIABLE


def test_a_zero_cost_is_a_measured_cost():
    probe = budget.SpendProbe(0.05)
    assert probe(_end("toolUse", 0)) is None
    assert not probe.unverified


def test_a_probe_that_fails_stops_the_run_and_stays_unverifiable(monkeypatch):
    """The runtime stops consulting a probe that raises, which would leave the run uncapped."""
    probe = budget.SpendProbe(5.0)

    def boom(_line):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(budget.json, "loads", boom)
    assert probe(_end("stop", 0.01)) == budget.UNVERIFIABLE
    monkeypatch.undo()
    assert probe(_end("toolUse", 0.01)) == budget.UNVERIFIABLE


@pytest.mark.parametrize(
    "line",
    [
        _raw_cost_end("9" * 5000),  # past Python's integer-conversion digit limit
        '{"type":"message_end","message":{"role":"assistant"',
        '{"type":"compaction_end","result":' + "[" * 100_000,
    ],
)
def test_a_watched_event_that_does_not_parse_fails_closed(line):
    """Its cost was dropped unseen, so a later gate let the run continue uncounted."""
    probe = budget.SpendProbe(5.0)
    assert probe(line) == budget.UNVERIFIABLE
    assert probe(pf.line({"type": "auto_retry_start"})) == budget.UNVERIFIABLE


@pytest.mark.parametrize("total", ["NaN", "-1"])
def test_usage_reports_an_unmeasurable_cost_as_unknown(total):
    from amicus.backends.pi import normalize

    usage, _ = normalize.parse_event_metadata(_raw_cost_end(total) + "\n")
    assert usage is not None and usage.cost_usd is None


def test_a_cut_line_fails_closed():
    cut = '{"type":"message_end","message":{' + streamcap._LINE_TRUNC_SENTINEL
    assert streamcap.is_loss_marker(cut)
    assert budget.SpendProbe(5.0)(cut) == budget.UNVERIFIABLE


@pytest.mark.parametrize(
    "line",
    [
        pf.SESSION,
        "not json message_end\n",
        '{"type": "message_end", "message": "x"}\n',
        pf.line({"type": "message_end", "message": {"role": "user", "stopReason": "toolUse"}}),
        pf.line({"type": "message_update", "note": '"message_end"'}),
        "[1, 2]\n",
    ],
)
def test_other_lines_are_ignored(line):
    probe = budget.SpendProbe(0.01)
    assert probe(line) is None
    assert probe.spent_usd == 0 and not probe.unverified


def _compaction_start(reason: str = "threshold") -> str:
    return pf.line({"type": "compaction_start", "reason": reason})


def test_a_post_answer_compaction_over_the_cap_is_stopped_as_after_final():
    """pi compacts after a settled answer; stopping it must not withhold that answer."""
    probe = budget.SpendProbe(1.0)
    assert probe(_end("stop", 1.1)) is None
    assert probe(_compaction_start("overflow")) == budget.AFTER_FINAL
    under = budget.SpendProbe(5.0)
    assert under(_end("stop", 1.1)) is None
    assert under(_compaction_start()) is None


def test_a_compaction_after_an_error_settles_only_when_it_will_not_retry():
    probe = budget.SpendProbe(0.5)
    assert probe(_end("error", 0.6)) is None
    assert probe(_compaction_start("threshold")) == budget.AFTER_FINAL
    retrying = budget.SpendProbe(0.5)
    assert retrying(_end("error", 0.6)) is None
    assert retrying(_compaction_start("overflow")) == budget.BUDGET


def test_a_compaction_that_will_retry_is_gated_at_its_end():
    """pi resumes with agent.continue() straight after a willRetry compaction_end."""
    probe = budget.SpendProbe(1.0)
    assert probe(_end("length", 0.4)) is None
    assert probe(_compaction_start("overflow")) is None
    usage = {"cost": {"total": 0.7, "totalFromProvider": True}}
    end = {"type": "compaction_end", "result": {"usage": usage}, "willRetry": True}
    assert probe(pf.line(end)) == budget.BUDGET
    settled = budget.SpendProbe(1.0)
    assert settled(pf.line({**end, "willRetry": False})) is None


# --- wiring ----------------------------------------------------------------------------------


async def test_prepare_installs_a_fresh_probe_only_when_a_cap_applies():
    backend = pf.make_backend()
    async with backend.prepare(_req()) as prep:
        assert prep.stop_on_line is None
    async with (
        backend.prepare(_req(budget_usd=0.5)) as one,
        backend.prepare(_req(budget_usd=0.5)) as two,
    ):
        assert isinstance(one.stop_on_line, budget.SpendProbe)
        assert one.stop_on_line is not two.stop_on_line
        assert one.stop_on_line.cap_usd == 0.5


async def test_the_configured_default_cap_applies_when_the_call_omits_one():
    backend = pf.make_backend({"AMICUS_PI_MAX_BUDGET_USD": "0.25"})
    async with backend.prepare(_req()) as prep:
        assert isinstance(prep.stop_on_line, budget.SpendProbe)
        assert prep.stop_on_line.cap_usd == 0.25


@pytest.mark.parametrize(
    ("reason", "phrase"),
    [(budget.BUDGET, "max-budget threshold"), (budget.UNVERIFIABLE, "not reported")],
)
def test_a_stopped_run_is_budget_exceeded(reason, phrase):
    stream = pf.SESSION + _end("toolUse", 0.6)
    run = CommandRun(stream, "", -9, 5, False, stop_reason=reason)
    failure = pf.make_backend().inspect_outcome(
        RunOutcome(run=run, events=stream), _req(budget_usd=0.5)
    )
    assert failure is not None and failure.code == "budget_exceeded"
    assert phrase in failure.detail and "0.50 USD" in failure.detail
    assert failure.details == {"field": "backend_options.max_budget_usd"}


def test_the_spend_so_far_rides_usage():
    stream = pf.SESSION + _end("toolUse", 0.6)
    run = CommandRun(stream, "", -9, 5, False, stop_reason=budget.BUDGET)
    result = pf.make_backend().finalize(RunOutcome(run=run, events=stream), _req(budget_usd=0.5))
    assert result.usage is not None and result.usage.cost_usd == pytest.approx(0.6)


def test_a_post_answer_stop_keeps_the_answer():
    stream = pf.SESSION + _end("stop", 1.1)
    run = CommandRun(stream, "", -9, 5, False, stop_reason=budget.AFTER_FINAL)
    backend = pf.make_backend()
    outcome = RunOutcome(run=run, events=stream)
    assert backend.inspect_outcome(outcome, _req(budget_usd=0.5)) is None
    assert backend.finalize(outcome, _req(budget_usd=0.5)).answer == "x"


def test_a_post_answer_stop_after_an_error_reports_the_error():
    stream = pf.SESSION + _end("error", 0.6)
    run = CommandRun(stream, "", -9, 5, False, stop_reason=budget.AFTER_FINAL)
    failure = pf.make_backend().inspect_outcome(RunOutcome(run=run, events=stream), _req())
    assert failure is not None and failure.code != "budget_exceeded"


def test_a_post_answer_stop_with_no_answer_is_empty():
    stream = pf.SESSION + pf.assistant_end(None, stop="stop", usage=pf.usage())
    run = CommandRun(stream, "", -9, 5, False, stop_reason=budget.AFTER_FINAL)
    failure = pf.make_backend().inspect_outcome(RunOutcome(run=run, events=stream), _req())
    assert failure is not None and failure.code == "empty_response"


def test_compaction_spend_rides_usage_and_an_unpriced_one_makes_it_unknown():
    cost = {"total": 0.6, "totalFromProvider": True}
    compaction = {"type": "compaction_end", "result": {"usage": {"input": 100, "cost": cost}}}
    run = CommandRun("", "", -9, 5, False, stop_reason=budget.BUDGET)
    stream = pf.SESSION + _end("toolUse", 0.5) + pf.line(compaction)
    result = pf.make_backend().finalize(RunOutcome(run=run, events=stream), _req())
    assert result.usage is not None and result.usage.cost_usd == pytest.approx(1.1)
    compaction["result"]["usage"]["cost"] = {"total": 0.6}
    stream = pf.SESSION + _end("toolUse", 0.5) + pf.line(compaction)
    result = pf.make_backend().finalize(RunOutcome(run=run, events=stream), _req())
    assert result.usage is not None and result.usage.cost_usd is None


def test_the_repair_says_a_configured_default_still_applies():
    assert "AMICUS_PI_MAX_BUDGET_USD" in cli.BUDGET_REPAIR


def test_budget_failure_without_a_cap_omits_it():
    assert "USD" not in cli.budget_failure(budget.BUDGET, None).detail


async def test_runtime_stops_a_live_pi_shaped_stream_between_calls(tmp_path):
    """End to end through the runtime: the probe sees each message_end as it is written, and
    the run is killed before the producer's next "model call" rather than at its exit."""
    first, second = _end("toolUse", 0.6), _end("toolUse", 0.6)
    code = (
        "import sys, time\n"
        f"sys.stdout.write({first!r}); sys.stdout.flush(); time.sleep(0.3)\n"
        f"sys.stdout.write({second!r}); sys.stdout.flush()\n"
        "time.sleep(30)\n"
        "sys.stdout.write('never\\n')\n"
    )
    run = await runtime.run_async(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        timeout_seconds=20,
        stop_on_line=budget.SpendProbe(1.0),
    )
    assert run.stop_reason == budget.BUDGET and not run.timed_out
    assert run.elapsed_ms < 10_000 and "never" not in run.stdout
    assert run.stdout.count("message_end") == 2


# --- config ------------------------------------------------------------------------------------


def test_no_default_cap_unless_configured():
    assert pc.load_config({}).max_budget_usd is None
    assert pc.load_config({"AMICUS_PI_MAX_BUDGET_USD": "1.5"}).max_budget_usd == 1.5


@pytest.mark.parametrize("raw", ["abc", "0.00123", "77"])
def test_a_bad_default_cap_warns_and_is_dropped(raw):
    cfg = pc.load_config({"AMICUS_PI_MAX_BUDGET_USD": raw})
    assert cfg.max_budget_usd is None
    assert any("AMICUS_PI_MAX_BUDGET_USD" in w for w in cfg.warnings)
    assert not any(raw in w.replace("AMICUS_PI_MAX_BUDGET_USD", "") for w in cfg.warnings)


def test_the_option_maps_to_the_request_budget():
    cfg = pc.load_config({"AMICUS_PI_MAX_BUDGET_USD": "2"})
    opt = next(o for o in options_for(cfg) if o.name == "max_budget_usd")
    assert opt.maps_to == "budget_usd" and opt.default == 2.0


async def test_a_stop_lands_before_a_quick_next_call(tmp_path):
    """The kill must not wait out a poll slice (#454 review): a continuation that follows the
    over-cap message closely is not allowed to start, let alone finish."""
    over, final = _end("toolUse", 0.6), _end("stop", 0.1)
    code = (
        "import sys, time\n"
        f"sys.stdout.write({over!r}); sys.stdout.flush(); time.sleep(0.05)\n"
        f"sys.stdout.write({final!r}); sys.stdout.flush()\n"
    )
    run = await runtime.run_async(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        timeout_seconds=20,
        stop_on_line=budget.SpendProbe(0.5),
    )
    assert run.stop_reason == budget.BUDGET
    assert run.stdout.count("message_end") == 1
