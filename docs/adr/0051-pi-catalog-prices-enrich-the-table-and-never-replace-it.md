# ADR 0051: pi's catalog prices enrich the table and never replace it

**Status:** Accepted (2026-11-21)

Adds a second catalog source to the pi backend of [ADR 0047](0047-pi-backend-validates-an-exact-model-and-fails-closed.md), whose model check is unchanged.

## Context

`amicus_models` could not say what a pi model costs (issue #554).
The pi backend read its catalog from the `pi --list-models` table, which has no price column, and a router provider lists hundreds of models whose prices differ by orders of magnitude.
A host could not estimate a call, and could not tell in advance whether a prepaid provider would refuse one, which it does unless the balance covers the model's whole output limit at its output price.

pi's RPC mode answers a `get_available_models` request with each model's full definition, including `cost` in US dollars per million tokens and the exact `contextWindow` and `maxTokens`.
Probes on pi 1.5.0, 1.5.2 and 1.6.0, recorded in `docs/pi-help/1.6.0/FINDINGS.md`, found that it makes no model call, exits at stdin EOF, and names the same models as the table in every configuration tried.
They also found three differences that decide the design.
The reply is not sorted as the table is, so a cut at a fixed number of rows keeps different models.
The reply is built from a snapshot where the table awaits the catalog, so a provider that discovers models at run time could appear in one and not the other, which was not tested.
And pi reports a model that has no catalog price as costing zero, exactly as it reports a free one.

## Decision

**The table stays the authority on which rows exist and in what order.**
`PiModels.read` reads the table as before and then asks the RPC listing, and uses the reply only to give a row it already has its exact limits and its price, matched by slug.
A row the reply does not describe, or describes twice, keeps the table's figures and no price.
So the listing's rows, their order and the cut at `MAX_ENTRIES` cannot change with the second source, and a difference between the two sources can cost a row its price and nothing else.

**The pre-spend check does not use the reply.**
`PiModels.lookup` remains the targeted table search of ADR 0047.
It needs no price, it can vouch for a model past the listing's cut, and it is the path the fail-closed argument was made for.

**A failed second probe is not a failed listing.**
A reply that is missing, unsuccessful, repeated, cut at the capture cap or from a run that failed leaves the table's rows as they are, without prices.
Such a listing is cached for `PRICING_RETRY_SECONDS` rather than the full cache lifetime, so one failed probe does not hide prices for five minutes.
The reply is captured under a byte cap while pi runs, through `run_sync_capture`'s `max_output_bytes`, because it is one line whose size grows with the number of credentialed providers.

**A price is published only where it says something.**
`pricing` is null when the four base rates are all zero and there is no tier, because that is pi's spelling of both free and unpriced, and null on any row whose `cost` is malformed in any part.
Null therefore means unknown and never free, and the field's description says so where a caller reads it.
The description also says the figures are a snapshot of pi's cached catalog and not a quote: amicus probes with `--offline`, the reply carries no timestamp, and the amount billed is `meta.usage.cost_usd` where the provider reports it.
Tiers are published in full, since a base rate alone understates a long request.

**Only named fields are read.**
The reply also carries each model's endpoint URL and, for some providers, fixed request headers and a credential-source label.
amicus reads the provider, the id, the two limits and `cost`, and writes the reply to no log.

**Reasoning efforts are not narrowed.**
The reply's `thinkingLevelMap` says which levels a model maps, but ADR 0047 lets pi clamp an effort and reports the level that ran, and the pre-spend check enforces the listed set.
Narrowing it would change which calls are refused, so it is left for a decision of its own.

## Consequences

`amicus_models` on `pi` runs two probes where it ran one, each bounded by `PROBE_TIMEOUT_SECONDS`, on a cache miss.
`context_tokens` and `max_output_tokens` are exact when the second probe answered and rounded when it did not, and a row does not say which, so their descriptions keep the advice to leave headroom.
The request sent on stdin is a fixed literal in `contract.py` and no prompt input can reach it, so rule 18 gains no carrier.
The reply's shape is not covered by the `--help` comparison that guards the flags amicus sends, so a pi release that changed it would lose prices silently rather than fail; `docs/RELEASING.md` checks it by hand before a release.
The prices rank nothing: pi's catalog has no quality signal and no account balance, so choosing among models still needs a source outside amicus.
