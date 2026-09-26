# ADR 0046: a keyed run's stored error is never temporary

**Status:** Accepted (2026-09-26)

Generalizes the keyed-timeout rule of [ADR 0039](0039-a-deadline-timeout-is-never-temporary.md) to every code, and leaves the replay contract of [ADR 0020](0020-idempotency-keys-on-the-sync-tools.md) as it is.

## Context

A keyed paid call records its run as a job, and the same call under the same key replays that job's stored outcome without running again, whatever the outcome was (ADR 0020).
`temporary` means that re-issuing the identical call may succeed later (`RepairRule` in `amicus.sdk.conventions.envelope`).
So a keyed run that ended in a temporary error, such as `backend_rate_limited`, `nonzero_exit`, `internal_error`, `invalid_json` or `schema_violation`, invited a retry that could only replay the same error until the job record expired or was consumed (#254).
ADR 0039 had fixed one case of this, codex's capture-failed `timeout`, inside `render_failure`, which leaves every error built by `error_envelope` rather than `render_failure`, and every other backend-classified code, unfixed.

Three remedies were weighed.
Keeping `temporary: true` and naming a new key in the repair contradicts the definition of `temporary`, which is about the identical call.
Not replaying a stored error under its key would let a keyed duplicate spend twice, which is the one thing ADR 0020 promises it never does.
Changing the stored error keeps both contracts.

## Decision

**Every error a keyed run stores is stored as `temporary: false`.**
The job worker writes a run's outcome to `result.json` in one place, and a keyed run's outcome goes through `errors.keyed_stored_error` there, whatever built it.
That covers `render_failure`, every `error_envelope` inside the run, a worker crash and a backend that failed to load.
The worker reads `keyed` and `tool` from `spec.json` directly, so a keyed job whose inputs fail to load is covered too.
`render_failure` no longer takes `keyed`: the rule has one home.

**The error keeps its code and message; its repair is rewritten for the caller who holds the key.**
Its prose leads with `KEYED_REPLAY_NOTE`, which says that the same key replays this error and that any retry needs a new `idempotency_key`.
A `retry_after_delay` step names the same call, so it becomes `use_new_idempotency_key` on the tool that ran, with no arguments, since they would echo prompt inputs (rule 18).
Any other step already names a different action and is kept.
`retry_after_ms` must be null on a non-temporary error, so a delay the backend asked for moves into the prose, which says that a new key does not shorten it.

**What is not stored is not changed.**
A keyed sync wait that hits its own bound returns a temporary `timeout` whose run is still going (ADR 0020); it is never stored, and the same keyed call does reattach to that run.
The idempotency errors (`idempotency_in_progress`, the transient index read) are returned before or beside a job, not stored as its outcome, and their same-key retry does work.
An error amicus builds when it cannot read a stored result back is built at delivery, after the worker's write, and is outside this rule.
Its own rule reaches the same place for the one case that could mislead: a result stored under this release's result format that fails validation is `internal_error` with `temporary: false` and a `start_new_job` step, keyed or not, because every re-read of that record fails the same way, and its prose says a keyed call needs a new key (#277).

## Consequences

- A keyed run's temporary error now says `temporary: false`, `retry_after_ms: null`, and, where the step was `retry_after_delay`, `use_new_idempotency_key`; the same failure on an unkeyed call is unchanged.
- The rule is a per-call override made at render time, which ADR 0044 leaves out of the fingerprint's `repair_rules` pin, and no published schema or parameter contract changes, so `FINGERPRINT` does not move.
- `RESULT_FORMAT` stays 9: every stored value this writes was already valid under the result schema.
- A record written before this change keeps its stored `temporary: true`, and the same keyed call still replays it until it expires.
