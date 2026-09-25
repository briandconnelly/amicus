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
The prose states the spend, names the four `_async` twins, and gates polling on `status` as the `job_running` repair does.

**The repair names the verb's `_async` twin and carries no arguments.**
`repair.tool` is set where the verb is known: the sync await in `jobs.lifecycle` and `errors.render_failure`, which now takes the run's `kind`.
The arguments would echo prompt inputs (rule 18), and ADR 0021 already accepts a repair that names a tool without arguments when the correction is not unique; the prose says the arguments are the caller's own.

**A backend-classified CLI timeout is the same condition.**
The worker applies the caller's `timeout_seconds` to the backend subprocess, so the classifier's `timeout` is the one that fires in practice, and it takes the same rule.
Codex's capture-failed timeout is the one exception: its hint says to retry the same call once, so it sets `retryable: true` itself, and on that one repair no `_async` tool is named, because its hint prescribes retrying the same call.

**A keyed sync wait's timeout stays temporary.**
ADR 0020 already made it so whatever the backend's rule said; the run continues and the repair polls it.

## Consequences

- `error.temporary` on `timeout` changes from `true` to `false` for codex and kimi, and `retry_after_ms` is always null: **Breaking** in the CHANGELOG sense, since a value a caller read has changed meaning.
- The codex and kimi result differentials record the deviation from the siblings' `temporary: true`.
- `FINGERPRINT` moves (with #246, to `schema-45`); `RESULT_FORMAT` stays 9.
- The design spec's "timeout is not retryable for Claude" now reads "never temporary".
