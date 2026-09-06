"""Durability the M2 gate names: a worker that ignores SIGTERM is hard-killed and its
declared worktree removed; a job started by one server process is readable, pollable and
finishable from a fresh process (restart survival, via the per-job worker lock)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pontonier.core.jobs import JobStore

from amicus import config
from amicus.jobs import lifecycle
from amicus.orchestration.isolation import WORKTREE_PREFIX


def _settings(tmp_path):
    return config.settings({"AMICUS_STATE_DIR": str(tmp_path / "state")})


def _stubborn_worker_cmd(worktree: Path):
    """A worker that declares `worktree` in cleanup.json, ignores SIGTERM, and sleeps."""
    code = (
        "import json,signal,sys,time,pathlib;"
        "d=pathlib.Path(sys.argv[1]);"
        "(d/'cleanup.json').write_text(json.dumps({'paths':[sys.argv[2]]}));"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(120)"
    )

    def factory(job_dir):
        return [sys.executable, "-c", code, str(job_dir), str(worktree)]

    return factory


async def test_cancel_hard_kills_a_worker_that_ignores_sigterm_and_removes_its_worktree(
    tmp_path, monkeypatch
):
    worktree = Path(tempfile.mkdtemp(prefix=WORKTREE_PREFIX, dir=tempfile.gettempdir()))
    (worktree / "file").write_text("x")
    monkeypatch.setattr(JobStore, "terminate_grace_seconds", 1.0)
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _stubborn_worker_cmd(worktree))
    job_id, _ = store.start(
        lifecycle.worker_cmd, str(tmp_path), kind="delegate", extra={"backend": "codex"}
    )
    deadline = time.monotonic() + 5
    while not (store._job_dir(str(tmp_path), job_id) / "cleanup.json").exists():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    t0 = time.monotonic()
    row = await asyncio.to_thread(store.cancel, str(tmp_path), job_id)
    assert row is not None and row["status"] == "cancelled"
    assert 0.9 <= time.monotonic() - t0 < 5, "graceful wait, then the kill"
    assert row["cleanup_warnings"] == [] and not worktree.exists()
    pid = json.loads((store._job_dir(str(tmp_path), job_id) / "meta.json").read_text())["pid"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        alive = (
            subprocess.run(["kill", "-0", str(pid)], capture_output=True, check=False).returncode
            == 0
        )
        if not alive:
            break
        await asyncio.sleep(0.05)
    assert not alive


async def test_cancel_reports_a_worktree_it_may_not_remove(tmp_path, monkeypatch):
    outside = tmp_path / "not-a-worktree"
    outside.mkdir()
    monkeypatch.setattr(JobStore, "terminate_grace_seconds", 0.2)
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _stubborn_worker_cmd(outside))
    job_id, _ = store.start(
        lifecycle.worker_cmd, str(tmp_path), kind="delegate", extra={"backend": "codex"}
    )
    deadline = time.monotonic() + 5
    while not (store._job_dir(str(tmp_path), job_id) / "cleanup.json").exists():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    row = await asyncio.to_thread(store.cancel, str(tmp_path), job_id)
    assert row["status"] == "cancelled" and outside.exists()
    assert row["cleanup_warnings"] and str(outside) in row["cleanup_warnings"][0]


_OTHER_PROCESS = """
import json, sys, time
from amicus import config
from amicus.jobs import lifecycle
settings = config.settings({"AMICUS_STATE_DIR": sys.argv[1]})
store = lifecycle.job_store(settings)
cwd, job_id = sys.argv[2], sys.argv[3]
seen = []
deadline = time.monotonic() + 20
while True:
    rec = store.status(cwd, job_id)
    seen.append(None if rec is None else rec["status"])
    if rec is None or rec["status"] != "running" or time.monotonic() > deadline:
        break
    time.sleep(0.05)
rec, payload = store.result_payload(cwd, job_id)
out = {"seen": seen, "final": rec and rec["status"], "ok": payload and payload.get("ok")}
print(json.dumps(out))
"""


async def test_a_job_survives_the_server_that_started_it(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "1.5")
    settings = _settings(tmp_path)
    store = lifecycle.job_store(settings)
    from amicus.request import RunSpec

    spec = RunSpec(
        backend="codex",
        kind="consult",
        tool="amicus_consult_async",
        cwd=str(tmp_path),
        workspace_source="param",
        roots_source="none",
        host_name="H",
        timeout_seconds=60,
        question="why?",
    )
    job_id, _ = store.start(
        lifecycle.worker_cmd,
        str(tmp_path),
        kind="consult",
        extra={"result_format": 1, "backend": "codex", "tool": "amicus_consult_async"},
        write_spec=spec.public(),
        stdin_text=spec.inputs_json(),
    )
    # "Restart": a different Python process (a fresh _PROCESS_OWNER) reads the same store.
    other = subprocess.run(
        [sys.executable, "-c", _OTHER_PROCESS, str(tmp_path / "state"), str(tmp_path), job_id],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    out = json.loads(other.stdout.strip().splitlines()[-1])
    assert out["seen"][0] == "running", out  # the worker's lock proves liveness to a stranger
    assert out["final"] == "done" and out["ok"] is True, out
    assert store.status(str(tmp_path), job_id)["status"] == "done"
