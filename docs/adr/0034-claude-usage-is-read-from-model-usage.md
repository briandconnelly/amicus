# ADR 0034: Claude usage is read from `modelUsage`

**Status:** Accepted (2026-09-17)

## Context

`normalize.extract_usage` (`src/amicus/backends/claude/normalize.py`) read a claude envelope's token counts from its top-level `usage` block and its cost from `total_cost_usd`, and never read `modelUsage`.
Issue #158 reported a budget-stopped review on 0.3.0 whose `meta.usage` said `input_tokens: 0` and `output_tokens: 0` beside `cost_usd: 3.36`, so the zeros read as a measurement of a run that had plainly spent.

A capture on claude 2.1.274 reproduced the shape (`docs/claude-help/2.1.274/FINDINGS.md`): the budget-stop envelope prints the top-level block zeroed while `modelUsage` carries the real counts and a `costUSD` equal to `total_cost_usd`.
The binary's own result schema describes the top-level block as "main agent loop only ... prefer modelUsage for token/cost accounting" and `modelUsage` as "the correct field for token/cost accounting", covering the same calls as `total_cost_usd`.

## Decision

**Token counts come from `modelUsage` whenever the envelope has a dict-shaped entry under it, summed across models; the top-level block is read only when it has none.**
`cost_usd` stays `total_cost_usd`, the cumulative estimate that covers the same calls.

A field comes from one block, never from both.
When `modelUsage` is in use, a field that any one entry does not state as an integer is `None`: a sum over the entries that do state it would read as a whole-run total, and the top-level block's number counts a different scope.
An entry that is not an object at all is a model whose counts cannot be read, so every count is `None` while `modelUsage` stays the source.
When the top-level block is in use, its explicit zeros are zeros; the CLI reported them, and a nonzero cost alone does not prove a particular counter wrong.
`total_tokens` stays `None`, as before, because claude's input count excludes cached tokens.

## Consequences

- A budget stop now reports the counts claude recorded (#158's fixture: 4,707 in, 53 out) beside its cost, on every route the envelope can take (exit 1 on 2.1.274, exit 0 on the older capture in #73).
- On an older envelope whose `modelUsage` lacks the cache keys, such as the sibling's golden recording, the cache counters are `None` where they used to be read from the top-level block; the numbers were only equal there because that run had one call.
- `RESULT_FORMAT` does not move: every field keeps its type, and `None` was already a value each could carry.
- The mechanism is version-scoped to what was read on 2.1.274; a CLI that drops `modelUsage` falls back to the block and loses nothing it had before this decision.
