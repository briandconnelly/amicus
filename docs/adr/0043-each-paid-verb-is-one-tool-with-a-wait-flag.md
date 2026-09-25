# ADR 0043: each paid verb is one tool with a `wait` flag

**Status:** Proposed (2026-09-24)

## Context

`tools/list` is 112,683 bytes on the `all` profile as `tests/test_discovery_cost.py` measures it in-process (112,730 on the raw stdio wire, as #247 captured it), 27,975 o200k tokens, for 18 tools, and a preloading host (Codex CLI, `docs/host-captures/install-smoke/codex/0.153.4/transcript.md`) pays it per session (#247).
Output schemas are 46% of it; the four `_async` records are 26,513 bytes, each carrying an input schema that repeats its sync twin's minus two parameters, and a byte-identical 1,959-byte `JobStarted` output schema.
The sync and `_async` twins carry identical annotations in every profile, and every sync call already runs as a detached job that the sync tail awaits (`jobs.lifecycle.run_sync` is `start_job` plus `await_job_result`), so the twin is the sync call without the wait.
The two paths still differ in more than the wait: an unkeyed sync run is prepared with the caller's clamped `timeout_seconds` and is terminated at it, a keyed one is prepared with the job deadline (ADR 0020), and only the sync tools are registered for task-augmented calls (`task=settings.tasks_enabled`), so the twins are never tasked.
Neither captured host negotiates the tasks extension (`docs/host-captures/claude-code/2.1.263/FINDINGS.md`, `docs/host-captures/codex/0.153.4/FINDINGS.md`: `tasks_negotiated=False`), so a task cannot yet stand in for the twin's non-waiting start.
The two dry-run tools are annotated `readOnlyHint: true` (`ann.free_read()`, free, no model call), while the paid tools are annotated `readOnlyHint: false` (`ann.active()`).
Hosts gate tool approval on that annotation: the Codex install-smoke capture (`docs/host-captures/install-smoke/codex/0.153.4/notes.md`) observed auto-approval of the read-only-hinted tools and refusal of the others under `approval_policy = "never"`.
Folding a dry run into its paid tool behind a flag would lose that read-only annotation, which the worst-enabled-backend annotation rule (`[3.ap-mode-annotations]`) requires; nothing like that separates a twin from its sync tool.
The prose kept on the output schemas by #38, #52 and #65 guards specific misreadings and is not repetition; #41 already compressed the repeated parameter prose behind `amicus://params`.

## Decision

**Each paid verb becomes one tool, its sync tool, with a `wait: bool = true` parameter.**
`wait: true` keeps the sync tool's behaviour exactly, including its timeout, keyed-call and task semantics.
`wait: false` takes exactly the `_async` twin's path today: `prepare_run` with no `timeout_seconds` and `background=True`, then `lifecycle.start_async`, returning the `JobStarted` handle.
An explicit `timeout_seconds` or `detail` beside `wait: false` is `invalid_arguments` before any spend, rather than silently ignored, because neither can have an effect on that path.
The output schema is `published_schema(<Result>, JobStarted)`, a union of the verb's result and the handle behind the existing `ok` discriminator.
A caller tells them apart by a field its validator can enforce: `job_id` is required on the handle, and `tool`, which every result already carries as a `const` but no result schema lists in `required` today (the consult branch requires only `meta` and `summary`), becomes required on every result branch, so top-level `job_id` means a handle and `tool` means a result.
A keyed `wait: false` start and a keyed `wait: true` call share the `(tool, key)` reservation, because both run under the sync tool's name, so a caller can start in the background and later attach with the same key: a keyed `wait: true` call whose key names a running job awaits that job, as a keyed duplicate does today.
For that to hold, `wait` joins `IDENTITY_EXCLUDE` (`src/amicus/request.py`) beside `background`, so the two modes of one call have one `arg_hash`; any other changed argument is still `idempotency_conflict`.
The deprecated twins keep their own `(tool, key)` namespace until removal, so a key used on a twin never replays or conflicts with the merged tool; the `idempotency_key` contract's sentence that sync and `_async` never share a key becomes "the `_async` twins, while they last, never share a key with the merged tool".

**`wait: false` is never task-wrapped.**
The merged tool stays registered for task-augmented calls, which today only its `wait: true` path can meaningfully use; a task-augmented call with `wait: false` is `invalid_arguments` before any spend, because a task that completes with a job handle would put two recovery handles on one run.
Whether to drop the twins' role in favour of tasks, rather than a `wait` flag, is revisited when a preloading host negotiates the tasks extension.

**The four `_async` tools are deprecated under the published policy and removed at the end of the window.**
They keep their whole records, gain the lifecycle marker with `replaced_by` naming the sync tool and a migration that says to pass `wait: false`, lead their descriptions with the deprecation, and move to the end of `ACTIVE_TOOLS` as one contiguous suffix in their current relative order (`amicus_consult_async`, `amicus_review_changes_async`, `amicus_delegate_async`, `amicus_adversarial_review_async`).
`ACTIVE_TOOLS` is a single cost group, so ADR 0028's rule that a deprecated tool "sits last in its group" is read for four tools as a deprecated suffix after the four sync tools, whose own relative order, like every other tool's, is unchanged.
`since` is the next minor release and `removal_at_or_after` is two minors later, written as constants when the follow-up plan is executed; `scripts/check_release_state.py` and `tests/test_meta.py` hold the window.
Removal takes out the four `_async` records, about 26.5 KB on the `all` profile, but that is the removal's delta, not the consolidation's net win.
The merged tools keep a `JobStarted` branch in their output schemas for good: measured in-process on this branch with `publish.published_schema(<Result>, JobStarted)` against today's schema, each grows by 1,668 bytes of compact JSON, 6,672 across the four.
So the net win after removal is about 19.8 KB less the four `wait` parameters, and during the window `tools/list` grows by those 6,672 bytes, the four markers and the `wait` parameters; `tests/test_discovery_cost.py` records each move with its reason, and the measured-evidence gate below starts from these figures.

**The window opens only on measured evidence.**
Before the follow-up plan starts the deprecation, it records four `tools/list` sizes on the `all` profile, so that the win is judged net of the permanent `JobStarted` branches, each both in-process and on the raw stdio wire: `main` at that time, the deprecation window (markers and `wait` added), after removal, and after the output-schema trimming that #247 lists as its second remediation, with and without the merge, saying which reductions are additive.
It also validates the merged output schema against a real result, a real handle and a real error envelope with a JSON Schema validator; a result that validates against the handle branch, or the reverse, blocks the merge.
If the window's growth cancels most of the removal's saving, or agents measurably fail to tell a handle from a result, the merge is deferred and the reductions that need no window are taken instead.

**What is taken now, before the window.**
`timeout_seconds` and `detail`, the two sync-only parameters, join the `amicus://params` mechanism as `ParamContract`s, and `_meta.fastmcp` is stripped from every catalog record (done in #250).
The output-schema prose #38, #52 and #65 chose to keep is not trimmed.
Two fields are never branched on, `raw_response` and `context_summary`; making them opaque needs a home for their schema, and none of the existing resources is it, so that is left to the follow-up plan as an `amicus_capabilities` `include_schemas` value.

## Consequences

- The follow-up plan implements the merge and the deprecation, sweeps the skill, the commands, the README and `docs/MIGRATION.md` (fifteen files name the `_async` tools), and updates the design spec's tool table and parameter matrix; `tests/test_params.py` gains `wait` in `SYNC_ONLY_PARAMS`.
- Until removal, `amicus_capabilities` still lists 18 tools; after it, 14.
- `FINGERPRINT` moves at each step; `RESULT_FORMAT` does not, since the stored result shapes are unchanged: requiring `tool` changes the published schema, not what a stored result holds.
- The `wait: false` pre-spend refusals, the task refusal, the `wait` identity exclusion and the twins' separate key namespace each need a test in the follow-up plan.
- The amendments above came from a review on 2026-09-25 in which the author and Codex, working independently, both recommended accepting with amendments; its one unresolved difference is how much client-side validation evidence the union needs, which the measured-evidence gate above settles by testing rather than by assumption.
