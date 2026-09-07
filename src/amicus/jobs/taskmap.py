"""A persisted task_id -> job_id map, written atomically under a cross-process flock
(ADR 0004). ``record()`` is a read-modify-write over the whole file: two concurrent
tasked runs (same or different amicus processes sharing AMICUS_STATE_DIR) racing this
without a lock interleave and the later writer silently drops the earlier entry, which
defeats the map's entire purpose (a client that loses its task id must still recover the
job via amicus_job_list(task_id=...)). The lock mirrors pontonier's own approach to
cross-process coordination (an advisory ``flock`` on a lockfile, bounded by a timeout so
a contended lock degrades to a raised OSError rather than hanging a worker) for
consistency with ``lifecycle.py``'s idempotency locking, rather than an in-process
``threading.Lock`` — which would not protect two separate server processes sharing one
state dir, the exact scenario the tasks extension is built for."""

from __future__ import annotations

import contextlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

# Bound on acquiring the map's cross-process lock: a sibling holding it degrades this
# record() call to a raised OSError (caught and logged by lifecycle.run_sync's narrow
# OSError handler) rather than blocking a worker indefinitely.
LOCK_ACQUIRE_TIMEOUT_S = 2.0
_LOCK_POLL_SECONDS = 0.01


def _acquire_flock(fd: int, timeout: float) -> None:
    """Take ``LOCK_EX`` on ``fd``, polling ``LOCK_NB`` until ``timeout`` elapses. Raises
    OSError on timeout (never blocks indefinitely) so a stuck sibling degrades a single
    record() call instead of hanging the caller."""
    try:
        import fcntl  # noqa: PLC0415 - POSIX only; server startup guard rejects non-POSIX
    except ImportError:  # pragma: no cover - non-POSIX
        return
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError(f"timeout must be finite and non-negative, got {timeout!r}")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError("timed out acquiring the task map lock") from None
            time.sleep(min(_LOCK_POLL_SECONDS, remaining))


def _release_flock(fd: int) -> None:
    try:
        import fcntl  # noqa: PLC0415 - mirrors the import guard in _acquire_flock
    except ImportError:  # pragma: no cover - non-POSIX
        return
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


class TaskJobMap:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def entries(self) -> dict[str, str]:
        return self._read()

    def job_for(self, task_id: str) -> str | None:
        return self._read().get(task_id)

    def task_for(self, job_id: str) -> str | None:
        for task_id, job in self._read().items():
            if job == job_id:
                return task_id
        return None

    def record(self, task_id: str, job_id: str) -> None:
        """Read-modify-write the whole map under an exclusive cross-process lock, so
        concurrent tasked runs never clobber each other's entries. Raises OSError (never
        blocks indefinitely) if the lock cannot be taken within LOCK_ACQUIRE_TIMEOUT_S."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_name(self._path.name + ".lock")
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            _acquire_flock(lock_fd, LOCK_ACQUIRE_TIMEOUT_S)
            try:
                data = self._read()
                data[task_id] = job_id
                fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
                tmp = Path(tmp_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, sort_keys=True)
                    tmp.replace(self._path)
                finally:
                    if tmp.exists():
                        tmp.unlink()
            finally:
                _release_flock(lock_fd)
        finally:
            os.close(lock_fd)
