# ADR 0022: A consume reports its discard outcome as delivery-only metadata

**Status:** Accepted (2026-09-13); amended 2026-09-14 for issue #94

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
Its values are pontonier's `DiscardOutcome` verbatim (`removed`, `missing`, `not_done`, `delete_failed`), and a test fails if the two sets drift.
The first design was a `record_deleted` boolean.
Codex held that it would credit a `missing` record's absence to this call, and overstate what `delete_failed` proves, since that outcome also covers a deletion that could not be verified.
Only `removed` and `missing` support the repeat-call `job_not_found` promise, and the description now says so.
`missing` means the store no longer serves the record, not that its files are gone.
Codex's review of the branch found that a record expiring between the read and the discard is cleaned up inside the discard, and that cleanup ignores its own failure before the discard reports `MISSING`.
A repeat call still returns `job_not_found`, because an expired record is dropped on every read, so the promise holds while physical deletion does not.
The `missing` description and the follow-up's `job_not_found` branch say "no longer serves", and a test pins that path.

**A record that may remain gets a `follow_up` that inspects it.**
For `not_done` and `delete_failed`, `follow_up` is `{next_step: "inspect_and_retry", tool: "amicus_job_status", arguments: {job_id, workspace_root}}`, with `workspace_root` only when the caller supplied it.
Its `arguments` are a closed object that requires `job_id`, so the published schema admits only a call `amicus_job_status` accepts.
It is the `Repair` shape narrowed to that one action, as `JobFollowUp` narrows it for an async start.
The first design pointed at `amicus_job_list`; Codex preferred the tool that addresses this job, since `amicus_job_list` is the surface for recovering a lost id.
`next_step` stays in pontonier's vocabulary, as ADR 0005 requires, and echoing `job_id` and a caller's `workspace_root` follows the `job_running` and `job_not_found` repairs.
Its `alternative` promises neither redelivery nor deletion at expiry.
Pontonier has no reaper daemon, so an expired record goes only when a later job call finds it, and a real failed delete can leave a record that reads as `failed`.

**The field is delivery-only, so `RESULT_FORMAT` stays 5.**
`Meta.consume` is excluded from every dump, and `attach_consume_disposition` sets it on the delivered dictionary after the discard.
An ordinary delivery scrubs any stored copy, because strict validation returns the stored dictionary itself.
Persisting the field was not an option: `dump_success` keeps null optionals, and a probe showed that a format-5 reader rejects a record whose `meta` carries one extra null key as `internal_error`, not `job_result_incompatible`.
Bumping `RESULT_FORMAT` instead would have made every retained format-5 record unreadable, for a field no stored record needs.
Excluding the field only in `dump_success` was rejected on Codex's advice, since several results dump `Meta` directly.

**A terminal-error job is described, not delivered, so a consume attempts no discard.**
Issue #94 found that every consume surface said `meta.consume.discard_outcome` reports what the store did, while a consume of a `failed`, `cancelled` or `timeout` job attached no `meta.consume` and deleted nothing.
Such a job has no stored envelope, so `finished_job_envelope` builds its terminal error and reports it undelivered, and a consume returns that error without calling the store's discard.
The behavior stays, every surface now names the case, and a test pins all three states end to end, including that no discard is attempted.
Reporting the case as `not_done` by calling the store's discard anyway was rejected, because that call is not safe for `failed`.
Pontonier stamps `cancelled` and `timeout` into the record, but it derives `failed` on every read without stamping it, so a record read as `failed` turns `done` if its `result.json` appears later.
The discard re-reads the state under the store's lock, so a discard after that flip would delete a result this call never delivered.
No public store call lets amicus delete a terminal-error record on request: pontonier's discard returns `NOT_DONE` for any record that is not `done`, and the store has no other public delete.
Such a record goes when it expires or the per-workspace cap evicts it, or through an ordinary consume if a `failed` one turns `done` first.
A safe deletion needs an atomic compare-and-delete from pontonier, requested as briandconnelly/pontonier#31.

## Consequences

- `FINGERPRINT` moves to `schema-21`.
  The result-format snapshot's persisted section is byte-identical, and only its schema view moved.
- The #94 amendment moves `FINGERPRINT` to `schema-30` for the corrected descriptions.
  Behavior and `RESULT_FORMAT` are unchanged.
- A future delivery-only `Meta` field should follow the same pattern: excluded from every dump, set on the delivered dictionary, and scrubbed from a stored copy.
- Pontonier's `_rmtree` comment says a partial failure leaves the record fully readable.
  It does not once `result.json` has been unlinked, and the leftover record then reports the job as `failed`.
  Expired-record cleanup in `_read_live_job` likewise returns "no record" after a failed `_rmtree`, which is how `missing` can leave files behind.
  Both are pontonier's to fix, since rule 17 forbids editing the sibling here, so the prose in this ADR and on the wire describes the behavior as it is.
