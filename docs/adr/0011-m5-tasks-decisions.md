# ADR 0011: What the M5 tasks wiring decided

**Status:** Accepted (2026-09-07, M5)

## Context

M5 finishes the `task=True` half of ADR 0004 on top of the M2 jobs surface.
The M0 spike had shown that the semantic `isError` flip is lost on the tasked path, that the task id is reachable inside the tool, and that the task TTL is Docket's 15 minutes rather than the 60 s the spec assumed.
Two of ADR 0004's clauses could not be built as written: the sync tools are unkeyed (ADR 0007 deviation 8) and `fastmcp-tasks` 4.0.3's `tasks/cancel` returns an empty ack.
The maintainer approved decisions 1–3 in the M5 planning session.

## Decisions

- The host captures are produced by the agent non-interactively (`claude -p`, `codex exec`) against the worktree's server with `AMICUS_TASKS=1`, asking for the free `amicus_backends`; one host-model turn each, zero backend spend; recorded under `docs/host-captures/<host>/<version>/` and checked by `tests/test_host_captures.py`.
- ADR 0004's keyed-task cancel clause is amended: a tasked call is always unkeyed, so `tasks/cancel` always cancels the job, and the `job_id` is recovered through `amicus_job_list(task_id=...)`.
  Amended again by [ADR 0020](0020-idempotency-keys-on-the-sync-tools.md) (2026-09-12): the sync tools now take a key, so an unkeyed tasked call's job is cancelled with its task and a keyed one's survives, which restores ADR 0004's original clause.
- One surface bump (`amicus/0.1/schema-4` → `schema-5`): the capability summary and `amicus_capabilities.tasks.fallback` say what a task delivers, when a task is returned, the 15-minute result window and the job that outlives it; the dead `not_implemented` code leaves the catalog.
  `RESULT_FORMAT` stays 2.
- The `isError` carrier is the `guard` wrapper: `tools._guard.as_tool_result` returns `ToolResult(structured_content=envelope, is_error=True)` for every `ok: false` envelope on both delivery paths; the wire shape equals FastMCP's own dict conversion (pinned by a parity test); `SemanticErrorMiddleware` stays as a foreground safety net.
- Returning a `ToolResult` bypasses FastMCP's output-schema validation, which a returned dict still receives, so error envelopes are no longer validated at the boundary while success envelopes are.
  This is acceptable: the error branch of the schema is nearly opaque (`ok`, `error`, `meta`, with `error` a bare object), every error envelope is produced by the one `guard` builder, and it dumps a validated model.
- Task-map recording lives in `jobs.lifecycle.run_sync`, keyed by `lifecycle.current_task_id()` (the extension's `get_task_context`, imported lazily), through a `task_map` keyword the four sync tools pass; the id also rides `meta.task_id`; a map write failure is logged and never fails the run.
- Cancel propagation is the existing `CancelledError` path in `await_job_result`; nothing new is wired.
- `TasksExtension` gets `redelivery_timeout = max(AMICUS_JOB_MAX_SECONDS, MAX_TIMEOUT_SECONDS) + SYNC_AWAIT_GRACE_S` as belt and braces.
  A caller's own `timeout_seconds` is clamped to `MAX_TIMEOUT_SECONDS` (600 s), which can exceed a low `AMICUS_JOB_MAX_SECONDS`, so the `max` keeps the bound above any sync run that can actually happen.
  Docket's lease renewal already prevents re-execution of a live task, and a probe test pins that.
- `ConnectionLogMiddleware` logs one DEBUG line per `tools/call` (tool name, protocol version, client name/version, tasks declared); it is the capture instrument and carries no argument (rule 18).
- Host identity was broken and is fixed here: MCP SDK v2 names the field `client_info` (snake_case), `client_name_from_ctx` read `clientInfo`, so `host_display_name` always fell back to the neutral `Caller` and the spec's first branch was dead.
  The test that covered it built its own `SimpleNamespace(clientInfo=...)` fake, so it could not fail; the fake now uses `mcp.types.InitializeRequestParams`, and a real-client test pins the whole path.
- M4 follow-ups closed without moving the surface: `framing_for` raises `ValueError` on an unknown verb; `is_permission_denied` no longer matches a bare `denied`; the unused `ENVELOPE_KEYS` and the Kimi `schema_instruction` re-export shim are gone.
- Not changed: `classify_envelope`'s stderr scope (reordering classification would move the claude-in-codex differential; it belongs with a sibling recapture).

## Consequences

- An agent on a modern-era connection that declares the extension gets a task for every paid sync call, sees `isError` on a failed delivery, and can always fall back to `amicus_job_*` with the `task_id`.
- Both v1 hosts keep the plain path; nothing changes for them except the summary text.
- Prompt framing now names the calling host (`Claude Code`, `Codex`) instead of the neutral `Caller` whenever the client declares a name and `AMICUS_HOST_NAME` is unset; no wire schema moves, and the whole M4 suite stays green under the fix.
- A `fastmcp-tasks` release that exposes `execution_ttl` should set it to at least `AMICUS_JOB_TTL` and drop the 15-minute sentence from the summary (a fingerprint bump).
