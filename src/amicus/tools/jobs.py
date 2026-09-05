"""The five amicus_job_* tools (schema-only until M2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.errors import error_envelope
from amicus.schemas.params import (
    DetailParam,
    JobIdParam,
    JobLimitParam,
    JobStatusFilterParam,
    OptionalBackendParam,
    TaskIdParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import JOB_LIST_SCHEMA, JOB_RESULT_SCHEMA, JOB_STATUS_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, base_meta, lifecycle_meta
from amicus.tools._resolve import FREE_MARKER

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_RETENTION = (
    "Records expire after AMICUS_JOB_TTL (default 24h) and a per-workspace cap evicts the "
    "oldest terminal records; read results promptly."
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    def pending(tool_name: str) -> dict[str, Any]:
        return error_envelope(
            "not_implemented", f"{tool_name} lands with the jobs surface (M2)", base_meta(settings)
        )

    @app.tool(
        name="amicus_job_status",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Poll a background job (free)",
        meta=lifecycle_meta("amicus_job_status"),
        description=(
            f"{FREE_MARKER} Poll a job's state without fetching its result: status, elapsed "
            "time, result_available, result_ok, and poll_after_ms to honor before the next "
            f"poll. {_RETENTION}"
        ),
    )
    @guard("amicus_job_status", settings)
    async def amicus_job_status(
        job_id: JobIdParam, workspace_root: WorkspaceRootParam = None
    ) -> dict[str, Any]:
        """Poll a background job."""
        return pending("amicus_job_status")

    @app.tool(
        name="amicus_job_result",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch a background job's result (free)",
        meta=lifecycle_meta("amicus_job_result"),
        description=(
            f"{FREE_MARKER} Return the originating paid tool's envelope once result_available; "
            "branch on `tool`. The record is retained, so a re-read is free. A still-running "
            f"job is job_running with retry_after_ms. {_RETENTION}"
        ),
    )
    @guard("amicus_job_result", settings)
    async def amicus_job_result(
        job_id: JobIdParam,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch a background job's result."""
        return pending("amicus_job_result")

    @app.tool(
        name="amicus_job_consume_result",
        annotations=annotations_for("job_consume", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch and delete a background job's result (free)",
        meta=lifecycle_meta("amicus_job_consume_result"),
        description=(
            f"{FREE_MARKER} Like amicus_job_result, then delete the record: a repeat call "
            "returns job_not_found, so this is not idempotent."
        ),
    )
    @guard("amicus_job_consume_result", settings)
    async def amicus_job_consume_result(
        job_id: JobIdParam,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch and delete a background job's result."""
        return pending("amicus_job_consume_result")

    @app.tool(
        name="amicus_job_cancel",
        annotations=annotations_for("job_cancel", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Cancel a background job (free)",
        meta=lifecycle_meta("amicus_job_cancel"),
        description=(
            f"{FREE_MARKER} Ask the worker to stop and mark the job cancelled; a terminal job "
            "is returned unchanged, so cancel is idempotent. An unkeyed task-augmented call "
            "cancels its job; a keyed job survives and the result names its job_id."
        ),
    )
    @guard("amicus_job_cancel", settings)
    async def amicus_job_cancel(
        job_id: JobIdParam, workspace_root: WorkspaceRootParam = None
    ) -> dict[str, Any]:
        """Cancel a background job."""
        return pending("amicus_job_cancel")

    @app.tool(
        name="amicus_job_list",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_LIST_SCHEMA,
        title="List background jobs (free)",
        meta=lifecycle_meta("amicus_job_list"),
        description=(
            f"{FREE_MARKER} List the jobs known for this workspace, newest first, across all "
            "backends; narrow with `backend`, `status`, or `task_id` (the tasks-extension id "
            "recorded at task creation). Only an explicit `limit` truncates (truncated: true, "
            f"no cursor). {_RETENTION}"
        ),
    )
    @guard("amicus_job_list", settings)
    async def amicus_job_list(
        workspace_root: WorkspaceRootParam = None,
        limit: JobLimitParam = None,
        status: JobStatusFilterParam = None,
        backend: OptionalBackendParam = None,
        task_id: TaskIdParam = None,
    ) -> dict[str, Any]:
        """List background jobs."""
        return pending("amicus_job_list")

    return (
        "amicus_job_status",
        "amicus_job_result",
        "amicus_job_consume_result",
        "amicus_job_cancel",
        "amicus_job_list",
    )
