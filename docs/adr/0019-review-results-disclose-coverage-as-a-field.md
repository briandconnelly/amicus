# ADR 0019: Review results and the dry run disclose coverage as a field

**Status:** Accepted (2026-09-12)

Supersedes the coverage clause of [ADR 0007](0007-m1-codex-port-decisions.md); the rest of that record stands.

## Context

ADR 0007 dropped codex-in-claude's `coverage` object from `ReviewResult` when M1 ported the sibling.
Its reason was that the coverage rule survived as a verdict fold and that `meta.truncated`, `meta.truncation_hint` and `meta.redacted_paths` carried the machine signal.
The fold did survive: a model `pass` over partial coverage is still delivered as `unknown`/`low` with a caveat in `summary`.
The machine signal did not.
Those meta fields carry two of the five reasons the fold acts on, `truncated` and `redacted`.
`untracked_omitted`, `tree_changed_during_gather` and `focused` reached a caller only as a sentence prepended to `summary`, so a client could not branch on them, count omitted files, or tell one reason from another without parsing English.
`amicus_dry_run` carried none of it, so the free preview could not say that the paid call would skip an untracked file, which is the one thing a preview before spend exists to say (issue #65).

Issue #65 also said the `Coverage` shape was already in `src/amicus/schemas/results.py`.
It was not: amicus had ported the fold and never the model.

## Decision

**`coverage` is a required, non-null field on `ReviewResult`, `AdversarialReviewResult` and `DryRunResult`.**
A default would answer, on a producer's behalf, a question that producer never measured, which is the reasoning issue #38 applied to `findings_diagnostics`.
A `not_run` result carries one too, computed from the empty gather, so an untracked-only tree reports `untracked_omitted` with its counts; `review_status`, not `coverage`, says that nothing ran.
A critique with no attached scope gathered nothing, so its untracked counts are null and it is `complete` unless it was focused.

**The shape is the siblings', plus one reason of amicus's own.**
`status`, `untracked_files_detected`, `untracked_files_included`, `untracked_files_omitted`, `omission_reasons` and `redaction` mean what they mean on codex-in-claude and moonbridge, so a client migrating from either has a field to read.
`redaction` is ported rather than left to `meta.redacted_paths`, because a file whose changes were withheld whole and a file sent with one value masked are different facts, and a flat path list cannot tell them apart.
`focused` is the fifth reason; neither sibling has a `focus` parameter.

**One builder feeds both the disclosure and the fold.**
`review.build_coverage` derives the object from the gathered diff and the call's `focus`, and `apply_coverage` reads that object rather than a separate list of reasons.
The two cannot disagree, because there is only one of them.
The dry run calls the same builder and now accepts `focus`, so a preview and the paid call it previews report the same coverage for the same arguments; before this, a focused review could not be previewed at all.

**The model makes every field agree with every other.**
`status` is `partial` exactly when a reason is listed, and the reasons are unique and in their fixed order.
The three untracked counts are all set or all null, non-negative and summing, and the omitted count is non-zero exactly when `untracked_omitted` is listed.
`tree_changed_during_gather` appears only beside the working-tree counts, and `redaction` only beside `redacted`, naming at least one path, with its two path lists disjoint.
That is stricter than either sibling.
Delivery validates a stored result strictly and otherwise trusts whatever validates, and a client branches on these fields without reading `summary`, so an inconsistent disclosure must be unconstructible rather than merely unlikely.

**Coverage is not only what the backend was shown, and the published text says so reason by reason.**
`focused` withholds nothing; it records that the backend was not asked for a full review.
`tree_changed_during_gather` is a best-effort consistency caveat, so its absence is not proof the tree held still.
`complete` means that nothing in scope was left out of what amicus assembled, not that the backend examined every line.
Describing coverage generically as "what the model saw" would have been false for two of the five reasons, and that misreading is the one this record exists to prevent.

## Declined

`redacted_paths_count` on the dry run: the count is `len(meta.redacted_paths)`, and `coverage.redaction` splits those files by what happened to them.
A top-level `deadline_advisory` on the dry run: it is not a coverage fact, it is already carried in `warnings`, and the delegate dry run would need the same change to stay consistent.
Issue #65 listed both as absent; neither was lost by accident, and `docs/MIGRATION.md` says what replaces each.

## Consequences

`FINGERPRINT` moves to `schema-16`: the review, critique and dry-run output schemas, the dry run's input schema and description, and the discovery `returns` strings all change.
`RESULT_FORMAT` moves to 5, because every stored review now carries `coverage`, and a format-4 record is reported as `job_result_incompatible` rather than delivered.
The caveat sentence in `summary` is unchanged, so a client that parsed it still finds it.
