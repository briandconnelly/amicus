# ADR 0053: amicus_models takes one query object

**Status:** Accepted (2026-11-21)

Narrows the listing of [ADR 0051](0051-pi-catalog-prices-enrich-the-table-and-never-replace-it.md) on request, and leaves the pre-spend check of [ADR 0047](0047-pi-backend-validates-an-exact-model-and-fails-closed.md) unchanged.

## Context

`amicus_models(backend="pi")` returned every row of pi's catalog, up to 1,024, and took no argument but `backend` (issue #560).
With one router provider credentialed that is several hundred rows, and since ADR 0051 each priced row also carries a `pricing` object.
A host that wanted a model under some price with at least some context had to receive the whole catalog and filter it itself, which in practice meant saving the response to a file and filtering it with a shell tool.
The catalog was also cut at 1,024 rows before any filter could run, so a filter applied by the host over a cut catalog was incomplete in a way the rows did not show.

## Decision

**One optional argument, `query`, a closed object.**
Its members are `slug_prefix`, `max_input_price`, `max_output_price`, `min_context_tokens`, `sort_by` and `limit`, each optional; `limit` defaults to 50 and is at most 1,024.
The model is strict: a boolean or a numeric string is not a price, a price is finite and not negative, and an unknown member is `invalid_arguments`.
Its full semantics are the `query` contract at `amicus://params`, so the tool's schema carries a one-line summary rather than the whole contract.

**Without a query, nothing changes but one key.**
Omitted or `null`, the listing has today's rows, order and counts, and gains `selection: null`, on the tool and on `amicus://models/{backend}` alike.
The resource takes no arguments and stays the unfiltered listing, equal to the tool's response when `query` is omitted.

**An unknown value never passes a bound.**
A row whose `pricing` is null fails a price bound, and a row whose `context_tokens` is null fails `min_context_tokens`; a known `0.0` passes.
The response counts what it excluded in `selection`: `excluded_by_filter` for a known value that failed, `excluded_unknown_context` and `excluded_unknown_pricing` for an unknown one, and `omitted_by_limit` for a match `limit` cut.
The counts are disjoint: each row is tested by prefix, then context, then input price, then output price, and counted at the first test that excludes it, so with the rows returned they sum to `examined`.

**A price compares the highest rate across tiers.**
A price bound and a price sort compare the highest rate across the base rate and every tier, separately for input and output, and the response says so as `price_basis: "max_across_tiers"`.
A price sort orders by that rate and then by slug, with unknown prices last.

**Policy runs first.**
`AMICUS_DENY_MODELS` hides rows before the query sees them, `hidden_by_policy` keeps its meaning over the rows examined, and `selection.examined` counts only the rows policy allows.

**The same semantics on every backend.**
`codex` and `claude` publish no prices, so a price bound there excludes every row and `excluded_unknown_pricing` says how many.
Nothing is refused per backend: the counts already say why nothing matched, and the tools layer needs no per-backend table.

**A query scans past the plain listing's cut.**
`PiModels.read` now parses up to `MAX_SCAN_ENTRIES = 4096` rows and marks the listing's `display_limit` as 1,024.
A plain listing, `PiBackend.list_models` and the resource show the first 1,024 rows as before; a query examines the whole scan.
At pi 1.6.0's measured sizes 4,096 rows are about 2.3 MB of RPC reply, under `RPC_MAX_BYTES` (4 MiB), and the table probe keeps its whole-output-or-nothing check at `MODELS_CACHE_MAX_BYTES`, so neither byte cap changes.
`PiModels.lookup` and its probe are unchanged.
On a query response `truncated` is true only when the scan itself was cut, and its hint says the rows past the scan were never compared; `limit` is reported separately as `omitted_by_limit`.
When the RPC reply is lost, every row has unknown pricing, a price query excludes them all as unknown, and nothing new is cached or retried.

**Nothing ranks a model by quality.**
pi's catalog has no quality signal, so the query narrows by slug, price and context only.

## Alternatives rejected

**A skill-only recipe.**
Documenting a filter in the skill keeps the surface small, but every host would still receive the whole catalog and re-derive the same filter, and could not see past the 1,024-row cut.

**Flat arguments.**
Six top-level arguments would each carry a description in `tools/list` on every session; one closed object keeps the growth to one property and puts the semantics at `amicus://params`.

**A switch to keep rows with unknown pricing.**
Codex proposed a tri-state switch for it.
It was cut, as the issue invites: an unknown value never passes a bound, and the response counts it, so a caller that wants those rows can drop the bound and read them.

**Comparing the base rate only.**
A base rate alone understates a long request, so a bound on it would admit a model whose tier exceeds the caller's limit.

**Refusing price arguments on `codex` and `claude`.**
Codex proposed it.
Uniform semantics were taken because the exclusion counts already say why nothing matched, and a refusal would need a per-backend table in the tools layer.

**Filtering only the first 1,024 rows.**
A filter over a cut catalog would miss a matching row past the cut and could not say whether one existed.

**A scan bound that needs larger byte caps.**
A larger bound would move `RPC_MAX_BYTES` or `MODELS_CACHE_MAX_BYTES`, which bound what a probe may hold in memory; 4,096 rows fit both as they are.

## Consequences

`amicus_models`' input schema gains `query` and its result gains `selection`, so `FINGERPRINT` moves to `amicus/0.1/schema-80` and the `tools/list` budget rises.
A pi listing holds up to four times as many rows in the cache, all of them enriched by the one RPC probe a read already runs.
A short or empty query result is not evidence that a model is unavailable: it may be unknown, past the scan, or cut by `limit`, and the counts and `truncated` say which.
