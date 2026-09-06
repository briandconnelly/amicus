"""What every amicus_job_* tool does before and after it touches the JobStore: resolve
the workspace (ADR 0003), build the lifecycle-error meta, read the record's backend and
kind, and render JobStatus/JobSummary. Foreign records (no valid backend tag) are never
reported (ADR 0008 decision 6)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pontonier.core import redaction

from amicus.errors import error_envelope
from amicus.jobs.delivery import STATE_TO_ERROR
from amicus.jobs.taskmap import TaskJobMap
from amicus.orchestration import workspace as ws
from amicus.schemas.envelope import ErrorDetail, Meta, RootsSource, Workspace
from amicus.schemas.results import JobStatus, JobSummary

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings

BACKEND_REF_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TASK_MAP_FILENAME = "tasks.json"


def backend_of(row: dict[str, Any]) -> str | None:
    """The backend tag amicus stamps on every record, or None for a foreign record."""
    extra = row.get("extra")
    value = extra.get("backend") if isinstance(extra, dict) else None
    return value if isinstance(value, str) and BACKEND_REF_RE.match(value) else None


def kind_of(row: dict[str, Any]) -> str:
    kind = row.get("kind")
    return kind if isinstance(kind, str) else ""


def task_map(settings: Settings) -> TaskJobMap:
    return TaskJobMap(settings.state_dir / TASK_MAP_FILENAME)


def workspace_of(cwd: str, source: str | None) -> Workspace:
    return Workspace(
        cwd=cwd,
        workspace_source=source,  # ty: ignore[invalid-argument-type]
        workspace_warning=ws.workspace_warning_for(source, cwd),
    )


def job_meta(
    settings: Settings,
    cwd: str | None,
    source: str | None,
    roots_source: RootsSource,
    *,
    backend: str | None = None,
    kind: str | None = None,
) -> Meta:
    """Meta for a lifecycle-GENERATED envelope: the job's backend and kind when a record
    was resolved, the job deadline as the timeout, and the roots state this lookup saw."""
    return Meta(
        backend=backend,
        cwd=cwd,
        workspace_source=source,  # ty: ignore[invalid-argument-type]
        workspace_warning=ws.workspace_warning_for(source, cwd),
        roots_source=roots_source,
        timeout_seconds=settings.job_max_seconds,
        job_kind=kind or None,
    )


async def resolve_job_workspace(
    settings: Settings, ctx: Any, workspace_root: str | None
) -> tuple[str | None, str | None, str, dict[str, Any] | None]:
    """(cwd, source, roots_source, error). The error is a ready envelope whose meta
    carries the roots state, which is often why the caller looks in the wrong place."""
    roots, roots_source = await ws.roots_from_ctx(ctx)
    res = ws.resolve(workspace_root, roots, allow_cwd=settings.allow_cwd_workspace)
    if res.error_code is not None:
        meta = job_meta(settings, None, None, roots_source)  # ty: ignore[invalid-argument-type]
        return (
            None,
            None,
            roots_source,
            error_envelope(
                res.error_code,
                redaction.sanitize_echo_prose(res.error_detail) or "invalid workspace",
                meta,
                details=ErrorDetail(field="workspace_root"),
                candidate_roots=list(roots)
                if res.error_code == "workspace_outside_roots" and roots
                else None,
            ),
        )
    assert res.path is not None
    return res.path, res.source, roots_source, None


def job_not_found(job_id: str, meta: Meta, workspace_root: str | None) -> dict[str, Any]:
    args = {"workspace_root": workspace_root} if workspace_root else None
    return error_envelope(
        "job_not_found",
        f"No job '{redaction.sanitize_echo(job_id)}' in this workspace.",
        meta,
        details=ErrorDetail(field="job_id"),
        repair_arguments=args,
    )


def status_model(
    row: dict[str, Any], workspace: Workspace, task_id: str | None, meta: Meta
) -> dict[str, Any]:
    """A JobStatus dump. Raises ValueError for a foreign row; callers report not-found."""
    backend = backend_of(row)
    if backend is None:
        raise ValueError("record carries no amicus backend tag")
    state = row["status"]
    meta.job_id = row["job_id"]
    meta.task_id = task_id
    return JobStatus(
        meta=meta,
        job_id=row["job_id"],
        backend=backend,
        kind=kind_of(row),
        status=state,
        elapsed_ms=row["elapsed_ms"],
        result_available=row["result_available"],
        result_ok=row["result_ok"],
        poll_after_ms=row["poll_after_ms"] if state == "running" else None,
        expires_at=row["expires_at"],
        task_id=task_id,
        workspace=workspace,
        cleanup_warnings=list(row.get("cleanup_warnings", [])),
    ).model_dump(mode="json")


def summary_model(row: dict[str, Any], task_id: str | None) -> JobSummary:
    backend = backend_of(row)
    if backend is None:
        raise ValueError("record carries no amicus backend tag")
    return JobSummary(
        job_id=row["job_id"],
        backend=backend,
        kind=kind_of(row),
        status=row["status"],
        started_at=row["started_at"],
        elapsed_ms=row["elapsed_ms"],
        result_available=row["result_available"],
        result_ok=row["result_ok"],
        expires_at=row["expires_at"],
        task_id=task_id,
    )


__all__ = [
    "BACKEND_REF_RE",
    "STATE_TO_ERROR",
    "backend_of",
    "job_meta",
    "job_not_found",
    "kind_of",
    "resolve_job_workspace",
    "status_model",
    "summary_model",
    "task_map",
    "workspace_of",
]
