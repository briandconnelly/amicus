# Options and errors

Optional parameters, duplicate-spend protection, and what to do with an error envelope.
`amicus_capabilities` carries the full error catalog and is authoritative.

## Rules

- **Read `error.code` and `error.repair`; never infer a fix from the message prose.**
- **Never retry a call whose failing condition has not changed.**
- **Follow `repair.next_step`**, and use `repair.tool` / `repair.arguments` when they are present
  rather than composing a retry yourself.
- **Use `invalid_arguments[].allowed_values` to pick a corrected value** rather than guessing one.
- **Reuse the same `idempotency_key` when retrying the same logical request** after an
  ambiguous failure, with identical arguments, on the same tool.
- **Never reuse a key across a different tool or backend** — that is a different operation.
- **Recover an existing job before paying again.**

## The error envelope

On `ok: false` the envelope carries `error.code` (from a closed catalog), a message, optional
`error.details`, optional `invalid_arguments[]`, and `error.repair`.

`repair.next_step` is symbolic and closed. The ones you will meet most:

| `next_step` | What it means |
| --- | --- |
| `correct_arguments` / `use_allowed_value` | Fix the call. `invalid_arguments[].allowed_values` names the accepted set. |
| `authenticate` / `install_backend` | The backend is not ready. `amicus_backends` reports the same thing for free. |
| `poll_job_status` / `list_jobs` | The work exists; find or wait for it rather than starting another. |
| `start_new_job` | The prior job is unrecoverable; a new one is the correct action. |
| `reduce_input` | Make the next attempt smaller. It is a recovery action, **not** a statement about spend — `budget_exceeded` maps here and may already have spent. Read `error.code`. |
| `retry_after_delay` | Transient; honor `retry_after_ms` when present. |
| `inspect_and_retry` / `retry_then_report` | No mechanical fix — look before retrying, and report if it recurs. |
| `use_new_idempotency_key` | The key is bound to different arguments. |

A pre-dispatch rejection — an out-of-set `backend`, a bad `untracked` value, an oversized input —
costs nothing. Reaching a backend is what spends.

## `idempotency_key`

An optional dedup key on every paid tool, sync and `_async`, scoped to **this tool + backend +
workspace**.

- Same key, same arguments → the prior run is replayed with **no new spend**; an `_async` call
  returns the same `job_id`, a sync call awaits that run and returns its result.
  `meta.idempotency_replayed: true` marks a replayed response.
- Same key, different arguments → refused as `idempotency_conflict`. On a sync tool
  `timeout_seconds` counts as an argument; `detail` does not.
- A key whose result was consumed or evicted → `idempotency_result_unavailable`.
- A reservation still publishing → `idempotency_in_progress` (retry; a sync call waits about a
  second for it first).
- A completed result stays replayable while its job record lives (its TTL).
- A keyed sync wait that hits its deadline or is cancelled leaves the run going: the `timeout`
  repair polls `amicus_job_status` for that job, and repeating the same keyed call reattaches.
  Under the tasks extension a keyed task's job survives `tasks/cancel`; an unkeyed one's is
  cancelled with it.
- An empty key is refused pre-spend.

Sync and `_async` are separate tools and never share a key. Changing `backend` makes it a
different operation, not a retry of the same one.

Use it where duplicate spend is the risk: an interrupted call whose outcome you never saw, a
transport error that may or may not have started the run, a workflow step you may need to repeat.
Choose a key that identifies the *logical request* — stable across retries, distinct across
different requests.

## Recovering an interrupted call

If a call was interrupted and you do not know whether it started:

1. `amicus_job_list` (free), narrowed by `backend`, `status`, or `task_id`. A task-augmented call
   maps to its job by `task_id`.
2. If the job exists, resume it with `amicus_job_status` / `amicus_job_result` — the recovery
   rule above is what makes a replacement the wrong move.
3. Only if no job exists, retry — with the same `idempotency_key` if the original had one.

Prefer `amicus_job_result` over `amicus_job_consume_result` while a workflow is still running.
Consuming deletes the record, and a later synthesis, comparison, or second reviewer cannot read an
artifact you have already destroyed.

## Backend-local codes

Some codes exist only for one backend and are preserved verbatim rather than generalized:
`user_config_rejected` (codex — the user's own CLI config carries something the installed CLI
refuses at startup; zero spend), and `budget_exceeded`, `claude_permission_error`,
`api_key_invalid`, `api_key_missing` (claude). `budget_exceeded` is the one to read carefully: the
best-effort spend cap stopped the run, and it **may already have spent**.

`feature_unsupported` means the backend does not declare the verb — a delegate routed to `claude`,
for example. `amicus_backends`' `features` list answers that for free, before the call.
