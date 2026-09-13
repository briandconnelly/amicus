# ADR 0020: The sync paid tools take an idempotency key

**Status:** Accepted (2026-09-12)

Supersedes the "sync tools stay unkeyed" clause of [ADR 0008](0008-m2-jobs-surface-decisions.md) and amends decision 2 of [ADR 0011](0011-m5-tasks-decisions.md); the rest of both records stands.

## Context

`idempotency_key` was accepted only by the four `_async` twins (`ASYNC_ONLY_PARAMS` in `src/amicus/schemas/params.py`).
Both siblings accept it on their sync tools, and `docs/MIGRATION.md` presented `codex_consult` → `amicus_consult(backend="codex", ...)` as a straight substitution, so a migrating caller that passed the key got `invalid_arguments` on an argument the table said would carry over (issue #66).

The guarantee lost was the valuable one.
Dedup exists so that a retry racing a completed run does not pay twice, and a sync call is where a client-side retry happens: a host deadline, a dropped connection, a re-issued tool call.
The async path already hands back a job id to poll, so it needs dedup least.

ADR 0008 recorded the restriction as "ADR 0007, deviation 8".
ADR 0007 contains no such decision; the restriction was M2 sequencing, and it bought one simplification, which ADR 0011 then relied on: a tasked call was always unkeyed, so `tasks/cancel` could always cancel the job.
A Codex consult on this issue (2026-09-12) reached the same conclusion independently and found no other rationale in the tree.

## Decision

**Every paid tool takes `idempotency_key`.**
`ASYNC_ONLY_PARAMS` is empty and stays as the named half of the split, so the pair-parity test and `expected_params` read as before.
The key is `minLength: 1` on every tool, as it is on both siblings: an empty string is not a dedup identity.
Sync and `_async` remain separate identities, keyed by tool name in the workspace index, so a key never replays across the pair.

**A keyed sync call awaits the run the key names, its own or another caller's.**
A first reservation spawns and awaits its own job.
A duplicate awaits the existing job for that key and arguments and delivers whatever it delivers, stamped `meta.idempotency_replayed: true`: a stored success, a stored error, or the terminal error for a cancelled or failed run, exactly what `amicus_job_result` would report.
`conflict` and `unavailable` are their envelopes.
A transient outcome (`in_progress`, `io_error`, an outcome this release does not know) is re-asked for about a second at a 50 ms interval before it is surfaced, because publication is normally sub-second and a momentary blip self-heals into a clean replay; the `_async` twin never waits.
A replayed job whose record vanishes before its result is read is `idempotency_result_unavailable`, the code an already-evicted key gets from a keyed async start; a job this call spawned that vanishes stays `internal_error`.

**A keyed waiter does not own the job.**
Unkeyed, a sync call cancels its job when its local grace deadline passes and when the caller cancels, including a cancellation that lands while the task id is being recorded.
Keyed, it does none of that: another idempotent caller may be awaiting the same run.
On the deadline it returns `timeout` with `repair.next_step: poll_job_status` naming `amicus_job_status` for that job and echoing the record's `poll_after_ms`, and its `alternative` says not to switch to the async twin or drop the key, because either starts a second paid run under a different dedup identity while this one completes unobserved.
Only `amicus_job_cancel` stops a keyed run.

**Task cancellation follows ownership.**
ADR 0011 decision 2 said a tasked call is always unkeyed, so `tasks/cancel` always cancels the job.
It now reads: an unkeyed tasked call's job is cancelled with its task; a keyed tasked call's job survives, and is recovered through `amicus_job_list(task_id=...)` or by replaying the key.
This is ADR 0004's original clause, which M5 could not build because the sync tools carried no key.

**A job named by several tasks reports the task that created it.**
A keyed replay from a second tasked call records a second forward association, so a list filtered by either task finds the job.
`TaskJobMap.task_for` already returned the first association in insertion order; `amicus_job_list` built its reverse map with a comprehension that kept the last, so the same job would have carried one task on `amicus_job_status` and `amicus_job_result` and another on the list.
Every surface now reports the first association, and `meta.task_id` on a delivered envelope is the task delivering it.
Exposing every associated task was declined: `task_id` stays singular, and a caller that needs the association it made has it, because it made it.

**The identity is the effective execution arguments, and the contract says which.**
`timeout_seconds` is in `RunSpec` and therefore in the hash, and on a sync call it is also the job's deadline, so a retry with a different timeout is a `conflict` rather than a silent change to a running job.
`detail` is not in `RunSpec`: it only shapes delivery and may differ on a replay.
The `amicus://params` text names both.

## Consequences

`FINGERPRINT` moves to `schema-18`: four input schemas gain a property, every `idempotency_key` property gains `minLength`, the `timeout_seconds` description and the server instructions qualify "terminated" and "cancelling a task cancels its job", the sync tools' error catalogs name the three dedup codes, the task-support fallback text carries the exception, and the `idempotency_key` contract at `amicus://params` describes the sync path.
`RESULT_FORMAT` stays 5: no stored result shape moves.
The `tools/list` wire grows by 1532 bytes on the `all` profile, mostly the four new copies of the parameter summary; `tests/test_discovery_cost.py` records the raise.
`docs/MIGRATION.md`'s mapping table is now true for a caller that passed the key, and its "Behavior deltas" names the two places a keyed sync call differs from the siblings': the one-second transient wait, and the task-cancellation exception, which the siblings never had because they had no tasks.
