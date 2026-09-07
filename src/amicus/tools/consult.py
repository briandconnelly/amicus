"""amicus_consult and amicus_consult_async."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context

from amicus.jobs import lifecycle, lookup
from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    DetailParam,
    ExtraContextParam,
    IdempotencyKeyParam,
    InstructionsAppendParam,
    ModelParam,
    QuestionParam,
    ReasoningEffortParam,
    TimeoutSecondsParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import CONSULT_RESULT_SCHEMA, JOB_STARTED_SCHEMA
from amicus.tools import _resolve
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._prepare import prepare_run

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_EGRESS = (
    "Egress: sends question, extra_context and instructions_append raw to the backend's "
    "provider; the backend can read files outside the workspace."
)
_DESC = (
    f"{_resolve.PAID_MARKER} Read-only second opinion or Q&A from `backend` on a question, "
    "design, or a diff you paste inline; use amicus_review_changes when the diff is in "
    f"git. {_EGRESS} Recorded as a job (meta.job_id). Prefer amicus_consult_async for a "
    "high-effort or broad repo-grounded consult that can exceed the deadline."
)
_ASYNC_DESC = (
    f"{_resolve.PAID_MARKER} Async twin of amicus_consult: returns a job handle "
    f"immediately; poll amicus_job_status, read amicus_job_result. {_EGRESS} Starting a "
    "job commits to spend. Deadline: AMICUS_JOB_MAX_SECONDS (default 1800s)."
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    @app.tool(
        name="amicus_consult",
        annotations=annotations_for("active", settings),
        output_schema=CONSULT_RESULT_SCHEMA,
        title="Consult a backend model (paid)",
        meta=lifecycle_meta("amicus_consult"),
        description=_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_consult", settings)
    async def amicus_consult(
        backend: BackendParam,
        question: QuestionParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Consult the selected backend for a read-only second opinion."""
        err = _resolve.blank_input_error(question, "question", "amicus_consult", settings, backend)
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_consult",
            verb="consult",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            instructions_append=instructions_append,
            extra_context=extra_context,
            question=question,
        )
        if isinstance(prep, dict):
            return prep
        return await lifecycle.run_sync(
            lifecycle.job_store(settings),
            prep.spec,
            prep.meta,
            prep.plugin,
            timeout=prep.spec.timeout_seconds,
            detail=detail,
            ctx=ctx,
            task_map=lookup.task_map(settings),
        )

    @app.tool(
        name="amicus_consult_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background consult (paid)",
        meta=lifecycle_meta("amicus_consult_async"),
        description=_ASYNC_DESC,
    )
    @guard("amicus_consult_async", settings)
    async def amicus_consult_async(
        backend: BackendParam,
        question: QuestionParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background consult on the selected backend."""
        err = _resolve.blank_input_error(
            question, "question", "amicus_consult_async", settings, backend
        )
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_consult_async",
            verb="consult",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            background=True,
            instructions_append=instructions_append,
            extra_context=extra_context,
            question=question,
        )
        if isinstance(prep, dict):
            return prep
        return await lifecycle.start_async(
            lifecycle.job_store(settings),
            prep.spec,
            prep.meta,
            prep.plugin,
            deadline=prep.spec.timeout_seconds,
            idempotency_key=idempotency_key,
        )

    return ("amicus_consult", "amicus_consult_async")
