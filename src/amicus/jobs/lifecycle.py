"""start / await / run_sync over pontonier's JobStore (ported from codex-in-claude
server.py's `_start_job`/`_await_job_result`/`_run_sync`; the keyed/idempotent paths are M2).
The prompt inputs stream to the worker over stdin; only `RunSpec.public()` is persisted."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pontonier.core import redaction
from pontonier.core.jobs import JobStore

from amicus.errors import error_envelope
from amicus.jobs.delivery import finished_job_envelope
from amicus.orchestration.isolation import WORKTREE_PREFIX
from amicus.schemas.envelope import Repair
from amicus.schemas.fingerprint import RESULT_FORMAT
from amicus.schemas.results import JobStarted

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from amicus.config import Settings
    from amicus.plugin import BackendPlugin
    from amicus.request import RunSpec
    from amicus.schemas.envelope import Meta

SYNC_POLL_INTERVAL_S = 0.25
SYNC_AWAIT_GRACE_S = 30
SYNC_PROGRESS_THROTTLE_S = 1.0


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
) -> dict[str, Any]:
    meta.job_id = job_id
    poll_arguments: dict[str, Any] = {"job_id": job_id, "workspace_root": spec.cwd}
    return JobStarted(
        job_id=job_id,
        backend=spec.backend,
        kind=spec.kind,
        status=status,  # ty: ignore[invalid-argument-type]
        started_at=started_at,
        deadline_seconds=deadline,
        poll_after_ms=1000,
        expires_at=expires_at,
        follow_up=Repair(
            next_step="poll_job_status",
            tool="amicus_job_status",
            arguments=poll_arguments,
            alternative=(
                "Poll amicus_job_status with these arguments, honoring poll_after_ms; read "
                "the result with amicus_job_result once result_available is true. Recover a "
                "lost job_id with amicus_job_list."
            ),
        ),
        meta=meta,
    ).model_dump(mode="json")


def _spawn_failure(exc: Exception, meta: Meta, plugin: BackendPlugin) -> dict[str, Any]:
    return error_envelope(
        "internal_error",
        f"failed to start background job: {redaction.exc_summary(exc)}"[:300],
        meta,
        plugin=plugin,
        repair_alternative="Check the job state-dir permissions (AMICUS_STATE_DIR) and retry.",
    )


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
                    await ctx.report_progress(
                        progress=float(events), message=f"backend events: {events}"
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


async def run_sync(
    store: JobStore,
    spec: RunSpec,
    meta: Meta,
    plugin: BackendPlugin,
    *,
    timeout: int,
    detail: str,
    ctx: Any,
) -> dict[str, Any]:
    """The synchronous paid-tool tail: start the detached job and await it."""
    handle = await start_job(store, spec, meta, plugin, deadline=timeout)
    if handle.get("ok") is False:
        return handle
    return await await_job_result(
        store, spec.cwd, handle["job_id"], spec.kind, meta, detail, timeout, ctx, plugin
    )
