"""Sync-through-detached-job: a real JobStore, a fake worker, the await loop."""

from __future__ import annotations

import asyncio
import json
import sys
import threading

import pytest
from tests.support import fakeplugin

from amicus import config
from amicus.jobs import lifecycle
from amicus.request import RunSpec, meta_for
from amicus.schemas.envelope import Meta, dump_success
from amicus.schemas.results import ConsultResult, RawResponse


def _spec(cwd, **kw):
    base = dict(
        backend="fake",
        kind="consult",
        tool="amicus_consult",
        cwd=cwd,
        workspace_source="param",
        roots_source="client",
        host_name="H",
        timeout_seconds=10,
        question="why?",
    )
    base.update(kw)
    return RunSpec(**base)


def _settings(tmp_path):
    return config.settings({"AMICUS_STATE_DIR": str(tmp_path / "state")})


def _success(cwd, raw="RAW"):
    return dump_success(
        ConsultResult(
            summary="Looks fine",
            raw_response=RawResponse(text=raw),
            meta=Meta(backend="fake", cwd=cwd),
        )
    )


def _fake_worker_cmd(envelope: dict):
    payload = json.dumps(envelope)

    def factory(job_dir):
        code = (
            "import os,sys,pathlib;d=pathlib.Path(sys.argv[1]);t=d/'result.json.tmp';"
            "t.write_text(sys.argv[2]);os.replace(str(t),str(d/'result.json'))"
        )
        return [sys.executable, "-c", code, str(job_dir), payload]

    return factory


def _sleeping_worker_cmd(seconds=60.0):
    def factory(job_dir):
        return [
            sys.executable,
            "-c",
            "import time,sys;time.sleep(float(sys.argv[1]))",
            str(seconds),
        ]

    return factory


def test_job_store_is_wired_to_settings_and_the_worktree_prefix(tmp_path):
    store = lifecycle.job_store(_settings(tmp_path))
    assert store.root == tmp_path / "state" and store.cleanup_prefix == "amicus-wt-"
    assert store.ttl_seconds == 86_400 and store.max_seconds == 1_800 and store.max_count == 50
    assert lifecycle.worker_cmd("/jd") == [sys.executable, "-m", "amicus._worker", "/jd"]


async def test_run_sync_delivers_and_records_the_job(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
    )
    assert (
        out["ok"] is True and out["summary"] == "Looks fine" and out["raw_response"]["text"] is None
    )
    job_id = out["meta"]["job_id"]
    rec, payload = store.result_payload(str(tmp_path), job_id)
    assert rec is not None and rec["status"] == "done" and payload["raw_response"]["text"] == "RAW"
    assert (
        rec["kind"] == "consult"
        and rec["extra"]["backend"] == "fake"
        and rec["extra"]["tool"] == "amicus_consult"
    )
    spec_on_disk = json.loads((store._job_dir(str(tmp_path), job_id) / "spec.json").read_text())
    assert "question" not in spec_on_disk and spec_on_disk["kind"] == "consult"


async def test_full_detail_keeps_raw_text(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store, spec, meta_for(spec), fakeplugin.make_plugin(), timeout=10, detail="full", ctx=None
    )
    assert out["raw_response"]["text"] == "RAW"


async def test_spawn_failure_is_an_internal_error_with_no_record(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", lambda jd: ["/nonexistent-binary-xyz"])
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
    )
    assert (
        out["ok"] is False
        and out["error"]["code"] == "internal_error"
        and "start background job" in out["error"]["message"]
    )
    assert store.list_jobs(str(tmp_path)) == []


async def test_orphaned_start_cleanup_cancels_the_spawned_job(tmp_path, monkeypatch):
    """A cancellation racing the spawn (store.start already running in its thread) must
    not orphan the paid job: the done-callback registered under `asyncio.shield` cancels
    it once the spawn actually completes."""
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _sleeping_worker_cmd())
    release = threading.Event()
    real_start = store.start

    def blocking_start(worker_cmd_factory, cwd, **kw):
        release.wait(5)
        return real_start(worker_cmd_factory, cwd, **kw)

    monkeypatch.setattr(store, "start", blocking_start)
    spec = _spec(str(tmp_path))
    task = asyncio.create_task(
        lifecycle.start_job(store, spec, meta_for(spec), fakeplugin.make_plugin(), deadline=10)
    )
    await asyncio.sleep(0.05)  # let asyncio.to_thread enter store.start and block on release
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    # A concurrent store.status()/list_jobs() poll here would race the orphan cleanup's
    # own unlocked termination window in pontonier's JobStore (a real library property,
    # not something this task owns) and can observe/persist a transient "failed" read.
    # A single check after a fixed grace period avoids that race; real callers never
    # poll this tightly against their own just-cancelled start anyway.
    await asyncio.sleep(0.5)
    jobs = store.list_jobs(str(tmp_path))
    assert jobs
    status = store.status(str(tmp_path), jobs[0]["job_id"])
    assert status is not None and status["status"] == "cancelled"


async def test_orphaned_start_cleanup_swallows_a_raising_cancel(tmp_path, monkeypatch):
    """`_swallow` must retrieve a raised exception from the cleanup's cancel future
    rather than letting it propagate (which would surface as an unhandled-exception
    warning or crash the event loop)."""
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _sleeping_worker_cmd())
    release = threading.Event()
    real_start = store.start

    def blocking_start(worker_cmd_factory, cwd, **kw):
        release.wait(5)
        return real_start(worker_cmd_factory, cwd, **kw)

    monkeypatch.setattr(store, "start", blocking_start)
    cancel_calls: list[str] = []

    def raising_cancel(cwd, job_id):
        cancel_calls.append(job_id)
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "cancel", raising_cancel)
    spec = _spec(str(tmp_path))
    task = asyncio.create_task(
        lifecycle.start_job(store, spec, meta_for(spec), fakeplugin.make_plugin(), deadline=10)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    for _ in range(200):
        if cancel_calls:
            break
        await asyncio.sleep(0.01)
    assert cancel_calls  # store.cancel was invoked for the orphaned job
    # If _swallow failed to retrieve the exception, it would still be pending here and
    # asyncio would log it (or, on some loops, raise) when the future is garbage
    # collected; give the loop a beat and rely on pytest-asyncio's strict warning
    # handling to catch a regression.
    await asyncio.sleep(0.05)


async def test_grace_exhausted_cancels_and_times_out(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "SYNC_AWAIT_GRACE_S", 0.05)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(lifecycle, "worker_cmd", _sleeping_worker_cmd())
    spec = _spec(str(tmp_path), timeout_seconds=1)
    out = await lifecycle.run_sync(
        store, spec, meta_for(spec), fakeplugin.make_plugin(), timeout=1, detail="summary", ctx=None
    )
    assert out["error"]["code"] == "timeout" and "cancelled" in out["error"]["message"]
    status = store.status(str(tmp_path), out["meta"]["job_id"])
    assert status is not None and status["status"] == "cancelled"


async def test_cancellation_cancels_the_job(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.01)
    job_id, _ = store.start(
        _sleeping_worker_cmd(), str(tmp_path), kind="consult", extra={"result_format": 1}
    )
    task = asyncio.create_task(
        lifecycle.await_job_result(
            store,
            str(tmp_path),
            job_id,
            "consult",
            Meta(),
            "summary",
            60,
            None,
            fakeplugin.make_plugin(),
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.status(str(tmp_path), job_id)["status"] == "cancelled"


async def test_cancellation_runs_store_cancel_off_the_event_loop(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.01)
    job_id, _ = store.start(
        _sleeping_worker_cmd(), str(tmp_path), kind="consult", extra={"result_format": 1}
    )
    event_loop_thread = threading.get_ident()
    recorded: list[int] = []
    real_cancel = store.cancel

    def spy_cancel(cwd, jid):
        recorded.append(threading.get_ident())
        return real_cancel(cwd, jid)

    monkeypatch.setattr(store, "cancel", spy_cancel)
    task = asyncio.create_task(
        lifecycle.await_job_result(
            store,
            str(tmp_path),
            job_id,
            "consult",
            Meta(),
            "summary",
            60,
            None,
            fakeplugin.make_plugin(),
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert recorded and recorded[0] != event_loop_thread


async def test_vanished_record_and_missing_payload_are_internal_errors(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    out = await lifecycle.await_job_result(
        store,
        str(tmp_path),
        "a" * 32,
        "consult",
        Meta(),
        "summary",
        1,
        None,
        fakeplugin.make_plugin(),
    )
    assert out["error"]["code"] == "internal_error" and "disappeared" in out["error"]["message"]


async def test_missing_stored_payload_after_done_is_an_internal_error(tmp_path, monkeypatch):
    """rec exists and is done, but result_payload comes back empty (record expired
    between the status check and the read) -> covers lifecycle.py's other guard."""
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(store, "result_payload", lambda cwd, jid: (None, None))
    job_id, _ = store.start(
        _fake_worker_cmd(_success(str(tmp_path))), str(tmp_path), kind="consult", extra={}
    )
    out = await lifecycle.await_job_result(
        store,
        str(tmp_path),
        job_id,
        "consult",
        Meta(),
        "summary",
        10,
        None,
        fakeplugin.make_plugin(),
    )
    assert (
        out["error"]["code"] == "internal_error"
        and "expired before its result was read" in out["error"]["message"]
    )


async def test_progress_is_reported_throttled_while_running(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(lifecycle, "SYNC_PROGRESS_THROTTLE_S", 0.0)
    reports: list = []

    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            reports.append((progress, message))

    def worker(job_dir):
        code = (
            "import json,sys,time,pathlib;d=pathlib.Path(sys.argv[1]);"
            "(d/'activity.json').write_text(json.dumps({'events_seen':3,'last_event_epoch':time.time()}));time.sleep(0.2);"
            "(d/'result.json').write_text(sys.argv[2])"
        )
        return [sys.executable, "-c", code, str(job_dir), json.dumps(_success(str(tmp_path)))]

    monkeypatch.setattr(lifecycle, "worker_cmd", worker)
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=Ctx(),
    )
    assert out["ok"] is True
    assert any(m and "events" in m for _, m in reports)


async def test_a_hanging_report_progress_does_not_stall_the_poll_loop(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(lifecycle, "SYNC_PROGRESS_THROTTLE_S", 0.0)
    monkeypatch.setattr(lifecycle, "SYNC_PROGRESS_REPORT_TIMEOUT_S", 0.05)

    class HangingCtx:
        async def report_progress(self, progress, total=None, message=None):
            await asyncio.Event().wait()  # never sets: a report_progress call that hangs

    def worker(job_dir):
        code = (
            "import json,sys,time,pathlib;d=pathlib.Path(sys.argv[1]);"
            "(d/'activity.json').write_text(json.dumps({'events_seen':3,'last_event_epoch':time.time()}));time.sleep(0.2);"
            "(d/'result.json').write_text(sys.argv[2])"
        )
        return [sys.executable, "-c", code, str(job_dir), json.dumps(_success(str(tmp_path)))]

    monkeypatch.setattr(lifecycle, "worker_cmd", worker)
    spec = _spec(str(tmp_path))
    out = await asyncio.wait_for(
        lifecycle.run_sync(
            store,
            spec,
            meta_for(spec),
            fakeplugin.make_plugin(),
            timeout=10,
            detail="summary",
            ctx=HangingCtx(),
        ),
        timeout=10,
    )
    assert out["ok"] is True
