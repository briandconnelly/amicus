# ADR 0008: The M2 jobs surface — identity, outcomes, filters, foreign records

**Status:** Accepted (2026-09-06, M2)

## Context

M2 makes the `_async` twins and `amicus_job_*` real on top of pontonier's `JobStore`.
The spec fixes the shape; the sibling (codex-in-claude) persisted its whole spec, prompt included, and hashed it for dedup, which amicus cannot do because it never persists a prompt.
The maintainer settled the open choices on 2026-09-06.

## Decisions

- The keyed-dedup identity is `RunSpec.public()` minus `cwd`, `workspace_source`, `roots_source`, `host_name`, `kind` and `tool`, plus `inputs_digest`, a sha256 of the canonical inputs JSON.
  A key reused with a different prompt is `idempotency_conflict`; a reconnect with different roots replays.
- Keyed outcomes: `created` returns a running handle; `replay` returns the existing job's real handle with `meta.idempotency_replayed`; `conflict` and `unavailable` repair with `use_new_idempotency_key` naming the twin; `in_progress` and a transient `io_error` are temporary with `retry_after_ms` (250 and 1000 ms).
  An `_async` caller never blocks on `in_progress`.
- The sync tools stay unkeyed (ADR 0007, deviation 8); the sibling's keyed-await path is not ported.
- A twin's run timeout is `AMICUS_JOB_MAX_SECONDS` (default 1800 s), unclamped; the handle's `deadline_seconds` and `meta.timeout_seconds` report it.
- `amicus_job_list(task_id=...)` is a filter: no match is an empty list.
  The task map lives at `<AMICUS_STATE_DIR>/tasks.json`; handles, statuses and summaries echo `task_id` by reverse lookup (recording lands in M5).
- A record without a valid `extra.backend` tag was not written by amicus: the job tools report `job_not_found` for it and `amicus_job_list` omits it; nothing deletes it.
- A job tool's generated error carries the record's backend and kind when resolved, the job deadline as `timeout_seconds`, and the roots state the lookup saw.
- `amicus_job_cancel` is the store's cancel: SIGTERM, a grace period, SIGKILL of the process group, then guarded removal of the declared worktree; a terminal job is returned unchanged.
  Task-scoped cancel semantics (an unkeyed task cancels its job; a keyed job survives) are wired in M5.
- The wire-shape fixture gains a `handles` section rendered through the real builders; nothing new is persisted, so `RESULT_FORMAT` stays 1 while `FINGERPRINT` moves to `schema-3` for the description and schema changes.

## Consequences

- Every host can drive a background run through ordinary tools today; the tasks extension (M5) adds a second entry point onto the same records.
- A caller that wants a retry to be a new paid run must pass a new key; a caller that wants a replay must repeat the inputs exactly.
