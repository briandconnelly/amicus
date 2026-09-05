# ADR 0004: Async is both durable jobs and the tasks extension

**Status:** Proposed (2026-09-04; spike in M0, wiring in M5)

## Context

Durable `JobStore` jobs survive a dropped connection and a server restart, and every host can drive them through ordinary tools.
The `io.modelcontextprotocol/tasks` extension (SEP-2663) is the spec-native lifecycle, but it is an extension the host must negotiate and it needs a Docket backend.

## Decision

Keep the `_async` twins and `amicus_job_*` as the universal path.
Additionally register the four paid sync tools with `task=True` when `AMICUS_TASKS=1` and the `fastmcp[tasks]` extra is installed.
Persist a `task_id → job_id` mapping at task creation so `amicus_job_list(task_id=...)` recovers the job behind a task.
Cancellation propagation is explicit: an unkeyed task cancels its job; a keyed job survives and the cancel result names its `job_id`.

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
