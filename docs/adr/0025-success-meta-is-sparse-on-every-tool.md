# ADR 0025: Every success envelope's meta is sparse on the wire, with a required core

**Status:** Accepted (2026-09-14)

## Context

Issue #47, from the 2026-09-09 agent-friendliness audit, measured a plain `amicus_job_list` success at 27 `meta` keys, 15 of them null and 3 empty lists, 626 bytes that were about a third of the result and paid twice because `content[0].text` mirrors `structuredContent`.
The checklist's `[8.strip-nulls]` exempts only fields a contract marks always-present, and no such contract existed: `meta_fields` was a flat list of names and `amicus://result-meta` made no presence claim.
The wire already had two shapes.
A delivered paid result went through `jobs.delivery.slim_meta`, which dropped null keys but was gated on the tool being a paid one, and the result-meta schema's description said a delivered success drops them.
A job-lifecycle handle, a job status, a job list and a dry run dumped the full model, so a free envelope contradicted the published description.
Issue #48 from the same audit is fixed in the same change and needs no decision: resource size moves from the private triage `_meta` block to the native `Resource.size`, and it is omitted rather than reported as `0` when the body is built per read.

## Decision

**Slimming happens once, at the guard, for every tool.**
`slim_meta` moves to `schemas.envelope` and `tools._guard.as_tool_result` applies it to every `ok: true` envelope.
Every tool is guarded, and the guard is already the one chokepoint a task-augmented call shares with the middleware path (ADR 0004), so no delivery path is left out.
The delivery chokepoint keeps applying it to a stored result, so the wire-shape snapshot, which drives that chokepoint directly, still renders the delivered shape; its handles section applies the same function, because the builders it calls dump the full model and the guard is what slims them in production.
Slimming at each builder was rejected: seven dump sites today, and a new one would default to the wrong shape.

**The always-present core is the schema's own `required`.**
`META_ALWAYS_PRESENT` is derived from the model: the fields whose default is never None, minus `server_version`, which a stored payload can predate and which is then omitted rather than backfilled.
It is `elapsed_ms`, `truncated`, `compat_warnings`, `security_warnings`, `redacted_paths`, `request_id` and `fingerprint`.
`amicus://result-meta` publishes it as `required`, the native JSON Schema carrier for a presence claim, and its description says what it means.
A new `Meta` field with a non-null default joins the core without a separate declaration, and a test asserts the set, so the change is visible.
A new field in the capabilities payload was rejected: `meta_fields` still lists every name, and the presence claim belongs beside the schema it qualifies.

**Empty lists stay.**
`security_warnings: []` means checked, none found, which is information a reader acts on, and the skill tells an agent to read all three lists before drawing a conclusion.
They are required, never dropped.

**Only `meta`'s top level is touched.**
A null inside `usage` or another nested object, and a null outside `meta` such as `JobStatus.poll_after_ms` or `JobListResult.truncation_hint`, is that object's own contract and is delivered as it is.
The persisted dump is unchanged, so `RESULT_FORMAT` stays 6.

## Consequences

- `FINGERPRINT` moves to `schema-24`, for the result-meta schema, the resource metadata and the job-envelope shapes.
- A reader may index a `required` key without a presence check and must check presence for every other key; the skill's reading guidance says so.
- A stored result read back with `amicus_job_result` is slimmed twice, once at delivery and once at the guard, and the second pass is a no-op.
