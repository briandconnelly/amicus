# ADR 0004: Async is both durable jobs and the tasks extension

**Status:** Accepted (durable jobs 2026-09-06, M2; `task=True` 2026-09-07, M5; the keyed-task cancel clause amended by ADR 0011).

## Context

Durable `JobStore` jobs survive a dropped connection and a server restart, and every host can drive them through ordinary tools.
The `io.modelcontextprotocol/tasks` extension (SEP-2663) is the spec-native lifecycle, but it is an extension the host must negotiate and it needs a Docket backend.

## Decision

Keep the `_async` twins and `amicus_job_*` as the universal path.
Additionally register the four paid sync tools with `task=True` when `AMICUS_TASKS=1` and the `fastmcp[tasks]` extra is installed.
Persist a `task_id → job_id` mapping at task creation so `amicus_job_list(task_id=...)` recovers the job behind a task.
Cancellation propagation is explicit and unconditional: a tasked call is always unkeyed (the sync tools carry no `idempotency_key`, ADR 0007), so cancelling a task cancels its job; `tasks/cancel` is an empty ack (SEP-2663), and the job behind a task is recovered with `amicus_job_list(task_id=...)`.
Since [ADR 0020](0020-idempotency-keys-on-the-sync-tools.md) (2026-09-12) the sync tools do carry the key, and the clause reads as first written: an unkeyed task's job is cancelled with it; a keyed task's job survives.

## Spike report (M0)

- Extension: `fastmcp-tasks` 4.0.3 (`fastmcp[tasks]`), Docket backend `memory://`, no Redis needed in-process; it pulls `pydocket` and `cryptography`.
- Registration: `app.add_extension(TasksExtension(url=...))` before any `task=True` tool; a `task=True` tool without the extension raises at registration.
- Advertisement: `server/discover` lists `io.modelcontextprotocol/tasks`; the UI-extension filter leaves it intact.
- Delivery: a task-augmented `amicus_consult` delivers the same envelope (`structured_content`) as the plain call; `isError` on the delivered result is `false`, not `true` as the plain call produces — the semantic-error flip does not survive task delivery.
- Finding: once a client's session negotiates the tasks extension (the default for any `fastmcp.Client` when `fastmcp_tasks` is importable — `Client._auto_internal_extensions` defaults to `True`), every call to an `optional`-mode `task=True` tool is intercepted server-side into a task, including a call made with the ordinary `client.call_tool()`; there is no per-call way to force a synchronous path from an already-opted-in client. `TasksExtension.intercept_tool_call` returns a `CreateTaskResult` in place of the tool's `ToolResult` before `on_call_tool` middleware's `call_next` reaches the tool body, and the Docket worker later invokes the tool's underlying callable directly to produce the eventual result — neither leg re-enters the FastMCP middleware chain. `SemanticErrorMiddleware` (`src/amicus/middleware.py`) originally assumed every `on_call_tool` result was a `ToolResult` and crashed with `AttributeError: 'CreateTaskResult' object has no attribute 'structured_content'` on any tasked call; this M0 spike fixed it to pass non-`ToolResult` results through unchanged, which is why the semantic flip is now confirmed absent rather than merely uncrashed. Wiring the flip onto the tasked path is deferred work.
- Task id: reachable inside the tool via `fastmcp_tasks.context.get_task_context()`, which returns a `TaskContextInfo(task_id, task_scope)` — the field is `task_id`; persisted through `TaskJobMap` at task creation.
- TTL: `create_result.ttl_ms` observed = `900000` (15 minutes, Docket's own execution-TTL default) — well above a 60 s floor; still, the M5 job wiring must confirm this stays at least the job deadline as jobs grow longer-running.
- Legacy era: a `mode="legacy"` client calling a `task=True` tool gets a plain result (observed) — the extension is not negotiated on a handshake-era connection, so the tool runs synchronously and the client sees an ordinary `CallToolResult`.
- Cancellation, keyed replay, and `amicus_job_list(task_id=...)` are M2/M5 work; M0 only proves the seam.

## M5 wiring (2026-09-07)

- `isError`: produced by the tool itself (`tools._guard.as_tool_result` returns an `is_error` `ToolResult` for every `ok: false` envelope), so it survives task delivery; `SemanticErrorMiddleware` is a foreground safety net.
- `task_id → job_id`: recorded by `jobs.lifecycle.run_sync` right after the job exists, read through `fastmcp_tasks.context.get_task_context`; the id also rides `meta.task_id`.
- Cancel: `tasks/cancel` cancels the coroutine cooperatively and `await_job_result` cancels the job on `CancelledError`; proven end to end in `tests/test_tasks_client.py`.
- TTL: `ttlMs` is Docket's `execution_ttl` (15 minutes after completion) and `TasksExtension` 4.0.x cannot set it; the job record outlives it for `AMICUS_JOB_TTL`.
- Redelivery: Docket renews a running task's lease (a 1.2 s run past a 300 ms `redelivery_timeout` executes once); amicus still sets `redelivery_timeout` to the sync deadline plus grace.
- Hosts: Claude Code 2.1.263 and Codex CLI 0.153.4 negotiate the handshake era (`docs/host-captures/`), so today the extension serves only modern-era clients such as `fastmcp.Client`.
