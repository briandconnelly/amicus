"""start / await / run_sync over pontonier's JobStore (ported from codex-in-claude
server.py's `_start_job`/`_await_job_result`/`_run_sync`; the keyed path lands here in M2;
ADR 0008). The prompt inputs stream to the worker over stdin; only `RunSpec.public()` is
persisted."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pontonier.core.jobs import JobStore

from amicus import obs
from amicus.errors import error_envelope
from amicus.jobs.delivery import finished_job_envelope
from amicus.orchestration.isolation import WORKTREE_PREFIX
from amicus.schemas.fingerprint import RESULT_FORMAT
from amicus.schemas.results import JobFollowUp, JobStarted

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from amicus.config import Settings
    from amicus.jobs.taskmap import TaskJobMap
    from amicus.plugin import BackendPlugin
    from amicus.request import RunSpec
    from amicus.schemas.envelope import Meta

SYNC_POLL_INTERVAL_S = 0.25
SYNC_AWAIT_GRACE_S = 30
SYNC_PROGRESS_THROTTLE_S = 1.0
SYNC_PROGRESS_REPORT_TIMEOUT_S = 5.0

# The waiting instruction every async start hands back. Kept beside the repair table's
# job_running prose (errors.py) and amicus_job_result's description: all three describe
# one lifecycle, and tests/test_surface_honesty.py holds them to it.
POLL_FOLLOW_UP = (
    "Poll amicus_job_status with these arguments while status is running, honoring "
    "poll_after_ms. On any terminal status, call amicus_job_result for the stored result "
    "or the terminal error. Recover a lost job_id with amicus_job_list."
)

# Bound on acquiring the idempotency coordination locks for a keyed start: a peer holding
# the flock degrades to a retryable idempotency_in_progress instead of hanging a worker.
IDEM_LOCK_ACQUIRE_TIMEOUT_S = 0.5
IDEM_IN_PROGRESS_RETRY_MS = 250
IDEM_IO_ERROR_RETRY_MS = 1000
_IDEM_MESSAGES: dict[str, str] = {
    "idempotency_conflict": (
        "idempotency_key already used with different effective arguments (backend, model, "
        "reasoning_effort, scope, options or the prompt inputs)."
    ),
    "idempotency_result_unavailable": (
        "A prior run for this idempotency_key already completed; its result is no longer "
        "available (consumed or evicted)."
    ),
    "idempotency_in_progress": (
        "Idempotency coordination is momentarily busy (a run is still starting or the "
        "workspace lock is contended); retry shortly."
    ),
}
# Terminal keyed outcomes -> (code, retry_after_ms). Anything unexpected degrades to the
# retryable in_progress so a new pontonier outcome can never become a silent success.
_IDEM_TERMINAL: dict[str, tuple[str, int | None]] = {
    "conflict": ("idempotency_conflict", None),
    "unavailable": ("idempotency_result_unavailable", None),
    "in_progress": ("idempotency_in_progress", IDEM_IN_PROGRESS_RETRY_MS),
}
# An unexpected pontonier outcome degrades to the retryable in_progress.
_IDEM_UNKNOWN_OUTCOME = _IDEM_TERMINAL["in_progress"]


def job_store(settings: Settings) -> JobStore:
    return JobStore(
        root=settings.state_dir,
        ttl_seconds=settings.job_ttl_seconds,
        max_seconds=settings.job_max_seconds,
        max_count=settings.job_max_count,
        cleanup_root=Path(tempfile.gettempdir()),
        cleanup_prefix=WORKTREE_PREFIX,
    )


def worker_cmd(job_dir: object) -> list[str]:
    return [sys.executable, "-m", "amicus._worker", str(job_dir)]


def _extra(spec: RunSpec) -> dict[str, Any]:
    return {"result_format": RESULT_FORMAT, "backend": spec.backend, "tool": spec.tool}


def job_started_handle(
    job_id: str,
    *,
    spec: RunSpec,
    status: str,
    started_at: str,
    deadline: int,
    expires_at: str | None,
    meta: Meta,
    poll_after_ms: int = 1000,
    task_id: str | None = None,
) -> dict[str, Any]:
    meta.job_id = job_id
    meta.task_id = task_id
    poll_arguments: dict[str, Any] = {"job_id": job_id, "workspace_root": spec.cwd}
    return JobStarted(
        job_id=job_id,
        backend=spec.backend,
        kind=spec.kind,
        status=status,  # ty: ignore[invalid-argument-type]
        started_at=started_at,
        deadline_seconds=deadline,
        poll_after_ms=poll_after_ms,
        expires_at=expires_at,
        task_id=task_id,
        follow_up=JobFollowUp(
            next_step="poll_job_status",
            tool="amicus_job_status",
            arguments=poll_arguments,
            alternative=POLL_FOLLOW_UP,
        ),
        meta=meta,
    ).model_dump(mode="json")


def _spawn_failure(exc: Exception, meta: Meta, plugin: BackendPlugin) -> dict[str, Any]:
    return error_envelope(
        "internal_error",
        f"failed to start background job: {obs.safe_type_name(exc)}",
        meta,
        plugin=plugin,
        repair_alternative="Check the job state-dir permissions (AMICUS_STATE_DIR) and retry.",
    )


def idem_error(
    code: str,
    meta: Meta,
    plugin: BackendPlugin,
    *,
    tool: str,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    return error_envelope(
        code,
        _IDEM_MESSAGES[code],
        meta,
        plugin=plugin,
        retry_after_ms=retry_after_ms,
        repair_tool=tool,
        repair_alternative=(
            "Retry the same call with the same idempotency_key after retry_after_ms."
            if code == "idempotency_in_progress"
            else "Call the same tool again with a new idempotency_key (a new paid run)."
        ),
    )


def _idem_io_error(meta: Meta, plugin: BackendPlugin, *, tool: str) -> dict[str, Any]:
    return error_envelope(
        "internal_error",
        "Transient storage error reading the idempotency record.",
        meta,
        plugin=plugin,
        retry_after_ms=IDEM_IO_ERROR_RETRY_MS,
        repair_tool=tool,
        repair_alternative="Retry the same call with the same idempotency_key.",
    )


def mark_replayed(envelope: dict[str, Any]) -> dict[str, Any]:
    """Stamp meta.idempotency_replayed on an outgoing envelope so the caller can see that no
    new spend occurred. Applied after the envelope is built, never persisted."""
    meta = envelope.get("meta")
    if isinstance(meta, dict):
        meta["idempotency_replayed"] = True
    return envelope


_PENDING_START_CLEANUPS: set[asyncio.Future] = set()


def _swallow(fut: asyncio.Future) -> None:
    if not fut.cancelled():
        fut.exception()


def _stop_orphaned_start(store: JobStore, cwd: str) -> Callable[[asyncio.Future], None]:
    def _cb(fut: asyncio.Future) -> None:
        _PENDING_START_CLEANUPS.discard(fut)
        if fut.cancelled() or fut.exception() is not None:
            return
        job_id, _ = fut.result()
        with contextlib.suppress(RuntimeError):
            cancel = asyncio.get_running_loop().run_in_executor(None, store.cancel, cwd, job_id)
            cancel.add_done_callback(_swallow)

    return _cb


async def start_job(
    store: JobStore, spec: RunSpec, meta: Meta, plugin: BackendPlugin, *, deadline: int
) -> dict[str, Any]:
    """Spawn the detached worker (off-loop, shielded so a cancellation mid-spawn cannot
    orphan a paid job) and return the JobStarted handle or an internal_error envelope."""
    start_fut = asyncio.ensure_future(
        asyncio.to_thread(
            store.start,
            worker_cmd,
            spec.cwd,
            kind=spec.kind,
            extra=_extra(spec),
            write_spec=spec.public(),
            stdin_text=spec.inputs_json(),
        )
    )
    try:
        job_id, started_at = await asyncio.shield(start_fut)
    except asyncio.CancelledError:
        _PENDING_START_CLEANUPS.add(start_fut)
        start_fut.add_done_callback(_stop_orphaned_start(store, spec.cwd))
        raise
    except OSError as exc:
        return _spawn_failure(exc, meta, plugin)
    return job_started_handle(
        job_id,
        spec=spec,
        status="running",
        started_at=started_at,
        deadline=deadline,
        expires_at=None,
        meta=meta,
    )


async def start_async(
    store: JobStore,
    spec: RunSpec,
    meta: Meta,
    plugin: BackendPlugin,
    *,
    deadline: int,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """The _async return path. Unkeyed it is exactly start_job. Keyed it reserves
    (tool, key) in the workspace index: a first reservation spawns and returns a running
    handle; a duplicate returns the existing job's REAL handle; the other outcomes become
    their envelopes (ADR 0008 decision 2). The store call blocks on a cross-process lock,
    so it runs off the event loop; an _async caller never waits on in_progress.

    A cancellation that lands during a keyed spawn leaves the job running (the reservation
    and worker are already committed); the caller recovers it by replaying the same key or
    via amicus_job_list — deliberately unlike the unkeyed path, which cancels its orphan."""
    if idempotency_key is None:
        return await start_job(store, spec, meta, plugin, deadline=deadline)
    try:
        outcome = await asyncio.to_thread(
            store.start_idempotent,
            worker_cmd,
            spec.cwd,
            kind=spec.kind,
            tool=spec.tool,
            key=idempotency_key,
            arg_hash=spec.arg_hash(),
            extra=_extra(spec),
            write_spec=spec.public(),
            stdin_text=spec.inputs_json(),
            lock_timeout=IDEM_LOCK_ACQUIRE_TIMEOUT_S,
        )
    except OSError as exc:
        return _spawn_failure(exc, meta, plugin)
    result_kind = outcome["kind"]
    if result_kind == "created":
        return job_started_handle(
            outcome["job_id"],
            spec=spec,
            status="running",
            started_at=outcome["started_at"],
            deadline=deadline,
            expires_at=None,
            meta=meta,
        )
    if result_kind == "replay":
        snap = await asyncio.to_thread(store.status, spec.cwd, outcome["job_id"])
        if snap is None:
            return idem_error("idempotency_result_unavailable", meta, plugin, tool=spec.tool)
        return mark_replayed(
            job_started_handle(
                outcome["job_id"],
                spec=spec,
                status=snap["status"],
                started_at=snap["started_at"],
                deadline=snap["deadline_seconds"],
                expires_at=snap["expires_at"],
                meta=meta,
                poll_after_ms=snap["poll_after_ms"],
            )
        )
    if result_kind == "io_error":
        return _idem_io_error(meta, plugin, tool=spec.tool)
    code, retry = _IDEM_TERMINAL.get(result_kind, _IDEM_UNKNOWN_OUTCOME)
    return idem_error(code, meta, plugin, tool=spec.tool, retry_after_ms=retry)


async def await_job_result(
    store: JobStore,
    cwd: str,
    job_id: str,
    kind: str,
    meta: Meta,
    detail: str,
    timeout: int,
    ctx: Any,
    plugin: BackendPlugin,
) -> dict[str, Any]:
    """Await this handler's own detached job. Explicit cancellation cancels the job so
    spend stops; a transport drop leaves the record recoverable. Throttled progress rides
    ctx.report_progress when the caller gave a progress token (a no-op otherwise)."""
    deadline = time.monotonic() + timeout + SYNC_AWAIT_GRACE_S
    last_progress_at = 0.0
    last_events = -1
    try:
        while True:
            rec = await asyncio.to_thread(store.status, cwd, job_id)
            if rec is None:
                return error_envelope(
                    "internal_error", "job record disappeared while awaiting", meta, plugin=plugin
                )
            if rec["status"] != "running":
                break
            events = rec.get("events_seen", 0)
            now = time.monotonic()
            if (
                ctx is not None
                and events != last_events
                and now - last_progress_at >= SYNC_PROGRESS_THROTTLE_S
            ):
                last_events = events
                last_progress_at = now
                with contextlib.suppress(Exception):
                    # asyncio.TimeoutError is an Exception subclass on 3.11+, so a hung
                    # report_progress is bounded and still swallowed here, not left to
                    # stall the poll loop past the job's own deadline.
                    await asyncio.wait_for(
                        ctx.report_progress(
                            progress=float(events), message=f"backend events: {events}"
                        ),
                        timeout=SYNC_PROGRESS_REPORT_TIMEOUT_S,
                    )
            if time.monotonic() > deadline:
                await asyncio.to_thread(store.cancel, cwd, job_id)
                return error_envelope(
                    "timeout",
                    f"the run exceeded {timeout}s and the grace window; job cancelled.",
                    meta,
                    plugin=plugin,
                )
            await asyncio.sleep(SYNC_POLL_INTERVAL_S)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await asyncio.shield(asyncio.to_thread(store.cancel, cwd, job_id))
        raise
    rec2, payload = await asyncio.to_thread(store.result_payload, cwd, job_id)
    if rec2 is None:
        return error_envelope(
            "internal_error", "job record expired before its result was read", meta, plugin=plugin
        )
    envelope, _delivered = finished_job_envelope(rec2, payload, job_id, kind, meta, detail, cwd)
    return envelope


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
        except asyncio.CancelledError:
            # A cancellation landing between start_job returning and await_job_result
            # being entered would otherwise propagate straight out of run_sync, past
            # await_job_result's own cancel-on-CancelledError handler, and orphan the
            # already-spawned job. Shield the cleanup (mirrors await_job_result) and
            # re-raise so the caller still sees the cancellation.
            with contextlib.suppress(Exception):
                await asyncio.shield(asyncio.to_thread(store.cancel, spec.cwd, job_id))
            raise
        except OSError as exc:
            # The type, not `exc_summary(exc)`: rule 18 keeps exception text out of the
            # log, and `exc_summary` masks secrets rather than prompt inputs. The path
            # this failed on is already named by `job_id`. Through `safe_type_name` rather
            # than `type(exc).__name__`, because `__name__` is writable: a forged one
            # carrying a newline would otherwise arrive as an ordinary string and forge a
            # whole log line.
            obs.get_logger(__name__).warning(
                "task map write failed for task %s -> job %s: %s",
                task_id,
                job_id,
                obs.safe_type_name(exc),
            )
    envelope = await await_job_result(
        store, spec.cwd, job_id, spec.kind, meta, detail, timeout, ctx, plugin
    )
    return _with_task_id(envelope, task_id)
