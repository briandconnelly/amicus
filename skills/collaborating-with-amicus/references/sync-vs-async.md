# Sync vs async

Every paid verb (`amicus_consult`, `amicus_review_changes`, `amicus_delegate`,
`amicus_adversarial_review`) has an `_async` twin. Both spend quota; the difference is when and how
you get the result back.

## Rules

- **Prefer the `_async` twin whenever you are unsure the work finishes inside the sync deadline.**
- **Never start both the sync and the `_async` form of the same work.**
- **Wait at least the returned `poll_after_ms` before each `amicus_job_status` call.**
- **Poll only while `status == "running"`.** On any terminal status, stop polling and fetch.
- **Fetch a completed result promptly**; the job store is not long-term storage.
- **Prefer `amicus_job_result` to `amicus_job_consume_result`** unless deletion is intended.
- **Recover an existing job before repeating paid work** — `amicus_job_list`, or an
  `idempotency_key` replay ([options and errors](options-and-errors.md)).

## The deadline

A synchronous call runs to a bounded deadline (`timeout_seconds`, default 300s). If the backend
has not finished by then the call is terminated and you receive nothing — the work it had already
done is unrecoverable. An `_async` call returns a job handle immediately and the backend keeps
running against a separate, longer job deadline (`AMICUS_JOB_MAX_SECONDS`, default 1800s).
Starting the job commits the spend right away, even if you never poll.

Prefer `_async` for:

- a high-reasoning-effort or broad repo-grounded consult
- a multi-file or whole-branch review
- any delegate task (implementation work is usually the slowest of the four verbs)

What a terminated sync call costs at the provider is not reported to amicus, so nothing here
claims it equals a completed call's cost. The reason to prefer `_async` under uncertainty is that
a sync timeout destroys the result you paid for.

## What `_async` returns

A job handle: `job_id`, `poll_after_ms`, `expires_at`, and a `follow_up` pointer. It is not the
consult/review/delegate result.

## Polling

1. Call the matching `_async` tool once and keep its `job_id`.
2. Wait at least the returned `poll_after_ms`, then call `amicus_job_status` with the same
   `job_id` and the same absolute `workspace_root`.
3. **While `status` is `running`**, honor each new `poll_after_ms` and poll again.
4. **Once `status` is terminal** — `done`, `failed`, `cancelled`, or `timeout` — stop polling and
   branch:
   - `done` with `result_available: true` → fetch it.
   - any other terminal status → there is no result to wait for. `amicus_job_result` returns the
     terminal error (`job_cancelled`, `job_failed`, …); read `error.code` and `error.repair`.
5. Branch on the *fetched envelope's* own `ok`. A `done` job can hold a stored error
   (`result_ok: false`) — see [reading results](reading-results.md).

**`poll_after_ms` is `null` on every terminal status.** A loop written as "repeat until
`result_available` is true" therefore never terminates for a cancelled, failed, or timed-out job:
the flag stays false and there is no interval left to honor. Drive the loop from `status`.

`amicus_job_cancel` stops a running job (SIGTERM, then SIGKILL) and cleans up its worktree;
calling it on an already-terminal job is a no-op that returns the job unchanged. A cancelled job
reports `result_available: false`.

## Recovering a lost job

`amicus_job_list` narrows by `backend`, `status`, or `task_id`. A job started under MCP task
support (where the host tracks a `task_id` rather than the raw tool response) is recoverable via
`amicus_job_list(task_id=...)` even if you never captured `job_id`.

Job records expire after `AMICUS_JOB_TTL` (default 24h), and a per-workspace cap evicts the oldest
terminal records first. An `amicus_job_list` result carries its own `truncated` and
`truncation_hint` when the listing itself was cut.
