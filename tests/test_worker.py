"""python -m amicus._worker: spec + stdin inputs → run_request → result.json; crash sink."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading

import pytest
from tests.support import fakeplugin

from amicus import _worker, obs
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


def test_worker_crash_keeps_exception_text_out_of_the_stored_result(tmp_path, monkeypatch):
    _use_fake_plugin(monkeypatch)
    marker = "PROMPTMARKER56"

    async def boom(spec, *a, **k):
        raise RuntimeError(f"backend rejected {spec.question}")

    monkeypatch.setattr(_worker, "run_request", boom)
    jd = _job(tmp_path)
    assert _worker.main([str(jd)], stdin_text=json.dumps({"question": marker})) == 0
    stored = (jd / "result.json").read_text()
    out = json.loads(stored)
    assert (
        out["ok"] is False
        and out["error"]["code"] == "internal_error"
        and out["error"]["message"] == "background worker crashed: RuntimeError"
    )
    assert marker not in stored and out["meta"]["backend"] == "fake"


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
    assert out["error"]["message"] == "background worker crashed: ValueError"
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
    assert out["error"]["message"] == "background worker crashed: ValueError"
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


# --- #128: the worker process installs the log policy ----------------------------------
#
# This process's stdout and stderr are both `<job_dir>/stderr.log` (`JobStore.start`), so a
# record that reaches `logging.lastResort` is written to a file the job keeps. `lastResort`
# renders an exception's own text and its traceback; the policy handlers `obs.configure`
# installs render only its type and frame locations. Before this, the worker never called
# `obs.configure`, so the SDK runtime's `logger.error("stdout capture failed: %s", exc,
# exc_info=True)` (`sdk/core/runtime.py:317`) landed there verbatim.
#
# Assembled from fragments so the literal never appears on a source line: a frame's source
# line is not rendered, and this keeps the assertion from passing for that reason.
_LEAK_MARKER = "PROMPT" + "MARKER" + "128"

_POLICY_HANDLERS = (obs.PolicyStreamHandler, obs.PolicyFileHandler)

# What `amicus.sdk.core.runtime` logs on a capture failure, verbatim from runtime.py:317.
_WORKER_LEAK_SCRIPT = f"""
import logging
{{preamble}}
logger = logging.getLogger("amicus.sdk.core.runtime")
try:
    raise ValueError({_LEAK_MARKER!r})
except ValueError as exc:
    logger.error("stdout capture failed: %s", exc, exc_info=True)
"""


def _run_redirected(tmp_path, name, preamble):
    """Run a script with stdout AND stderr on one file, the way `JobStore.start` puts both
    on `stderr.log`, and return what was written."""
    script = tmp_path / f"{name}.py"
    script.write_text(_WORKER_LEAK_SCRIPT.format(preamble=preamble), encoding="utf-8")
    log = tmp_path / f"{name}.log"
    with log.open("w") as sink:
        subprocess.run(
            [sys.executable, str(script)], stdout=sink, stderr=sink, cwd=tmp_path, check=False
        )
    return log.read_text(encoding="utf-8")


def test_the_worker_entry_keeps_exception_text_out_of_the_job_log(tmp_path):
    """The real entry runs first, exactly as the worker process reaches it."""
    output = _run_redirected(tmp_path, "worker", "from amicus import _worker\n_worker.main([])")
    assert _LEAK_MARKER not in output, "the exception's own text reached the job's log"
    assert "amicus.sdk.core.runtime" in output, "the record itself never arrived"
    assert "Traceback (most recent call last)" not in output


def test_without_the_worker_entry_the_same_record_dumps_it(tmp_path):
    """Mutation control: the identical record, from a process that never configured — the
    worker's own state before #128. If this does not leak, the assertion above proves
    nothing about the policy."""
    output = _run_redirected(tmp_path, "control", "")
    assert _LEAK_MARKER in output, "control did not reproduce the leak; the test proves nothing"
    assert "Traceback (most recent call last)" in output


def test_the_policy_is_installed_before_the_first_early_return(monkeypatch):
    """`main([])` returns 2 without reading a job dir, and the handlers are already on. The
    worker process always makes the first `obs.configure` call, so the flag starts clear."""
    monkeypatch.setattr(obs, "_configured", False)
    amicus_log = logging.getLogger(obs.ROOT_LOGGER_NAME)
    monkeypatch.setattr(amicus_log, "handlers", [])
    monkeypatch.setattr(amicus_log, "propagate", True)
    assert not [h for h in amicus_log.handlers if isinstance(h, _POLICY_HANDLERS)]

    assert _worker.main([]) == 2

    assert [h for h in amicus_log.handlers if isinstance(h, _POLICY_HANDLERS)]
    assert amicus_log.propagate is False
