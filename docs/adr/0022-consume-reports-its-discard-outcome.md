# ADR 0022: A consume reports its discard outcome as delivery-only metadata

**Status:** Accepted (2026-09-13); amended 2026-09-14 for issue #94, 2026-09-24 for issues #124 and #125, and 2026-09-24 for issue #126

## Context

Issue #44, from the 2026-09-09 agent-friendliness audit, found that `amicus_job_consume_result` delivered the stored envelope when deleting the record failed, and reported plain success.
Its description promised, unconditionally, that a repeat call returns `job_not_found`.
The checklist's `[3.dispatched-vs-applied]` requires the structured result to carry the confirmation status and a `follow_up` naming the reconciliation surface.
Delivering the result on a failed delete stays right, because refusing would lose paid work; the defect was that the outcome was invisible.
A Codex consult on this issue (2026-09-13) corrected the first design three ways, and each correction is recorded below.
A probe then found a real failed delete worse than the audit described.
When the job directory's `rmdir` fails, pontonier has already unlinked `result.json` and restores only `meta.json`, which the store then reads as `failed`.
A repeat consume of that record returns `job_failed` and deletes nothing.

## Decision

**The outcome rides `meta.consume`, not the envelope's top level.**
A delivered success is the originating paid tool's closed envelope, and `amicus_job_result`'s schema promises that it matches that tool's advertised success branch.
`Meta` is shared by success and error envelopes, and a consume delivers both.
`Meta` is published once at `amicus://result-meta`, so the field costs `tools/list` nothing.

**`discard_outcome` is the store's own four-valued outcome.**
Its values are the store's `DiscardOutcome` verbatim (`removed`, `missing`, `state_changed`, `delete_failed`), and a test fails if the two sets drift.
They were pontonier's until issue #126 renamed `not_done` to `state_changed`, below.
The first design was a `record_deleted` boolean.
Codex held that it would credit a `missing` record's absence to this call, and overstate what `delete_failed` proves, since that outcome also covers a deletion that could not be verified.
Only `removed` and `missing` support the repeat-call `job_not_found` promise, and the description now says so.
`missing` means the store no longer serves the record, not that its files are gone.
Codex's review of the branch found that a record expiring between the read and the discard is cleaned up inside the discard, and that cleanup ignored its own failure before the discard reported `MISSING`.
Since issue #125 a failed expiry cleanup is reported as `delete_failed`, because its files remain.
The follow-up's call then returns `job_not_found`, because an expired record is dropped on every read, and a test pins that path.
The `missing` description and the follow-up's `job_not_found` branch still say "no longer serves", because a delete whose restore also fails can leave a directory that holds no readable record.

**A record that may remain gets a `follow_up` that inspects it.**
For `state_changed` and `delete_failed`, `follow_up` is `{next_step: "inspect_and_retry", tool: "amicus_job_status", arguments: {job_id, workspace_root}}`, with `workspace_root` only when the caller supplied it.
Its `arguments` are a closed object that requires `job_id`, so the published schema admits only a call `amicus_job_status` accepts.
It is the `Repair` shape narrowed to that one action, as `JobFollowUp` narrows it for an async start.
The first design pointed at `amicus_job_list`; Codex preferred the tool that addresses this job, since `amicus_job_list` is the surface for recovering a lost id.
`next_step` stays in pontonier's vocabulary, as ADR 0005 requires, and echoing `job_id` and a caller's `workspace_root` follows the `job_running` and `job_not_found` repairs.
Its `alternative` promises neither redelivery nor deletion at expiry.
The store has no reaper daemon, so an expired record goes only when a later job call finds it.
A failed delete leaves the record as it was, but one whose restore also fails can leave a record that reads as `failed`.

**The field is delivery-only, so `RESULT_FORMAT` stays 5.**
`Meta.consume` is excluded from every dump, and `attach_consume_disposition` sets it on the delivered dictionary after the discard.
An ordinary delivery scrubs any stored copy, because strict validation returns the stored dictionary itself.
Persisting the field was not an option: `dump_success` keeps null optionals, and a probe showed that a format-5 reader rejects a record whose `meta` carries one extra null key as `internal_error`, not `job_result_incompatible`.
Bumping `RESULT_FORMAT` instead would have made every retained format-5 record unreadable, for a field no stored record needs.
Excluding the field only in `dump_success` was rejected on Codex's advice, since several results dump `Meta` directly.

**A terminal-error job is discarded in the state the consume read (#126).**
Issue #94 found that every consume surface said `meta.consume.discard_outcome` reports what the store did, while a consume of a `failed`, `cancelled` or `timeout` job attached no `meta.consume` and deleted nothing.
Such a job has no stored envelope, so `finished_job_envelope` builds its terminal error and reports it undelivered.
Under #94 a consume then returned that error without calling the store's discard, and every surface named the case.
Calling the discard anyway was not safe for `failed`.
The store stamps `cancelled` and `timeout` into the record, but it derives `failed` on every read without stamping it, so a record read as `failed` turns `done` if its `result.json` appears later.
The discard re-read the state under the store's lock and deleted only a `done` record, so a discard after that flip would have deleted a result this call never delivered.

Issue #126 made the store's discard a compare-and-delete: it takes the terminal state the caller read, `done` by default, and deletes the record only if a fresh read still finds it in that state.
Because `failed` is derived rather than stamped, the discard also requires it to be final: it deletes a `failed` record only once the worker is verifiably gone.
A worker that is gone never writes `result.json`, so the record can no longer turn `done`.
For a job this process started, the proof is that its child has exited.
For any other job, the proof is a `worker.lock` that exists and is free and a PID that is no longer alive.
A free lock alone is not proof: every liveness probe briefly takes the lock, and a worker whose own attempt collided with one used to give up and run without it.
The worker now retries its lock for up to two seconds, and the PID check covers a worker that still ran unlocked.
Both checks err only toward keeping a record, since a reused PID reads as alive.
A PID that is not a positive integer proves nothing, since `meta.json` is not validated on read, so such a record is kept.
The discard proves the worker gone before it reads the state a second time, and deletes only if that read is still `failed`.
The first read alone is not enough, because a worker running without its lock can write `result.json` and exit between that read and the proof, and only once the worker is gone can no result appear.
An unowned record with no lock file reads as `failed` but its worker may still run, so the discard keeps it.
Such a record returns `state_changed` on every retry, so it stays until it expires or is evicted.
The first design held the job's `worker.lock` through the read and the delete instead.
It was dropped before review, because a held lock is how every reader, in any process, tells a live worker from a reused PID.
Another server process sharing the state root would then have read a dead, overdue job as running and signalled its PID, which may belong to an unrelated process by then.
A consume now discards a terminal-error record in the state it read and attaches `meta.consume` as it does for a delivered envelope, so a repeat call returns `job_not_found` after `removed` or `missing`.
A done record whose stored result does not read back is still described, not delivered, and is kept.
A mismatch, or a `failed` record not yet final, is `state_changed`, which replaced `not_done`, because a consume that read `failed` can now find the record `done`, and a record that became `done` is not "not done".
Its `follow_up` is the same inspection call, and the `alternative` says that a retried consume returns what the record now holds and deletes it only if it can.
It names the two records a retry never deletes, and says to stop retrying them: a `failed` one the store cannot prove final, and a `done` one whose result does not read back.
A consume can also land while a cancel waits, unlocked, for the worker to exit.
If the worker exits without a result, the consume reads `failed`, the worker is provably gone, and the record is deleted before the cancel can stamp `cancelled`; the cancel then returns `job_not_found`.
No result is lost, because none existed, so this is accepted.
The one-caller-wins guarantee stays process-local, as it was for a `done` record, because the store's lock serializes only threads in one process; issue #237 tracks the related cross-process window during a delete.

## Consequences

- `FINGERPRINT` moves to `schema-21`.
  The result-format snapshot's persisted section is byte-identical, and only its schema view moved.
- The #94 amendment moves `FINGERPRINT` to `schema-30` for the corrected descriptions.
  Behavior and `RESULT_FORMAT` are unchanged.
- The #126 amendment moves `FINGERPRINT` to `schema-43`, for the renamed outcome and the consume descriptions.
  It is a breaking change: a consume now deletes a terminal-error record, and a caller that branched on `not_done` must branch on `state_changed`.
  `RESULT_FORMAT` does not move, because `meta.consume` is never stored and the result-format snapshot's persisted section is byte-identical.
- A future delivery-only `Meta` field should follow the same pattern: excluded from every dump, set on the delivered dictionary, and scrubbed from a stored copy.
- Pontonier's `_rmtree` comment said a partial failure leaves the record fully readable.
  It did not once `result.json` had been unlinked, and the leftover record then reported the job as `failed`.
  Expired-record cleanup in `_read_live_job` likewise returned "no record" after a failed `_rmtree`, which is how `missing` could leave files behind.
  The store has been amicus's own since ADR 0030, and issues #124 and #125 fixed both.
  `_rmtree` now unlinks `result.json` and `meta.json` after every other entry, and restores both when either unlink or the final `rmdir` fails, marker first, never the result without its marker.
  A discard whose expiry cleanup fails reports `delete_failed`.
  No description had to change, because each already hedged for the worse behavior, so `FINGERPRINT` did not move; `RESULT_FORMAT` did not either, because `meta.consume` is never stored.
  Pontonier's copy keeps both defects, and the #126 compare-and-delete is amicus's alone too; carrying either there is the maintainer's call under rule 17.
