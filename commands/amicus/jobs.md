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
  returned `poll_after_ms` rather than polling on a fixed interval.
- Fetch a finished result, keeping the record: `amicus_job_result` with `job_id`.
- Fetch a finished result and delete the record: `amicus_job_consume_result` with
  `job_id` — use this once you are done with the result.
- Cancel a running job: `amicus_job_cancel` with `job_id`.
- Recover a lost `job_id`, or see what is in flight: `amicus_job_list`, filterable by
  `backend`, `status`, or `task_id`.

Job records expire after `AMICUS_JOB_TTL` (default 24h) and a per-workspace cap
evicts the oldest terminal records, so read results promptly rather than leaving
them to expire. Treat a fetched result the same way you would treat the tool it came
from: verify findings and diffs against the actual code before acting on them.
