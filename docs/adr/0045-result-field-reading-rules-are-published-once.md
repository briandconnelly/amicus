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
Two precedents already took that trade: #41 moved repeated parameter prose behind `amicus://params`, and `meta` is published on every tool as a 44-byte pointer whose schema lives once at `amicus://result-meta` and behind `amicus_capabilities(include_schemas=["result-meta"])`.
Neither captured host read a resource in any recorded run (`docs/host-captures/install-smoke/codex/0.153.4/transcript.md`, `docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md`), so a resource alone is not a carrier an agent is known to follow; a free tool call is.
The skill (`skills/collaborating-with-amicus/references/reading-results.md`) already carries every reason vocabulary and every reading rule, so an agent using the skill does not depend on the schema prose.
#247 names this as its second remediation and calls a definition every client pays for on every connection the one discovery cost that can be lowered everywhere.

## Decision

**The three fields keep their structure on every tool's published schema, and their reading rules are published once.**
`status`, the reason enums, the required members, the nullability and the invariants stay in each tool's `outputSchema`, so a client validator enforces the same shape it enforces today and a caller still branches on the same fields.
The vocabulary definitions and the explanatory prose move to the schema behind `amicus://result-meta` and `amicus_capabilities(include_schemas=["result-meta"])`, which grows from the `Meta` schema to the result-field schemas, and the published resource description says so.
Each field keeps one sentence on the wire: the warning that guards its own misreading, and a pointer naming both carriers.
For `findings_diagnostics` that sentence is that `dropped: 0` can still mean content was lost and `dropped: null` that the count was unknowable, so read `reasons`; for `lists_diagnostics` that a null member is a clean list and a non-null one names what was lost; for `coverage` that `complete` means nothing was withheld, not that nothing was missed.
Nothing about what a result carries changes: the stored payload, `RESULT_FORMAT` and the delivery rules are untouched.

**The pointer names the tool path first.**
The resource URI is kept for clients that read resources; the free tool is the carrier every host can use, so it is what the sentence leads with.

**The saving is measured on the wire, and the guards are exercised on a host.**
The change ships only if the measured `tools/list` reduction on every profile is at least 8,000 bytes, and only if the host exercise the #247 plan already runs shows an agent, given a result with `coverage: partial` and a non-null `findings_diagnostics` and no skill loaded, reading the pointer and reaching the reading rules; an agent that treats such a result as clean is the defect these fields exist for, and the prose returns in full.

## Consequences

- `tools/list` on `all` is expected to drop by about 9,500 bytes: 10,897 bytes of prose leave and about ten pointer sentences of roughly 120 bytes arrive; the delivered figure is recorded in `tests/test_discovery_cost.py` with `MEASURED` and `BUDGET` moved together.
- The `KEPT_DESCRIPTIONS` set in `src/amicus/schemas/publish.py` shrinks to the pointer sentences; every sentence that leaves it is asserted present in the `result-meta` schema by a test that fails if a rule is dropped rather than moved.
- The skill and `docs/MIGRATION.md` name the new carrier; the skill's rules are unchanged because they never depended on the schema prose.
- `FINGERPRINT` moves once, for the output-schema descriptions, the resource body and its size, and the `result-meta` schema; `RESULT_FORMAT` does not.
- An MCP-only caller that never calls `amicus_capabilities` and never reads resources sees one sentence per field instead of a vocabulary; that is the trade #41 and `meta` already made for parameters and metadata, and the host exercise above is what bounds it.

## Alternatives considered

- **Opaque stubs for the three fields, as `meta` is published.** Saves about 16,500 bytes, but removes the enums and required members from the schema, so a validator can no longer enforce them and `coverage`'s invariants become invisible; rejected because ADR 0019 made those invariants part of the contract.
- **Within-tool `$ref` for the `ListDiagnostics` member inlined three times.** Saves about 2,200 bytes of structure, needs `publish.py` to stop dereferencing, and no captured host has been shown to resolve `$ref`; not taken.
- **Leave the prose.** Keeps every guard inline and leaves the ceiling on discovery cost where it is; this is the fallback if the host exercise fails.
