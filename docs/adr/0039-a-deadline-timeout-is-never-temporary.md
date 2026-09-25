# ADR 0039: a deadline timeout is never temporary

**Status:** Accepted (2026-09-24)

Amends [ADR 0010](0010-m4-claude-port-decisions.md), whose Claude-only timeout override this makes the rule for every backend.

## Context

When a sync paid call on codex or kimi passed its deadline, the `timeout` envelope said `temporary: true` with `next_step: "retry_after_delay"`, while its own prose said the same synchronous call would likely time out again (#245).
`temporary` means the identical call may succeed later; here the identical call is a sync call that spends again and hits the same deadline.
Claude's plugin already overrode the rule to `temporary: false`, `next_step: "start_new_job"`, because a Claude timeout may already have been charged.
So one condition had two contracts, chosen by `backend`, and an agent that branched on the machine field rather than the prose burned quota in a loop.

## Decision

**The `timeout` rule is amicus-wide: `temporary: false`, `next_step: "start_new_job"`, one prose text.**
It lives in `amicus.errors._LOCAL_RULES`, above the SDK default; Claude's `repair_overrides` entry and its classifier's own `RepairHint` are gone, and the classifier keeps `retryable: false` and its detail about a possibly charged run.
A plugin cannot override it: `repair_table` re-applies it after a plugin's `local_codes` and `repair_overrides`, so only a single failure's own `retryable` or repair, applied in `render_failure`, changes that failure's envelope.
The prose states the spend, names the four `_async` twins, and gates polling on `status` as the `job_running` repair does.

**On a sync run, the repair names the verb's `_async` twin and carries no arguments.**
`repair.tool` is set where the verb is known: the sync await in `jobs.lifecycle` and `errors.render_failure`, which now takes the run's `kind` and whether it is a background run.
The arguments would echo prompt inputs (rule 18), and ADR 0021 already accepts a repair that names a tool without arguments when the correction is not unique; the prose says the arguments are the caller's own.

**A backend-classified CLI timeout is the same condition.**
On an unkeyed sync call the worker applies the caller's `timeout_seconds` to the backend subprocess, so there the classifier's `timeout` is the one that fires in practice, and it takes the same rule.
Codex's capture-failed timeout is the one exception: its hint says to retry the same call once, so it sets `retryable: true` itself, and on that one repair no `_async` tool is named, because its hint prescribes retrying the same call.

**A background run's timeout names no tool.**
A background run, an `_async` job or a keyed sync call, gives the backend subprocess `AMICUS_JOB_MAX_SECONDS` (default 1800s) rather than the caller's wait, so its `_async` twin is the run that already timed out.
Its `timeout` keeps `temporary: false` and `next_step: "start_new_job"`, names no `repair.tool`, and carries its own prose, which names that deadline, says the same call, sync or `_async`, will likely time out again and that any next attempt is a new paid run, and suggests narrowing the task or having the operator raise `AMICUS_JOB_MAX_SECONDS`.
`RunSpec.background` carries the fact to `render_failure`; it is not a prompt input, it stays out of the idempotency identity so a keyed record written before it existed still replays, and a record that lacks it loads as `False`.
The same condition on a background run can instead surface as `job_timeout`, depending on when the job is polled: the job store's deadline starts when the job is recorded, before the subprocess's own, and a poll past it reaps the job.
That is a separate code, which this ADR leaves unchanged.

**A keyed sync wait's timeout stays temporary.**
ADR 0020 already made it so whatever the backend's rule said; the run continues and the repair polls it.

## Consequences

- `error.temporary` on `timeout` changes from `true` to `false` for codex and kimi, and `retry_after_ms` is always null: **Breaking** in the CHANGELOG sense, since a value a caller read has changed meaning.
- The codex and kimi result differentials record the deviation from the siblings' `temporary: true`.
- `FINGERPRINT` moves (with #246, to `schema-45`); `RESULT_FORMAT` stays 9.
- The design spec's "timeout is not retryable for Claude" now reads "never temporary".
