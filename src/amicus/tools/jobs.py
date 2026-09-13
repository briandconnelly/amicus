"""The five amicus_job_* tools: status, result, consume_result, cancel, list. Every
stored result is delivered through jobs.delivery.finished_job_envelope, the chokepoint
the sync path shares; workspace and roots follow ADR 0003; a record without amicus's
backend tag is foreign and reported not-found (ADR 0008)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastmcp import Context

from amicus.jobs import lifecycle, lookup
from amicus.jobs.delivery import finished_job_envelope
from amicus.schemas.params import (
    DetailParam,
    JobIdParam,
    JobLimitParam,
    JobStatusFilterParam,
    OptionalBackendParam,
    TaskIdParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import (
    JOB_LIST_SCHEMA,
    JOB_RESULT_SCHEMA,
    JOB_STATUS_SCHEMA,
    JobListResult,
)
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
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
    def store():
        return lifecycle.job_store(settings)

    async def resolve(ctx: Any, workspace_root: str | None):
        return await lookup.resolve_job_workspace(settings, ctx, workspace_root)

    def task_for(job_id: str) -> str | None:
        return lookup.task_map(settings).task_for(job_id)

    async def read_status(
        ctx: Any, workspace_root: str | None, job_id: str, *, cancel: bool
    ) -> dict[str, Any]:
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        # Read first, even for a cancel: a foreign record is never signalled (decision 6).
        row = await asyncio.to_thread(store().status, cwd, job_id)
        if row is not None and cancel and lookup.backend_of(row) is not None:
            row = await asyncio.to_thread(store().cancel, cwd, job_id)
        if row is None or lookup.backend_of(row) is None:
            return lookup.job_not_found(
                job_id, lookup.job_meta(settings, cwd, source, roots_source), workspace_root
            )
        meta = lookup.job_meta(
            settings,
            cwd,
            source,
            roots_source,
            backend=lookup.backend_of(row),
            kind=lookup.kind_of(row),
        )
        return lookup.status_model(row, lookup.workspace_of(cwd, source), task_for(job_id), meta)

    async def read_result(
        ctx: Any, workspace_root: str | None, job_id: str, detail: str, *, consume: bool
    ) -> dict[str, Any]:
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        rec, payload = await asyncio.to_thread(store().result_payload, cwd, job_id)
        backend = lookup.backend_of(rec) if rec is not None else None
        if rec is None or backend is None:
            return lookup.job_not_found(
                job_id, lookup.job_meta(settings, cwd, source, roots_source), workspace_root
            )
        kind = lookup.kind_of(rec)
        meta = lookup.job_meta(settings, cwd, source, roots_source, backend=backend, kind=kind)
        meta.task_id = task_for(job_id)
        envelope, delivered = finished_job_envelope(
            rec, payload, job_id, kind, meta, detail, workspace_root
        )
        if delivered and isinstance(envelope.get("meta"), dict) and meta.task_id is not None:
            envelope["meta"]["task_id"] = meta.task_id
        if not (consume and delivered):
            return envelope
        # Once delivered is true, every discard outcome still returns the envelope: MISSING
        # means the record is already gone (what consume promised), DELETE_FAILED means
        # deletion is best-effort and the TTL reaper owns the retained record, and REMOVED
        # is the normal case.
        await asyncio.to_thread(store().discard, cwd, job_id)
        return envelope

    @app.tool(
        name="amicus_job_status",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Poll a background job (free)",
        meta=lifecycle_meta("amicus_job_status"),
        description=(
            f"{FREE_MARKER} Poll a job's state without fetching its result: status, elapsed "
            "time, result_available, result_ok, and poll_after_ms to honor before the next "
            f"poll (it grows with elapsed time). {_RETENTION}"
        ),
    )
    @guard("amicus_job_status", settings)
    async def amicus_job_status(
        job_id: JobIdParam, ctx: Context | None = None, workspace_root: WorkspaceRootParam = None
    ) -> dict[str, Any]:
        """Poll a background job."""
        return await read_status(ctx, workspace_root, job_id, cancel=False)

    @app.tool(
        name="amicus_job_result",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch a background job's result (free)",
        meta=lifecycle_meta("amicus_job_result"),
        description=(
            f"{FREE_MARKER} Fetch a job once amicus_job_status reports a terminal status: "
            "`done` returns the originating paid tool's stored envelope — check `ok`, then "
            "branch on `tool`; `cancelled`, `failed` and `timeout` return that terminal error "
            "instead. The record is retained, so a re-read is free. A still-running job is "
            f"job_running with retry_after_ms. {_RETENTION}"
        ),
    )
    @guard("amicus_job_result", settings)
    async def amicus_job_result(
        job_id: JobIdParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch a background job's result."""
        return await read_result(ctx, workspace_root, job_id, detail, consume=False)

    @app.tool(
        name="amicus_job_consume_result",
        annotations=annotations_for("job_consume", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch and delete a background job's result (free)",
        meta=lifecycle_meta("amicus_job_consume_result"),
        description=(
            f"{FREE_MARKER} Like amicus_job_result, then delete the record: a repeat call "
            "returns job_not_found, so this is not idempotent. A corrupt or incompatible "
            "record is not deleted."
        ),
    )
    @guard("amicus_job_consume_result", settings)
    async def amicus_job_consume_result(
        job_id: JobIdParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch and delete a background job's result."""
        return await read_result(ctx, workspace_root, job_id, detail, consume=True)

    @app.tool(
        name="amicus_job_cancel",
        annotations=annotations_for("job_cancel", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Cancel a background job (free)",
        meta=lifecycle_meta("amicus_job_cancel"),
        description=(
            f"{FREE_MARKER} Stop the worker (SIGTERM, then SIGKILL), remove its worktree, "
            "and mark the job cancelled; a terminal job is returned unchanged, so cancel is "
            "idempotent. cleanup_warnings names any leftover path."
        ),
    )
    @guard("amicus_job_cancel", settings)
    async def amicus_job_cancel(
        job_id: JobIdParam, ctx: Context | None = None, workspace_root: WorkspaceRootParam = None
    ) -> dict[str, Any]:
        """Cancel a background job."""
        return await read_status(ctx, workspace_root, job_id, cancel=True)

    @app.tool(
        name="amicus_job_list",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_LIST_SCHEMA,
        title="List background jobs (free)",
        meta=lifecycle_meta("amicus_job_list"),
        description=(
            f"{FREE_MARKER} List the jobs known for this workspace, newest first, across all "
            "backends; narrow with `backend`, `status`, or `task_id` (no match is an empty "
            "list). Only an explicit `limit` "
            f"truncates (truncated: true, no cursor). {_RETENTION}"
        ),
    )
    @guard("amicus_job_list", settings)
    async def amicus_job_list(
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        limit: JobLimitParam = None,
        status: JobStatusFilterParam = None,
        backend: OptionalBackendParam = None,
        task_id: TaskIdParam = None,
    ) -> dict[str, Any]:
        """List background jobs."""
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        rows = await asyncio.to_thread(store().list_jobs, cwd)
        tasks = lookup.task_map(settings).entries()
        # First association wins, as TaskJobMap.task_for does: a keyed replay from a second
        # task adds a forward entry for recovery, and the job's own task_id stays the task
        # that created it on every surface (ADR 0020).
        task_by_job: dict[str, str] = {}
        for task, job in tasks.items():
            task_by_job.setdefault(job, task)
        rows = [r for r in rows if lookup.backend_of(r) is not None]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if backend is not None:
            rows = [r for r in rows if lookup.backend_of(r) == backend]
        if task_id is not None:
            wanted = tasks.get(task_id)
            rows = [r for r in rows if wanted is not None and r["job_id"] == wanted]
        truncated = limit is not None and len(rows) > limit
        if limit is not None:
            rows = rows[:limit]
        result = JobListResult(
            jobs=[lookup.summary_model(r, task_by_job.get(r["job_id"])) for r in rows],
            workspace=lookup.workspace_of(cwd, source),
            truncated=truncated,
            truncation_hint=(
                f"showing the {limit} newest of more matching jobs; omit `limit` for every "
                "retained match, or narrow with `status`, `backend` or `task_id`"
                if truncated
                else None
            ),
            meta=lookup.job_meta(settings, cwd, source, roots_source),
        ).model_dump(mode="json")
        return result

    return (
        "amicus_job_status",
        "amicus_job_result",
        "amicus_job_consume_result",
        "amicus_job_cancel",
        "amicus_job_list",
    )
