"""amicus_delegate and amicus_delegate_async."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    DetailParam,
    IdempotencyKeyParam,
    ModelParam,
    ReasoningEffortParam,
    TaskParam,
    TimeoutSecondsParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import DELEGATE_RESULT_SCHEMA, JOB_STARTED_SCHEMA
from amicus.tools import _resolve
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_DESC = (
    f"{_resolve.PAID_MARKER} `backend` implements `task` in a throwaway git worktree "
    "seeded from tracked state and returns the diff — never applied to your working "
    "tree. Codex and Kimi in v1 (feature delegate); Claude stays review-only. Egress: "
    "sends task raw to the backend's provider; a backend sandbox may also write the OS "
    "temp roots, which are neither in the diff nor cleaned up. Recorded as a job "
    "(meta.job_id)."
)
_ASYNC_DESC = (
    f"{_resolve.PAID_MARKER} Async twin of amicus_delegate: returns a job handle; poll "
    "amicus_job_status, read amicus_job_result. Same egress and feature gate. Starting a "
    "job commits to spend."
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    async def _run(tool_name: str, backend: str, task: str, options: Any) -> dict[str, Any]:
        err = _resolve.blank_input_error(task, "task", tool_name, settings, backend)
        if err is not None:
            return err
        resolved = _resolve.resolve_paid_call(
            registry=registry,
            settings=settings,
            tool_name=tool_name,
            verb="delegate",
            backend=backend,
            backend_options=options,
        )
        if isinstance(resolved, dict):
            return resolved
        return _resolve.not_implemented(tool_name, settings, backend)

    @app.tool(
        name="amicus_delegate",
        annotations=annotations_for("active", settings),
        output_schema=DELEGATE_RESULT_SCHEMA,
        title="Delegate a coding task for a reviewable diff (paid)",
        meta=lifecycle_meta("amicus_delegate"),
        description=_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_delegate", settings)
    async def amicus_delegate(
        backend: BackendParam,
        task: TaskParam,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Delegate a task to the selected backend in a throwaway worktree."""
        return await _run("amicus_delegate", backend, task, backend_options)

    @app.tool(
        name="amicus_delegate_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background delegate (paid)",
        meta=lifecycle_meta("amicus_delegate_async"),
        description=_ASYNC_DESC,
    )
    @guard("amicus_delegate_async", settings)
    async def amicus_delegate_async(
        backend: BackendParam,
        task: TaskParam,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background delegate on the selected backend."""
        return await _run("amicus_delegate_async", backend, task, backend_options)

    return ("amicus_delegate", "amicus_delegate_async")
