# ADR 0045: result-field reading rules are published once

**Status:** Proposed (2026-09-26)

Refines [ADR 0019](0019-review-results-disclose-coverage-as-a-field.md) and [ADR 0024](0024-prose-list-loss-is-disclosed-never-folded.md), which keep their decisions; extends [ADR 0006](0006-fingerprint-and-surface-digest.md), whose snapshots move.

## Context

Three disclosure fields exist so that a result cannot look clean while something was lost: `findings_diagnostics` (#38), `lists_diagnostics` (#52) and `coverage` (#65).
Each was given prose on the published output schema that defines its reason vocabulary and warns against the specific misreading it guards, because an MCP-only caller sees the schema and nothing else.
Measured on the raw stdio wire at `main` `2ab6a8c`, `all` profile, 112,105 bytes in total, the three fields cost 18,088 bytes across ten occurrences, a third of all output-schema bytes, and 10,897 of those bytes are description text.

| Field | Occurrences | Bytes | Structure | Prose |
| --- | --- | --- | --- | --- |
| `findings_diagnostics` | 4 | 6,592 | 1,380 | 5,212 |
| `coverage` | 3 | 5,874 | 2,448 | 3,426 |
| `lists_diagnostics` | 3 | 5,622 | 3,363 | 2,259 |

The prose is the same text once per tool, because MCP has no cross-tool schema sharing and `publish.py` inlines every branch on purpose; the only cross-tool carrier amicus has is a resource, or the schema a free tool returns.
Two precedents already took that trade: #41 moved repeated parameter prose behind `amicus://params`, and `meta` is published on every tool as a 44-byte pointer whose schema lives once at `amicus://result-meta` and behind `amicus_capabilities(include_schemas=["result-meta"])`, whose published description already calls it a resource-blind fallback.
Those precedents establish the carrier, not that these particular guards stay effective once moved, which is why the guards do not move.
Neither captured host read a resource in any recorded run (`docs/host-captures/install-smoke/codex/0.153.4/transcript.md`, `docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md`), so a resource alone is not a carrier an agent is known to follow; a free tool call is.
The skill (`skills/collaborating-with-amicus/references/reading-results.md`) already carries every reason vocabulary and every reading rule, so an agent using the skill does not depend on the schema prose.
The prose is of two kinds: guards, which name the misreading a field exists to prevent, and vocabularies, which define each reason value; measured by constant, the guards are 3,132 bytes and the vocabularies 7,098.
#247 names this as its second remediation and calls a definition every client pays for on every connection the one discovery cost that can be lowered everywhere.

## Decision

**The three fields keep their structure and their guards on every tool's published schema, and their vocabularies are published once.**
`status`, the reason enums, the required members, the nullability and the numeric bounds stay in each tool's `outputSchema`, byte for byte, so a client validator enforces the same shape it enforces today and a caller still branches on the same fields; the cross-field invariants of `Coverage` are enforced by the model at delivery, as today, and are described with the vocabularies.
The guards stay verbatim: `_DIAGNOSTICS_DESC` and `_DROPPED_DESC` on `findings_diagnostics`, `_COVERAGE_DESC` on `coverage`, and the first 289 bytes of `_LISTS_DESC` on `lists_diagnostics`, up to where its reason definitions begin; none of these is rewritten, so the disclosed semantics, including that `number_stringified` loses nothing and that `complete` means no detected omission, do not change.
The vocabularies move: `_REASONS_DESC`, the reason definitions of `_LISTS_DESC`, `_OMISSION_REASONS_DESC`, `_UNTRACKED_DESC`, `_REDACTION_DESC`, `_WITHHELD_DESC` and `_MASKED_DESC`, 6,231 bytes on the `all` wire, replaced on each field by one pointer sentence of about 90 bytes.
Nothing about what a result carries changes: the stored payload, `RESULT_FORMAT` and the delivery rules are untouched.

**The vocabularies get their own document, and `Meta` keeps its own.**
A new `include_schemas` value, `result-fields`, and a fourth static resource, `amicus://result-fields`, carry the `FindingsDiagnostics`, `ListDiagnostics` and `Coverage` schemas with their full prose; `result-meta` stays the `Meta` schema alone, so a client that validates `meta` against it sees no change.
The pointer sentence names the tool path first and the resource second, because the tool is the carrier every host can use.

**The saving is measured on the wire, and the guards are exercised on a host.**
The projected net saving is about 5,200 bytes on `all`, 4.6% of the catalog: 6,231 bytes leave, about 900 bytes of pointer sentences and about 40 bytes of enum value arrive.
The change ships only if the measured reduction on every profile is at least 4,500 bytes, and only if the host scenarios in the #247 plan show an agent with no skill loaded reading each disclosure correctly after following the pointer: a list lost on an otherwise clean result, a finding that lost content at `dropped: 0`, and a `number_stringified` normalization that lost nothing.
An agent that reads any of those as the backend saying none, or as loss where there was none, is the defect these fields exist for; then the vocabularies return in full and this ADR is recorded as rejected on that evidence.

## Consequences

- `tools/list` on `all` is expected to drop by about 5,200 bytes; that is modest, about 1,300 tokens per connection on a preloading host, and it is the whole of the repeated prose, since the remaining output-schema bytes are structure MCP cannot share across tools; the delivered figure is recorded in `tests/test_discovery_cost.py` with `MEASURED` and `BUDGET` moved together.
- The `KEPT_DESCRIPTIONS` set in `src/amicus/schemas/publish.py` loses the vocabulary constants and gains the pointer sentences; every sentence that leaves it is asserted present in the `result-fields` schema by a test that fails if a rule is dropped rather than moved, and the guards are asserted unchanged by a test that compares them to the pre-change text.
- `STATIC_RESOURCE_URIS`, the server's static set, the `include_schemas` enum and the manifest snapshots gain `result-fields`; `FINGERPRINT` moves once, for the output-schema descriptions, the new resource and the enum; `RESULT_FORMAT` does not.
- The skill and `docs/MIGRATION.md` name the new carrier; the skill's rules are unchanged because they never depended on the schema prose.
- An MCP-only caller that never calls `amicus_capabilities` and never reads resources sees each field's guard and the enum values, and not the definition of each value; that is the trade #41 and `meta` already made, narrowed to vocabularies, and the host scenarios above are what bound it.

## Alternatives considered

- **Opaque stubs for the three fields, as `meta` is published.** Saves about 16,500 bytes, but removes the enums and required members from the schema, so a validator can no longer enforce them and `coverage`'s invariants become invisible; rejected because ADR 0019 made those invariants part of the contract.
- **Within-tool `$ref` for the `ListDiagnostics` member inlined three times.** Saves about 2,200 bytes of structure, needs `publish.py` to stop dereferencing, and no captured host has been shown to resolve `$ref`; not taken.
- **Move the guards as well as the vocabularies.** Would save about 9,500 bytes, but the guards are the sentences #38, #52 and #65 wrote to stop a specific misreading, and a rewrite of them in a review of this ADR was found to change their semantics twice; rejected.
- **Extend `result-meta` instead of adding `result-fields`.** Saves a resource, but changes the root of a document clients may validate `meta` against; rejected.
- **Leave the prose.** Keeps everything inline and leaves the ceiling on discovery cost where it is; this is the outcome if the host scenarios fail.
