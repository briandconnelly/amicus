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
    for stop in ("length", "error", "aborted"):
        assert budget.SpendProbe(0.1)(_end(stop, 3.0)) is None


@pytest.mark.parametrize("stop", ["toolUse", "pending", "deferred", "something-new"])
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
