"""Detached background worker: `python -m amicus._worker <job_dir>`.

Reads `<job_dir>/spec.json` (the public RunSpec half) and the input half from stdin,
re-resolves the backend plugin by id, runs `orchestration.run.run_request`, and writes
`<job_dir>/result.json` atomically. Import-light: never the FastMCP app. A crash still
leaves a readable envelope; a SIGTERM (cancel/timeout) cancels cleanly and leaves none."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pontonier.core import redaction
from pontonier.core.jobs import ActivityRecorder

from amicus.errors import error_envelope
from amicus.orchestration.run import run_request
from amicus.registry import BackendRegistry
from amicus.request import RunSpec, meta_for
from amicus.schemas.envelope import Meta

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from amicus.plugin import BackendPlugin

_held_locks: list[int] = []


def _hold_job_lock(job_dir: Path) -> None:
    """Hold `<job_dir>/worker.lock` for this process's life so the JobStore can tell this
    worker from a reused PID after a server restart."""
    try:
        import fcntl  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return
    with contextlib.suppress(OSError):
        fd = os.open(str(job_dir / "worker.lock"), os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # pragma: no cover
            os.close(fd)
            return
        _held_locks.append(fd)


def load_plugin(backend_id: str) -> BackendPlugin | None:
    return BackendRegistry.load((backend_id,)).get(backend_id)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


def _write_cleanup_manifest(job_dir: Path, parent: str) -> None:
    _atomic_write(job_dir / "cleanup.json", {"paths": [parent]})


def _activity_observer(job_dir: Path) -> tuple[Callable[[str], None], ActivityRecorder]:
    recorder = ActivityRecorder(job_dir)

    def _observe(line: str) -> None:
        text = line.strip()
        if not text or text[0] != "{":
            return
        try:
            event = json.loads(text)
        except ValueError:
            return
        if isinstance(event, dict):
            recorder.record(time.time())

    return _observe, recorder


async def _run(job_dir: Path, spec: RunSpec, plugin: BackendPlugin) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None
    with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    on_event, recorder = _activity_observer(job_dir)
    try:
        return await run_request(
            spec,
            plugin,
            on_event=on_event,
            on_worktree_parent=lambda parent: _write_cleanup_manifest(job_dir, parent),
        )
    finally:
        recorder.flush()


def _parse_stdin_inputs(raw_inputs: str) -> dict[str, Any]:
    """Undecodable or non-object stdin must fail the job rather than silently degrade to
    an empty prompt (which would spend a real backend call on nothing); the message never
    echoes the stdin text itself."""
    if not raw_inputs.strip():
        return {}
    try:
        inputs = json.loads(raw_inputs)
    except ValueError as exc:
        raise ValueError("worker stdin was not valid JSON") from exc
    if not isinstance(inputs, dict):
        raise ValueError("worker stdin was not a JSON object")
    return inputs


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return 2
    job_dir = Path(args[0])
    spec_path = job_dir / "spec.json"
    if not spec_path.exists():
        return 2
    _hold_job_lock(job_dir)
    spec: RunSpec | None = None
    plugin: BackendPlugin | None = None
    try:
        public = json.loads(spec_path.read_text())
        raw_inputs = stdin_text if stdin_text is not None else sys.stdin.read()
        inputs = _parse_stdin_inputs(raw_inputs)
        spec = RunSpec.from_parts(public, inputs)
        plugin = load_plugin(spec.backend)
        if plugin is None:
            _atomic_write(
                job_dir / "result.json",
                error_envelope(
                    "backend_unavailable",
                    f"backend {spec.backend!r} could not be loaded in the worker",
                    meta_for(spec),
                    backend=spec.backend,
                ),
            )
            return 0
        payload = asyncio.run(_run(job_dir, spec, plugin))
    except asyncio.CancelledError:
        return 0  # graceful termination: the JobStore owns the terminal status
    except Exception as exc:
        payload = error_envelope(
            "internal_error",
            f"background worker crashed: {redaction.exc_summary(exc)}"[:300],
            meta_for(spec) if spec is not None else Meta(),
            plugin=plugin,
        )
    _atomic_write(job_dir / "result.json", payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
