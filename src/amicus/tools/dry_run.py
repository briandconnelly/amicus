"""amicus_dry_run and amicus_delegate_dry_run: free previews of a review/delegate call's
scope, size and resolved options, failing pre-spend exactly where the paid call would."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context
from pontonier.core import redaction, worktree

from amicus.errors import error_envelope
from amicus.orchestration import prompts, review
from amicus.orchestration.isolation import WORKTREE_PREFIX
from amicus.schemas.envelope import Workspace, dump_success
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
from amicus.schemas.results import (
    DELEGATE_DRY_RUN_SCHEMA,
    DRY_RUN_SCHEMA,
    DelegateDryRunResult,
    DryRunResult,
    WorktreePlan,
)
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._prepare import deadline_advisory, prepare_run
from amicus.tools._resolve import FREE_MARKER, blank_input_error

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry
    from amicus.tools._prepare import Prepared

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


def _workspace(prep: Prepared) -> Workspace:
    return Workspace(
        cwd=prep.spec.cwd,
        workspace_source=prep.spec.workspace_source,  # ty: ignore[invalid-argument-type]
        workspace_warning=prep.meta.workspace_warning,
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
        ctx: Context | None = None,
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
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_dry_run",
            verb="review_changes",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            instructions_append=instructions_append,
            extra_context=extra_context,
            scope=scope,
            base=base,
            commit=commit,
            paths=paths,
            untracked=untracked,
        )
        if isinstance(prep, dict):
            return prep
        spec, meta = prep.spec, prep.meta
        gathered = review.gather(spec, meta, prep.plugin)
        warnings: list[str] = []
        if isinstance(gathered, dict):
            if gathered.get("ok") is not True:
                return gathered
            would_call_model, prompt_bytes = False, 0
            warnings.append(gathered["summary"])
        else:
            prompt = prompts.review_prompt(
                spec.host_name,
                gathered.text,
                prompts.review_label(scope, base, commit),
                prompts.review_caller_text(spec.focus, extra_context),
                plugin=prep.plugin,
            )
            would_call_model, prompt_bytes = True, len(prompt.encode("utf-8"))
            if gathered.truncated and gathered.truncation_hint:
                warnings.append(gathered.truncation_hint)
            if gathered.redacted_paths:
                warnings.append(
                    f"{len(gathered.redacted_paths)} path(s) had secrets redacted: "
                    f"{', '.join(gathered.redacted_paths)}"
                )
        advisory = deadline_advisory(
            would_call_model,
            prompt_bytes,
            spec.reasoning_effort,
            spec.timeout_seconds,
            "amicus_review_changes_async",
        )
        if advisory:
            warnings.append(advisory)
        return dump_success(
            DryRunResult(
                backend=backend,
                would_call_model=would_call_model,
                scope=scope,
                base=base,
                commit=commit,
                paths=paths,
                prompt_bytes=prompt_bytes,
                context_summary=meta.context_summary,
                model=spec.model,
                reasoning_effort=spec.reasoning_effort,
                backend_options=spec.options,
                workspace=_workspace(prep),
                warnings=warnings,
                meta=meta,
            )
        )

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
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Preview a delegate call without spending."""
        err = blank_input_error(task, "task", "amicus_delegate_dry_run", settings, backend)
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_delegate_dry_run",
            verb="delegate",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            task=task,
        )
        if isinstance(prep, dict):
            return prep
        spec, meta = prep.spec, prep.meta
        try:
            plan = worktree.plan(spec.cwd, timeout=spec.git_timeout)
        except (worktree.NoCommitsError, worktree.WorktreeError) as exc:
            return error_envelope(
                "worktree_error",
                redaction.sanitize_echo_prose(str(exc))[:300],
                meta,
                plugin=prep.plugin,
            )
        task_bytes = len(task.encode("utf-8"))
        prompt_bytes = len(
            prompts.delegate_prompt(spec.host_name, task, plugin=prep.plugin).encode("utf-8")
        )
        warnings: list[str] = []
        advisory = deadline_advisory(
            True, prompt_bytes, spec.reasoning_effort, spec.timeout_seconds, "amicus_delegate_async"
        )
        if advisory:
            warnings.append(advisory)
        if plan.uncommitted_tracked_files:
            warnings.append(
                f"{plan.uncommitted_tracked_files} uncommitted tracked change(s) would be "
                f"replayed into the worktree; untracked files ({plan.untracked_files}) are "
                "never copied."
            )
        return dump_success(
            DelegateDryRunResult(
                backend=backend,
                task_bytes=task_bytes,
                worktree=WorktreePlan(baseline_ref=plan.head_commit, prefix=WORKTREE_PREFIX),
                model=spec.model,
                reasoning_effort=spec.reasoning_effort,
                backend_options=spec.options,
                workspace=_workspace(prep),
                warnings=warnings,
                meta=meta,
            )
        )

    return ("amicus_dry_run", "amicus_delegate_dry_run")
