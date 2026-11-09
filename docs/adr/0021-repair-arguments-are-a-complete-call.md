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
Copilot's review found a third: an `amicus_models` repair for such a backend still named a tool it could not call.
A second Codex review found that explicit `RepairHint` arguments bypassed that guard, and that the skill still read `error.repair` unconditionally.

## Decision

**An unknown-argument rejection carries the corrected call.**
When every rejected argument is an unknown key the caller actually sent, `repair.arguments` is the call as sent minus those keys (`middleware.corrected_arguments`).

**It echoes only values whose own domain proves them safe.**
Every surviving value must be null, a bool, a number, a member of its parameter's published enum, or an object built from those.
Any other string suppresses the arguments, because it can be a mispasted secret or a prompt input (rule 18), and it cannot be dropped without changing the call.
The first design denylisted `INPUT_FIELDS` instead; Codex showed that `idempotency_key`, paths and model slugs are just as free-form, and the published `details.value` policy already declines to echo caller strings.

**A lookup repair carries the call that makes it.**
`amicus_models` repairs name the failing call's `backend`, which that tool requires, and `amicus_backends` repairs name it as the filter (`errors.complete_lookup`).
`job_not_found` repairs to `amicus_job_list({})` when the workspace came from the client's roots, since that call resolves the same workspace.
A third-party plugin's id is a valid `error.backend` but outside both tools' closed `backend` enum, so it is never named, and `amicus_backends` falls back to its unfiltered call.
Without a backend it accepts, `amicus_models` cannot be called at all, so that repair names no tool and stays a symbolic next step.
The guard applies to a plugin's own `RepairHint` arguments as well as to completed calls, so an explicit lookup call is kept only in a shape its tool accepts.

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

## Amendment (2026-11-09): a self-repair names the failing tool, and is not a lookup

Issue #444 found the same code naming the failing tool on one tool and no tool on another, and `amicus_models` losing its own tool at the boundary.
The cause of the last was `complete_lookup`: it read any repair naming `amicus_models` or `amicus_backends` as a lookup, found no backend to complete it with, and dropped the tool.
The rule is now one: a tool failure whose `repair.next_step` is `correct_arguments` names, in `repair.tool`, the tool that was called (`errors.repair_call`).
The call is corrected on that tool, so it is a self-repair, and a self-repair is never completed or dropped as a lookup, even when the failing tool is a lookup tool.
`repair.arguments` on a self-repair follows this ADR unchanged: present only for the unique echo-safe correction the call boundary builds, and only when the builder named the failing tool beside it.
The failing tool is threaded to every place an envelope is built, before a job stores it, so an `_async` run's stored refusal and a keyed replay name the tool that was called.
A repair that points at a lookup uses the step that matches it: the `pi` and `kimi` model and effort hints that named `amicus_models` under `correct_arguments` now say `use_allowed_value`, and `complete_lookup` still completes every lookup repair, whatever its step.
`NO_CORRECTIVE_CALL` codes still carry no repair.
The Consequences paragraph above that left the tool-only `invalid_arguments` repair "to a decision of its own" is that decision: the tool-only self-repair is kept, and now holds on every path.
