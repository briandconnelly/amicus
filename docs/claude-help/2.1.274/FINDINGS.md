# Claude Code 2.1.274 — the budget-stop envelope (#158)

Captured 2026-09-17 on the maintainer's machine, resolving what issue #158 left open: whether a budget-stop envelope carries the real token counts anywhere, and why the stop overshoots.
One model call was made, at a recorded estimated cost of $0.004972; everything else here came from reading the installed binary.

## The capture

`claude-version.txt`: `2.1.274 (Claude Code)`.

`budget-stop-envelope-shape.json`: the key names of the envelope `claude -p --output-format json` printed for a one-turn toolless run (`--tools ""`, `--safe-mode`, `--model haiku`) stopped by `--max-budget-usd 0.001`.
The envelope itself, with its session id and uuid masked, is `tests/fixtures/claude_budget_stop_envelope.json`; `tests/test_claude_golden_envelope.py` pins its shape to this document and replays it through the classifier and the loop.
The prompt was a one-sentence literal written for the capture and is not recorded; a budget stop carries no `result`, so no prompt text reaches the envelope.
The threshold used is below amicus's own 0.01 floor, so the fixture is a replay of what claude prints, not an end-to-end amicus reproduction.

What it shows:

- The process exits 1, with `subtype: "error_max_budget_usd"`, `is_error: true`, `terminal_reason: "budget_exhausted"`, `num_turns: 1`, `stop_reason: "end_turn"` and `errors: ["Reached maximum budget ($0.001)"]`.
- The top-level `usage` block is zeroed: `input_tokens`, `output_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` are all 0, beside `total_cost_usd: 0.004972`.
  This is the zero-beside-a-cost shape #158 reported on 0.3.0.
- `modelUsage` carries the real accounting under the model id: `inputTokens: 4707`, `outputTokens: 53`, `thinkingTokens: 36`, both cache counters 0, and `costUSD` equal to `total_cost_usd`.
- One tiny call carried the cost to 4.972 times the threshold.

## What the binary says

The result schema embedded in the 2.1.274 binary describes the fields; quoted from the binary's strings, not from documentation:

- `usage`: "MAIN AGENT LOOP ONLY — excludes Task subagent, sidechain, and auxiliary model calls, and is per-turn in streaming-input sessions. Prefer modelUsage for token/cost accounting."
- `modelUsage`: "Per-model totals for every model call made through the query pipeline during this query() call ... The correct field for token/cost accounting; treat it as an estimate, not a billing statement."
- `total_cost_usd`: "Cumulative estimated cost in USD for this query() call, covering the same query-pipeline calls as modelUsage ... An estimate, not a billing statement."

The budget check in the same binary compares the accumulated session cost against the threshold (`!(cost < threshold)`) after each message the engine yields inside the turn loop, and the cost only moves when a model call's usage arrives.
So on this version the threshold is checked between model calls and a call in progress is never cut short; a single long generation can carry the cost well past it, which is what the 3.4x overshoot on a one-turn toolless `xhigh` review in #158 looks like.
The flag's parser rejects values that are not greater than 0, so no zero-spend capture exists.
This describes the one loop that was read; it is not a claim that every auxiliary call is serialized behind that check, and it is version-scoped to 2.1.274.

## What amicus does with it

- `normalize.extract_usage` reads token counts from `modelUsage` whenever the envelope has a dict-shaped entry under it, summing across models, and falls back to the top-level block only when it has none (ADR 0034).
- `budget_exceeded`'s detail, its repair, the `max_budget_usd` option description and `AMICUS_CLAUDE_MAX_BUDGET_USD`'s description all say the threshold is checked between model calls and that the estimated cost can exceed it; none states an overshoot bound.
