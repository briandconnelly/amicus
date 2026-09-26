---
description: Poll, fetch, list, or cancel a background amicus job
argument-hint: "status|result|consume|cancel|list [job_id]"
---

Manage background jobs started by an `_async` amicus tool (`amicus_consult_async`,
`amicus_review_changes_async`, `amicus_delegate_async`,
`amicus_adversarial_review_async`). All five job tools here are free — none spends
quota on their own.

Request: $ARGUMENTS

- Poll without fetching the result: `amicus_job_status` with `job_id`. Honor the
  returned `poll_after_ms` rather than polling on a fixed interval, or pass
  `wait_seconds` (up to 50) to wait inside the call: it returns when the job is terminal
  or when the wait runs out, and then `status` is still `running`. Never read or watch
  amicus's job store directly.
- Fetch a finished result, keeping the record: `amicus_job_result` with `job_id`, once
  `amicus_job_status` reports any status but `running`. Do not wait on
  `result_available` for this: it is true only for `done`, so a job that failed, was
  cancelled or timed out never sets it, and `amicus_job_result` returns that job's
  terminal error instead.
- Fetch a finished result and delete the record: `amicus_job_consume_result` with
  `job_id` — use this once you are done with the result. Its
  `meta.consume.discard_outcome` reports what the store did: after `removed` or
  `missing` it no longer serves the record, so a repeat call returns `job_not_found`;
  after `state_changed` or `delete_failed` the record may remain, and
  `meta.consume.follow_up` names the call that shows what is left. A failed,
  cancelled or timed-out job returns its terminal error, and `meta.consume` reports
  its discard too.
- Cancel a running job: `amicus_job_cancel` with `job_id`.
- Recover a lost `job_id`, or see what is in flight: `amicus_job_list`, filterable by
  `backend`, `status`, or `task_id`.

Job records expire after `AMICUS_JOB_TTL` (default 24h), so read results promptly
rather than leaving them to expire. A per-workspace cap evicts the oldest terminal
records but never a result amicus has tracked and not yet returned (records written
before delivery tracking are evictable); when unfetched results and running jobs fill
it, a new paid call is refused with `job_cap_reached` until you fetch, consume or cancel
one, or, for a result another amicus release wrote, until that release fetches it or it
expires. Treat a fetched result the same way you would treat the tool it came
from: verify findings and diffs against the actual code before acting on them.
