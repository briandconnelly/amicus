"""Sync-through-detached-job: a real JobStore, a fake worker, the await loop."""

from __future__ import annotations

import asyncio
import json
import sys

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
