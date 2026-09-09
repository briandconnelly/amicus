"""Sync-through-detached-job: a real JobStore, a fake worker, the await loop."""

from __future__ import annotations

import asyncio
import builtins
import json
import logging
import sys
import threading
import time

import pytest
from pontonier.core import jobs as pjobs
from tests.support import fakeplugin

from amicus import config
from amicus.jobs import lifecycle
from amicus.jobs.taskmap import TaskJobMap
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


async def _start(store, spec, key, **kw):
    return await lifecycle.start_async(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        deadline=1800,
        idempotency_key=key,
        **kw,
    )


async def test_unkeyed_async_start_returns_a_running_handle(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _sleeping_worker_cmd(30))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, None)
    assert out["ok"] is True and out["status"] == "running" and out["deadline_seconds"] == 1800
    assert out["backend"] == "fake" and out["kind"] == "consult" and out["task_id"] is None
    assert out["poll_after_ms"] == 1000 and out["expires_at"] is None
    assert out["follow_up"]["tool"] == "amicus_job_status"
    assert out["follow_up"]["arguments"] == {
        "job_id": out["job_id"],
        "workspace_root": str(tmp_path),
    }
    # A handle is a plain model dump (nulls kept; only delivered paid results are slimmed).
    assert out["meta"]["job_id"] == out["job_id"] and out["meta"]["idempotency_replayed"] is None
    store.cancel(str(tmp_path), out["job_id"])


async def test_keyed_start_creates_then_replays_the_real_handle(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    first = await _start(store, spec, "k1")
    assert first["ok"] is True and first["meta"]["idempotency_replayed"] is None
    deadline = time.monotonic() + 10
    while store.status(str(tmp_path), first["job_id"])["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    again = await _start(store, spec, "k1")
    assert again["ok"] is True and again["job_id"] == first["job_id"]
    assert again["meta"]["idempotency_replayed"] is True
    assert again["status"] == "done" and again["expires_at"] is not None
    assert again["started_at"] == first["started_at"]
    assert len(store.list_jobs(str(tmp_path))) == 1
    spec_on_disk = json.loads(
        (store._job_dir(str(tmp_path), first["job_id"]) / "spec.json").read_text()
    )
    assert "why?" not in json.dumps(spec_on_disk)


async def test_keyed_start_with_different_inputs_is_a_conflict(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    first = await _start(store, spec, "k2")
    other_spec = _spec(
        str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800, question="else?"
    )
    other = await _start(store, other_spec, "k2")
    assert other["ok"] is False and other["error"]["code"] == "idempotency_conflict"
    assert other["error"]["temporary"] is False
    assert other["error"]["repair"]["next_step"] == "use_new_idempotency_key"
    assert other["error"]["repair"]["tool"] == "amicus_consult_async"
    assert other["meta"]["backend"] == "fake" and "job_id" not in other["meta"]
    assert len(store.list_jobs(str(tmp_path))) == 1 and first["ok"] is True


async def test_keyed_start_after_the_record_is_gone_is_unavailable(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    first = await _start(store, spec, "k3")
    deadline = time.monotonic() + 10
    while store.status(str(tmp_path), first["job_id"])["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    assert store.discard(str(tmp_path), first["job_id"]) is pjobs.DiscardOutcome.REMOVED
    gone = await _start(store, spec, "k3")
    assert gone["ok"] is False and gone["error"]["code"] == "idempotency_result_unavailable"
    assert gone["error"]["repair"]["next_step"] == "use_new_idempotency_key"


@pytest.mark.parametrize(
    ("outcome", "code", "retry"),
    [
        ({"kind": "in_progress"}, "idempotency_in_progress", 250),
        ({"kind": "io_error"}, "internal_error", 1000),
        ({"kind": "something_new"}, "idempotency_in_progress", 250),
    ],
)
async def test_transient_keyed_outcomes_are_retryable_envelopes(
    tmp_path, monkeypatch, outcome, code, retry
):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(store, "start_idempotent", lambda *a, **kw: outcome)
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, "k4")
    assert out["ok"] is False and out["error"]["code"] == code
    assert out["error"]["temporary"] is True and out["error"]["retry_after_ms"] == retry
    assert "idempotency_key" in out["error"]["repair"]["alternative"]


async def test_keyed_replay_whose_record_vanished_is_unavailable(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(
        store, "start_idempotent", lambda *a, **kw: {"kind": "replay", "job_id": "0" * 32}
    )
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, "k5")
    assert out["ok"] is False and out["error"]["code"] == "idempotency_result_unavailable"


async def test_keyed_spawn_failure_is_an_internal_error(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", lambda jd: ["/nonexistent-binary-xyz"])
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, "k6")
    assert out["ok"] is False and out["error"]["code"] == "internal_error"
    assert "failed to start background job" in out["error"]["message"]
    assert store.list_jobs(str(tmp_path)) == []


async def test_keyed_start_runs_off_the_event_loop(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    seen: dict = {}

    def blocking(cmd_factory, cwd, **kw):
        seen["thread"] = threading.current_thread().name
        seen["kw"] = kw
        return {"kind": "conflict"}

    monkeypatch.setattr(store, "start_idempotent", blocking)
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    await _start(store, spec, "k7")
    assert seen["thread"] != threading.main_thread().name
    assert seen["kw"]["key"] == "k7" and seen["kw"]["tool"] == "amicus_consult_async"
    assert seen["kw"]["arg_hash"] == spec.arg_hash() and seen["kw"]["kind"] == "consult"
    assert seen["kw"]["lock_timeout"] == lifecycle.IDEM_LOCK_ACQUIRE_TIMEOUT_S
    assert seen["kw"]["write_spec"] == spec.public()
    assert seen["kw"]["stdin_text"] == spec.inputs_json()
    assert seen["kw"]["extra"] == {
        "result_format": 4,
        "backend": "fake",
        "tool": "amicus_consult_async",
    }


async def test_keyed_start_cancellation_leaves_the_job_running_and_replayable(
    tmp_path, monkeypatch
):
    """Cancelling the awaiting task while the thread is inside store.start_idempotent
    must not orphan the job: the reservation and the worker are already committed by the
    time the thread finishes, so a same-key replay recovers the real job (ADR 0008;
    F1)."""
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    entered = threading.Event()
    finished = threading.Event()
    real_start_idempotent = store.start_idempotent

    def slow_start_idempotent(*args, **kwargs):
        entered.set()
        time.sleep(0.3)
        try:
            return real_start_idempotent(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(store, "start_idempotent", slow_start_idempotent)
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)

    task = asyncio.create_task(_start(store, spec, "k-cancel"))
    while not entered.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    deadline = time.monotonic() + 5
    while not finished.is_set():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)

    replayed = await _start(store, spec, "k-cancel")
    assert replayed["ok"] is True and replayed["meta"]["idempotency_replayed"] is True
    assert len(store.list_jobs(str(tmp_path))) == 1


def test_mark_replayed_stamps_meta_only_when_present():
    replayed = lifecycle.mark_replayed({"ok": True, "meta": {"job_id": "x"}})
    assert replayed["meta"]["idempotency_replayed"] is True
    assert lifecycle.mark_replayed({"ok": False}) == {"ok": False}


def test_current_task_id_is_none_outside_a_task_and_without_the_extension(monkeypatch):
    assert lifecycle.current_task_id() is None
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastmcp_tasks"):
            raise ImportError("no fastmcp_tasks")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert lifecycle.current_task_id() is None


def test_current_task_id_ignores_a_blank_task_context(monkeypatch):
    import fastmcp_tasks.context as task_context

    class _Info:
        task_id = ""

    monkeypatch.setattr(task_context, "get_task_context", lambda: _Info())  # noqa: PLW0108
    assert lifecycle.current_task_id() is None
    monkeypatch.setattr(task_context, "get_task_context", lambda: None)
    assert lifecycle.current_task_id() is None


async def test_run_sync_records_the_task_id_when_inside_a_task(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")
    task_map = TaskJobMap(tmp_path / "tasks.json")
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
        task_map=task_map,
    )
    assert out["ok"] is True and out["meta"]["task_id"] == "task-abc"
    assert task_map.job_for("task-abc") == out["meta"]["job_id"]


async def test_run_sync_outside_a_task_records_nothing(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    task_map = TaskJobMap(tmp_path / "tasks.json")
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
        task_map=task_map,
    )
    assert out["ok"] is True and "task_id" not in out["meta"]
    assert task_map.entries() == {}


async def test_run_sync_survives_a_task_map_write_failure(tmp_path, monkeypatch, caplog):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")

    class _BrokenMap:
        def record(self, task_id, job_id):
            raise OSError("disk full")

    spec = _spec(str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="amicus.jobs.lifecycle"):
        out = await lifecycle.run_sync(
            store,
            spec,
            meta_for(spec),
            fakeplugin.make_plugin(),
            timeout=10,
            detail="summary",
            ctx=None,
            task_map=_BrokenMap(),
        )
    assert out["ok"] is True and out["meta"]["task_id"] == "task-abc"
    assert any("task map" in r.getMessage() for r in caplog.records)


async def test_run_sync_spawn_failure_still_carries_the_task_id(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", lambda job_dir: ["/nonexistent-binary-xyz"])
    spec = _spec(str(tmp_path))
    out = await lifecycle.run_sync(
        store,
        spec,
        meta_for(spec),
        fakeplugin.make_plugin(),
        timeout=10,
        detail="summary",
        ctx=None,
        task_map=TaskJobMap(tmp_path / "tasks.json"),
    )
    assert out["ok"] is False and out["meta"]["task_id"] == "task-abc"
    assert TaskJobMap(tmp_path / "tasks.json").entries() == {}


async def test_cancellation_during_task_map_record_still_cancels_the_job(tmp_path, monkeypatch):
    """A cancellation landing between start_job returning and await_job_result being
    entered (i.e. while the task-map record is in flight) must still cancel the already
    -spawned job, not orphan it (finding 2, fix round 1)."""
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _sleeping_worker_cmd())
    monkeypatch.setattr(lifecycle, "current_task_id", lambda: "task-abc")
    entered = threading.Event()
    release = threading.Event()

    class _BlockingMap:
        def record(self, task_id, job_id):
            entered.set()
            release.wait(5)

    spec = _spec(str(tmp_path))
    task = asyncio.create_task(
        lifecycle.run_sync(
            store,
            spec,
            meta_for(spec),
            fakeplugin.make_plugin(),
            timeout=10,
            detail="summary",
            ctx=None,
            task_map=_BlockingMap(),
        )
    )
    deadline = time.monotonic() + 5
    while not entered.is_set():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    jobs = store.list_jobs(str(tmp_path))
    assert jobs
    job_id = jobs[0]["job_id"]
    deadline = time.monotonic() + 5
    while store.status(str(tmp_path), job_id)["status"] != "cancelled":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    assert store.status(str(tmp_path), job_id)["status"] == "cancelled"
