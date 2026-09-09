# ADR 0017: an unreadable machine enum falls to its own honest floor, and `low` is not one

**Status:** Accepted (2026-09-09)

## Context

`_parse_reviewed` (`src/amicus/orchestration/finalize.py`) is strict about the SHAPE of a backend's reply and lenient about its FIELDS.
Output that is not a JSON object is a hard error; an object that deviates field by field is coerced, so a malformed reply can never be delivered as a `pass`.
Coercion needs a value to fall to, and until now the two machine enums chose theirs differently.
`verdict` fell to `unknown`, which the file's own docstring defends as honest.
`confidence` fell to `medium` — higher than `low`.

A backend that returned nothing readable about its own certainty was therefore delivered as moderately confident, and nothing in the envelope said the value had been invented.
That is issue #38's defect on a different field: the result asserts more than the backend said.

The path is live rather than theoretical.
Only `codex` is held to `REVIEW_OUTPUT_SCHEMA` natively; `claude` and `kimi` receive it as prompt text, and `classify_structured` checks only that the payload is a JSON object.
Field-level deviation on two of three backends is the expected case.
Measured against the tree at `e0f60e2`, a reply carrying a valid findings list and `confidence: "very high"` was delivered as `pass`/`medium` with `findings_diagnostics: null` — an envelope asserting that nothing deviated while a required member had been unreadable.

Issue #53 framed the fix as `medium` → `low`, and asked separately whether an invented value should be signalled rather than merely defaulted.
A Codex consult on 2026-09-09 rejected the framing, and the argument held.

## Decision

**`unknown` joins the published `Confidence` enum, and an unreadable confidence falls to it.**

`low` is not the analogue of `verdict`'s `unknown`.
It is the lowest rating a backend can REPORT, so defaulting to it manufactures a claim in the same direction as `medium` did — smaller, and harder to notice.
`unknown` declines to make one.
The enum widens on the RESULT only: `REVIEW_OUTPUT_SCHEMA` still asks backends for `low|medium|high`, so no backend is invited to report unreadable certainty as a value in its own right.

**An unreadable confidence does not disturb the verdict.**
Confidence answers how sure the backend was, not what it found.
A reply carrying `fail` and no readable confidence is delivered as `fail`/`unknown`, neither softened nor promoted — the same principle `apply_findings_loss` already applies when it lets a concrete negative keep its verdict and its confidence.

**The coverage and findings-loss folds keep stating `low`.**
They speak for amicus rather than for the backend, on a basis amicus has: a diff the model did not fully see, or findings amicus could not relay.
`low` there is an assessment, not an invented reading of the backend.
So `unknown` survives only where neither the backend nor a fold had anything to say.
Both folds lower the rating and withhold the verdict together or not at all, which is what makes the published description checkable: a `low` beside any verdict other than `unknown` is the backend's own word, and a high confidence is never evidence that coverage was complete.
`review_status: not_run` turns out to be a third amicus-substituted `low`, and it obeys the same invariant — it too sits beside an `unknown` verdict.
So the three cases share one rule rather than needing three, and the published description names all three rather than implying a `not_run` result had a backend rating that partial coverage replaced.
Whether `not_run` should instead carry `unknown` confidence is issue #54; describing today's behaviour honestly does not decide it.

**Therefore the meaning of `confidence` is published, not merely documented.**
The field is two things at once, and a caller who cannot see which one it is holding will read `unknown` as a low rating — the exact inversion the value exists to prevent.
`publish._strip_schema_noise` drops any description not registered in `publish.KEPT_DESCRIPTIONS`, so the description is registered before the schema that carries it is built, and a test asserts it survives to the wire.

**No provenance diagnostics.**
Distinguishing a reported value from a substituted one is a broader requirement than declining to invent certainty, and it would have to cover both enums symmetrically.
It is not attempted here.

## Consequences

`FINGERPRINT` moves to `schema-10` (`value_enums`, `tool_output_schemas`) and `RESULT_FORMAT` to `4`.
A format-3 reader's closed enum rejects a format-4 record carrying `unknown`.
That is the intended trade: the alternative was a format-3-valid `medium` amicus had invented, so a reader that refuses the new record is refusing to be misled rather than losing information.

`tools/list` grows 1130 bytes, most of it one description carried byte-identically on both review tools — the duplication issue #41 is about.
It is kept for the reason #38's diagnostics prose was kept: an MCP-only caller has no skill file to fall back on.

A premise worth recording, because it was wrong on the way in.
`verdict: "unknown"` looked like a non-value that conflates with nothing a backend would report; `REVIEW_OUTPUT_SCHEMA` explicitly permits it, so a defaulted `unknown` verdict has never been distinguishable from a reported one.
After this change both enums carry an `unknown` a backend may or may not have supplied.
Neither is provenance, and this repository should not imply otherwise.

`review_status: "not_run"` still returns `unknown`/`low`.
No backend ran, so there is an argument that it should carry `unknown` confidence too; it is filed rather than decided here.
