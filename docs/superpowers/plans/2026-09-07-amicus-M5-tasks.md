# amicus M5 Implementation Plan: the tasks extension for real

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the `task=True` half of ADR 0004: a task-augmented call to any of the four paid sync tools delivers the same envelope as the plain call with `isError` intact, records `task_id → job_id` so `amicus_job_list(task_id=...)` recovers the job, cancels its job when the task is cancelled, and the capability summary says what both v1 hosts were captured doing.

**Architecture:** No new subsystem. The wiring lands on three existing seams: the `guard` wrapper every tool passes through (the `isError` carrier on both delivery paths), the sync lifecycle tail `run_sync` (task-map recording and `meta.task_id`), and the server's middleware list (a connection-log line that is the capture instrument).
`task=settings.tasks_enabled` is already on all four paid sync tools, the extension is already added under `AMICUS_TASKS=1`, and the task map plus the `task_id` filter and echo exist since M2; nothing records into the map yet, and the semantic `isError` flip is lost on the tasked path (the M0 spike).
One surface-moving task rewords the capability summary and the `amicus_capabilities` tasks block and drops the dead `not_implemented` code; the fingerprint moves once, `schema-4` → `schema-5`.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `prek`.
Runtime: `fastmcp[tasks]>=4.0,<4.1` (installed 4.0.3: `fastmcp` 4.0.3, `fastmcp-tasks` 4.0.3, `pydocket` 0.25.0), `mcp>=2.1,<2.2`, `pontonier==0.9.0`, `pydantic>=2`, `anyio>=4`.
No new dependency.
Hosts captured: Claude Code `2.1.263` and Codex CLI `0.153.4` on the maintainer's machine.

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — "Milestones" row M5 (scope: `task=True` on the four paid sync tools behind `AMICUS_TASKS`; capability-summary wording; host captures; gate: in-memory task-client tests; both host captures); "Jobs and tasks" (`task=True` wraps the same coroutine; the job store persists `task_id → job_id` at task creation; cancellation propagation; legacy fallback is claimed only after a host capture); "Annotations, lifecycle metadata, capability summary, workspace" (`CAPABILITY_SUMMARY` is rules-then-context: task `completed` is a delivery statement, when a task may be returned, `amicus_job_*` fallback and task→job recovery, handle TTLs).
ADR 0004 (both halves; its spike section is the list of facts this plan closes), ADR 0005 (envelope), ADR 0006 (fingerprint), ADR 0007 (deviation 8: the sync tools stay unkeyed), ADR 0008 (the M2 jobs surface: task map, filter, echo).
Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`; binding repo rules: `AGENTS.md`.
No sibling is ported in this milestone.

## Global Constraints

- Repo: `/Users/bdc/projects/amicus`.
  Work on branch `feat/m5-tasks` in the sibling git worktree `/Users/bdc/projects/amicus-wt-m5` (created from `main` at `a98b150`; baseline 938 tests green, 96.97% branch coverage).
  Never commit to `main`.
- Dependencies exactly as `pyproject.toml` has them; this plan adds none.
- Gate (AGENTS.md rule 2): `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest` at ≥95% branch coverage.
  Coverage floor never lowered.
  Every `uv run` assumes `uv sync` ran once in the worktree; `uv run --no-sync` is fine while iterating.
- Import rules (import-linter, `pyproject.toml`): `amicus.orchestration`, `amicus.jobs` and `amicus._worker` never import `amicus.server` or `amicus.tools`; `amicus.tools` never imports `amicus.server`; `amicus.backends.*` never imports the server layer.
  `amicus.server` MAY import `amicus.jobs.lifecycle` (Task 3 does, for one constant).
- Tool surface stays exactly 18 tools in `amicus.tools.TOOL_ORDER`; 6 resources; no prompts; no tool gains or loses a parameter.
  The surface moves in this milestone, deliberately and in one place (Task 4): the capability summary (the `initialize` `instructions` text) and the `amicus_capabilities` `tasks.fallback` text change, and `not_implemented` leaves the error catalog (`LOCAL_CODES`, `ErrorCode`, the repair table, every tool's `error_codes` inventory and output-schema enum).
  `FINGERPRINT` moves `amicus/0.1/schema-4` → `amicus/0.1/schema-5`; `RESULT_FORMAT` stays `2` (no persisted result model changes shape: `Meta.task_id` already exists).
  Every pin (manifest snapshots and hashes, surface digests, wire-shape and result-format snapshots, the tools/list ratchet) is regenerated in its own commit (rule 10).
  No other task may move a pin; Task 7 verifies they are byte-identical to the Task 4 regeneration.
- Prompt inputs (`question`, `task`, `extra_context`, `instructions_append`, `focus`, `target`, `evidence`) never land in `spec.json`, on the worker's argv, or in a log (AGENTS.md rule 18).
  The new connection-log line (Task 2) carries the tool NAME and connection facts only, never an argument; `tests/test_middleware.py` asserts an argument value is absent from the line.
- Spend guard: `tests/conftest.py` keeps `AMICUS_CODEX_BIN`, `AMICUS_KIMI_BIN` and `AMICUS_CLAUDE_BIN` unusable (autouse); every unit test drives `tests/support/fake_codex.py` or a scratch app.
  No live gate runs in this milestone (rule 5); the two host captures (Tasks 6 and 7) spend one host-model turn each (a Claude Max turn, a Codex turn) and zero backend quota: the only tool the host is asked to call is the free `amicus_backends`.
  The Codex capture must wait for the Codex quota reset at `2026-09-07T19:14:35Z`.
- Commit messages: Conventional Commits `type(scope): subject`; scopes from `scripts/check_commit_message.py` (`schemas`, `plugin`, `registry`, `config`, `errors`, `middleware`, `server`, `tools`, `resources`, `manifest`, `orchestration`, `jobs`, `tasks`, `backends`, `packaging`, `docs`, `ci`, `deps`, `release`).
  Imperative lowercase subject, no trailing period.
  End every commit body with the attribution trailer given in the session.
- Markdown under `docs/`: one sentence per line.
- Off limits (AGENTS.md rules 9, 17): `.github/**`, `AGENTS.md`, `CLAUDE.md`; any sibling checkout; releasing; merging or approving the PR.

## Decisions made here (surface in ADR 0011, the ADR 0004 status update, and the PR body)

The maintainer approved decisions 1–3 in the planning session (2026-09-07); 4–9 are the planner's rulings on questions the spec leaves open.

1. **The host captures are driven by the agent, non-interactively.** `claude -p` and `codex exec` are each pointed at the worktree's server with `AMICUS_TASKS=1`, `AMICUS_LOG_LEVEL=DEBUG` and `AMICUS_LOG_FILE`, and asked to call the free `amicus_backends`; the connection line amicus logs (protocol version, `clientInfo`, whether the tasks extension was declared) and the host's final output are recorded under `docs/host-captures/<host>/<version>/`.
   One host-model turn each; zero backend spend.
2. **ADR 0004's keyed-task cancel clause is amended.** The sync tools are unkeyed (ADR 0007 deviation 8) and `fastmcp-tasks` 4.0.3's `tasks/cancel` returns an empty ack (SEP-2663), so "a keyed job survives and the cancel result names its `job_id`" cannot occur as written.
   A tasked call is always unkeyed: `tasks/cancel` always cancels the job; the `job_id` stays recoverable through `amicus_job_list(task_id=...)`.
3. **One surface bump.** The capability-summary wording lands in the `initialize` response, so the fingerprint moves; the same task drops the dead `not_implemented` code (a surface move on its own).
   Non-surface M4 follow-ups ride along as plain fixes (Task 5).
4. **The `isError` carrier is the `guard` wrapper.** `tools/_guard.as_tool_result` returns a `ToolResult(structured_content=envelope, is_error=True)` for every `ok: false` envelope, on the foreground and the tasked path alike.
   FastMCP derives the text mirror of such a `ToolResult` from `structured_content` through the same `_convert_to_content` it uses for a dict return under an explicit output schema, so the wire shape is unchanged (a parity test pins it), and `fastmcp_tasks.handlers._inline_result` passes a `ToolResult` through with `isError` intact.
   `SemanticErrorMiddleware` stays as a no-op safety net for the foreground path.
5. **Task-map recording lives in `run_sync`**, right after `start_job` returns a `job_id`, via `lifecycle.current_task_id()` (the extension's `get_task_context`, imported lazily) and a `task_map` keyword the four sync tools pass as `lookup.task_map(settings)`.
   The recorded `task_id` also rides `meta.task_id` on every envelope `run_sync` returns; a map write failure is logged and never fails the run.
6. **Cancel propagation is the existing `CancelledError` path.** `tasks/cancel` is `docket.cancel(execution.key)`, which cancels the coroutine cooperatively; `await_job_result` already cancels the job on `CancelledError` (M1).
   Nothing new is wired; the in-memory test proves the chain end to end against the job record.
7. **Docket timing.** `TasksExtension` 4.0.x does not expose Docket's `execution_ttl`, so a task result stays readable through `tasks/get` for 15 minutes after completion (Docket's default; `ttlMs` = 900000); the job record outlives it for `AMICUS_JOB_TTL` (default 24 h) and the summary says so.
   Docket renews a running task's lease, so a run longer than `redelivery_timeout` (default 5 min) is not re-executed; amicus still sets `redelivery_timeout` to `job_max_seconds + SYNC_AWAIT_GRACE_S` as belt and braces, and a probe test pins the single-execution behaviour.
8. **The connection line is a middleware**, `ConnectionLogMiddleware`, first in the chain, one DEBUG line per `tools/call` naming the tool, the protocol version, `clientInfo` name/version and whether the tasks extension was declared for the request.
   It is the instrument behind the captures and stays useful to operators.
9. **Host identity is fixed here, not deferred.** The connection log and the host captures both read the client's declared name, and it was unreadable: the MCP SDK v2 field is `client_info`, `client_name_from_ctx` read `clientInfo`, and the covering test's hand-built fake used the wrong name so it could never fail.
   The fix ships in Task 2 with the real SDK models in the fake and an end-to-end test through a real client; it moves no wire schema and leaves the whole baseline suite green (measured).
10. **`classify_envelope`'s stderr scope is out of scope.** Widening which branches see `stderr` reorders classification, and the claude-in-codex differential fixture pins the order; that change belongs with a sibling recapture, not here.

## File map

Created in this milestone (responsibility in one line each):

- `tests/test_guard.py` — the guard: `ok: false` is an MCP error result with FastMCP's own dict wire shape; exceptions become `internal_error`.
- `tests/test_tasks_client.py` — the in-memory task-client suite (the M5 gate): delivery parity, `isError` on the tasked path, task-map recording and recovery, cancel propagation to the job record, all four tools tasked, the legacy-era plain result, the result TTL, the redelivery guard.
- `tests/test_host_captures.py` — the host captures are checked artifacts: each `docs/host-captures/<host>/<version>/connection.log` shows a handshake-era `amicus_backends` call with the extension not negotiated.
- `tests/test_structured.py` — the moved `schema_instruction` test.
- `docs/host-captures/claude-code/2.1.263/{FINDINGS.md,connection.log,host-output.json}` — the Claude Code capture.
- `docs/host-captures/codex/0.153.4/{FINDINGS.md,connection.log,host-output.jsonl}` — the Codex CLI capture.
- `docs/adr/0011-m5-tasks-decisions.md` — the decisions above.

Modified: `src/amicus/tools/_guard.py`, `src/amicus/middleware.py`, `src/amicus/server.py`, `src/amicus/orchestration/workspace.py`, `tests/test_workspace.py`, `src/amicus/jobs/lifecycle.py`, `src/amicus/tools/consult.py`, `tools/review.py`, `tools/delegate.py`, `tools/discovery.py`, `src/amicus/schemas/codes.py`, `schemas/fingerprint.py`, `src/amicus/errors.py`, `src/amicus/orchestration/prompts.py`, `src/amicus/backends/claude/contract.py`, `src/amicus/backends/kimi/cli.py`, `backends/kimi/adapter.py`, `tests/test_tasks_spike.py`, `tests/test_middleware.py`, `tests/test_lifecycle.py`, `tests/test_server.py`, `tests/test_codes.py`, `tests/test_errors.py`, `tests/test_discovery.py`, `tests/test_adversarial.py`, `tests/test_claude_contract.py`, `tests/test_kimi_cli.py`, `tests/test_kimi_argv_differential.py`, `tests/test_manifest.py`, `tests/test_fingerprint.py`, `tests/test_discovery_cost.py`, `tests/fixtures/manifest_snapshot.*.json`, `tests/fixtures/wire_shape_snapshot.json`, `tests/fixtures/result_format_snapshot.json`, `docs/adr/0004-tasks-and-jobs.md`, `README.md`.

---

### Task 0: Worktree and baseline

**Files:** none changed.

- [ ] **Step 1: Confirm the worktree, branch and baseline**

```bash
cd /Users/bdc/projects/amicus-wt-m5
git status --short --branch
git log --oneline -1
uv sync
uv run pytest -q 2>&1 | tail -2
```

Expected: `## feat/m5-tasks`, a clean tree, HEAD `a98b150`, `938 passed`, total coverage `96.97%`.
If the worktree does not exist: `git -C /Users/bdc/projects/amicus worktree add /Users/bdc/projects/amicus-wt-m5 -b feat/m5-tasks main`.

- [ ] **Step 2: Commit this plan (if not already committed)**

```bash
git add docs/superpowers/plans/2026-09-07-amicus-M5-tasks.md
git commit -m "docs(tasks): add the M5 implementation plan"
```

---

### Task 1: The guard is the `isError` carrier on both delivery paths

**Files:**
- Modify: `src/amicus/tools/_guard.py` (whole file)
- Modify: `src/amicus/middleware.py:143-156` (the `SemanticErrorMiddleware` docstring)
- Modify: `tests/test_tasks_spike.py:51-58`
- Test: `tests/test_guard.py` (new)

**Interfaces:**
- Produces: `amicus.tools._guard.as_tool_result(envelope: dict[str, Any]) -> dict[str, Any] | ToolResult`; `guard(tool_name, settings)` now returns a decorator whose wrapper is `Callable[..., Awaitable[dict[str, Any] | ToolResult]]`.

Background for the implementer: FastMCP builds a tool's result in `Tool.convert_result` (`fastmcp/tools/base.py`): a `ToolResult` is passed through, a dict under an explicit output schema becomes `ToolResult(content=_convert_to_content(structured), structured_content=structured)`.
`ToolResult.__init__` with only `structured_content` derives `content` through the same `_convert_to_content`.
FastMCP reads a tool's signature through `__wrapped__` (the guard uses `functools.wraps`), and every one of the 18 tools passes an explicit `output_schema`, so the wrapper's return annotation never reaches a schema.
On the tasked path Docket runs the raw function (`fastmcp_tasks.components.register_component_with_docket` registers `component.fn`) and `fastmcp_tasks.handlers._inline_result` passes a returned `ToolResult` through unchanged, which is why the flip must be produced by the function itself.

- [ ] **Step 1: Write the failing tests**

`tests/test_guard.py`:

```python
"""The guard: an `ok: false` envelope is an MCP error result on every delivery path, with
the wire shape FastMCP's own dict conversion produces; an unexpected exception is an
internal_error envelope that names the exception type and never its text."""

from __future__ import annotations

from fastmcp import Client, FastMCP
from fastmcp.tools import ToolResult

from amicus import config
from amicus.errors import error_envelope
from amicus.schemas.envelope import Meta
from amicus.tools._guard import GUARD_MARKER, as_tool_result, guard


def _envelope() -> dict:
    return error_envelope("internal_error", "boom", Meta(timeout_seconds=5))


def test_ok_false_becomes_an_error_tool_result_and_ok_true_passes_through():
    env = _envelope()
    out = as_tool_result(env)
    assert isinstance(out, ToolResult) and out.is_error is True
    assert out.structured_content == env
    assert as_tool_result({"ok": True, "x": 1}) == {"ok": True, "x": 1}
    assert as_tool_result({"x": 1}) == {"x": 1}


async def test_guard_result_matches_fastmcp_dict_conversion_byte_for_byte():
    """Parity instrument: content and structured_content are exactly what FastMCP builds
    from the same dict returned under an explicit output schema."""
    app = FastMCP(name="scratch")

    @app.tool(name="probe", output_schema={"type": "object", "additionalProperties": True})
    async def probe() -> dict:
        return {}

    tool = await app.get_tool("probe")
    env = _envelope()
    theirs = tool.convert_result(env)
    ours = as_tool_result(env)
    assert isinstance(ours, ToolResult)
    assert ours.structured_content == theirs.structured_content
    assert [c.model_dump() for c in ours.content] == [c.model_dump() for c in theirs.content]
    assert theirs.is_error is False and ours.is_error is True


async def test_guarded_tool_delivers_is_error_without_any_middleware():
    settings = config.settings({})
    app = FastMCP(name="scratch")  # deliberately no SemanticErrorMiddleware

    @app.tool(name="failing", output_schema={"type": "object", "additionalProperties": True})
    @guard("failing", settings)
    async def failing(backend: str | None = None) -> dict:
        return _envelope()

    @app.tool(name="raising", output_schema={"type": "object", "additionalProperties": True})
    @guard("raising", settings)
    async def raising(backend: str | None = None) -> dict:
        raise RuntimeError("secret detail")

    @app.tool(name="fine", output_schema={"type": "object", "additionalProperties": True})
    @guard("fine", settings)
    async def fine(backend: str | None = None) -> dict:
        return {"ok": True, "answer": 42}

    assert getattr(failing, GUARD_MARKER) is True
    async with Client(app) as c:
        res = await c.call_tool("failing", {}, raise_on_error=False)
        exc = await c.call_tool("raising", {"backend": "codex"}, raise_on_error=False)
        ok = await c.call_tool("fine", {})
    assert res.is_error is True and res.structured_content["error"]["code"] == "internal_error"
    assert exc.is_error is True
    err = exc.structured_content["error"]
    assert err["code"] == "internal_error" and err["backend"] == "codex"
    assert "RuntimeError" in err["message"] and "secret detail" not in err["message"]
    assert ok.is_error is False and ok.structured_content == {"ok": True, "answer": 42}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_guard.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'as_tool_result'`.

- [ ] **Step 3: Rewrite the guard**

`src/amicus/tools/_guard.py` (whole file):

```python
"""Wrap a tool so an unexpected exception becomes an internal_error envelope and an
`ok: false` envelope is an MCP error result on every delivery path."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from fastmcp.tools import ToolResult
from pontonier.core.redaction import exc_summary

from amicus import obs
from amicus.errors import error_envelope
from amicus.tools._meta import base_meta

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Awaitable, Callable

    from amicus.config import Settings

GUARD_MARKER = "_amicus_guarded"


def as_tool_result(envelope: dict[str, Any]) -> dict[str, Any] | ToolResult:
    """An `ok: false` envelope becomes a `ToolResult` with `is_error=True`; anything else
    is returned unchanged for FastMCP's own conversion.

    FastMCP derives the text mirror of a `ToolResult` built from `structured_content` on
    the same path (`_convert_to_content`) it uses for a dict returned under an explicit
    output schema, so the wire shape equals the middleware-flipped result
    (`tests/test_guard.py` pins the parity). The flip has to be produced here, not only in
    `SemanticErrorMiddleware`: a task-augmented call (ADR 0004) never re-enters the
    middleware chain, and the tasks handler passes a `ToolResult` through with `isError`
    intact."""
    if envelope.get("ok") is False:
        return ToolResult(structured_content=envelope, is_error=True)
    return envelope


def guard(
    tool_name: str, settings: Settings
) -> Callable[
    [Callable[..., Awaitable[dict[str, Any]]]],
    Callable[..., Awaitable[dict[str, Any] | ToolResult]],
]:
    """Cancellation is a BaseException and propagates; only `Exception` is enveloped."""

    def decorator(
        fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> Callable[..., Awaitable[dict[str, Any] | ToolResult]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any] | ToolResult:
            try:
                return as_tool_result(await fn(*args, **kwargs))
            except Exception as exc:
                # Full detail (exc_summary) goes to the log only; the client-facing
                # message names the exception type but never echoes its text, which may
                # carry caller-supplied content that failed to redact cleanly.
                obs.get_logger(__name__).exception(
                    "%s failed unexpectedly: %s", tool_name, exc_summary(exc)
                )
                return as_tool_result(
                    error_envelope(
                        "internal_error",
                        f"{tool_name} failed unexpectedly: {type(exc).__name__}",
                        base_meta(settings, backend=kwargs.get("backend")),
                    )
                )

        setattr(wrapper, GUARD_MARKER, True)
        return wrapper

    return decorator
```

- [ ] **Step 4: Update the middleware docstring and the spike assertion**

In `src/amicus/middleware.py`, replace the `SemanticErrorMiddleware` docstring with:

```python
    """An `ok: false` envelope is an MCP `isError: true` result ([6.tool-errors]).

    Safety net for the foreground path only. A task-augmented call (`fastmcp[tasks]`,
    ADR 0004) intercepts `tools/call` before this middleware's `call_next` reaches the
    tool body and returns a `CreateTaskResult` instead of a `ToolResult`, and the eventual
    task result never re-enters this middleware (the worker invokes the tool directly), so
    the flip an agent relies on is produced by the tool itself: `tools._guard.as_tool_result`
    returns an `is_error` `ToolResult` for every `ok: false` envelope on both paths (M5).
    """
```

In `tests/test_tasks_spike.py`, replace lines 51–58 (the comment block and the `assert result.is_error is False` line) with:

```python
    # M0 finding: the SemanticErrorMiddleware flip did NOT survive task delivery (the
    # extension intercepts tools/call before call_next, and the Docket worker invokes the
    # tool directly). M5 closes it: the guard returns an is_error ToolResult for every
    # ok: false envelope, and the tasks handler passes a ToolResult through intact.
    assert result.is_error is True
```

- [ ] **Step 5: Run the tests and the pins**

Run: `uv run --no-sync pytest tests/test_guard.py tests/test_tasks_spike.py tests/test_middleware.py tests/test_manifest.py tests/test_fingerprint.py tests/test_wire_shape.py -q --no-cov`
Expected: all pass. The pin tests prove the guard change moved no schema (FastMCP reads the original function through `__wrapped__`; every tool passes an explicit `output_schema`).
If a manifest pin fails here, a tool's output schema was derived from the wrapper's annotation: find the tool without `output_schema=` (`grep -c 'output_schema=' src/amicus/tools/*.py` must equal the `@app.tool(` count, 18) and give it one; never regenerate pins in this task.

Run: `uv run --no-sync pytest -q`
Expected: green, coverage ≥ 95%.

- [ ] **Step 6: Commit**

```bash
git add src/amicus/tools/_guard.py src/amicus/middleware.py tests/test_guard.py tests/test_tasks_spike.py
git commit -m "fix(tools): carry isError on the tasked path from the guard"
```

---

### Task 2: Host identity read from the wire, and the connection-log middleware

**Files:**
- Modify: `src/amicus/orchestration/workspace.py:94-102` (`client_name_from_ctx`)
- Modify: `tests/test_workspace.py:43-50,96-100` (the fake that hid the bug)
- Modify: `src/amicus/middleware.py` (add `TASKS_EXTENSION_ID`, `connection_facts`, `ConnectionLogMiddleware`)
- Modify: `src/amicus/server.py:106-112` (register it first)
- Test: `tests/test_middleware.py` (`_scratch_app` gains the middleware; three new tests)

**Interfaces:**
- Produces: `amicus.middleware.TASKS_EXTENSION_ID = "io.modelcontextprotocol/tasks"`; `connection_facts(context: object) -> dict[str, Any]` with keys `protocol`, `client`, `client_version` (strings, `"unknown"` when absent) and `tasks` (bool); `class ConnectionLogMiddleware(Middleware)`.
- The log line format, which Task 6's `tests/test_host_captures.py` parses: `tools/call <tool>: protocol=<version> client=<name>/<version> tasks_negotiated=<True|False>` on logger `amicus.middleware` at DEBUG.

**The bug this task fixes (measured 2026-09-07, not a guess).** MCP SDK v2 names the field snake_case: `InitializeRequestParams.client_info` (`mcp.types`, fields `capabilities`, `client_info`, `meta`, `protocol_version`).
`client_name_from_ctx` reads `params.clientInfo`, which never exists, so it always returns `None` and `prompts.host_display_name` always falls back to the neutral `"Caller"` — the spec's "Host identity: normalized handshake-era `clientInfo.name` … else neutral framing" never reaches its first branch.
A client sending `client_info={"name": "claude-code", "version": "2.1.263"}` was observed arriving as `name='claude-code'` on the wire while the helper returned `None`.
`tests/test_workspace.py`'s `_Session` fake builds `SimpleNamespace(clientInfo=...)`, encoding the wrong field name, so the test passes against the fake and could never fail against the SDK — fix the fake to use the real `mcp.types` models.
Both eras carry it (an in-memory client defaults to `mcp/0.1.0` on 2026-07-28 and on 2025-11-25), so the fix also gives the connection log a real client name, which is what makes the host captures evidence.
Applying the one-line fix alone leaves all 938 baseline tests green (measured), so nothing else depends on the broken behaviour.

- [ ] **Step 1: Write the failing host-identity test**

In `tests/test_workspace.py`, replace the `client_params` line of the `_Session` fake (line 47-49) with the real SDK models:

```python
        self.client_params = (
            InitializeRequestParams(
                protocol_version="2025-11-25",
                capabilities=ClientCapabilities(),
                client_info=Implementation(name=name, version="1.0"),
            )
            if name
            else None
        )
```

and add to the imports:

```python
from mcp.types import ClientCapabilities, Implementation, InitializeRequestParams
```

Append a test that pins the real wire path end to end:

```python
async def test_client_name_reaches_the_host_framing_from_a_real_client():
    """Regression: the SDK v2 field is `client_info` (snake_case). Reading `clientInfo`
    silently yielded None on every real connection, so host framing was always neutral."""
    from fastmcp import Client, FastMCP
    from fastmcp.server.middleware import Middleware

    from amicus.orchestration import prompts

    seen: list[str | None] = []

    class _Probe(Middleware):
        async def on_call_tool(self, context, call_next):
            seen.append(ws.client_name_from_ctx(context.fastmcp_context))
            return await call_next(context)

    app = FastMCP(name="scratch")
    app.add_middleware(_Probe())

    @app.tool(name="t", output_schema={"type": "object", "additionalProperties": True})
    async def t() -> dict:
        return {"ok": True}

    async with Client(
        app, mode="legacy", client_info={"name": "claude-code", "version": "2.1.263"}
    ) as c:
        await c.call_tool("t", {})
    assert seen == ["claude-code"]
    assert prompts.host_display_name(seen[0], None) == prompts.HOST_DISPLAY_NAMES["claude-code"]
```

(Read `prompts.HOST_DISPLAY_NAMES` first; if `claude-code` is not a key, assert the sanitized `"claude-code"` instead.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --no-sync pytest tests/test_workspace.py -q --no-cov`
Expected: FAIL — `assert [None] == ['claude-code']` on the new test, and the existing `test_client_name_from_ctx` fails too once the fake uses the real model (both prove the old fake was the only thing keeping the helper green).

- [ ] **Step 3: Fix the helper**

In `src/amicus/orchestration/workspace.py`, in `client_name_from_ctx`:

```python
    params = getattr(session, "client_params", None)
    # MCP SDK v2 names it `client_info`; `clientInfo` is the pre-v2 alias, kept as a
    # fallback so a handshake-era session object built by an older client still reads.
    info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
```

and update the docstring to `"""The client's declared name (`clientInfo.name`, `client_info` on the v2 SDK), or None."""`.

- [ ] **Step 4: Run the host-identity tests**

Run: `uv run --no-sync pytest tests/test_workspace.py tests/test_prompts.py tests/test_prepare.py -q --no-cov`
Expected: all pass.

Run: `uv run --no-sync pytest -q`
Expected: green, 95%+ (measured: the fix alone keeps all 938 baseline tests green).

- [ ] **Step 5: Commit the fix separately**

```bash
git add src/amicus/orchestration/workspace.py tests/test_workspace.py
git commit -m "fix(orchestration): read the client name from the v2 client_info field"
```

- [ ] **Step 6: Write the failing middleware tests**

In `tests/test_middleware.py`, add `import logging` and `from types import SimpleNamespace` to the imports, register the middleware first in `_scratch_app`:

```python
def _scratch_app() -> FastMCP:
    settings = config.settings({})
    app = FastMCP(name="scratch")
    app.add_middleware(middleware.ConnectionLogMiddleware())
    app.add_middleware(middleware.InputSchemaDialectMiddleware())
    app.add_middleware(middleware.SemanticErrorMiddleware())
    app.add_middleware(middleware.ValidationEnvelopeMiddleware(app, settings))
    app.add_middleware(middleware.ResourceErrorMiddleware())
    ...
```

and append:

```python
async def test_connection_log_names_the_negotiated_facts_and_never_an_argument(caplog):
    app = _scratch_app()
    with caplog.at_level(logging.DEBUG, logger="amicus.middleware"):
        async with Client(app) as c:
            await c.call_tool("probe", {"mode": "ok", "paths": ["SECRET-PATH"]})
        async with Client(
            app, mode="legacy", client_info={"name": "claude-code", "version": "2.1.263"}
        ) as c:
            await c.call_tool("probe", {"mode": "ok", "paths": ["SECRET-PATH"]})
    lines = [r.getMessage() for r in caplog.records if r.name == "amicus.middleware"]
    assert len(lines) == 2 and all(line.startswith("tools/call probe: ") for line in lines)
    modern, legacy = lines
    # Measured: an in-memory client declares mcp/0.1.0 by default, on BOTH eras; the
    # tasks extension is not negotiated because this scratch app registers none.
    assert "protocol=2026-07-28" in modern and "client=mcp/0.1.0" in modern
    assert "protocol=2025-11-25" in legacy and "client=claude-code/2.1.263" in legacy
    assert "tasks_negotiated=False" in modern and "tasks_negotiated=False" in legacy
    assert all("SECRET-PATH" not in line for line in lines)


def test_connection_facts_are_unknown_without_a_request():
    facts = middleware.connection_facts(SimpleNamespace())
    assert facts == {
        "protocol": "unknown",
        "client": "unknown",
        "client_version": "unknown",
        "tasks": False,
    }


def test_connection_facts_tolerate_a_context_whose_session_raises():
    class _Ctx:
        request_context = SimpleNamespace(protocol_version="2025-11-25")

        @property
        def session(self):
            raise RuntimeError("no active session")

        def client_extension_settings(self, identifier):
            raise RuntimeError("no active request")

    facts = middleware.connection_facts(SimpleNamespace(fastmcp_context=_Ctx()))
    assert facts["protocol"] == "2025-11-25" and facts["client"] == "unknown"
    assert facts["tasks"] is False
```

- [ ] **Step 7: Run the middleware tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_middleware.py -q --no-cov`
Expected: FAIL — `AttributeError: module 'amicus.middleware' has no attribute 'ConnectionLogMiddleware'`.

- [ ] **Step 8: Implement the connection log**

In `src/amicus/middleware.py`, add `from amicus import obs` to the imports, add the constant next to `RESOURCE_NOT_FOUND_MODERN`:

```python
TASKS_EXTENSION_ID = "io.modelcontextprotocol/tasks"
```

and add, before `class InputSchemaDialectMiddleware`:

```python
def connection_facts(context: object) -> dict[str, Any]:
    """What a tool call's connection negotiated: the protocol version, the handshake-era
    clientInfo (modern connections carry none) and whether the client declared the tasks
    extension for this request. Every read is defensive: an in-memory client, a legacy
    session and a sessionless request each lack some of these."""
    fastmcp_context = getattr(context, "fastmcp_context", None)
    request_context = getattr(fastmcp_context, "request_context", None)
    version = getattr(request_context, "protocol_version", None)
    session = None
    if fastmcp_context is not None:
        try:
            session = fastmcp_context.session
        except RuntimeError:
            session = None
    params = getattr(session, "client_params", None)
    # `client_info` on the MCP SDK v2; `clientInfo` is the pre-v2 alias (see Task 2's fix).
    info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
    name = getattr(info, "name", None)
    client_version = getattr(info, "version", None)
    tasks = False
    if fastmcp_context is not None:
        try:
            tasks = fastmcp_context.client_extension_settings(TASKS_EXTENSION_ID) is not None
        except Exception:
            tasks = False
    return {
        "protocol": str(version) if version else "unknown",
        "client": name if isinstance(name, str) and name else "unknown",
        "client_version": (
            client_version if isinstance(client_version, str) and client_version else "unknown"
        ),
        "tasks": tasks,
    }


class ConnectionLogMiddleware(Middleware):
    """One DEBUG line per tool call naming what the connection negotiated. The line carries
    the tool NAME and connection facts only, never an argument (AGENTS.md rule 18); it is
    the instrument behind the host captures under docs/host-captures/ (M5)."""

    async def on_call_tool(self, context, call_next):  # type: ignore[no-untyped-def]
        facts = connection_facts(context)
        obs.get_logger(__name__).debug(
            "tools/call %s: protocol=%s client=%s/%s tasks_negotiated=%s",
            getattr(getattr(context, "message", None), "name", "?"),
            facts["protocol"],
            facts["client"],
            facts["client_version"],
            facts["tasks"],
        )
        return await call_next(context)
```

In `src/amicus/server.py`, import `ConnectionLogMiddleware` alongside the other three and register it first:

```python
    app.add_middleware(ConnectionLogMiddleware())
    app.add_middleware(InputSchemaDialectMiddleware())
    app.add_middleware(SemanticErrorMiddleware())
    app.add_middleware(ValidationEnvelopeMiddleware(app, settings))
    app.add_middleware(ResourceErrorMiddleware())
```

Update the module docstring's first line to `"""FastMCP middlewares: connection log, schema dialect, semantic isError, the invalid_arguments`.

- [ ] **Step 9: Run the middleware tests**

Run: `uv run --no-sync pytest tests/test_middleware.py tests/test_server.py -q --no-cov`
Expected: all pass. Diagnose by symptom:
- `client=unknown/unknown` missing on the modern line: the in-memory modern client sent clientInfo after all; read what the line says and, if a name is present, change the modern assertion to `"client=unknown/" not in modern` and note it in the commit body (the capture test only needs the legacy branch).
- `protocol=2025-11-25` missing: `Client(app, mode="legacy")` negotiated a different legacy version; assert `"protocol=2026-07-28" not in legacy` instead.

Run: `uv run --no-sync pytest -q`
Expected: green.

- [ ] **Step 10: Commit the middleware**

```bash
git add src/amicus/middleware.py src/amicus/server.py tests/test_middleware.py
git commit -m "feat(middleware): log what each tool call's connection negotiated"
```

---

### Task 3: Task-map recording, `meta.task_id`, Docket timing, and the in-memory task-client suite

**Files:**
- Modify: `src/amicus/jobs/lifecycle.py:373-389` (`run_sync`; add `current_task_id`, `_with_task_id`)
- Modify: `src/amicus/tools/consult.py:95-103`, `tools/review.py:128-136`, `tools/review.py:263-271`, `tools/delegate.py:90-98` (pass `task_map`)
- Modify: `src/amicus/server.py:119-131` (extension timing)
- Test: `tests/test_lifecycle.py` (four new tests), `tests/test_server.py` (one new test), `tests/test_tasks_client.py` (new)

**Interfaces:**
- Consumes: `TaskJobMap.record(task_id, job_id)`, `.job_for(task_id)`, `.entries()` (`amicus.jobs.taskmap`); `lookup.task_map(settings) -> TaskJobMap` (`amicus.jobs.lookup`); `lifecycle.SYNC_AWAIT_GRACE_S = 30`.
- Produces: `lifecycle.current_task_id() -> str | None`; `lifecycle.run_sync(store, spec, meta, plugin, *, timeout, detail, ctx, task_map: TaskJobMap | None = None)`; `server.tasks_redelivery_seconds(settings) -> int`.

- [ ] **Step 1: Write the failing lifecycle and server tests**

In `tests/test_lifecycle.py`, add `import builtins` and `from amicus.jobs.taskmap import TaskJobMap` to the imports, then append:

```python
def test_current_task_id_is_none_outside_a_task_and_without_the_extension(monkeypatch):
    assert lifecycle.current_task_id() is None
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastmcp_tasks"):
            raise ImportError("no fastmcp_tasks")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert lifecycle.current_task_id() is None


def test_current_task_id_ignores_a_blank_task_context(monkeypatch):
    import fastmcp_tasks.context as task_context

    class _Info:
        task_id = ""

    monkeypatch.setattr(task_context, "get_task_context", lambda: _Info())
    assert lifecycle.current_task_id() is None
    monkeypatch.setattr(task_context, "get_task_context", lambda: None)
    assert lifecycle.current_task_id() is None


async def test_run_sync_records_the_task_id_when_inside_a_task(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")
    task_map = TaskJobMap(tmp_path / "tasks.json")
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
        task_map=task_map,
    )
    assert out["ok"] is True and out["meta"]["task_id"] == "task-abc"
    assert task_map.job_for("task-abc") == out["meta"]["job_id"]


async def test_run_sync_outside_a_task_records_nothing(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    task_map = TaskJobMap(tmp_path / "tasks.json")
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
        task_map=task_map,
    )
    assert out["ok"] is True and "task_id" not in out["meta"]
    assert task_map.entries() == {}


async def test_run_sync_survives_a_task_map_write_failure(tmp_path, monkeypatch, caplog):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")

    class _BrokenMap:
        def record(self, task_id, job_id):
            raise OSError("disk full")

    spec = _spec(str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="amicus.jobs.lifecycle"):
        out = await lifecycle.run_sync(
            store,
            spec,
            meta_for(spec),
            fakeplugin.make_plugin(),
            timeout=10,
            detail="summary",
            ctx=None,
            task_map=_BrokenMap(),
        )
    assert out["ok"] is True and out["meta"]["task_id"] == "task-abc"
    assert any("task map" in r.getMessage() for r in caplog.records)


async def test_run_sync_spawn_failure_still_carries_the_task_id(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", lambda job_dir: ["/nonexistent/worker"])
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
        task_map=TaskJobMap(tmp_path / "tasks.json"),
    )
    assert out["ok"] is False and out["meta"]["task_id"] == "task-abc"
    assert TaskJobMap(tmp_path / "tasks.json").entries() == {}
```

Add `import logging` to the imports too.
Check how the existing `test_spawn_failure_is_an_internal_error_with_no_record` makes the spawn fail (lines 122–141) and reuse its exact mechanism for the last test if it differs from a nonexistent worker path.

In `tests/test_server.py`, append:

```python
def test_tasks_extension_redelivery_covers_the_sync_deadline():
    from datetime import timedelta

    settings = config.settings({"AMICUS_TASKS": "1", "AMICUS_JOB_MAX_SECONDS": "120"})
    app = server.create_app(settings, BackendRegistry({}, {}))
    ext = app._extensions["io.modelcontextprotocol/tasks"]
    assert server.tasks_redelivery_seconds(settings) == 150
    assert ext.docket_settings.redelivery_timeout == timedelta(seconds=150)
    assert ext.docket_settings.url == "memory://"
```

(If `AMICUS_JOB_MAX_SECONDS` has a floor above 120 in `config/__init__.py`, use a value at the floor and adjust `150` to floor + 30.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_lifecycle.py tests/test_server.py -q --no-cov`
Expected: FAIL — `AttributeError: module 'amicus.jobs.lifecycle' has no attribute 'current_task_id'`, and `TypeError: run_sync() got an unexpected keyword argument 'task_map'`, and `AttributeError: ... 'tasks_redelivery_seconds'`.

- [ ] **Step 3: Implement the lifecycle change**

In `src/amicus/jobs/lifecycle.py`, add `from amicus import obs` to the imports and `from amicus.jobs.taskmap import TaskJobMap` under `TYPE_CHECKING`, then replace `run_sync` with:

```python
def current_task_id() -> str | None:
    """The tasks-extension task id when this coroutine runs inside a task-augmented call
    (ADR 0004), else None. The import is lazy: the extension is only active under
    AMICUS_TASKS=1, and a server without it must never pay for the import."""
    try:
        from fastmcp_tasks.context import get_task_context  # noqa: PLC0415
    except ImportError:
        return None
    task_id = getattr(get_task_context(), "task_id", None)
    return task_id if isinstance(task_id, str) and task_id else None


def _with_task_id(envelope: dict[str, Any], task_id: str | None) -> dict[str, Any]:
    meta = envelope.get("meta")
    if task_id is not None and isinstance(meta, dict):
        meta["task_id"] = task_id
    return envelope


async def run_sync(
    store: JobStore,
    spec: RunSpec,
    meta: Meta,
    plugin: BackendPlugin,
    *,
    timeout: int,
    detail: str,
    ctx: Any,
    task_map: TaskJobMap | None = None,
) -> dict[str, Any]:
    """The synchronous paid-tool tail: start the detached job and await it. Under a
    task-augmented call the task id is recorded against the job as soon as the job exists,
    so amicus_job_list(task_id=...) recovers it after a cancel or after the task's result
    window lapses, and it rides meta.task_id on whatever envelope is returned."""
    handle = await start_job(store, spec, meta, plugin, deadline=timeout)
    task_id = current_task_id()
    if handle.get("ok") is False:
        return _with_task_id(handle, task_id)
    job_id = handle["job_id"]
    if task_id is not None and task_map is not None:
        try:
            await asyncio.to_thread(task_map.record, task_id, job_id)
        except OSError as exc:
            obs.get_logger(__name__).warning(
                "task map write failed for task %s -> job %s: %s",
                task_id,
                job_id,
                redaction.exc_summary(exc),
            )
    envelope = await await_job_result(
        store, spec.cwd, job_id, spec.kind, meta, detail, timeout, ctx, plugin
    )
    return _with_task_id(envelope, task_id)
```

`redaction` is already imported in this module; confirm `redaction.exc_summary` exists (`tools/_guard.py` imports it from `pontonier.core.redaction`).

- [ ] **Step 4: Pass the task map from the four sync tools**

In `src/amicus/tools/consult.py`, `tools/review.py` and `tools/delegate.py`, change the `from amicus.jobs import lifecycle` import to `from amicus.jobs import lifecycle, lookup` and add `task_map=lookup.task_map(settings),` as the last keyword of every `lifecycle.run_sync(` call in the SYNC tools (`amicus_consult`, `amicus_review_changes`, `amicus_adversarial_review`, `amicus_delegate`; four call sites; the `_async` twins call `start_async`, untouched).

- [ ] **Step 5: Implement the extension timing**

In `src/amicus/server.py`, add `from datetime import timedelta` and `from amicus.jobs.lifecycle import SYNC_AWAIT_GRACE_S` to the imports, add after `UI_EXTENSION_ID`:

```python
def tasks_redelivery_seconds(settings: Settings) -> int:
    """Docket's redelivery_timeout for the tasks extension: longer than any sync run can
    take (deadline plus the await grace), so a healthy worker is never asked to re-run a
    paid call. Docket renews a running task's lease anyway; this is belt and braces
    (ADR 0011)."""
    return settings.job_max_seconds + SYNC_AWAIT_GRACE_S
```

(`Settings` is imported under `TYPE_CHECKING` in this module already; move the import out from under `TYPE_CHECKING` only if `ty` requires it, otherwise keep the string annotation as `from __future__ import annotations` makes it valid.)

and change the extension construction to:

```python
            app.add_extension(
                TasksExtension(
                    url=settings.tasks_backend_url,
                    redelivery_timeout=timedelta(seconds=tasks_redelivery_seconds(settings)),
                )
            )
```

- [ ] **Step 6: Run the lifecycle and server tests**

Run: `uv run --no-sync pytest tests/test_lifecycle.py tests/test_server.py tests/test_sync_tools.py tests/test_tasks_spike.py -q --no-cov`
Expected: all pass.

- [ ] **Step 7: Commit the wiring**

```bash
git add src/amicus/jobs/lifecycle.py src/amicus/server.py src/amicus/tools/consult.py src/amicus/tools/review.py src/amicus/tools/delegate.py tests/test_lifecycle.py tests/test_server.py
git commit -m "feat(tasks): record the task behind a sync run and bound docket redelivery"
```

- [ ] **Step 8: Write the in-memory task-client suite**

`tests/test_tasks_client.py`:

```python
"""In-memory task-client tests (M5 gate): the paid sync tools behind AMICUS_TASKS=1 driven
through fastmcp[tasks] against the real codex plugin and the fake codex executable. Proves
delivery parity, isError on the tasked path, task-map recording and recovery through
amicus_job_list(task_id=...), cancel propagation to the job record, the legacy-era plain
result, the task result window and the redelivery guard."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from datetime import timedelta

import pytest
from fastmcp import Client, FastMCP

from amicus import config, server
from amicus.jobs import lifecycle, lookup
from amicus.registry import BackendRegistry
from amicus.schemas.results import PAID_TOOLS

pytest.importorskip("fastmcp_tasks")
from fastmcp_tasks import TasksExtension, call_tool_task

TASKS = "io.modelcontextprotocol/tasks"


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    monkeypatch.setenv("AMICUS_TASKS", "1")
    monkeypatch.setenv("AMICUS_TASKS_BACKEND_URL", "memory://")
    for key in (
        "FAKE_CODEX_EXIT",
        "FAKE_CODEX_STDERR",
        "FAKE_CODEX_ANSWER",
        "FAKE_CODEX_WRITE",
        "FAKE_CODEX_EVENTS",
        "FAKE_CODEX_SLEEP",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


@pytest.fixture
def settings(app):
    return server.state_of(app).settings


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.co")
    _git(r, "config", "user.name", "t")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    (r / "a.py").write_text("x = 2\n")
    return r


async def _wait(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.05)


async def test_tasked_consult_delivers_the_plain_envelope_plus_task_id(
    app, settings, tmp_path, caplog
):
    args = {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path)}
    with caplog.at_level(logging.DEBUG, logger="amicus.middleware"):
        async with Client(app) as c:
            task = await call_tool_task(c, "amicus_consult", args)
            result = await task.result()
            status = await task.status()
    body = result.structured_content
    assert result.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    assert body["meta"]["task_id"] == task.task_id and body["meta"]["job_id"]
    assert status.status == "completed"
    assert lookup.task_map(settings).job_for(task.task_id) == body["meta"]["job_id"]
    assert any(
        "tools/call amicus_consult: " in r.getMessage() and "tasks_negotiated=True" in r.getMessage()
        for r in caplog.records
    )


async def test_tasked_failure_is_an_error_result_with_the_task_id(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_EXIT", "1")
    monkeypatch.setenv("FAKE_CODEX_STDERR", "Error: not logged in; run `codex login`")
    args = {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)}
    async with Client(app) as c:
        task = await call_tool_task(c, "amicus_consult", args, raise_on_error=False)
        result = await task.result()
    assert result.is_error is True  # the M0 finding, closed by the guard
    body = result.structured_content
    assert body["error"]["code"] == "backend_auth_required"
    assert body["meta"]["task_id"] == task.task_id and body["meta"]["job_id"]


async def test_zero_spend_refusal_is_an_error_result_and_records_no_task(app, settings, tmp_path):
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False
        )
        result = await task.result()
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "invalid_workspace_root"
    assert lookup.task_map(settings).entries() == {}
    assert not (tmp_path / "argv.jsonl").exists()


async def test_job_list_recovers_the_job_behind_a_task(app, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q", **ws}
        )
        body = (await task.result()).structured_content
        job_id = body["meta"]["job_id"]
        listed = (
            await c.call_tool("amicus_job_list", {"task_id": task.task_id, **ws})
        ).structured_content
        assert [j["job_id"] for j in listed["jobs"]] == [job_id]
        assert listed["jobs"][0]["task_id"] == task.task_id
        status = (
            await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})
        ).structured_content
        assert status["task_id"] == task.task_id
        stored = (
            await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})
        ).structured_content
        assert stored["ok"] is True and stored["meta"]["task_id"] == task.task_id
        none = (await c.call_tool("amicus_job_list", {"task_id": "nope", **ws})).structured_content
        assert none["jobs"] == []


async def test_cancelling_a_task_cancels_its_job(app, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "30")
    store = lifecycle.job_store(settings)
    task_map = lookup.task_map(settings)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q", **ws}, raise_on_error=False
        )
        await _wait(lambda: task_map.job_for(task.task_id) is not None)
        job_id = task_map.job_for(task.task_id)
        assert store.status(str(tmp_path), job_id)["status"] == "running"
        await task.cancel()
        await _wait(lambda: store.status(str(tmp_path), job_id)["status"] == "cancelled")
        final = await task.status()
        assert final.status == "cancelled"
        listed = (
            await c.call_tool("amicus_job_list", {"task_id": task.task_id, **ws})
        ).structured_content
        assert listed["jobs"][0]["status"] == "cancelled"


async def test_tasked_review_runs_the_second_verb(app, repo):
    async with Client(app) as c:
        task = await call_tool_task(
            c,
            "amicus_review_changes",
            {"backend": "codex", "workspace_root": str(repo), "scope": "working_tree"},
        )
        result = await task.result()
    body = result.structured_content
    assert result.is_error is False and body["ok"] is True
    assert body["review_status"] == "reviewed" and body["meta"]["task_id"] == task.task_id


async def test_all_four_paid_sync_tools_are_task_tools_and_nothing_else_is(app):
    for name in PAID_TOOLS:
        assert (await app.get_tool(name)).task_config.supports_tasks(), name
        assert not (await app.get_tool(f"{name}_async")).task_config.supports_tasks(), name
    for name in ("amicus_backends", "amicus_capabilities", "amicus_dry_run", "amicus_job_list"):
        assert not (await app.get_tool(name)).task_config.supports_tasks(), name


async def test_legacy_era_client_gets_a_plain_result(app, tmp_path, caplog):
    with caplog.at_level(logging.DEBUG, logger="amicus.middleware"):
        async with Client(app, mode="legacy") as c:
            res = await c.call_tool(
                "amicus_consult",
                {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)},
            )
    body = res.structured_content
    assert body["ok"] is True and "task_id" not in body["meta"]
    assert any("tasks_negotiated=False" in r.getMessage() for r in caplog.records)


async def test_task_result_window_is_docket_execution_ttl(app, settings, tmp_path):
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)}
        )
        await task.result()
    # Docket's execution_ttl default; TasksExtension 4.0.x cannot set it. The job record
    # outlives the task result (AMICUS_JOB_TTL), which the capability summary says.
    assert task.create_result.ttl_ms == 15 * 60 * 1000
    assert settings.job_ttl_seconds * 1000 > task.create_result.ttl_ms


def test_redelivery_timeout_is_the_sync_deadline_plus_grace(app, settings):
    ext = app._extensions[TASKS]
    assert ext.docket_settings.redelivery_timeout == timedelta(
        seconds=settings.job_max_seconds + lifecycle.SYNC_AWAIT_GRACE_S
    )


async def test_a_live_task_outlasting_redelivery_timeout_runs_once():
    """Docket renews a running task's lease, so a run longer than redelivery_timeout is not
    re-executed (which would be double spend). If this ever fails, lease renewal regressed:
    keep the server-side redelivery_timeout override and record the finding in ADR 0011."""
    scratch = FastMCP(name="scratch")
    scratch.add_extension(
        TasksExtension(url="memory://", redelivery_timeout=timedelta(milliseconds=300))
    )
    runs: list[float] = []

    @scratch.tool(name="slow", task=True)
    async def slow() -> dict:
        runs.append(time.monotonic())
        await asyncio.sleep(1.2)
        return {"ok": True}

    async with Client(scratch) as c:
        task = await call_tool_task(c, "slow", {})
        result = await task.result()
    assert result.structured_content == {"ok": True} and len(runs) == 1
```

- [ ] **Step 9: Run the suite**

Run: `uv run --no-sync pytest tests/test_tasks_client.py -q --no-cov -x -v`
Expected: all pass (about 40 s: two runs sleep). Diagnose by symptom:
- `test_tasked_review_runs_the_second_verb` fails on `review_status`: read `tests/test_sync_tools.py::test_review_end_to_end_and_not_run` for the exact arguments the fake codex review needs and mirror them.
- `test_cancelling_a_task_cancels_its_job` times out waiting for `cancelled`: check `store.status(...)` is keyed by the same cwd string `amicus_job_list` uses (`str(tmp_path)` works in `tests/test_job_tools.py`); if the record stays `running`, the cooperative cancel never reached `await_job_result` — print `await task.status()` and inspect whether Docket reports `cancelled`; a `working` status after `task.cancel()` is a library finding to record, not a test to weaken.
- `test_a_live_task_outlasting_redelivery_timeout_runs_once` sees two runs: lease renewal did not hold; the server-side override in Task 3 Step 5 is then load-bearing — record the finding in ADR 0011 (Task 6) and keep the test as `len(runs) == 1` only if a smaller `minimum_check_interval` fixes it; otherwise report to the maintainer before changing the assertion.
- `client=unknown/unknown` in the first test: not asserted here; ignore.

Run: `uv run --no-sync pytest -q`
Expected: green, coverage ≥ 95%.

- [ ] **Step 10: Commit**

```bash
git add tests/test_tasks_client.py
git commit -m "test(tasks): drive the paid tools through the in-memory task client"
```

---

### Task 4: The surface change (one commit) and the pin regeneration (one commit)

**Files:**
- Modify: `src/amicus/server.py:33-71` (`CAPABILITY_SUMMARY`), `src/amicus/tools/discovery.py:68-112,538-546`, `src/amicus/schemas/codes.py:30-35,93-97`, `src/amicus/errors.py:46-52`, `src/amicus/schemas/fingerprint.py:7`, `README.md:6-10`
- Modify tests: `tests/test_codes.py:43`, `tests/test_errors.py:20,115-116`, `tests/test_discovery.py:89`
- Regenerate: `tests/fixtures/manifest_snapshot.*.json`, `tests/fixtures/wire_shape_snapshot.json`, `tests/fixtures/result_format_snapshot.json`, `tests/test_manifest.py`, `tests/test_fingerprint.py`, `tests/test_discovery_cost.py`

This is the ONLY task that moves the agent-visible surface. Every change is deliberate and named in the PR body; the pins are regenerated in a dedicated second commit (AGENTS.md rule 10).

- [ ] **Step 1: Reword the capability summary**

In `src/amicus/server.py`, inside `CAPABILITY_SUMMARY`, replace the sentence

```
    "Target protocol: MCP 2026-07-28, served dual-era (2025-11-25 clients negotiate the "
    "initialize handshake); the io.modelcontextprotocol/tasks extension is advertised "
    "only when AMICUS_TASKS=1. "
```

with

```
    "Target protocol: MCP 2026-07-28, served dual-era (2025-11-25 clients negotiate the "
    "initialize handshake). The io.modelcontextprotocol/tasks extension is advertised only "
    "when AMICUS_TASKS=1, and only a modern-era client that declares it gets a task; a "
    "handshake-era client always gets the plain result (Claude Code and Codex CLI both do, "
    "captured in docs/host-captures/). "
```

and replace the sentences

```
    "When a task-augmented call returns resultType: task, a `completed` task is a "
    "delivery statement, not a success statement: inspect the delivered result's ok "
    "field. amicus_job_list(task_id=...) recovers the durable job behind a task, and the "
    "amicus_job_* tools are the fallback for every host without the tasks extension. "
    "Job handles expire after AMICUS_JOB_TTL (default 24h); read results promptly. "
```

with

```
    "When a task-augmented call returns resultType: task, a `completed` task is a "
    "delivery statement, not a success statement: inspect the delivered result's ok "
    "field (isError is set on it too). Cancelling a task cancels its job. A task result "
    "stays readable through tasks/get for 15 minutes after completion; the job behind it "
    "(meta.task_id, meta.job_id) outlives that for AMICUS_JOB_TTL, amicus_job_list("
    "task_id=...) recovers it, and the amicus_job_* tools are the fallback for every host "
    "without the tasks extension. "
    "Job handles expire after AMICUS_JOB_TTL (default 24h); read results promptly. "
```

- [ ] **Step 2: Reword the `amicus_capabilities` tasks block and drop `not_implemented` from the inventory**

In `src/amicus/tools/discovery.py`:
- Remove the `"not_implemented",` line from `_COMMON_PAID_CODES` (line 90).
- Delete the comment block and the `_COMMON_PAID_CODES_SYNC = ...` line (lines 104–112 region: the three comment lines starting `# Lifecycle codes a sync tool's` stay, minus the clause about `not_implemented`, and become `# Lifecycle codes a sync tool's amicus_job_result-shaped envelope can carry once` / `# lifecycle.run_sync reaches jobs/delivery.py's STATE_TO_ERROR.`).
- Replace every `_COMMON_PAID_CODES_SYNC` with `_COMMON_PAID_CODES` (six uses: lines 128, 135, 142, 149, 160, 173).
- Replace the `fallback=(...)` text of `TaskSupport` with:

```python
            fallback=(
                "A `completed` task is a delivery statement, not a success statement: inspect "
                "the delivered result's ok field (isError is set on it too). Only a modern-era "
                "client that declares the extension gets a task; a handshake-era client gets "
                "the plain result. A task result is readable through tasks/get for 15 minutes "
                "after completion; the job behind it outlives that for AMICUS_JOB_TTL, "
                "amicus_job_list(task_id=...) recovers it, cancelling the task cancels the job, "
                "and every host can use the amicus_job_* tools instead."
            ),
```

- [ ] **Step 3: Drop `not_implemented` from the catalog, the enum, the repair table, and bump the fingerprint**

`src/amicus/schemas/codes.py`: delete the two lines `# The tool is registered but its backend has not landed in this release.` and `"not_implemented",` from `LOCAL_CODES`; delete `"not_implemented",` from the `ErrorCode` literal.
`src/amicus/errors.py`: delete the whole `"not_implemented": RepairRule(...)` entry from `_LOCAL_RULES`.
`src/amicus/schemas/fingerprint.py`: `FINGERPRINT = "amicus/0.1/schema-5"`.

Tests:
- `tests/test_codes.py`: delete `"not_implemented",` from the `LOCAL_CODES` set literal.
- `tests/test_errors.py:20`: replace `assert table["not_implemented"].tool == "amicus_capabilities"` with `assert table["backend_unavailable"].tool == "amicus_backends"` (check `_LOCAL_RULES["backend_unavailable"]`'s tool first and use whatever it names).
- `tests/test_errors.py:115-116`: change `"not_implemented"` to `"feature_unsupported"` in both lines.
- `tests/test_discovery.py:89`: delete `"not_implemented",` from the accepted-codes set.
- `grep -rn "not_implemented" src tests docs/adr README.md` must then show only `docs/superpowers/plans/` and ADR history text; anything else is a missed site.

`README.md`: change `**Status:** milestone M4 (Claude Code).` to `**Status:** milestone M5 (tasks extension).` and replace the line `` `task=True` wiring lands in M5. `` with:

```
With `AMICUS_TASKS=1` the four paid sync tools are also tasks for a modern-era client that declares the `io.modelcontextprotocol/tasks` extension; both v1 hosts negotiate the handshake era and get plain results (`docs/host-captures/`).
```

- [ ] **Step 4: Run the non-pin tests, then commit the surface change (pins still old, so the pin tests fail — expected)**

Run: `uv run --no-sync pytest tests/test_codes.py tests/test_errors.py tests/test_discovery.py tests/test_paid_tools.py tests/test_server.py tests/test_tasks_client.py -q --no-cov`
Expected: all pass (`test_errors::test_repair_table_covers_the_whole_catalog_and_no_more` passes because `_LOCAL_RULES` lost exactly the code the catalog lost).

Run: `uv run --no-sync pytest tests/test_manifest.py tests/test_fingerprint.py tests/test_wire_shape.py tests/test_result_format.py tests/test_discovery_cost.py -q --no-cov`
Expected: FAIL on the golden comparisons — the surface moved. The ratchet (`test_discovery_cost.py`) most likely PASSES: dropping a code from every error enum shrinks tools/list.

```bash
git add src/amicus/server.py src/amicus/tools/discovery.py src/amicus/schemas/codes.py src/amicus/schemas/fingerprint.py src/amicus/errors.py README.md tests/test_codes.py tests/test_errors.py tests/test_discovery.py
git commit -m "feat(schemas)!: say what a task delivers and drop the dead not_implemented code"
```

(The `!` marks the fingerprint bump; the body lists the three surface moves: summary wording, `tasks.fallback` wording, the removed code.)

- [ ] **Step 5: Regenerate every pin in a dedicated commit**

```bash
for p in all codex-kimi claude; do
  uv run --no-sync python -m amicus.manifest --profile "$p" > "tests/fixtures/manifest_snapshot.$p.json"
done
uv run --no-sync python -m amicus.wire_shape_snapshot > tests/fixtures/wire_shape_snapshot.json
uv run --no-sync python -m amicus.result_format_snapshot > tests/fixtures/result_format_snapshot.json
uv run --no-sync python -m amicus.manifest --measure
uv run --no-sync python - <<'EOF'
import asyncio
from amicus import manifest, surface
async def main():
    for p in sorted(manifest.PROFILES):
        app = manifest.app_for_profile(p)
        print(p, "manifest_hash", await manifest.manifest_hash(app))
        print(p, "surface_digest", await surface.surface_digest(app))
asyncio.run(main())
EOF
```

Then:
- `tests/test_manifest.py::EXPECTED_MANIFEST_HASH` ← the three `manifest_hash` values.
- `tests/test_fingerprint.py::EXPECTED_SURFACE_DIGEST` ← the three `surface_digest` values.
- `tests/test_discovery_cost.py::MEASURED` ← the three `--measure` values; change the docstring line to `Measured 2026-09-07 at schema-5 (18 tools; tasks wording, not_implemented dropped): see MEASURED.`

Review the snapshot diff before committing: `git diff --stat tests/fixtures && git diff tests/fixtures/manifest_snapshot.all.json | grep '^[-+]' | grep -v '^[-+][-+]' | head -80`.
Every hunk must be one of: the two summary sentences (in `instructions`), the `tasks.fallback` text, `not_implemented` leaving an `error_codes` list or an enum, the fingerprint string.
Anything else is an unexplained surface move: stop and find it.
`tests/fixtures/result_format_snapshot.json` is expected to change only in the fingerprint string (`RESULT_FORMAT` stays 2); `wire_shape_snapshot.json` likewise.

Run: `uv run --no-sync pytest -q`
Expected: green.

```bash
git add tests/fixtures tests/test_manifest.py tests/test_fingerprint.py tests/test_discovery_cost.py
git commit -m "chore(schemas): regenerate the pins for schema-5"
```

The commit body lists the per-profile byte deltas from `--measure` (old `92082 / 92090 / 92082` → new).

---

### Task 5: The M4 follow-ups that do not move the surface

**Files:**
- Modify: `src/amicus/orchestration/prompts.py:73-84`
- Modify: `src/amicus/backends/claude/contract.py:100-110,166`
- Modify: `src/amicus/backends/kimi/cli.py:29`, `src/amicus/backends/kimi/adapter.py:14-20,180`
- Test: `tests/test_adversarial.py`, `tests/test_claude_contract.py:59-60,100-123`, `tests/test_kimi_cli.py:161-163`, `tests/test_kimi_argv_differential.py:45-48`, `tests/test_structured.py` (new)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adversarial.py`:

```python
def test_framing_for_refuses_an_unknown_verb():
    with pytest.raises(ValueError, match="unknown verb 'transfer'"):
        prompts.framing_for(None, "transfer", "Codex")
```

In `tests/test_claude_contract.py`, in the `test_failure_signatures` parameter table, add two rows after the `"Permission denied for tool Read."` row:

```python
        ("Access denied.", False, False, False, False, True, False, False),
        ("The reviewer denied the claim.", False, False, False, False, False, False, False),
```

and delete the two lines `assert "usage" in contract.ENVELOPE_KEYS` and `assert contract.USAGE_KEYS.isdisjoint(contract.ENVELOPE_KEYS)`, replacing them with `assert "input_tokens" in contract.USAGE_KEYS`.

Create `tests/test_structured.py`:

```python
"""schemas.structured: the schema instruction appended to a structured-output prompt."""

from __future__ import annotations

from amicus.schemas.structured import schema_instruction


def test_schema_instruction_names_the_schema():
    text = schema_instruction({"type": "object"})
    assert text.startswith("\n\n# Required output format") and '"type": "object"' in text
```

Delete `test_schema_instruction_names_the_schema` from `tests/test_kimi_cli.py` (lines 161–163).
In `tests/test_kimi_argv_differential.py`, add `from amicus.schemas.structured import schema_instruction` to the imports and change line 48 to `assert schema_instruction({"type": "object"}) == FIXTURE["schema_instruction"]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_adversarial.py::test_framing_for_refuses_an_unknown_verb tests/test_claude_contract.py -q --no-cov`
Expected: FAIL — `KeyError: 'transfer'` (not a `ValueError`), and the `"The reviewer denied the claim."` row fails on `is_permission_denied`.

- [ ] **Step 3: Implement**

`src/amicus/orchestration/prompts.py`, `framing_for`:

```python
def framing_for(plugin: BackendPlugin | None, verb: str, host_name: str) -> str:
    """The user-turn framing for `verb`: the shared base, then the plugin's framing hook if it
    has one (the seam a backend uses to add its own stance per run; the host name is
    per-connection, so this is the one place a backend can name it)."""
    if verb == "adversarial_review":
        base = adversarial_framing(host_name)
    elif verb in _FRAMING_ATTR:
        base = getattr(_pp.framings(host_name), _FRAMING_ATTR[verb])
    else:
        known = sorted((*_FRAMING_ATTR, "adversarial_review"))
        raise ValueError(f"framing_for: unknown verb {verb!r}; expected one of {known}")
    if plugin is not None and plugin.framing is not None:
        return plugin.framing.frame(verb, base, host_name)
    return base
```

`src/amicus/backends/claude/contract.py`: delete the `ENVELOPE_KEYS = frozenset({...})` block (keep `USAGE_KEYS`), and change `_PERMISSION_PATTERNS` to:

```python
_PERMISSION_PATTERNS = (
    re.compile(r"\bpermission\b", re.I),
    re.compile(r"\baccess denied\b", re.I),
)
```

`src/amicus/backends/kimi/cli.py`: delete line 29 (`from amicus.schemas.structured import schema_instruction  # noqa: F401 ...`).
`src/amicus/backends/kimi/adapter.py`: add `from amicus.schemas.structured import schema_instruction` to the imports and change `cli.schema_instruction(request.schema)` to `schema_instruction(request.schema)`.

- [ ] **Step 4: Run the tests**

Run: `uv run --no-sync pytest tests/test_adversarial.py tests/test_claude_contract.py tests/test_claude_cli.py tests/test_claude_result_differential.py tests/test_kimi_cli.py tests/test_kimi_argv_differential.py tests/test_kimi_adapter.py tests/test_structured.py -q --no-cov`
Expected: all pass. If a Claude differential case fails on `claude_permission_error`, its text is the fixture's `"Permission denied for tool Read."`, which still matches `\bpermission\b`; any other text is a real finding — stop and report it rather than widening the pattern back.

Run: `uv run --no-sync pytest tests/test_manifest.py tests/test_fingerprint.py -q --no-cov`
Expected: pass (no pin moved).

Run: `uv run --no-sync pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/amicus/orchestration/prompts.py src/amicus/backends/claude/contract.py src/amicus/backends/kimi/cli.py src/amicus/backends/kimi/adapter.py tests/test_adversarial.py tests/test_claude_contract.py tests/test_kimi_cli.py tests/test_kimi_argv_differential.py tests/test_structured.py
git commit -m "refactor(backends): close the M4 review follow-ups that move no surface"
```

---

### Task 6: ADRs, README index, and the Claude Code host capture

**Files:**
- Modify: `docs/adr/0004-tasks-and-jobs.md` (status, decision, an M5 section)
- Create: `docs/adr/0011-m5-tasks-decisions.md`
- Modify: `README.md` ("Where things are", "Resuming the work")
- Create: `docs/host-captures/claude-code/2.1.263/{FINDINGS.md,connection.log,host-output.json}`
- Test: `tests/test_host_captures.py` (new)

- [ ] **Step 1: Write the capture test (fails until the capture exists)**

`tests/test_host_captures.py`:

```python
"""The host captures (M5): each v1 host connected to amicus with AMICUS_TASKS=1 and called the
free amicus_backends; the connection line amicus logged is the evidence behind the capability
summary's claim that a handshake-era host always gets the plain result."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from mcp.types.version import MODERN_PROTOCOL_VERSIONS

CAPTURES = Path("docs/host-captures")
HOSTS = ["claude-code"]  # Task 7 adds "codex"
LINE = re.compile(
    r"tools/call amicus_backends: protocol=(?P<protocol>\S+) client=(?P<client>\S+) "
    r"tasks_negotiated=(?P<tasks>True|False)$"
)


def _capture_dir(host: str) -> Path:
    [version_dir] = [p for p in (CAPTURES / host).iterdir() if p.is_dir()]
    return version_dir


@pytest.mark.parametrize("host", HOSTS)
def test_each_host_capture_shows_a_handshake_era_plain_call(host):
    version_dir = _capture_dir(host)
    assert (version_dir / "FINDINGS.md").exists()
    matches = [
        m for m in (LINE.search(line) for line in (version_dir / "connection.log").read_text().splitlines()) if m
    ]
    assert matches, f"{host}: no tools/call line for amicus_backends in connection.log"
    for m in matches:
        assert m["protocol"] not in MODERN_PROTOCOL_VERSIONS, m.group(0)
        assert m["tasks"] == "False", m.group(0)
        assert not m["client"].startswith("unknown/"), m.group(0)


def test_the_capture_regex_accepts_a_known_positive_and_rejects_a_modern_tasked_line():
    good = "2026-09-07 12:00:00,000 DEBUG amicus.middleware: tools/call amicus_backends: protocol=2025-06-18 client=claude-code/2.1.263 tasks_negotiated=False"
    m = LINE.search(good)
    assert m and m["protocol"] not in MODERN_PROTOCOL_VERSIONS and m["tasks"] == "False"
    modern = "tools/call amicus_backends: protocol=2026-07-28 client=unknown/unknown tasks_negotiated=True"
    m2 = LINE.search(modern)
    assert m2 and m2["protocol"] in MODERN_PROTOCOL_VERSIONS and m2["tasks"] == "True"
```

Run: `uv run --no-sync pytest tests/test_host_captures.py -q --no-cov`
Expected: the parametrized test FAILS (`docs/host-captures/claude-code` does not exist); the regex test passes.

- [ ] **Step 2: Run the Claude Code capture**

The session scratchpad directory is `$SCRATCH` (the `Scratchpad directory` named in the session's system prompt; never `/tmp`).

```bash
SCRATCH=<the session scratchpad directory>
WT=/Users/bdc/projects/amicus-wt-m5
mkdir -p "$SCRATCH/captures/claude-code" "$SCRATCH/captures/state-claude"
cat > "$SCRATCH/captures/claude-mcp.json" <<EOF
{"mcpServers":{"amicus":{"command":"uv","args":["run","--no-sync","--project","$WT","amicus-mcp"],"env":{"AMICUS_TASKS":"1","AMICUS_LOG_LEVEL":"DEBUG","AMICUS_LOG_FILE":"$SCRATCH/captures/claude-code/amicus.log","AMICUS_STATE_DIR":"$SCRATCH/captures/state-claude"}}}}
EOF
cd "$SCRATCH/captures" && claude -p \
  --strict-mcp-config --mcp-config "$SCRATCH/captures/claude-mcp.json" \
  --allowedTools mcp__amicus__amicus_backends --max-turns 3 --output-format json \
  "Call the amicus_backends tool with no arguments, then reply with exactly the JSON object the tool returned and nothing else." \
  > "$SCRATCH/captures/claude-code/host-output.json"
grep "tools/call" "$SCRATCH/captures/claude-code/amicus.log"
claude --version
```

Expected: one or more `tools/call amicus_backends: protocol=<pre-2026 version> client=<name>/<version> tasks_negotiated=False` lines, and `host-output.json` holding the host's final JSON.
If `claude -p` refuses to start inside a Claude Code session, prefix the command with `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT`.
If the log shows no `tools/call` line, the host never called the tool: check `host-output.json` for a permission refusal and re-run with `--permission-mode acceptEdits` added; if the host called `amicus_backends` under a different tool name prefix, use the name the log shows in the test regex only if it still starts with `amicus_backends`.
Spend: one Claude Max turn; `amicus_backends` spends no backend quota.

- [ ] **Step 3: Record the capture**

```bash
mkdir -p "$WT/docs/host-captures/claude-code/2.1.263"
grep "tools/call" "$SCRATCH/captures/claude-code/amicus.log" > "$WT/docs/host-captures/claude-code/2.1.263/connection.log"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); d.pop('session_id', None); d.pop('uuid', None); print(json.dumps(d, indent=2, sort_keys=True))" "$SCRATCH/captures/claude-code/host-output.json" > "$WT/docs/host-captures/claude-code/2.1.263/host-output.json"
```

Read `host-output.json` before committing: it must hold no account identifier, no key, and no path under the home directory other than the worktree; drop any such field the same way `session_id` is dropped.
`connection.log` holds only amicus's own lines (no prompt text; the line format carries the tool name only).

`docs/host-captures/claude-code/2.1.263/FINDINGS.md`:

```markdown
# Claude Code 2.1.263 — amicus M5 host capture

Captured 2026-09-07 on the maintainer's machine with `claude -p` pointed at the M5 worktree's server (`AMICUS_TASKS=1`, `AMICUS_LOG_LEVEL=DEBUG`, `AMICUS_LOG_FILE`), asking the host to call the free `amicus_backends`.
One Claude Max turn was spent; no backend quota was spent.

## What the capture shows

- `connection.log`: every `tools/call amicus_backends` line amicus logged; the protocol version is a handshake-era one (`<paste the protocol= value>`), `clientInfo` is `<paste the client= value>`, and `tasks_negotiated=False`.
  `tests/test_host_captures.py` asserts exactly that against this file, after first proving the same regex accepts a known-positive line and reads a modern tasked line as modern.
- `host-output.json`: the host's final JSON (with `session_id` and `uuid` dropped); the tool ran and the host received an ordinary tool result, not a task.

## What this settles

- ADR 0004's "legacy fallback is claimed only after a host capture": Claude Code 2.1.263 negotiates the handshake era, where the tasks extension cannot be negotiated, so its calls always take the plain path even with `AMICUS_TASKS=1`.
- The capability summary and `amicus_capabilities.tasks.fallback` claim only this (Task 4 wording).
```

Fill the two angle-bracket placeholders from `connection.log`.

- [ ] **Step 4: Amend ADR 0004 and write ADR 0011**

`docs/adr/0004-tasks-and-jobs.md`: change the status line to

```
**Status:** Accepted (durable jobs 2026-09-06, M2; `task=True` 2026-09-07, M5; the keyed-task cancel clause amended by ADR 0011).
```

In the Decision section, replace the sentence `Cancellation propagation is explicit: an unkeyed task cancels its job; a keyed job survives and the cancel result names its `job_id`.` with:

```
Cancellation propagation is explicit and unconditional: a tasked call is always unkeyed (the sync tools carry no `idempotency_key`, ADR 0007), so cancelling a task cancels its job; `tasks/cancel` is an empty ack (SEP-2663), and the job behind a task is recovered with `amicus_job_list(task_id=...)`.
```

Append a section after the spike report:

```
## M5 wiring (2026-09-07)

- `isError`: produced by the tool itself (`tools._guard.as_tool_result` returns an `is_error` `ToolResult` for every `ok: false` envelope), so it survives task delivery; `SemanticErrorMiddleware` is a foreground safety net.
- `task_id → job_id`: recorded by `jobs.lifecycle.run_sync` right after the job exists, read through `fastmcp_tasks.context.get_task_context`; the id also rides `meta.task_id`.
- Cancel: `tasks/cancel` cancels the coroutine cooperatively and `await_job_result` cancels the job on `CancelledError`; proven end to end in `tests/test_tasks_client.py`.
- TTL: `ttlMs` is Docket's `execution_ttl` (15 minutes after completion) and `TasksExtension` 4.0.x cannot set it; the job record outlives it for `AMICUS_JOB_TTL`.
- Redelivery: Docket renews a running task's lease (a 1.2 s run past a 300 ms `redelivery_timeout` executes once); amicus still sets `redelivery_timeout` to the sync deadline plus grace.
- Hosts: Claude Code 2.1.263 and Codex CLI 0.153.4 negotiate the handshake era (`docs/host-captures/`), so today the extension serves only modern-era clients such as `fastmcp.Client`.
```

`docs/adr/0011-m5-tasks-decisions.md`:

```markdown
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
- One surface bump (`amicus/0.1/schema-4` → `schema-5`): the capability summary and `amicus_capabilities.tasks.fallback` say what a task delivers, when a task is returned, the 15-minute result window and the job that outlives it; the dead `not_implemented` code leaves the catalog.
  `RESULT_FORMAT` stays 2.
- The `isError` carrier is the `guard` wrapper: `tools._guard.as_tool_result` returns `ToolResult(structured_content=envelope, is_error=True)` for every `ok: false` envelope on both delivery paths; the wire shape equals FastMCP's own dict conversion (pinned by a parity test); `SemanticErrorMiddleware` stays as a foreground safety net.
- Task-map recording lives in `jobs.lifecycle.run_sync`, keyed by `lifecycle.current_task_id()` (the extension's `get_task_context`, imported lazily), through a `task_map` keyword the four sync tools pass; the id also rides `meta.task_id`; a map write failure is logged and never fails the run.
- Cancel propagation is the existing `CancelledError` path in `await_job_result`; nothing new is wired.
- `TasksExtension` gets `redelivery_timeout = AMICUS_JOB_MAX_SECONDS + SYNC_AWAIT_GRACE_S` as belt and braces; Docket's lease renewal already prevents re-execution of a live task, and a probe test pins that.
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
```

- [ ] **Step 5: README index**

In `README.md`'s "Where things are" table, add after the M4 plan row:

```
| The M5 plan (tasks extension) | `docs/superpowers/plans/2026-09-07-amicus-M5-tasks.md` |
```

and after the Kimi evidence row:

```
| Host captures (Claude Code, Codex CLI with `AMICUS_TASKS=1`) | `docs/host-captures/` |
```

In "Resuming the work", change `1. `main` carries M4.` to `1. `main` carries M5.` and the M5 mentions in steps 2–3 to M6.

- [ ] **Step 6: Run the tests and commit**

Run: `uv run --no-sync pytest tests/test_host_captures.py -q --no-cov`
Expected: pass (Claude Code only).

Run: `uv run --no-sync pytest -q`
Expected: green.

```bash
git add docs/host-captures/claude-code tests/test_host_captures.py docs/adr/0004-tasks-and-jobs.md docs/adr/0011-m5-tasks-decisions.md README.md
git commit -m "docs(tasks): capture claude code on the handshake era and record the M5 decisions"
```

---

### Task 7: The Codex capture, pin verification, full gate, perturbation checks, draft PR

**Files:**
- Create: `docs/host-captures/codex/0.153.4/{FINDINGS.md,connection.log,host-output.jsonl}`
- Modify: `tests/test_host_captures.py` (`HOSTS = ["claude-code", "codex"]`)
- Verify unchanged since Task 4's regeneration commit: `tests/fixtures/manifest_snapshot.*.json`, `tests/fixtures/wire_shape_snapshot.json`, `tests/fixtures/result_format_snapshot.json`, `tests/test_manifest.py`, `tests/test_fingerprint.py`, `tests/test_discovery_cost.py`

- [ ] **Step 1: Wait for the Codex quota reset, then run the Codex capture**

Do not run before `2026-09-07T19:14:35Z` (`date -u`); a rate-limited run proves nothing and burns nothing but time. Check readiness first with the free `codex_status` skill or `codex login status`.

```bash
SCRATCH=<the session scratchpad directory>
WT=/Users/bdc/projects/amicus-wt-m5
mkdir -p "$SCRATCH/captures/codex" "$SCRATCH/captures/state-codex"
cd "$SCRATCH/captures" && codex exec \
  --skip-git-repo-check --ephemeral -s read-only -c 'approval_policy="never"' \
  -c 'mcp_servers.amicus.command="uv"' \
  -c "mcp_servers.amicus.args=[\"run\",\"--no-sync\",\"--project\",\"$WT\",\"amicus-mcp\"]" \
  -c "mcp_servers.amicus.env={AMICUS_TASKS=\"1\",AMICUS_LOG_LEVEL=\"DEBUG\",AMICUS_LOG_FILE=\"$SCRATCH/captures/codex/amicus.log\",AMICUS_STATE_DIR=\"$SCRATCH/captures/state-codex\"}" \
  --json \
  "Call the amicus_backends tool with no arguments, then reply with exactly the JSON object the tool returned and nothing else." \
  > "$SCRATCH/captures/codex/host-output.jsonl"
grep "tools/call" "$SCRATCH/captures/codex/amicus.log"
codex --version
```

Expected: `tools/call amicus_backends: protocol=<pre-2026 version> client=<name>/<version> tasks_negotiated=False` lines.
If `codex exec` rejects `--ephemeral` or `approval_policy`, drop that flag (check `codex exec --help`); if it rejects the inline-table `env` override, write the three `mcp_servers.amicus.env.<KEY>="..."` overrides as separate `-c` flags.
If no `tools/call` line appears, read `host-output.jsonl` for the MCP startup error (Codex prints one per failed server) before retrying; every retry after the reset costs a Codex turn.
Spend: one Codex turn; `amicus_backends` spends no backend quota.

- [ ] **Step 2: Record the capture**

```bash
mkdir -p "$WT/docs/host-captures/codex/0.153.4"
grep "tools/call" "$SCRATCH/captures/codex/amicus.log" > "$WT/docs/host-captures/codex/0.153.4/connection.log"
grep -v '"session_id"\|"thread_id"' "$SCRATCH/captures/codex/host-output.jsonl" > "$WT/docs/host-captures/codex/0.153.4/host-output.jsonl"
```

Read `host-output.jsonl` before committing: keep only the lines that show the tool call and the final message; drop any line naming an account, a token, a home-directory path other than the worktree, or another MCP server's output (Codex loads the user's configured servers too).

`docs/host-captures/codex/0.153.4/FINDINGS.md`: the Claude Code FINDINGS with `Claude Code 2.1.263` → `Codex CLI 0.153.4`, `claude -p` → `codex exec`, `Claude Max turn` → `Codex turn`, `host-output.json` → `host-output.jsonl` (kept lines only), the two placeholders filled from this `connection.log`, and the closing bullet naming Codex CLI 0.153.4.

`tests/test_host_captures.py`: `HOSTS = ["claude-code", "codex"]` and drop the trailing comment.

Run: `uv run --no-sync pytest tests/test_host_captures.py -q --no-cov`
Expected: both hosts pass.

```bash
git add docs/host-captures/codex tests/test_host_captures.py
git commit -m "docs(tasks): capture codex cli on the handshake era"
```

- [ ] **Step 3: Verify no pin moved after Task 4**

```bash
git diff --stat "$(git log --format=%h --grep='regenerate the pins for schema-5' -1)"..HEAD -- tests/fixtures tests/test_manifest.py tests/test_fingerprint.py tests/test_discovery_cost.py tests/test_wire_shape.py tests/test_result_format.py
```

Expected: empty.
If a pin moved, a later task changed the wire surface unexpectedly: stop, find the change (`git diff main -- src/amicus/tools src/amicus/schemas src/amicus/server.py`), and either revert it or, if it is deliberate and argued, regenerate the pins in their own commit and explain in the PR body.

- [ ] **Step 4: Full gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest
```

Expected: green, coverage ≥ 95%. Record the test count and coverage for the PR body.

- [ ] **Step 5: Perturbation checks (each reverted immediately; none committed)**

1. In `tools/_guard.py`, make `as_tool_result` return `envelope` unconditionally → `tests/test_guard.py` (two tests) and `tests/test_tasks_client.py::test_tasked_failure_is_an_error_result_with_the_task_id` FAIL; `tests/test_tasks_spike.py` FAILS. Revert.
2. In `jobs/lifecycle.py`, delete the `task_map.record` call → `test_lifecycle.py::test_run_sync_records_the_task_id_when_inside_a_task` and `test_tasks_client.py::test_job_list_recovers_the_job_behind_a_task` FAIL. Revert.
3. In `server.py`, construct `TasksExtension(url=settings.tasks_backend_url)` without `redelivery_timeout` → `test_server.py::test_tasks_extension_redelivery_covers_the_sync_deadline` and `test_tasks_client.py::test_redelivery_timeout_is_the_sync_deadline_plus_grace` FAIL. Revert.
4. In `server.py`, remove `app.add_middleware(ConnectionLogMiddleware())` → `test_tasks_client.py::test_legacy_era_client_gets_a_plain_result` FAILS (no log line). Revert.
5. In `schemas/codes.py`, put `"not_implemented"` back into `LOCAL_CODES` → `test_codes.py`, `test_errors.py` and the manifest pins FAIL. Revert.
6. In `docs/host-captures/codex/0.153.4/connection.log`, change `tasks_negotiated=False` to `True` → `test_host_captures.py[codex]` FAILS. Revert.
7. In `orchestration/workspace.py`, put the `client_info` read back to `clientInfo` only → `test_workspace.py::test_client_name_reaches_the_host_framing_from_a_real_client` and the `test_middleware.py` connection-log test FAIL. Revert.

Run the gate once more after the reverts: `git status --short` must be empty.

- [ ] **Step 6: Push and open the draft PR**

```bash
git push -u origin feat/m5-tasks
gh pr create --draft --title "feat: M5 tasks extension" --body-file "$SCRATCH/m5-pr-body.md"
```

PR body (write it to the path above, filling every angle-bracket placeholder from measured output):

```markdown
## What & why

M5 of the amicus design spec: the `task=True` half of ADR 0004 for real.
A task-augmented call to any of the four paid sync tools now delivers the same envelope as the plain call with `isError` intact, records `task_id → job_id` so `amicus_job_list(task_id=...)` recovers the job, cancels its job when the task is cancelled, and both v1 hosts were captured on the handshake era.

## Decisions (ADR 0011; ADR 0004 amended)

- Host captures driven non-interactively (`claude -p`, `codex exec`), one host turn each, zero backend spend.
- ADR 0004's keyed-task cancel clause amended: tasked calls are always unkeyed; cancel always cancels the job; recovery via `amicus_job_list(task_id=...)`.
- One surface bump (schema-4 → schema-5): summary and `tasks.fallback` wording; `not_implemented` dropped from the catalog.
- `isError` carried by the guard (`as_tool_result`) on both paths, wire shape pinned equal to FastMCP's dict conversion; task-map recording in `run_sync`; `redelivery_timeout` bounded; `ConnectionLogMiddleware` as the capture instrument.

## Surface change (one commit, one regeneration commit)

<the two summary sentences, the `tasks.fallback` text, `not_implemented` removed; per-profile tools/list bytes 92082 / 92090 / 92082 → <new> from `--measure`>

## Library facts pinned (fastmcp-tasks 4.0.3, docket 0.25.0)

- `ttlMs` = 900000 (Docket `execution_ttl`; not settable through `TasksExtension`); the job outlives it.
- A 1.2 s task past a 300 ms `redelivery_timeout` executes once (lease renewal).
- `tasks/cancel` reaches `await_job_result` as `CancelledError`; the job record ends `cancelled`.

## Host captures

- Claude Code 2.1.263: `<protocol= value>`, `<client= value>`, `tasks_negotiated=False` (`docs/host-captures/claude-code/2.1.263/`).
- Codex CLI 0.153.4: `<protocol= value>`, `<client= value>`, `tasks_negotiated=False` (`docs/host-captures/codex/0.153.4/`).

## Verification

- Gate: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest` — <N> passed, <coverage>% branch coverage.
- New spend-free suites: `tests/test_guard.py`, `tests/test_tasks_client.py`, `tests/test_host_captures.py`, `tests/test_structured.py`; extended `test_middleware.py`, `test_lifecycle.py`, `test_server.py`, `test_workspace.py`.
- Perturbation checks: guard flip removed (fails), map recording removed (fails), redelivery bound removed (fails), connection log removed (fails), `not_implemented` restored (fails), capture line falsified (fails). All reverted, gate green.
- No live gate ran (rule 5).

## Bug found and fixed while wiring the captures

`client_name_from_ctx` read `clientInfo`; the MCP SDK v2 field is `client_info`, so host identity always fell back to the neutral `Caller` and the spec's `clientInfo.name` branch was dead code.
The covering test built its own fake with the wrong field name, so it could never fail.
Fixed with the real SDK models in the fake plus an end-to-end test through a real client; the whole pre-existing suite stays green.

## Follow-ups closed from the M4 review

`framing_for` unknown verb → `ValueError`; `is_permission_denied` no longer matches a bare `denied`; `ENVELOPE_KEYS` and the Kimi `schema_instruction` shim removed.

## Out of scope

- `classify_envelope`'s stderr scope (moves the differential; a sibling recapture); packaging and docs (M6); the Codex `_gate_optional` value-rescan follow-up (a separate fix PR); a `fastmcp-tasks` release that exposes `execution_ttl`.
```

Do not merge or approve the PR (AGENTS.md rule 8).

---

## Self-review (writing-plans checklist)

- **Spec coverage (M5 row).** `task=True` on the four paid sync tools behind `AMICUS_TASKS` → already registered (M0); made real by Task 1 (`isError` on the tasked path), Task 3 (task-map recording, `meta.task_id`, cancel proven, Docket timing) and `tests/test_tasks_client.py::test_all_four_paid_sync_tools_are_task_tools_and_nothing_else_is`.
  Capability-summary wording → Task 4 (`CAPABILITY_SUMMARY`, `TaskSupport.fallback`), claimed only after the captures (Tasks 6–7) exist, which `tests/test_host_captures.py` enforces.
  Host captures → Tasks 6 and 7 (`docs/host-captures/`), the gate's "both host captures".
  In-memory task-client tests → Task 3 Step 8.
  "Jobs and tasks" clauses: `task_id → job_id` at task creation → Task 3 (`run_sync`); `amicus_job_list(task_id=...)` → M2, proven again in `test_job_list_recovers_the_job_behind_a_task`; cancellation propagation → Task 3 (`test_cancelling_a_task_cancels_its_job`) with the keyed clause amended (decision 2, Task 6 ADR text); legacy fallback claimed only after a host capture → Tasks 4, 6, 7.
  Host identity ("normalized handshake-era `clientInfo.name` … else neutral framing") → Task 2, where the spec's first branch is made reachable for the first time.
- **Measured before shipping (2026-09-07, in the M5 worktree against the installed libraries).** Every library claim in this plan was probed, not predicted: a `ToolResult(structured_content=…, is_error=True)` has byte-identical `content`/`structured_content` to `Tool.convert_result(dict)` (Task 1's parity test); an `is_error` `ToolResult` returned from a `task=True` tool arrives with `is_error` True through `tasks/get` (the M0 finding is genuinely closed); `get_task_context().task_id` inside a tasked tool equals the client's handle id; `ttl_ms` is 900000; a 1.2 s task under a 300 ms `redelivery_timeout` executes exactly once; `tasks/cancel` raises `CancelledError` inside the tool coroutine and the task ends `cancelled`; `on_call_tool` middleware DOES run for a tasked call and sees `tasks_negotiated=True`; an in-memory client declares `mcp/0.1.0` on both eras, and an explicit `client_info` arrives intact.
- **Placeholder scan.** No TBD/TODO. The angle-bracket placeholders are in the FINDINGS files and the PR body only, filled from measured output in Tasks 6 and 7; every code block is complete.
- **Type consistency.** `as_tool_result(envelope) -> dict | ToolResult` (Task 1) is what `guard`'s wrapper returns and what `tests/test_guard.py` imports; `connection_facts(context) -> dict` with keys `protocol`/`client`/`client_version`/`tasks` (Task 2) is what `ConnectionLogMiddleware` formats and `tests/test_middleware.py` asserts, and the line format `tools/call <tool>: protocol=… client=…/… tasks_negotiated=…` is what `tests/test_host_captures.py::LINE` (Task 6) and `tests/test_tasks_client.py` parse; `lifecycle.current_task_id() -> str | None` and `run_sync(..., task_map: TaskJobMap | None = None)` (Task 3) match the four tool call sites (`task_map=lookup.task_map(settings)`) and every `tests/test_lifecycle.py` call; `server.tasks_redelivery_seconds(settings) -> int` (Task 3) is asserted by `tests/test_server.py` and mirrored by `tests/test_tasks_client.py::test_redelivery_timeout_is_the_sync_deadline_plus_grace` through `lifecycle.SYNC_AWAIT_GRACE_S`; `PAID_TOOLS` (`schemas.results`) is the four sync names the task-tool test iterates; `TaskJobMap.record/job_for/entries` (`jobs.taskmap`) are the M2 methods used everywhere.
  `client_name_from_ctx(ctx) -> str | None` (Task 2) keeps its signature; only the field it reads changes, and `connection_facts` reads the same pair.
- **Ordering.** Task 1 before Task 3 so the tasked-failure test can assert `isError`; Task 2 before Task 3 so the tasks-negotiated line exists; Task 4's surface change after all wiring so Tasks 5–7 can prove no pin moved (Task 7 Step 3); Task 6 before Task 7 so the Codex capture, gated on the quota reset, is the last spend and the capture test grows from one host to two.
