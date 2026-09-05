"""amicus_dry_run and amicus_delegate_dry_run (free previews; bodies land in M1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    BaseParam,
    CommitParam,
    ExtraContextParam,
    InstructionsAppendParam,
    ModelParam,
    PathsParam,
    ReasoningEffortParam,
    ScopeParam,
    TaskParam,
    UntrackedParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import DELEGATE_DRY_RUN_SCHEMA, DRY_RUN_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._resolve import FREE_MARKER, blank_input_error, not_implemented, resolve_paid_call

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_PREVIEW_FACT = (
    "A dry run reports metadata about the input amicus would assemble; it does not invoke "
    "the backend, and it neither enumerates nor bounds the files the model itself reads "
    "during the paid call."
)
_DRY_RUN_DESC = (
    f"{FREE_MARKER} Preview an amicus_review_changes call: the diff scope, its byte size and "
    "summary, the resolved model, effort and backend_options, and whether the paid call "
    f"would run the model at all. {_PREVIEW_FACT}"
)
_DELEGATE_DRY_RUN_DESC = (
    f"{FREE_MARKER} Preview an amicus_delegate call: the worktree baseline and prefix, task "
    f"bytes, and the resolved model, effort and backend_options. {_PREVIEW_FACT}"
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    @app.tool(
        name="amicus_dry_run",
        annotations=annotations_for("free", settings),
        output_schema=DRY_RUN_SCHEMA,
        title="Preview a review (free)",
        meta=lifecycle_meta("amicus_dry_run"),
        description=_DRY_RUN_DESC,
    )
    @guard("amicus_dry_run", settings)
    async def amicus_dry_run(
        backend: BackendParam,
        scope: ScopeParam = "working_tree",
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Preview a review call without spending."""
        resolved = resolve_paid_call(
            registry=registry,
            settings=settings,
            tool_name="amicus_dry_run",
            verb="review_changes",
            backend=backend,
            backend_options=backend_options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented("amicus_dry_run", settings, backend)

    @app.tool(
        name="amicus_delegate_dry_run",
        annotations=annotations_for("free", settings),
        output_schema=DELEGATE_DRY_RUN_SCHEMA,
        title="Preview a delegate (free)",
        meta=lifecycle_meta("amicus_delegate_dry_run"),
        description=_DELEGATE_DRY_RUN_DESC,
    )
    @guard("amicus_delegate_dry_run", settings)
    async def amicus_delegate_dry_run(
        backend: BackendParam,
        task: TaskParam,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Preview a delegate call without spending."""
        err = blank_input_error(task, "task", "amicus_delegate_dry_run", settings, backend)
        if err is not None:
            return err
        resolved = resolve_paid_call(
            registry=registry,
            settings=settings,
            tool_name="amicus_delegate_dry_run",
            verb="delegate",
            backend=backend,
            backend_options=backend_options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented("amicus_delegate_dry_run", settings, backend)

    return ("amicus_dry_run", "amicus_delegate_dry_run")
