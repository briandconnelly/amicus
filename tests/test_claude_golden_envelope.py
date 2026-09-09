"""The upstream golden envelope (the sibling's recorded real `claude -p --output-format json`
output) through the adapter and through the loop, so an envelope-key rename fails here
without the live CLI."""

from __future__ import annotations

import json
from pathlib import Path

from pontonier.backend.protocol import RunOutcome, RunRequest
from pontonier.core.runtime import CommandRun
from tests.support import claudefixtures as cf

from amicus.orchestration import run as run_mod
from amicus.request import RunSpec

GOLDEN = json.loads(cf.GOLDEN)


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
    assert (result.usage.cached_input_tokens, result.usage.cache_creation_input_tokens) == (10, 5)
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
    assert meta["usage"]["cached_input_tokens"] == 10
    assert meta["usage"]["cache_creation_input_tokens"] == 5
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
