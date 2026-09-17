"""The upstream golden envelope (the sibling's recorded real `claude -p --output-format json`
output) through the adapter and through the loop, so an envelope-key rename fails here
without the live CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import claudefixtures as cf

from amicus.backends.claude import cli
from amicus.orchestration import run as run_mod
from amicus.request import RunSpec
from amicus.sdk.backend.protocol import RunOutcome, RunRequest
from amicus.sdk.core.runtime import CommandRun

GOLDEN = json.loads(cf.GOLDEN)
BUDGET_STOP = json.loads(cf.BUDGET_STOP)


def test_golden_keys_are_the_documented_shape():
    shape = json.loads(Path("docs/claude-help/2.1.263/envelope-shape.json").read_text())
    assert sorted(GOLDEN) == shape["top_level_keys"]
    assert sorted(GOLDEN["usage"]) == shape["usage_keys"]


def test_golden_through_the_adapter(pinned_claude_bin):
    _, backend = cf.make_backend()
    req = RunRequest(
        kind="review_changes",
        prompt="p",
        cwd="/repo",
        timeout_seconds=60,
        schema={"type": "object"},
    )
    outcome = RunOutcome(run=CommandRun(cf.GOLDEN, "", 0, 12, False))
    assert backend.inspect_outcome(outcome, req) is None
    result = backend.finalize(outcome, req)
    assert result.structured is not None and result.structured["verdict"] == "concerns"
    assert result.session_id == "sess-golden-1"
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 50)
    # This older envelope's modelUsage has no cache keys, and usage is read from one block
    # only (#158): the main-loop block's cache counters are not mixed in.
    assert (result.usage.cached_input_tokens, result.usage.cache_creation_input_tokens) == (
        None,
        None,
    )
    assert result.usage.cost_usd == 0.0123


async def test_golden_through_the_loop(pinned_claude_bin, monkeypatch, tmp_path):
    plugin, _ = cf.make_backend()
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout=cf.GOLDEN))
    spec = RunSpec(
        backend="claude",
        kind="consult",
        tool="amicus_consult",
        cwd=str(tmp_path),
        workspace_source="param",
        roots_source="client",
        host_name="Codex",
        timeout_seconds=60,
        options={"config_mode": "inherit", "access": "toolless", "max_budget_usd": 1.0},
        question="q",
    )
    out = await run_mod.run_request(spec, plugin)
    assert out["ok"] is True and out["summary"] == "Off-by-one in add()"
    meta = out["meta"]
    assert meta["session_id"] == "sess-golden-1" and meta["usage"]["cost_usd"] == 0.0123
    assert (meta["usage"]["input_tokens"], meta["usage"]["output_tokens"]) == (100, 50)
    assert meta["usage"]["cached_input_tokens"] is None  # no cache keys under modelUsage
    assert meta["usage"]["cache_creation_input_tokens"] is None
    assert meta["command_exit_code"] == 0
    # The sibling's finding shape (risk/recommendation) is not amicus's (evidence/suggestion),
    # and ADR 0010 declines to map one onto the other rather than half-mapping it. What the
    # ADR never decided was that the rest of the finding should go with them: this is a
    # RECORDED real claude response reporting a high-severity bug, and it used to arrive as
    # an empty findings list (issue #38). The finding stays and the unmappable keys go with
    # their content, which is why this is reported rather than passed off as intact.
    assert [(f["title"], f["severity"]) for f in out["findings"]] == [
        ("subtraction instead of addition", "high")
    ]
    assert out["findings"][0]["evidence"] == "return a - b"
    assert out["findings"][0]["suggestion"] is None, "risk/recommendation are not half-mapped"
    assert out["findings_diagnostics"] == {"dropped": 0, "reasons": ["extra_fields_omitted"]}


# --- The budget-stop envelope (#158) ------------------------------------------------------
# Recorded on claude 2.1.274 with a $0.001 threshold, below amicus's 0.01 floor, so these
# replay the envelope through amicus rather than reproduce the stop end to end.


def test_budget_stop_keys_are_the_documented_shape():
    shape = json.loads(Path("docs/claude-help/2.1.274/budget-stop-envelope-shape.json").read_text())
    assert sorted(BUDGET_STOP) == shape["top_level_keys"]
    assert sorted(BUDGET_STOP["usage"]) == shape["usage_keys"]
    (entry,) = BUDGET_STOP["modelUsage"].values()
    assert sorted(entry) == shape["modelUsage_inner_keys"]
    assert "result" not in BUDGET_STOP, "a budget stop carries no answer, so no prompt echo"


def test_budget_stop_zeroes_the_main_loop_block_beside_a_nonzero_cost():
    """What #158 reported, pinned on the recording so the precedence rule keeps its reason."""
    block = BUDGET_STOP["usage"]
    assert (block["input_tokens"], block["output_tokens"]) == (0, 0)
    assert BUDGET_STOP["total_cost_usd"] > 0
    (entry,) = BUDGET_STOP["modelUsage"].values()
    assert entry["inputTokens"] > 0 and entry["costUSD"] == BUDGET_STOP["total_cost_usd"]
    assert BUDGET_STOP["subtype"] == "error_max_budget_usd" and BUDGET_STOP["is_error"] is True


def test_budget_stop_through_the_classifier():
    """claude 2.1.274 exits 1 on the stop, which is classify_failure's route; the zero-exit
    route (#73) is inspect_outcome's, covered through the loop below."""
    run = CommandRun(cf.BUDGET_STOP, "", 1, 1432, False)
    failure = cli.classify_failure(run, config_mode="safe", sanitize=None)
    assert failure.code == "budget_exceeded" and failure.retryable is False
    assert failure.details == {"field": "backend_options.max_budget_usd"}
    assert failure.usage is not None
    assert (failure.usage.input_tokens, failure.usage.output_tokens) == (4707, 53)
    assert (failure.usage.cached_input_tokens, failure.usage.cache_creation_input_tokens) == (0, 0)
    assert failure.usage.cost_usd == BUDGET_STOP["total_cost_usd"]


@pytest.mark.parametrize("exit_code", [1, 0])
async def test_budget_stop_through_the_loop(pinned_claude_bin, monkeypatch, tmp_path, exit_code):
    """Both production routes: exit 1 (classify_failure, claude 2.1.274) and exit 0
    (inspect_outcome -> classify_envelope, the #73 capture) deliver the same usage."""
    plugin, _ = cf.make_backend()
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        cf.scripted_run_async(stdout=cf.BUDGET_STOP, exit_code=exit_code),
    )
    spec = RunSpec(
        backend="claude",
        kind="consult",
        tool="amicus_consult",
        cwd=str(tmp_path),
        workspace_source="param",
        roots_source="client",
        host_name="Codex",
        timeout_seconds=60,
        options={"config_mode": "safe", "access": "toolless", "max_budget_usd": 0.01},
        question="q",
    )
    out = await run_mod.run_request(spec, plugin)
    assert out["ok"] is False
    assert out["error"]["code"] == "budget_exceeded" and out["error"]["temporary"] is False
    meta = out["meta"]
    assert meta["command_exit_code"] == exit_code and meta["session_id"] == "sess-budget-1"
    usage = meta["usage"]
    assert (usage["input_tokens"], usage["output_tokens"]) == (4707, 53)
    assert (usage["cached_input_tokens"], usage["cache_creation_input_tokens"]) == (0, 0)
    assert usage["cost_usd"] == BUDGET_STOP["total_cost_usd"]
