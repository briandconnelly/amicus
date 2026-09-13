# Sync vs async

Every paid verb (`amicus_consult`, `amicus_review_changes`, `amicus_delegate`,
`amicus_adversarial_review`) has an `_async` twin. Both spend quota; the difference is when and how
you get the result back.

## Rules

Every obligation this file depends on is stated in SKILL.md → Binding rules — the `_async`
preference and job recovery under Spend, and polling, fetching and `amicus_job_result` under Jobs.
That is their authoritative home; this file adds none of its own, and explains how to carry them
out.

## The deadline

An unkeyed synchronous call runs to a bounded deadline (`timeout_seconds`, default 300s, at most
600s). If the backend has not finished by then the call is terminated and you receive nothing —
the work it had already done is unrecoverable. An `_async` call returns a job handle immediately
and the backend keeps running against a separate, longer job deadline (`AMICUS_JOB_MAX_SECONDS`,
default 1800s). Starting the job commits the spend right away, even if you never poll.

The default leaves a review little margin. A review of a few hundred lines at the default effort
has been reported to take two to four minutes on `codex` (issue #84): inside the 300s default,
but close enough that a slower draw is lost with it. For an unkeyed sync review of more than a
small diff, raise `timeout_seconds` toward its ceiling, or use a form that keeps the result.

Prefer `_async`, or a sync call with an `idempotency_key`, for:

- a high-reasoning-effort or broad repo-grounded consult
- a multi-file or whole-branch review
- any delegate task (implementation work is usually the slowest of the four verbs)

What a terminated sync call costs at the provider is not reported to amicus, so nothing here
claims it equals a completed call's cost. The reason to prefer `_async` under uncertainty is that
an unkeyed sync timeout destroys the result you paid for.

A sync call made with an `idempotency_key` is the exception. Its run gets the job deadline
(`AMICUS_JOB_MAX_SECONDS`), as an `_async` run does, and `timeout_seconds` only bounds the wait:
at that bound the call returns `timeout` with a `poll_job_status` repair for the job, which keeps
going, and repeating the same keyed call reattaches to it without new spend. Starting the `_async`
twin or dropping the key there is a second paid run; the Spend rules in SKILL.md say what to do
with that repair. This is the one way to wait for a long run inside a single call. Sync and
`_async` are separate identities (ADR 0020), so a keyed sync call cannot wait on a job you
started with the `_async` twin.

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

`poll_after_ms` grows with elapsed time — roughly "wait as long as the job has already run" —
but only up to `10 s`, the job library's ceiling. A job that runs for minutes is therefore polled
every ten seconds for almost its whole life: a two-to-four-minute review costs roughly 15–30
status calls. A hint that stops growing is the ceiling, not a stalled job. If that many polls is too
many, the keyed sync form above waits inside one call instead.

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
