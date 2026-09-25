# ADR 0038: the job cap never evicts an unreturned result

**Status:** Accepted (2026-09-24)

## Context

Every paid call, sync or async, is recorded as a job, and the job store keeps at most `AMICUS_JOB_MAX_COUNT` records per workspace (50 by default).
Until this decision, recording a new job evicted the oldest terminal records past that cap, whether or not anyone had fetched their results (#244).
A new paid call could therefore delete a finished, paid-for result the caller had not read yet, and a later `amicus_job_result` returned `job_not_found`, which looks the same as a mistyped id.

In the codex and kimi profile the paid tools also advertise `destructiveHint: false`, and `amicus_capabilities.annotations_reading` justified that without naming eviction.
ADR 0001 annotates for the worst enabled backend; it never said a paid call may remove state a caller still needs.

The issue offered two ways out: make the hint true in fact, or flip every paid tool to `destructiveHint: true`.
Flipping the hint would have kept the loss and only disclosed it, and would have raised a host approval prompt on every paid call in a profile whose backends write nothing outside a throwaway worktree.

## Decision

**The cap evicts only what nobody still needs from amicus.**
It may remove an expired record, a terminal error (`failed`, `cancelled`, `timeout`), a `done` result amicus has already returned once, and a record written before delivery tracking existed.
It never removes a running job, or a tracked `done` result that has not been returned, whatever its result format.

**A full cap refuses the new call before anything is spent.**
The check runs before the worker spawns: it reaps expired records, evicts what it may oldest first, and raises `JobCapReached` when the workspace still holds `AMICUS_JOB_MAX_COUNT` records.
The tool returns `job_cap_reached`, temporary with no `retry_after_ms`, because the room comes from the caller's own next step rather than from time: fetch or consume a result, or cancel a running job.
Its repair lists the workspace's jobs with `amicus_job_list`, and says that a result another release wrote, which this server reports as `job_result_incompatible` and a consume keeps, is fetched by a server of that release or expires after `AMICUS_JOB_TTL`.
Running jobs count toward the cap, so within one server process the cap bounds how many records a workspace holds, where running jobs used to overshoot it; across processes it is bounded as the last decision below says.
A refused keyed call leaves its idempotency key unreserved, so the same key works once there is room.

**"Returned once" is recorded by the server, not acknowledged by the client.**
A record carries `delivered_epoch`, `null` until amicus validates its stored result and hands it back, from `amicus_job_result`, `amicus_job_consume_result` or the sync tool that awaited it.
A status read, a list, a keyed wait that timed out, and a stored result that failed validation never stamp it.
A sync response lost in transport after the stamp is therefore evictable, as it was before; the prose says "returned", never "received".
A record without the key predates this decision and is evicted as before, so an upgrade cannot fill a workspace with protected records until their TTL runs out.

**Servers of different releases can share a state root.**
The store never reads a record's result format, because the release that wrote a result can still deliver it from a server sharing the root, whether it is older or newer than the one enforcing the cap.
This is the rule `amicus_job_consume_result` already follows: it keeps a result it cannot read rather than delete one another release could deliver (#126).
The cost is that unfetched results in a format no running server reads hold their slots until `AMICUS_JOB_TTL` expires them.
A release from before this decision still evicts by age alone, and the records it writes carry no delivery stamp, so they are evicted as before; that is unchanged, and it ends when the old server is upgraded.

**The store alone enforces it, under the process lock.**
`_LOCK` is process-local, so server processes sharing a state root can each pass the check at once and overshoot the cap by one start per process.
An overshoot deletes nothing, which is the property the annotation needs.

## Consequences

`destructiveHint: false` on the paid tools in the codex and kimi profile now holds for the job store: a paid call never deletes a tracked result amicus has not yet returned.
`annotations_reading`, the paid tools' retention sentence, the `amicus_job_*` retention sentence and the server instructions say so.
`job_cap_reached` is a new amicus-local error code, so `FINGERPRINT` moves.
`RESULT_FORMAT` does not: the code is refused before a job record exists, so no stored `result.json` can carry it.
An agent that starts many jobs and never fetches them now meets a refusal where it used to lose results silently.
