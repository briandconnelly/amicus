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

Filled in by Task 16 of the M0 plan.
