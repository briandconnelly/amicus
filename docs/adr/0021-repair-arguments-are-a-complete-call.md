# ADR 0021: Repair arguments are a complete call, and the workspace codes carry no repair

**Status:** Accepted (2026-09-13)

Amends [ADR 0005](0005-error-envelope-and-repair-precedence.md) on what `repair` carries; its shape and rendering precedence stand.

## Context

Issue #42, from the 2026-09-09 agent-friendliness audit, found that on the commonest validation failures `repair` named a tool and a prose `alternative` but no `arguments`, even where the corrected call was uniquely determined.
`invalid_workspace_root` carried no `tool` at all.
The checklist's `[6.repair-object]` makes `tool` and `arguments` one callable call and omits `repair` when none exists.
`[6.repair-intent]` keeps every still-valid, non-sensitive original argument, and `[6.offending-value]` makes safety a property of the value rather than of the parameter.
A Codex consult on this issue (2026-09-13) rejected two parts of the first design, and both corrections are recorded below.
Codex's review of the branch then found two gaps, a third-party backend id and the `render_failure` path, which the Decision also covers.

## Decision

**An unknown-argument rejection carries the corrected call.**
When every rejected argument is an unknown key the caller actually sent, `repair.arguments` is the call as sent minus those keys (`middleware.corrected_arguments`).

**It echoes only values whose own domain proves them safe.**
Every surviving value must be null, a bool, a number, a member of its parameter's published enum, or an object built from those.
Any other string suppresses the arguments, because it can be a mispasted secret or a prompt input (rule 18), and it cannot be dropped without changing the call.
The first design denylisted `INPUT_FIELDS` instead; Codex showed that `idempotency_key`, paths and model slugs are just as free-form, and the published `details.value` policy already declines to echo caller strings.

**A lookup repair carries the call that makes it.**
`amicus_models` repairs name the failing call's `backend`, which that tool requires, and `amicus_backends` repairs name it as the filter (`errors.lookup_arguments`).
`job_not_found` repairs to `amicus_job_list({})` when the workspace came from the client's roots, since that call resolves the same workspace.
A third-party plugin's id is a valid `error.backend` but outside both tools' closed `backend` enum, so it is never named, and `amicus_backends` falls back to its unfiltered call.

**`invalid_workspace_root` and `workspace_outside_roots` carry no repair.**
Only the caller holds the intended absolute directory, so no call can make the correction; `details.field` and `candidate_roots` name what to fix (`errors.NO_CORRECTIVE_CALL`).
The omission belongs to the code, so `render_failure` applies it as `make_error` does.
The first design named the failing tool with no arguments; Codex held that a tool alone is not a corrective call, and the issue asked for a lookup or omission, of which only omission exists here.

**A corrected call corrects the failures its envelope reports, and certifies nothing else.**
Per-backend option applicability, workspace resolution and effort shape are checked after the boundary, so a corrected call can still fail there, with a repair of its own.
A side-effect-free preflight of the candidate call was considered and not built: it would duplicate those checks in the middleware, and each later failure already carries its own repair.

The policy is published beside the offending-value policy on `amicus://error-envelope`, which moved `FINGERPRINT` to `schema-20`.

## Consequences

- `RESULT_FORMAT` stays 5: `Repair.arguments` was already in the stored schema, so an older reader accepts a record that fills it.
- An `invalid_arguments` repair whose correction is not unique (an enum value, a missing argument, or a free-form survivor) still names the failing tool with no arguments.
  Read strictly, the checklist would omit that repair too.
  That shape is the one the M6 first-repair capture exercised, and the skill's scenario S2 asserts on its `repair.tool`, so changing it is left to a decision of its own.
- Post-boundary `backend_options` applicability violations keep the same shape: their correction is unique, but the raw call is not available where they are detected.
- Next steps that name no call (`correct_config`, `reduce_input`, `retry_after_delay` and the like) keep their repair, because they are pontonier's closed vocabulary and a central "call or nothing" invariant would strip them from every code.
