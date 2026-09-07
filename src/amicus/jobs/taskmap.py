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
state dir, the exact scenario the tasks extension is built for.

The map is bounded, not job-store-aware: it deliberately does NOT check whether a job_id
still exists on disk to decide staleness. Job records live under the job store's root
(``settings.state_dir``, the same directory this file's parent is), keyed by a
workspace-hash directory a caller-supplied ``cwd`` produces — but a map entry only ever
records a ``job_id``, never the ``cwd`` that produced it, so "does this job still exist"
cannot be answered without either changing the persisted shape (out of scope for a prune
fix) or re-deriving cwd hashes by brute force. Even a filesystem probe scoped to "does any
workspace directory under this root contain a directory named ``job_id``" is unsound as a
staleness signal on its own: nothing here guarantees the job store and the task map share
a root in every deployment, and a probe that treats "no such directory" as "stale" would
prune an entry the instant it's written in any environment where the two roots diverge —
turning a bookkeeping decoupling elsewhere in the codebase into a silent loss of the
recovery guarantee this map exists to provide. Given ``amicus.jobs`` is free to import
pontonier's job store (import-linter only forbids ``amicus.server``/``amicus.tools`` from
this package) but pontonier's own store API requires a ``cwd`` for every existence check,
there is no coupling that is both correct and decoupled from the persisted shape. So this
prunes by a bounded, oldest-first eviction instead: entries are written in insertion order
(the JSON object key order, no longer alphabetically sorted) and, once the map holds more
than MAX_ENTRIES, the oldest are dropped first. This can, in principle, evict a mapping
for a job that is still running if a single amicus process ever has more than MAX_ENTRIES
tasked jobs in flight at once across every workspace sharing this state dir — the bound
below is chosen to make that practically impossible: it comfortably exceeds
AMICUS_JOB_MAX_COUNT's default (50, itself a per-workspace cap) many times over, and this
suite's own largest concurrency scenario (200 simultaneous writers, all of which must
survive)."""

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

# Bound on the number of task_id -> job_id entries the map retains. Once record() would
# push the map past this, the oldest entries (by insertion order) are dropped first, under
# the same lock as the write, so the file — and the read-modify-write cost and lock hold
# time around it — can never grow without bound. See the module docstring for why this is
# a size bound rather than a job-liveness check, and how the value below was chosen.
MAX_ENTRIES = 1000


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
        blocks indefinitely) if the lock cannot be taken within LOCK_ACQUIRE_TIMEOUT_S.

        Prunes under the SAME lock, before writing: once the map would hold more than
        MAX_ENTRIES, the oldest entries (by insertion order, i.e. JSON object key order —
        the file is no longer written with sort_keys, since alphabetical order would
        destroy the recency signal eviction depends on) are dropped first. A second lock
        or a background sweep would let pruning race a concurrent record(); doing it here
        makes that impossible."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_name(self._path.name + ".lock")
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            _acquire_flock(lock_fd, LOCK_ACQUIRE_TIMEOUT_S)
            try:
                data = self._read()
                data[task_id] = job_id
                if len(data) > MAX_ENTRIES:
                    for stale_task_id in list(data)[: len(data) - MAX_ENTRIES]:
                        del data[stale_task_id]
                fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
                tmp = Path(tmp_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(data, fh)
                    tmp.replace(self._path)
                finally:
                    if tmp.exists():
                        tmp.unlink()
            finally:
                _release_flock(lock_fd)
        finally:
            os.close(lock_fd)
