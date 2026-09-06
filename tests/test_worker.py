"""python -m amicus._worker: spec + stdin inputs → run_request → result.json; crash sink."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading

import pytest
from tests.support import fakeplugin

from amicus import _worker
from amicus.request import RunSpec

_PUBLIC = dict(
    backend="fake",
    kind="consult",
    tool="amicus_consult",
    cwd="/repo",
    workspace_source="param",
    roots_source="client",
    host_name="H",
    timeout_seconds=10,
    options={},
)


def _job(tmp_path, **over):
    jd = tmp_path / "job"
    jd.mkdir()
    (jd / "spec.json").write_text(json.dumps({**_PUBLIC, **over}))
    return jd


def _use_fake_plugin(monkeypatch):
    monkeypatch.setattr(_worker, "load_plugin", fakeplugin.make_plugin)


def test_worker_runs_the_loop_with_the_streamed_inputs(tmp_path, monkeypatch):
    _use_fake_plugin(monkeypatch)
    seen = {}

    async def fake_run(spec, plugin, *, on_event=None, on_worktree_parent=None):
        seen["spec"] = spec
        assert callable(on_event) and callable(on_worktree_parent)
        return {"ok": True, "tool": "amicus_consult", "summary": spec.question}

    monkeypatch.setattr(_worker, "run_request", fake_run)
    jd = _job(tmp_path)
    assert _worker.main([str(jd)], stdin_text=json.dumps({"question": "why?"})) == 0
    assert json.loads((jd / "result.json").read_text())["summary"] == "why?"
    assert isinstance(seen["spec"], RunSpec) and seen["spec"].question == "why?"
    assert "question" not in json.loads((jd / "spec.json").read_text())


def test_worker_crash_writes_a_redacted_internal_error(tmp_path, monkeypatch):
    _use_fake_plugin(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("kaboom token=sk-" + "c" * 32)

    monkeypatch.setattr(_worker, "run_request", boom)
    jd = _job(tmp_path)
    assert _worker.main([str(jd)], stdin_text="{}") == 0
    out = json.loads((jd / "result.json").read_text())
    assert (
        out["ok"] is False
        and out["error"]["code"] == "internal_error"
        and "kaboom" in out["error"]["message"]
    )
    assert "sk-" + "c" * 32 not in json.dumps(out) and out["meta"]["backend"] == "fake"


def test_worker_reports_an_unavailable_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(_worker, "load_plugin", lambda backend_id: None)
    jd = _job(tmp_path, backend="nope")
    assert _worker.main([str(jd)], stdin_text="{}") == 0
    out = json.loads((jd / "result.json").read_text())
    assert out["error"]["code"] == "backend_unavailable"


def _spy_load_plugin(monkeypatch, calls: list[str]):
    def spy(backend_id):
        calls.append(backend_id)
        return fakeplugin.make_plugin(backend_id)

    monkeypatch.setattr(_worker, "load_plugin", spy)


def test_worker_refuses_undecodable_stdin(tmp_path, monkeypatch):
    plugin_calls: list[str] = []
    run_calls: list[str] = []
    _spy_load_plugin(monkeypatch, plugin_calls)

    async def fake_run(spec, plugin, *, on_event=None, on_worktree_parent=None):
        run_calls.append("ran")
        return {"ok": True, "tool": "amicus_consult", "summary": "s"}

    monkeypatch.setattr(_worker, "run_request", fake_run)
    jd = _job(tmp_path)
    assert _worker.main([str(jd)], stdin_text="not json") == 0
    out = json.loads((jd / "result.json").read_text())
    assert out["ok"] is False and out["error"]["code"] == "internal_error"
    assert "stdin" in out["error"]["message"]
    assert "not json" not in out["error"]["message"]
    assert not plugin_calls and not run_calls


def test_worker_refuses_a_non_object_stdin_payload(tmp_path, monkeypatch):
    plugin_calls: list[str] = []
    run_calls: list[str] = []
    _spy_load_plugin(monkeypatch, plugin_calls)

    async def fake_run(spec, plugin, *, on_event=None, on_worktree_parent=None):
        run_calls.append("ran")
        return {"ok": True, "tool": "amicus_consult", "summary": "s"}

    monkeypatch.setattr(_worker, "run_request", fake_run)
    jd = _job(tmp_path)
    assert _worker.main([str(jd)], stdin_text="[]") == 0
    out = json.loads((jd / "result.json").read_text())
    assert out["ok"] is False and out["error"]["code"] == "internal_error"
    assert "stdin" in out["error"]["message"]
    assert not plugin_calls and not run_calls


def test_worker_no_args_and_missing_spec(tmp_path):
    assert _worker.main([]) == 2
    empty = tmp_path / "nospec"
    empty.mkdir()
    assert _worker.main([str(empty)], stdin_text="{}") == 2


def test_worker_records_activity_and_cleanup_manifest(tmp_path, monkeypatch):
    _use_fake_plugin(monkeypatch)

    async def fake_run(spec, plugin, *, on_event=None, on_worktree_parent=None):
        on_worktree_parent("/tmp/amicus-wt-abc")
        on_event('{"type":"x"}')
        on_event("not json")
        return {"ok": True, "tool": "amicus_consult", "summary": "s"}

    monkeypatch.setattr(_worker, "run_request", fake_run)
    jd = _job(tmp_path)
    _worker.main([str(jd)], stdin_text="{}")
    assert json.loads((jd / "cleanup.json").read_text()) == {"paths": ["/tmp/amicus-wt-abc"]}
    assert json.loads((jd / "activity.json").read_text())["events_seen"] == 1


@pytest.mark.skipif(not hasattr(signal, "SIGTERM"), reason="POSIX only")
def test_worker_sigterm_cancels_cleanly_and_leaves_no_result(tmp_path, monkeypatch):
    _use_fake_plugin(monkeypatch)
    state = {"cleaned": False}

    async def fake_run(spec, plugin, *, on_event=None, on_worktree_parent=None):
        try:
            await asyncio.sleep(10)
        finally:
            state["cleaned"] = True

    monkeypatch.setattr(_worker, "run_request", fake_run)
    jd = _job(tmp_path)
    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    assert _worker.main([str(jd)], stdin_text="{}") == 0
    assert state["cleaned"] and not (jd / "result.json").exists()


def test_worker_subprocess_end_to_end_with_the_fake_codex(tmp_path, fake_codex):
    """The real entrypoint, the real codex plugin, a stand-in codex binary: spec.json +
    stdin → result.json, with the prompt never touching the job dir."""
    jd = tmp_path / "job"
    jd.mkdir()
    spec = {
        **_PUBLIC,
        "backend": "codex",
        "cwd": str(tmp_path),
        "options": {"isolation": "inherit"},
    }
    (jd / "spec.json").write_text(json.dumps(spec))
    env = {
        **os.environ,
        "AMICUS_CODEX_BIN": str(fake_codex),
        "FAKE_CODEX_STDIN_FILE": str(tmp_path / "prompt.txt"),
    }
    for key in list(env):
        if key.startswith("CODEX_IN_CLAUDE_"):
            del env[key]
    proc = subprocess.run(
        [sys.executable, "-m", "amicus._worker", str(jd)],
        input=json.dumps({"question": "SECRET-QUESTION-42"}),
        cwd=str(jd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads((jd / "result.json").read_text())
    assert (
        out["ok"] is True
        and out["summary"] == "Looks fine"
        and out["meta"]["usage"]["cached_input_tokens"] == 80
    )
    assert "SECRET-QUESTION-42" in (tmp_path / "prompt.txt").read_text()
    assert "SECRET-QUESTION-42" not in (jd / "spec.json").read_text()
