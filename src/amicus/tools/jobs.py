"""The six amicus_job_* tools: status, result, consume_result, export_diff, cancel, list. Every
stored result is delivered through jobs.delivery.finished_job_envelope, the chokepoint
the sync path shares; workspace and roots follow ADR 0003; a record without amicus's
backend tag is foreign and reported not-found (ADR 0008)."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import TYPE_CHECKING, Any

from fastmcp import Context

from amicus.errors import error_envelope
from amicus.jobs import lifecycle, lookup
from amicus.jobs.delivery import (
    attach_consume_disposition,
    attach_diff_export,
    consumable_state,
    exportable_diff,
    finished_job_envelope,
    unreadable_result_envelope,
)
from amicus.jobs.export import ExportFailed, ExportLeft, ExportRefused, write_diff_file
from amicus.jobs.polling import job_status_arguments
from amicus.jobs.store import MAX_POLL_AFTER_MS, MetaUnreadable, ResultUnreadable
from amicus.schemas.envelope import InvalidArgument
from amicus.schemas.params import (
    MAX_STATUS_WAIT_SECONDS,
    DetailParam,
    DiffPathParam,
    JobCursorParam,
    JobIdParam,
    JobLimitParam,
    JobStatusFilterParam,
    OptionalBackendParam,
    TaskIdParam,
    WaitSecondsParam,
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
    "Records expire after AMICUS_JOB_TTL (default 24h); unfetched results fill a "
    "per-workspace cap that refuses paid calls (job_cap_reached)."
)

# A cursor is the anchor row's own (started_epoch, job_id), which is the listing's sort key
# (#249, ADR 0042): a page after it is every row that sorts below it, so an anchor that has
# since been consumed or evicted still resolves. Opaque to callers; this tool alone mints it.
_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")
# How often a status wait re-reads the record; a read is a local file stat, not a spend.
_WAIT_POLL_SECONDS = 0.25


_EXPORT_RUNNING_ALTERNATIVE = (
    "Poll amicus_job_status while status is running, honoring poll_after_ms, or pass a "
    "positive wait_seconds, which is itself the wait. On any terminal status, repeat this "
    "amicus_job_export_diff call with the same job_id, workspace_root and path; fetching "
    "the result with amicus_job_result instead returns the whole diff inline."
)


_EXPORT_FAILED_REPAIR: dict[ExportLeft, str] = {
    "nothing": (
        "amicus could not create the export file and created no file. The job's record is "
        "kept and not marked delivered. Fix the cause or pick another directory, then retry "
        "amicus_job_export_diff with the same job_id, to the same path or another."
    ),
    "empty_file": (
        "amicus could not finish the export (for example the disk filled) and emptied the "
        "file it created, which it never deletes; that file may still be at the path, or "
        "something else may have moved or removed it during the call. Delete what is at the "
        "path only if it is an empty file; anything non-empty there is not this export, so "
        "leave it and pass another path. The same path works once nothing is there (a path "
        "holding anything is refused as exists). Then retry amicus_job_export_diff with the "
        "same job_id. The job's record is kept and not marked delivered."
    ),
    "partial_file": (
        "amicus could not finish the export file and could not empty it, so a partial file "
        "may remain. Delete what is at the path only if it is this call's partial file, else "
        "pass another path, then retry amicus_job_export_diff with the same job_id. The "
        "job's record is kept and not marked delivered."
    ),
}


def _cursor_for(row: dict[str, Any]) -> str:
    return f"{row['started_epoch']!r}:{row['job_id']}"


def _parse_cursor(cursor: str) -> tuple[float, str] | None:
    """(started_epoch, job_id) from a cursor in the form this tool issues, else None. Only
    the form is checked: a well-formed cursor is an anchor whether or not it was issued."""
    epoch, sep, job_id = cursor.partition(":")
    if not sep or not _JOB_ID_RE.fullmatch(job_id):
        return None
    try:
        started = float(epoch)
    except ValueError:
        return None
    # `nan` compares false to every row, so it would page to nothing rather than fail.
    return (started, job_id) if math.isfinite(started) else None


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    def store():
        return lifecycle.job_store(settings)

    async def resolve(ctx: Any, workspace_root: str | None):
        return await lookup.resolve_job_workspace(settings, ctx, workspace_root)

    def task_for(job_id: str) -> str | None:
        return lookup.task_map(settings).task_for(job_id)

    async def read_status(
        ctx: Any, workspace_root: str | None, job_id: str, *, cancel: bool, wait: int = 0
    ) -> dict[str, Any]:
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        # Read first, even for a cancel: a foreign record is never signalled (decision 6).
        try:
            row = await asyncio.to_thread(store().status, cwd, job_id)
            deadline = time.monotonic() + wait
            while (
                row is not None
                and row["status"] == "running"
                and lookup.backend_of(row) is not None
                and (remaining := deadline - time.monotonic()) > 0
            ):
                await asyncio.sleep(min(_WAIT_POLL_SECONDS, remaining))
                row = await asyncio.to_thread(store().status, cwd, job_id)
            if row is not None and cancel and lookup.backend_of(row) is not None:
                row = await asyncio.to_thread(store().cancel, cwd, job_id)
        except ResultUnreadable as exc:
            # Report the read error, never a state. An unreadable result is met only once
            # the worker is stopped (#280), so a cancel's worker is stopped then. An
            # unreadable job record (#530) can meet a running worker: it is stopped only
            # when the store signalled it before the read failed, and otherwise the
            # free repair is the cancel itself.
            record = isinstance(exc, MetaUnreadable)
            stopped = cancel and (not record or (isinstance(exc, MetaUnreadable) and exc.signalled))
            unsent = cancel and not stopped
            return unreadable_result_envelope(
                lookup.job_meta(cwd, source, roots_source),
                tool="amicus_job_cancel" if unsent else "amicus_job_status",
                next_step="retry_after_delay" if unsent else "poll_job_status",
                arguments=job_status_arguments(job_id, workspace_root),
                job_id=job_id,
                errno=exc.errno,
                signalled=stopped,
                record=record,
                unsent_cancel=unsent,
            )
        if row is None or lookup.backend_of(row) is None:
            return lookup.job_not_found(
                job_id, lookup.job_meta(cwd, source, roots_source), workspace_root
            )
        meta = lookup.job_meta(
            cwd,
            source,
            roots_source,
            backend=lookup.backend_of(row),
            kind=lookup.kind_of(row),
        )
        return lookup.status_model(row, lookup.workspace_of(cwd, source), task_for(job_id), meta)

    async def deliver(
        ctx: Any,
        workspace_root: str | None,
        job_id: str,
        detail: str,
        *,
        consume: bool,
        retry: tuple[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str | None, bool, Any]:
        """The resolution, lookup and `finished_job_envelope` path every result reader
        shares: (envelope, record, cwd, delivered, meta). A workspace, read or lookup
        failure comes back as the envelope with no record. Nothing is marked delivered.
        `retry` is the (tool, arguments) an unreadable result's repair repeats; omitted,
        it is the fetch or consume this call made."""
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err, None, None, False, None
        assert cwd is not None
        try:
            rec, payload = await asyncio.to_thread(store().result_payload, cwd, job_id)
        except ResultUnreadable as exc:
            # Either read (status, then the payload) found a result that exists but cannot
            # be read (#280). The repair names the call made, which is free either way, with
            # the detail asked for: followed at the default, a full-detail consume would
            # deliver the summary and then delete the record. A consume deleted nothing.
            tool, arguments = retry or (
                "amicus_job_consume_result" if consume else "amicus_job_result",
                {**job_status_arguments(job_id, workspace_root), "detail": detail},
            )
            unreadable = unreadable_result_envelope(
                lookup.job_meta(cwd, source, roots_source),
                tool=tool,
                next_step="fetch_job_result",
                arguments=arguments,
                job_id=job_id,
                errno=exc.errno,
                record=isinstance(exc, MetaUnreadable),
            )
            return unreadable, None, cwd, False, None
        backend = lookup.backend_of(rec) if rec is not None else None
        if rec is None or backend is None:
            missing = lookup.job_not_found(
                job_id, lookup.job_meta(cwd, source, roots_source), workspace_root
            )
            return missing, None, cwd, False, None
        kind = lookup.kind_of(rec)
        meta = lookup.job_meta(cwd, source, roots_source, backend=backend, kind=kind)
        meta.task_id = task_for(job_id)
        envelope, delivered = finished_job_envelope(
            rec, payload, job_id, kind, meta, detail, workspace_root
        )
        if delivered and isinstance(envelope.get("meta"), dict) and meta.task_id is not None:
            envelope["meta"]["task_id"] = meta.task_id
        return envelope, rec, cwd, delivered, meta

    async def read_result(
        ctx: Any, workspace_root: str | None, job_id: str, detail: str, *, consume: bool
    ) -> dict[str, Any]:
        envelope, rec, cwd, delivered, _meta = await deliver(
            ctx, workspace_root, job_id, detail, consume=consume
        )
        if rec is None:
            return envelope
        assert cwd is not None
        if delivered:
            # Before any discard, so a consume that cannot delete leaves the record
            # evictable rather than holding a cap slot until its TTL (#244).
            await lifecycle.mark_delivered(store(), cwd, job_id)
        expected = consumable_state(rec["status"], delivered)
        if not consume or expected is None:
            return envelope
        # Every discard outcome still returns the envelope, since refusing would lose paid
        # work; meta.consume reports which outcome it was (#44). The discard deletes only a
        # record still in the state this call read, so a failed job whose result appeared
        # since is kept for a retried consume to deliver (#126).
        outcome = await asyncio.to_thread(store().discard, cwd, job_id, expected=expected)
        return attach_consume_disposition(envelope, outcome, job_id, workspace_root)

    @app.tool(
        name="amicus_job_status",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Poll a background job (free)",
        meta=lifecycle_meta("amicus_job_status"),
        description=(
            f"{FREE_MARKER} Poll a job's state without fetching its result: status, elapsed "
            "time, result_available, result_ok, and poll_after_ms to honor before the next "
            "poll while status is running (it grows with elapsed time, up to "
            f"{MAX_POLL_AFTER_MS / 1000:g} s; null on any terminal status), or pass a positive "
            "wait_seconds, which is itself the wait (at most "
            f"{MAX_STATUS_WAIT_SECONDS} s): call again at once if it returns running. "
            f"{_RETENTION}"
        ),
    )
    @guard("amicus_job_status")
    async def amicus_job_status(
        job_id: JobIdParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        wait_seconds: WaitSecondsParam = 0,
    ) -> dict[str, Any]:
        """Poll a background job."""
        return await read_status(ctx, workspace_root, job_id, cancel=False, wait=wait_seconds)

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
            "instead. A re-read is free until the record expires or, once this tool has "
            "returned it, the per-workspace cap evicts it for a later paid call. A "
            f"still-running job is job_running with retry_after_ms. {_RETENTION}"
        ),
    )
    @guard("amicus_job_result")
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
            f"{FREE_MARKER} Like amicus_job_result, then delete the record; "
            "meta.consume.discard_outcome says what happened. After removed or missing a "
            "repeat call returns job_not_found (not idempotent); otherwise the record may "
            "remain, so see meta.consume.follow_up. A failed, cancelled or timed-out job "
            "returns its terminal error, and meta.consume reports its discard too. "
            "A corrupt or incompatible record is kept."
        ),
    )
    @guard("amicus_job_consume_result")
    async def amicus_job_consume_result(
        job_id: JobIdParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch and delete a background job's result."""
        return await read_result(ctx, workspace_root, job_id, detail, consume=True)

    async def export_diff(
        ctx: Any, workspace_root: str | None, job_id: str, path: str
    ) -> dict[str, Any]:
        # The same read amicus_job_result makes at its default detail, so every workspace,
        # lookup, corrupt or incompatible outcome is that tool's (#556). Two repairs differ,
        # because following that tool's would return the diff inline: an unreadable result
        # repeats this export, and a running job's prose finishes with this export.
        # The path is the caller's own value, not a prompt input, and a repair's arguments
        # must be a complete call, so the retry carries it.
        retry_args = {**job_status_arguments(job_id, workspace_root), "path": path}
        envelope, rec, cwd, delivered, meta = await deliver(
            ctx,
            workspace_root,
            job_id,
            "summary",
            consume=False,
            retry=("amicus_job_export_diff", retry_args),
        )
        error = envelope.get("error") if envelope.get("ok") is False else None
        if rec is not None and isinstance(error, dict) and error.get("code") == "job_running":
            repair = error.get("repair")
            if isinstance(repair, dict):
                repair["alternative"] = _EXPORT_RUNNING_ALTERNATIVE
        if rec is None or not delivered:
            return envelope
        assert cwd is not None
        assert meta is not None
        if lookup.kind_of(rec) != "delegate":
            reason = "names a job that is not a delegate; only a delegate's diff is exported"
            return error_envelope(
                "invalid_arguments",
                f"amicus_job_export_diff: 1 invalid argument(s): job_id — {reason}",
                meta,
                failing_tool="amicus_job_export_diff",
                repair_alternative=(
                    "Pass the job_id of an amicus_delegate or amicus_delegate_async job; "
                    "read any other job with amicus_job_result."
                ),
                invalid_arguments=[InvalidArgument(field="job_id", reason=reason)],
            )
        found = exportable_diff(envelope)
        if found is not None:
            diff, where = found
            try:
                written = await asyncio.to_thread(
                    write_diff_file, path, diff, job_store_root=str(store().root)
                )
            except ExportRefused as exc:
                # Neither the message nor the repair echoes the path (AGENTS.md rule 18).
                return error_envelope(
                    "invalid_arguments",
                    f"amicus_job_export_diff: 1 invalid argument(s): path — {exc.reason}",
                    meta,
                    failing_tool="amicus_job_export_diff",
                    repair_alternative=(
                        "Pass an absolute path to a file that does not exist yet, in an "
                        "existing directory you can write that is outside amicus's job "
                        "store; nothing was written and the job is unchanged."
                    ),
                    invalid_arguments=[InvalidArgument(field="path", reason=exc.reason)],
                )
            except ExportFailed as exc:
                return error_envelope(
                    "export_failed",
                    f"amicus_job_export_diff: {exc}; the job's record is kept undelivered",
                    meta,
                    retry_after_ms=1000,
                    repair_alternative=_EXPORT_FAILED_REPAIR[exc.left],
                )
            attach_diff_export(envelope, written, where)
        # Only now, once the file is whole: a refused or failed export leaves the job
        # undelivered, so it still holds its cap slot and is never evicted unread.
        await lifecycle.mark_delivered(store(), cwd, job_id)
        return envelope

    @app.tool(
        name="amicus_job_export_diff",
        annotations=annotations_for("job_export", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Write a delegate job's diff to a new file (free)",
        meta=lifecycle_meta("amicus_job_export_diff"),
        description=(
            f"{FREE_MARKER} Write a finished delegate job's diff (or partial.diff) to one new "
            "file at `path` on the server's filesystem, never overwriting; returns "
            "amicus_job_result's envelope with that diff null. amicus applies nothing; "
            "review the diff. meta.diff_export gives bytes, SHA-256, source "
            '("partial" is incomplete); check meta.truncated, meta.redacted_paths too. The '
            "file is yours to delete, outside the job retention."
        ),
    )
    @guard("amicus_job_export_diff")
    async def amicus_job_export_diff(
        job_id: JobIdParam,
        path: DiffPathParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
    ) -> dict[str, Any]:
        """Write a delegate job's diff to a new file."""
        return await export_diff(ctx, workspace_root, job_id, path)

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
    @guard("amicus_job_cancel")
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
            "list). Only an explicit `limit` pages (has_more: true; pass next_cursor as "
            "`cursor` with the same filters for the page after it). The per-workspace cap "
            "AMICUS_JOB_MAX_COUNT limits how many jobs are kept; server processes sharing a "
            f"state root can each exceed it by one start. {_RETENTION}"
        ),
    )
    @guard("amicus_job_list")
    async def amicus_job_list(
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        limit: JobLimitParam = None,
        cursor: JobCursorParam = None,
        status: JobStatusFilterParam = None,
        backend: OptionalBackendParam = None,
        task_id: TaskIdParam = None,
    ) -> dict[str, Any]:
        """List background jobs."""
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        anchor: tuple[float, str] | None = None
        if cursor is not None:
            anchor = _parse_cursor(cursor)
            if anchor is None:
                reason = "not in the form of a next_cursor amicus_job_list returns"
                return error_envelope(
                    "invalid_arguments",
                    f"amicus_job_list: 1 invalid argument(s): cursor — {reason}",
                    lookup.job_meta(cwd, source, roots_source),
                    repair_tool="amicus_job_list",
                    failing_tool="amicus_job_list",
                    repair_alternative=(
                        "Pass the previous page's next_cursor as `cursor` unchanged, or omit "
                        "it to start from the newest job."
                    ),
                    invalid_arguments=[InvalidArgument(field="cursor", reason=reason)],
                )
        try:
            rows = await asyncio.to_thread(store().list_jobs, cwd)
        except ResultUnreadable as exc:
            # One record's result (#280) or job record (#530) exists but cannot be
            # read. The whole listing is refused rather than served without that row:
            # a page that silently omits a job would let the next cursor step past it,
            # and the schema has no way to say a row is missing. The repair repeats this exact call.
            filters = {
                "limit": limit,
                "cursor": cursor,
                "status": status,
                "backend": backend,
                "task_id": task_id,
            }
            return unreadable_result_envelope(
                lookup.job_meta(cwd, source, roots_source),
                tool="amicus_job_list",
                next_step="list_jobs",
                arguments={
                    "workspace_root": workspace_root,
                    **{k: v for k, v in filters.items() if v is not None},
                },
                job_id=None,
                errno=exc.errno,
                record=isinstance(exc, MetaUnreadable),
            )
        tasks = lookup.task_map(settings).entries()
        # First association wins, as TaskJobMap.task_for does: a keyed replay from another
        # task adds a forward entry for recovery, and the job's own task_id is the first
        # task that named it on every surface (ADR 0020). "First" is record order, not
        # proof of creation: a creator and a replayer record concurrently, and an untasked
        # creator records nothing.
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
        if anchor is not None:
            rows = [r for r in rows if (r["started_epoch"], r["job_id"]) < anchor]
        truncated = limit is not None and len(rows) > limit
        if limit is not None:
            rows = rows[:limit]
        result = JobListResult(
            jobs=[lookup.summary_model(r, task_by_job.get(r["job_id"])) for r in rows],
            workspace=lookup.workspace_of(cwd, source),
            has_more=truncated,
            truncated=truncated,
            truncation_hint=(
                f"showing the {limit} newest of more matching jobs; pass next_cursor as "
                "`cursor` with the same filters for the next page, or narrow with `status`, "
                "`backend` or `task_id`"
                if truncated
                else None
            ),
            next_cursor=_cursor_for(rows[-1]) if truncated else None,
            meta=lookup.job_meta(cwd, source, roots_source),
        ).model_dump(mode="json")
        return result

    return (
        "amicus_job_status",
        "amicus_job_result",
        "amicus_job_consume_result",
        "amicus_job_export_diff",
        "amicus_job_cancel",
        "amicus_job_list",
    )
