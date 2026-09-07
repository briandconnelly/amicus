"""amicus_review_changes(_async) and amicus_adversarial_review(_async)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context

from amicus.jobs import lifecycle
from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    BaseParam,
    CommitParam,
    DetailParam,
    EvidenceParam,
    ExtraContextParam,
    FocusParam,
    IdempotencyKeyParam,
    InstructionsAppendParam,
    ModelParam,
    OptionalScopeParam,
    PathsParam,
    ReasoningEffortParam,
    ScopeParam,
    TargetParam,
    TimeoutSecondsParam,
    UntrackedParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import (
    ADVERSARIAL_RESULT_SCHEMA,
    JOB_STARTED_SCHEMA,
    REVIEW_RESULT_SCHEMA,
)
from amicus.tools import _resolve
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._prepare import prepare_run

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_REVIEW_DESC = (
    f"{_resolve.PAID_MARKER} Structured review by `backend` of changes gathered from git — "
    "working_tree, branch, or commit — with verdict, confidence and findings. Egress: "
    "sends the bounded, secret-redacted diff plus raw extra_context and "
    "instructions_append to the backend's provider. An empty scope returns "
    "review_status=not_run with no spend. Recorded as a job (meta.job_id)."
)
_REVIEW_ASYNC_DESC = (
    f"{_resolve.PAID_MARKER} Async twin of amicus_review_changes: returns a job handle; "
    "poll amicus_job_status, read amicus_job_result. Same egress. Starting a job commits "
    "to spend. Deadline: AMICUS_JOB_MAX_SECONDS (default 1800s)."
)
_ADV_DESC = (
    f"{_resolve.PAID_MARKER} A fixed adversarial critic on `backend` attacks `target` (a "
    "plan, claim or decision) using `evidence` and an optionally attached git diff; the "
    "critic stance is the product, so there is no instructions_append. Claude only in v1 "
    "(feature adversarial_review). Egress: sends target, evidence, extra_context and the "
    "redacted diff raw to the backend's provider. An attached scope that gathers nothing "
    "returns review_status=not_run with no spend. Recorded as a job (meta.job_id)."
)
_ADV_ASYNC_DESC = (
    f"{_resolve.PAID_MARKER} Async twin of amicus_adversarial_review: returns a job "
    "handle; poll amicus_job_status, read amicus_job_result. Same egress and feature gate."
)


def register_review_changes(
    app: FastMCP, settings: Settings, registry: BackendRegistry
) -> tuple[str, ...]:
    @app.tool(
        name="amicus_review_changes",
        annotations=annotations_for("active", settings),
        output_schema=REVIEW_RESULT_SCHEMA,
        title="Review git changes (paid)",
        meta=lifecycle_meta("amicus_review_changes"),
        description=_REVIEW_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_review_changes", settings)
    async def amicus_review_changes(
        backend: BackendParam,
        ctx: Context | None = None,
        scope: ScopeParam = "working_tree",
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Review changes from git with the selected backend."""
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_review_changes",
            verb="review_changes",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            instructions_append=instructions_append,
            extra_context=extra_context,
            focus=focus,
            scope=scope,
            base=base,
            commit=commit,
            paths=paths,
            untracked=untracked,
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
        )

    @app.tool(
        name="amicus_review_changes_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background review (paid)",
        meta=lifecycle_meta("amicus_review_changes_async"),
        description=_REVIEW_ASYNC_DESC,
    )
    @guard("amicus_review_changes_async", settings)
    async def amicus_review_changes_async(
        backend: BackendParam,
        ctx: Context | None = None,
        scope: ScopeParam = "working_tree",
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background review with the selected backend."""
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_review_changes_async",
            verb="review_changes",
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
            focus=focus,
            scope=scope,
            base=base,
            commit=commit,
            paths=paths,
            untracked=untracked,
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

    return ("amicus_review_changes", "amicus_review_changes_async")


def register_adversarial(
    app: FastMCP, settings: Settings, registry: BackendRegistry
) -> tuple[str, ...]:
    @app.tool(
        name="amicus_adversarial_review",
        annotations=annotations_for("active", settings),
        output_schema=ADVERSARIAL_RESULT_SCHEMA,
        title="Adversarial critique of a plan or claim (paid)",
        meta=lifecycle_meta("amicus_adversarial_review"),
        description=_ADV_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_adversarial_review", settings)
    async def amicus_adversarial_review(
        backend: BackendParam,
        target: TargetParam,
        ctx: Context | None = None,
        evidence: EvidenceParam = None,
        scope: OptionalScopeParam = None,
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Attack a target with a fixed adversarial critic on the selected backend."""
        err = _resolve.blank_input_error(
            target, "target", "amicus_adversarial_review", settings, backend
        )
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_adversarial_review",
            verb="adversarial_review",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            extra_context=extra_context,
            focus=focus,
            scope=scope,
            base=base,
            commit=commit,
            paths=paths,
            untracked=untracked,
            target=target,
            evidence=evidence,
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
        )

    @app.tool(
        name="amicus_adversarial_review_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background adversarial critique (paid)",
        meta=lifecycle_meta("amicus_adversarial_review_async"),
        description=_ADV_ASYNC_DESC,
    )
    @guard("amicus_adversarial_review_async", settings)
    async def amicus_adversarial_review_async(
        backend: BackendParam,
        target: TargetParam,
        ctx: Context | None = None,
        evidence: EvidenceParam = None,
        scope: OptionalScopeParam = None,
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background adversarial critique on the selected backend."""
        err = _resolve.blank_input_error(
            target, "target", "amicus_adversarial_review_async", settings, backend
        )
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_adversarial_review_async",
            verb="adversarial_review",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            background=True,
            extra_context=extra_context,
            focus=focus,
            scope=scope,
            base=base,
            commit=commit,
            paths=paths,
            untracked=untracked,
            target=target,
            evidence=evidence,
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

    return ("amicus_adversarial_review", "amicus_adversarial_review_async")
