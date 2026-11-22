"""Generic, disk-backed background-job lifecycle.

This module takes all configuration (state root, TTL, deadline, count cap) as
parameters and knows nothing about tools, backends or envelopes, so nothing above it
in ``amicus.jobs`` has to be reached from here.

A job is an arbitrary command spawned detached (its own session leader). The
command is expected to write a final, already-normalized result envelope to
``result.json`` *in its own job directory* (the command is run with
``cwd=<job_dir>``). This store therefore treats ``result.json`` as opaque: a job is
``done`` when the process is gone and ``result.json`` parses to a JSON object;
otherwise the process exiting without one means ``failed``. Cancel/deadline reaps
mark ``cancelled``/``timeout``.

The one structural detail the store reads out of an otherwise-opaque envelope is a
top-level boolean ``ok`` — a widespread success/failure discriminator convention.
At finalization it stamps that flag (or ``None`` when absent/non-boolean) into the
record as ``result_ok``, so status/list can flag a stored failure without every
caller re-parsing the envelope. It is the producer-declared outcome at write time,
never re-derived, so a record finalized before this field existed reports ``None``.

State lives on disk keyed by workspace, so status/result/cancel survive MCP server
restarts. There is no daemon: single-job calls refresh and TTL-clean the requested
record, list calls clean the whole workspace, and the count cap is enforced when
jobs start.

Restart recovery: after a restart a prior worker is no longer this process's child,
so a persisted PID alone cannot be trusted — a PID reused by an unrelated process
must never be mistaken for the worker or signaled. Each worker therefore holds an
exclusive advisory lock on ``<job_dir>/worker.lock`` for its whole life; the store
treats that lock as the authority for liveness (a reused PID cannot hold this job's
lock). A PID is trusted without the lock only for jobs this instance itself started
(its own children); an unowned record whose lock is absent/indeterminate is treated
as not-running rather than signaled, so cancel/timeout never touch an unrelated
process. The lock needs a local filesystem to be reliable and uses POSIX ``fcntl``;
platforms without it degrade to the owned-child check (and never signal unowned PIDs).

Termination claims: a process about to stop a worker with the store's locks released
first becomes that job's claimant, under ``_LOCK`` and the record lock. It writes
``meta["terminating"] = {"reason": "timeout" | "cancelled", "epoch": ...}`` unless a
well-formed claim is already there (the first claim wins and is never replaced), and
takes an exclusive ``flock`` on ``<job_dir>/terminate.lock``, the claimant lock, which
it holds through signalling and finalization and releases once the record is stamped or
it gives up on an error; a claimant that dies releases it with its descriptors. Every
reader, in any process, reads a job whose claimant lock is held as ``running``, claim
written or not: never ``failed``, never evicted, never signalled. A claim whose lock is
free belongs to a claimant that is gone, so the reader finalizes the job by its claim once
its worker is positively stopped (our own child reaped, or an unowned worker's PID dead),
and becomes its claimant while the worker is safe to signal. A worker that is neither (an
unowned live PID holding no ``worker.lock``) leaves the job ``running``, untouched, until
its deadline plus the terminate grace, after which it reads as an unclaimed record would,
unstamped. The claimant lock is only ever tried, never waited for, while ``_LOCK`` or the
record lock is held, so it adds no rule to the lock order.
Writing the claim is best effort; on failure the claimant proceeds with the lock alone.
A ``cancel`` that meets a job whose claimant lock another holder has signals nothing while
it is held and waits at most the terminate grace plus one second; if that claimant then
goes away leaving the worker running, the cancel takes over as claimant and stops it, which
can take one further terminate grace.
The guarantee holds only among servers of the release that introduced it or later: an
older server sharing the root ignores the claim and its lock and can still read a job
being terminated as ``failed``.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypeVar
from uuid import uuid4

from amicus.jobs import idempotency

logger = logging.getLogger(__name__)

# Reserved subdirectory name (of a workspace dir) for the idempotency index; it is not
# a job and must be excluded from every job-directory iteration.
_IDEM_DIRNAME = ".idem"

# Reserved file (in a workspace dir) that every server process sharing the state root
# flocks around each read, write and delete of that workspace's records (#237). A file,
# so ``_job_dirs`` never takes it for a job; never deleted, so every process locks the
# same inode.
_RECORD_LOCK_NAME = ".records.lock"

# Per-job claimant lock (in a job dir): held by the one process terminating that job with
# the store's locks released, for as long as it does (see the module docstring).
_TERMINATE_LOCK_NAME = "terminate.lock"
_CLAIM_REASONS = ("timeout", "cancelled")
# Stands in for the claimant lock's descriptor when a claimant could not take the lock
# for a reason other than contention; ``_release_claim`` ignores it.
_NO_CLAIM_FD = -1

_T = TypeVar("_T")

_TERMINAL = frozenset({"done", "failed", "cancelled", "timeout"})
_LOCK = threading.RLock()

# This process's hold on each workspace's record lock: the open fd and how many nested
# sections hold it. Touched only under ``_LOCK``, which serializes this process's threads,
# so a nested section reuses the fd: a second open file description would block on the
# flock this process already holds.
_RECORD_LOCKS: dict[Path, list[int]] = {}

# Job dirs whose overrun worker a thread of this process is terminating with the locks
# released (#531). Touched only under ``_LOCK``. Every other thread reads such a job as
# ``running`` until the terminating thread re-takes the locks and finalizes it, so it is
# never reported ``failed``, reaped, evicted or terminated a second time meanwhile, and a
# ``cancel`` that stops it in that window finalizes it as the overrun it is.
_TERMINATING: set[Path] = set()

# Per-thread state of the outermost locked section running on this thread: the markers
# it has published in ``_TERMINATING`` (added at the same point, under ``_LOCK``), or
# ``None`` outside one. It is also the nesting flag: a nested section sees it set and
# lets ``_Overrun`` propagate to the outermost, the only frame whose exit really releases
# ``_LOCK`` and the record flock, and the outermost clears whatever it published.
_SECTION = threading.local()

# Job dirs whose worker this process terminated as an overrun and whose record is not
# yet stamped (#531). Touched only under ``_LOCK``. Whichever read, on any thread, first
# reads both meta.json and result.json finalizes such a job the overrun way (``done`` or
# ``timeout``), never ``failed``; a read error stamps nothing and leaves it pending. An
# entry goes once its record is stamped or confirmed absent.
_OVERRAN: set[Path] = set()

# The only job-id shape this store ever mints (``uuid4().hex``). A job id is used
# verbatim as a path component under the workspace directory, so its shape is
# confined at the join: anything else (separators, traversal, empty) must never
# reach the filesystem. Consumers validating ids at their own boundary should pin
# the same shape.
_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")


class _Overrun(Exception):
    """Raised by ``_status_of`` under the locks for a running job past its deadline,
    after marking it in ``_TERMINATING``. The outermost locked section catches it,
    terminates the worker with the locks released, re-takes them to finalize the job
    from a fresh read, and runs its body again (#531). The job dir's parent is the
    workspace dir whose record lock that finalization takes. ``claim_fd`` holds the
    job's claimant lock, which the section releases once it is done with the job, or is
    ``_NO_CLAIM_FD`` when the claimant could not take that lock (``_release_claim``
    ignores it)."""

    def __init__(self, jd: Path, meta: dict, claim_fd: int | None) -> None:
        super().__init__(jd.name)
        self.jd = jd
        self.meta = meta
        self.claim_fd = claim_fd


class ResultUnreadable(Exception):
    """A job's ``result.json`` exists but could not be read (``EACCES``, ``EIO``,
    ``EMFILE``, ...), so whether the job is done is not knowable right now (#280).

    Distinct from an absent result, which ``_read_envelope`` reports as ``None`` and
    which means the job produced none. Raised by every read that would otherwise have
    to invent a terminal state: nothing is stamped on the record, nothing is deleted or
    finalized, and the same read can succeed once the file is readable again, which is
    why a caller reports it as a temporary error naming a free re-read, never as
    ``failed`` (whose repair says to pay again). Carries ``errno`` only: the message of
    an ``OSError`` can name a path, which never leaves the store.

    ``_read_meta`` raises the subclass ``MetaUnreadable`` for a ``meta.json`` that
    exists but cannot be read (#530): the record's state is just as unknowable, and the
    same guarantees hold.
    """

    def __init__(self, errno: int | None) -> None:
        super().__init__(f"result unreadable (errno {errno})")
        self.errno = errno


class MetaUnreadable(ResultUnreadable):
    """A job's ``meta.json`` exists but could not be read (#530). Unlike an unreadable
    result, which a read reaches only once the worker is stopped, this can meet a running
    worker. ``signalled`` is True only when ``cancel`` raised it after signalling the
    worker; otherwise nothing is known about the worker, and nothing was sent to it."""

    def __init__(self, errno: int | None, *, signalled: bool = False) -> None:
        super().__init__(errno)
        self.args = (f"job record unreadable (errno {errno})",)
        self.signalled = signalled


class DiscardOutcome(StrEnum):
    """What ``JobStore.discard`` did, so callers never have to re-derive it from a
    post-hoc ``status`` read (a partial deletion can make the record unreadable
    while parts of it survive on disk — indistinguishable from a lost race)."""

    REMOVED = "removed"  # this call removed the record and verified it absent
    MISSING = "missing"  # no record: already discarded, expired, or evicted
    STATE_CHANGED = "state_changed"  # not (verifiably) in the named state; never deleted
    DELETE_FAILED = "delete_failed"  # removal failed or could not be verified


class JobCapReached(Exception):
    """A new start was refused because the workspace already holds ``max_count``
    records the cap may not evict: running jobs, and ``done`` results amicus has not
    yet returned once (#244). Raised before anything is spawned, so nothing was spent."""

    def __init__(self, max_count: int, held: int) -> None:
        super().__init__(f"{held} job records held against a per-workspace cap of {max_count}")
        self.max_count = max_count
        self.held = held


# Per-process identity stamped onto every job this process starts and compared on
# read to decide ownership. Generated ONCE at import, so it is stable across the many
# short-lived JobStore instances the server builds (one per tool call) and changes
# only across a real restart (a new process re-imports this module). Persisted into
# meta.json; a record whose owner differs was started by some other/earlier process.
_PROCESS_OWNER = uuid4().hex

# Default poll/backoff interval (ms) a job advertises to clients. The single source
# for this value; `jobs.polling` reads it to build the hint a tool result carries.
DEFAULT_POLL_AFTER_MS = 1000
# Upper bound for the growing poll backoff (ms): "wait about as long as it has already
# run", up to thirty seconds. A four-minute job is polled about thirteen times instead of
# about twenty-eight, and a finished job is noticed at most thirty seconds late. A
# sixty-second cap would save three of those polls and double that delay; a status read is
# free, while the host waiting on it is not. It was 10000 while the store was a copy of
# briandconnelly/pontonier's, and amicus re-capped the hint on its way out (#95).
MAX_POLL_AFTER_MS = 30_000
# Min seconds between activity.json disk writes while a job runs; the first event
# and the final flush always write. Keeps the hot path off the disk on every line.
ACTIVITY_WRITE_THROTTLE_S = 0.5

CmdFactory = Callable[[Path], list[str]]


def _is_job_id(job_id: str) -> bool:
    return _JOB_ID_RE.fullmatch(job_id) is not None


def _usable_epoch(epoch: int | float) -> bool:
    """True if ``epoch`` is finite AND in range for datetime.fromtimestamp().

    json.loads accepts NaN/Infinity, and a finite epoch can still be out of range
    (1e308 raises OverflowError/OSError/ValueError depending on the platform). The
    cheap finiteness check rejects the common corrupt case; the conversion probe
    catches the rare out-of-range finite value so a corrupt activity.json can never
    crash the job-status API."""
    if not math.isfinite(epoch):
        return False
    try:
        datetime.fromtimestamp(epoch, UTC)
    except (OverflowError, OSError, ValueError):
        return False
    return True


def poll_backoff_ms(
    elapsed_ms: int,
    *,
    base: int = DEFAULT_POLL_AFTER_MS,
    cap: int = MAX_POLL_AFTER_MS,
) -> int:
    """Suggested delay (ms) before the next job-status poll for a running job.

    Grows with how long the job has already run — roughly "wait about as long as it
    has already taken" — so a polling agent naturally backs off instead of tight-
    looping at the flat ``base``. Bounded to ``[base, cap]``; if a caller passes a
    ``cap`` below ``base`` (e.g. a configured base above the default cap), the base
    wins so the result is never below the configured floor."""
    return min(max(base, elapsed_ms), max(base, cap))


@dataclass
class ActivityRecorder:
    """Persists a job's agent-event activity as counters/timestamps ONLY.

    The worker calls ``record`` per observed event and ``flush`` at the end. Writes
    are throttled and atomic (temp + replace) so a concurrent JobStore reader sees
    either the old or new file, never a torn one. Raw events are never written."""

    job_dir: Path
    _count: int = 0
    _last_epoch: float = 0.0
    _last_write: float = 0.0

    def record(self, now_epoch: float) -> None:
        self._count += 1
        self._last_epoch = now_epoch
        if self._count == 1 or (now_epoch - self._last_write) >= ACTIVITY_WRITE_THROTTLE_S:
            self._write(now_epoch)

    def flush(self) -> None:
        if self._count:
            self._write(self._last_epoch or time.time())

    def _write(self, now_epoch: float) -> None:
        payload = {"events_seen": self._count, "last_event_epoch": self._last_epoch}
        tmp = self.job_dir / "activity.json.tmp"
        with contextlib.suppress(OSError):
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.job_dir / "activity.json")
            self._last_write = now_epoch


# os.kill and os.waitpid parse a pid as a C int, which is 32 bits wherever amicus runs;
# a larger int raises OverflowError rather than reaching the OS.
_PID_MAX = 2**31 - 1


def _meta_pid(meta: dict) -> int | None:
    """The record's worker pid, or None when ``meta.json`` holds anything else.

    ``meta.json`` is not validated on read, and only a positive int within the C int
    range names one process: ``-1`` makes ``waitpid`` wait on any child and ``kill``
    signal every process, a str or float raises ``TypeError``, and an int past the range
    raises ``OverflowError`` (#239). ``bool`` is excluded although it subclasses int.
    """
    pid = meta.get("pid")
    if type(pid) is not int or not 0 < pid <= _PID_MAX:
        return None
    return pid


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_running(pid: int | None) -> bool:
    """Whether the job process is still running.

    The job is detached but still our child until it exits, so we reap it with
    waitpid — otherwise it lingers as a zombie that kill(0) reports as alive
    forever. waitpid(WNOHANG) returns (pid, _) once it exits (reaping it), (0, 0)
    while it runs, and raises ChildProcessError when it is not our child (e.g.
    after a server restart), where we fall back to a kill(0) liveness probe.
    """
    if not pid:
        return False
    try:
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
        if reaped == 0:
            return True
    except ChildProcessError:
        pass  # not our child — use the liveness probe below
    except OSError:
        return False
    return _pid_alive(pid)


def _worker_lock_held(lock_path: Path) -> bool | None:
    """Whether a live worker still holds the per-job lock at ``lock_path``.

    ``True`` = held, so the worker is alive AND positively identified — a PID reused
    by an unrelated process after a server restart cannot be holding *this* job's
    lock. ``False`` = free (no live holder). ``None`` = indeterminate: the lock file
    does not exist yet (worker still starting, or a job from before this hardening)
    or ``fcntl`` is unavailable. Advisory locks need a local filesystem to be
    reliable; on a network filesystem the result may be ``None``/unreliable, which
    callers treat conservatively (no signaling of unverified PIDs)."""
    try:
        import fcntl  # noqa: PLC0415 - platform-guarded lazy import (POSIX only)
    except ImportError:  # pragma: no cover - non-POSIX
        return None
    try:
        fd = os.open(str(lock_path), os.O_RDONLY)
    except OSError:
        return None  # missing (worker not yet locked) or unreadable
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True  # someone holds it -> the worker is alive
        except OSError:
            return None
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)  # we grabbed it -> no holder; let it go
        return False
    finally:
        os.close(fd)


def _release_claim(fd: int | None) -> None:
    """Release a claimant lock ``_try_claim`` took: unlock it and close its descriptor.
    ``None`` and ``_NO_CLAIM_FD`` (no lock held) are no-ops."""
    if fd is None or fd == _NO_CLAIM_FD:
        return
    try:
        import fcntl  # noqa: PLC0415 - platform-guarded lazy import (POSIX only)

        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def _signal_proc(pid: int, sig: int) -> None:
    """Send ``sig`` to the job's process group, but only when ``pid`` is its own group
    leader — our workers are session leaders (``start_new_session=True``, so
    ``pgid == pid``). If the PID was reused by a non-leader process we fall back to
    signaling just that single PID rather than its unrelated group, narrowing the
    residual window where a reused PID could be signaled."""
    try:
        leader = hasattr(os, "killpg") and os.getpgid(pid) == pid
    except (ProcessLookupError, OSError):
        return  # already gone / not signalable
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if leader:
            os.killpg(pid, sig)
        else:  # pragma: no cover - reused non-leader PID / non-POSIX
            os.kill(pid, sig)


def _kill_pid_tree(pid: int | None) -> None:
    """SIGKILL the detached job via :func:`_signal_proc` (its process group when
    ``pid`` is the group leader — our workers are — else just that PID), then reap
    it if it was our child so it does not linger as a zombie."""
    if not pid:
        return
    _signal_proc(pid, signal.SIGKILL)
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, 0)


def _terminate_pid_tree(
    pid: int | None,
    grace_seconds: float,
    *,
    is_alive: Callable[[], bool] | None = None,
) -> None:
    """Stop the detached job's process group gracefully, then force-kill if it
    overstays.

    A plain SIGKILL (``_kill_pid_tree``) gives the worker no chance to run its own
    cleanup — for the propose tier that means a leaked temp worktree. So we send
    SIGTERM first and poll for up to ``grace_seconds`` (the worker cancels its run,
    tears down its worktree, and exits), then SIGKILL any survivor. Either way the
    process is reaped so it cannot linger as a zombie.

    ``is_alive`` is the liveness predicate used throughout — including before the
    initial SIGTERM and before the SIGKILL escalation. Callers pass a lock-aware
    check (``_job_running``) so that if the verified worker exits during the grace
    window and its PID is then reused, we do not signal the unrelated process. It
    defaults to the bare existence probe for direct/legacy callers."""
    if not pid:
        return
    alive = is_alive if is_alive is not None else (lambda: _is_running(pid))
    if not alive():  # already gone (or no longer the verified worker)
        return
    _signal_proc(pid, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        if not alive():  # exited gracefully (and was reaped)
            return
        time.sleep(0.02)
    if alive():  # still the verified worker after grace — force-kill it
        _kill_pid_tree(pid)


def _write_stdin(proc: subprocess.Popen, stdin_text: str) -> None:
    """Feed the worker's stdin from a daemon thread; a dead worker is not an error."""
    try:
        assert proc.stdin is not None
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass


@dataclass
class JobStore:
    """Disk-backed job lifecycle rooted at ``root``.

    ttl_seconds: how long a terminal record is kept after completion.
    max_seconds: a job's wall-clock cap (a status poll past it reaps the job).
    max_count: records per workspace. A new start first evicts the oldest records the
        cap may remove (terminal errors, results already returned once, records that
        predate delivery tracking) and is refused
        with :class:`JobCapReached` when that cannot make room (#244).
    """

    root: Path
    ttl_seconds: int
    max_seconds: int
    max_count: int

    poll_after_ms: int = DEFAULT_POLL_AFTER_MS

    # External paths a job declares it owns (in <job_dir>/cleanup.json) are removed
    # when the job is cancelled/timed out, but only when they resolve strictly
    # inside ``cleanup_root`` and (if set) carry ``cleanup_prefix`` — a guard so a
    # malformed manifest can never delete outside the throwaway-worktree temp area.
    cleanup_root: Path | None = None
    cleanup_prefix: str = ""
    terminate_grace_seconds: float = 5.0

    # ------------------------------------------------------------------ paths
    def _ws_dir(self, cwd: str) -> Path:
        canonical = os.path.realpath(cwd)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        base = os.path.basename(canonical.rstrip("/")) or "workspace"  # noqa: PTH119
        safe = "".join(c if (c.isalnum() or c in "._-") else "-" for c in base)[:40] or "ws"
        return self.root / f"{safe}-{digest}"

    def _job_dir(self, cwd: str, job_id: str) -> Path:
        # Backstop, not the caller-facing contract: _read_live_job screens
        # caller-supplied ids to not-found before reaching this join, and start()
        # mints its own, so a raise here means a store-internal programming error.
        if _JOB_ID_RE.fullmatch(job_id) is None:
            raise ValueError("job_id must be exactly 32 lowercase hexadecimal characters")
        return self._ws_dir(cwd) / job_id

    def _job_dirs(self, ws: Path) -> list[Path]:
        """Job subdirectories of a workspace, excluding reserved non-job dirs (the
        idempotency index). The single place every reap/count/list iteration goes
        through so the ``.idem`` dir is never mistaken for a job."""
        if not ws.is_dir():
            return []
        return [d for d in ws.iterdir() if d.is_dir() and d.name != _IDEM_DIRNAME]

    @contextlib.contextmanager
    def _record_lock(self, cwd: str, *, timeout: float | None = None) -> Generator[None]:
        """Hold the workspace's cross-process record lock; the caller holds ``_LOCK``.

        ``_LOCK`` serializes this process's threads only. Without this lock a server
        process sharing the state root could read a record while another deletes it,
        between ``result.json`` going and ``meta.json`` going, and report a finished
        job as ``failed`` (#237). Every section that reads, writes or deletes records
        takes it, so a delete and its restore are atomic to every reader. Lock order
        is ``_LOCK``, then the idempotency index's flock, then this; nothing takes them
        in another order. An overrun worker is terminated with all three released
        (#531, ``_terminate_overruns``), as ``cancel`` terminates, and so is a worker
        ``start`` spawned but could not record (#536); no wait for a worker happens
        under them. The workspace directory is created if it is missing, since
        another process can create it, and records in it, during this section; a lock
        that cannot be opened or taken raises rather than letting the section run
        unlocked. ``timeout`` bounds the wait as ``IdempotencyIndex.lock``'s does,
        raising ``idempotency.LockTimeout``; a nested section never waits."""
        with self._ws_record_lock(self._ws_dir(cwd), timeout=timeout):
            yield

    @staticmethod
    @contextlib.contextmanager
    def _ws_record_lock(ws: Path, *, timeout: float | None = None) -> Generator[None]:
        """``_record_lock`` for a workspace dir rather than a cwd."""
        held = _RECORD_LOCKS.get(ws)
        if held is not None:
            held[1] += 1
            try:
                yield
            finally:
                held[1] -= 1
            return
        ws.mkdir(parents=True, exist_ok=True)
        fd = os.open(ws / _RECORD_LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            idempotency._acquire_flock(fd, timeout)
        except BaseException:
            os.close(fd)
            raise
        _RECORD_LOCKS[ws] = [fd, 1]
        try:
            yield
        finally:
            del _RECORD_LOCKS[ws]
            idempotency._release_flock(fd)
            os.close(fd)

    def _terminate_overruns(self, attempt: Callable[[], _T]) -> _T:
        """Run ``attempt`` (which takes ``_LOCK`` and the record flock itself), and for
        each overrun job it meets, terminate the worker with every lock released,
        finalize it, then run ``attempt`` again (#531).

        ``_status_of`` never waits for a worker: on an overrun it publishes the job in
        ``_TERMINATING`` and raises ``_Overrun``, which unwinds ``attempt`` and so
        releases its locks. Only the outermost section on a thread does this; a nested
        one (``start`` inside ``start_idempotent``, the index's resolve) runs ``attempt``
        directly, because leaving a nested ``with`` does not release a re-entrant lock.
        Once the worker is stopped, ``_LOCK`` and that job's record lock are taken
        without a timeout and the job is finalized there (``_finalize_overrun``), so its
        outcome never depends on the retry reaching it again. The retry then re-reads
        everything from disk under its own locks. The retries end: a job raises
        ``_Overrun`` only while it is in neither ``_TERMINATING`` nor ``_OVERRAN``, and
        once terminated it stays in ``_OVERRAN`` until it is stamped or gone, so this
        process terminates each job at most once, and a section meets finitely many."""
        if getattr(_SECTION, "published", None) is not None:
            return attempt()
        published: set[Path] = set()
        claims: list[int] = []
        rollbacks: list[Callable[[], None]] = []
        _SECTION.published = published
        _SECTION.rollbacks = rollbacks
        try:
            while True:
                try:
                    return attempt()
                except _Overrun as overrun:
                    jd, meta = overrun.jd, overrun.meta
                    if overrun.claim_fd is not None:
                        claims.append(overrun.claim_fd)
                    _terminate_pid_tree(
                        _meta_pid(meta),
                        self.terminate_grace_seconds,
                        is_alive=lambda jd=jd, meta=meta: self._job_running(jd, meta),
                    )
                    with _LOCK, self._ws_record_lock(jd.parent):
                        _TERMINATING.discard(jd)
                        published.discard(jd)
                        _OVERRAN.add(jd)
                        # Not raised here, outside the body: the job stays pending and
                        # the retried body reads it itself, raising inside its caller's
                        # own handler (counted as held, skipped, DELETE_FAILED, the
                        # retention bound), as before #531. Nothing is stamped.
                        with contextlib.suppress(ResultUnreadable):
                            self._finalize_overrun(jd)
                    if overrun.claim_fd is not None:
                        claims.remove(overrun.claim_fd)
                        _release_claim(overrun.claim_fd)
        finally:
            _SECTION.published = None
            _SECTION.rollbacks = None
            # A termination or finalization that raised gives up its claim, so a later
            # reader, in any process, can take the job over.
            for fd in claims:
                _release_claim(fd)
            # A start that spawned a worker it could not record (#536): every lock is
            # released by now, and any idempotency reservation already dropped.
            # Each is bound to the store that queued it, so its grace and cleanup root
            # are that store's, not this one's.
            # One that raises, even an interrupt during its grace, does not skip the
            # rest: each left unrun is an orphaned paid worker. The first raise is
            # re-raised once all have run and the markers below are released.
            first: BaseException | None = None
            try:
                for rollback in rollbacks:
                    try:
                        rollback()
                    except BaseException as exc:
                        if first is None:
                            first = exc
            finally:
                if published:
                    # A termination or finalization that raised: release its marker, so
                    # this process does not read the job as running forever.
                    with _LOCK:
                        _TERMINATING.difference_update(published)
            if first is not None:
                raise first

    def _finalize_overrun(self, jd: Path) -> tuple[dict, str] | None:
        """Finalize a pending overrun job (``_OVERRAN``) under ``_LOCK`` and its record
        lock, from a fresh read: ``None`` if the record is gone, else its state as
        ``_finish_terminated`` gives it. Raises ``MetaUnreadable`` or ``ResultUnreadable``
        if meta.json or result.json cannot be read, with nothing written and the job
        left pending."""
        meta = self._read_meta(jd)
        if meta is None:
            _OVERRAN.discard(jd)
            return None
        return meta, self._finish_terminated(jd, meta, default="timeout")

    def _finish_terminated(
        self, jd: Path, meta: dict, default: Literal["timeout", "cancelled"]
    ) -> str:
        """The outcome of a stopped job that was claimed or terminated here, from
        ``meta`` as just read: its stamp if it has one, else ``done`` if the worker wrote
        its result in time (result-first), else the claim's reason (``default`` without a
        claim) with its declared paths cleaned up (the manifest re-read now). The write
        that stamps the record removes its claim. Drops the job from ``_OVERRAN`` once
        stamped; an unreadable result raises ``ResultUnreadable``, stamps nothing and
        keeps the claim."""
        terminal = meta.get("terminal_status")
        if not terminal:
            env = self._read_envelope(jd)
            claim = self._claim_of(meta)
            meta.pop("terminating", None)
            if env is not None:
                self._mark_done(jd, meta, env)
                terminal = "done"
            else:
                terminal = claim[0] if claim is not None else default
                self._finalize_cleanup(jd, meta, terminal, self._read_cleanup_manifest(jd))
        _OVERRAN.discard(jd)
        return terminal

    @staticmethod
    def _claim_of(meta: dict) -> tuple[str, float] | None:
        """The record's termination claim as ``(reason, epoch)``, or ``None`` when it has
        none or a malformed one (a reason other than the two, or a non-finite epoch)."""
        claim = meta.get("terminating")
        if not isinstance(claim, dict):
            return None
        reason, epoch = claim.get("reason"), claim.get("epoch")
        if reason not in _CLAIM_REASONS:
            return None
        if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
            return None
        if not math.isfinite(epoch):
            return None
        return reason, float(epoch)

    def _try_claim(
        self, jd: Path, meta: dict, reason: Literal["timeout", "cancelled"]
    ) -> int | None:
        """Become the job's claimant, under ``_LOCK`` and its record lock: try the
        claimant lock without waiting, then write the claim unless a well-formed one is
        there (best effort: an ``OSError`` leaves the lock alone to carry it). Returns
        ``None`` only when another holder has the lock, in which case nothing is written.
        Otherwise returns the descriptor holding it, or ``_NO_CLAIM_FD`` when the lock
        could not be taken for any other reason (the file cannot be opened, ``flock`` is
        unavailable or fails): the caller is then the claimant without a lock, as an
        indeterminate lock reads free to every reader, and still terminates the job."""
        fd = _NO_CLAIM_FD
        with contextlib.suppress(OSError):
            fd = os.open(jd / _TERMINATE_LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
        if fd != _NO_CLAIM_FD:
            try:
                import fcntl  # noqa: PLC0415 - platform-guarded lazy import (POSIX only)

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return None
            except (ImportError, OSError):  # pragma: no cover - non-POSIX, or e.g. ENOLCK
                os.close(fd)
                fd = _NO_CLAIM_FD
        if self._claim_of(meta) is None:
            meta["terminating"] = {"reason": reason, "epoch": time.time()}
            try:
                self._write_meta(jd, meta)
            except OSError:
                meta.pop("terminating", None)
        return fd

    def _locked(self, cwd: str, body: Callable[[], _T]) -> _T:
        """Run ``body`` under ``_LOCK`` and the workspace's record lock, terminating
        any overrun job it meets with both released (``_terminate_overruns``)."""

        def attempt() -> _T:
            with _LOCK, self._record_lock(cwd):
                return body()

        return self._terminate_overruns(attempt)

    def _idem_index(self, cwd: str) -> idempotency.IdempotencyIndex:
        """The dedup index for a workspace. The horizon is a conservative floor: a job's
        whole wall-clock life (max_seconds) plus its terminate grace plus the terminal
        TTL, so a reserved/gone entry is never reclaimed while any real duplicate could
        still be spawned against it."""
        horizon = self.max_seconds + self.terminate_grace_seconds + self.ttl_seconds
        return idempotency.IdempotencyIndex(
            self._ws_dir(cwd) / _IDEM_DIRNAME, horizon_seconds=horizon
        )

    def _resolve_job_facts(self, cwd: str, job_id: str) -> idempotency.JobFacts | None:
        """Injected into the index: does this job still exist and is it terminal? Uses
        the same live-read (and expiry reaping) as every other lookup, so a terminal
        job past its TTL reads as gone (→ result-unavailable), never as replayable."""
        try:
            with self._record_lock(cwd):
                live = self._read_live_job(cwd, job_id)
        except ResultUnreadable:
            # The record is there; only its outcome is unreadable. Reported as live and
            # not terminal: the key keeps replaying to this job (whose own reads say what
            # is wrong) and the index never reclaims it as a missing backing job.
            return idempotency.JobFacts(exists=True, terminal=False)
        if live is None:
            return None
        _jd, _meta, state = live
        return idempotency.JobFacts(exists=True, terminal=state in _TERMINAL)

    # --------------------------------------------------------------- meta i/o
    @staticmethod
    def _read_meta(jd: Path) -> dict | None:
        """Parse meta.json, or None if absent (not a record yet) or unparsable. One that
        exists but cannot be read raises ``ResultUnreadable`` (#530), as ``_read_envelope``
        does: the record is there, so it is neither absent nor safe to delete or evict."""
        try:
            text = (jd / "meta.json").read_text()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise MetaUnreadable(exc.errno) from None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _write_meta(jd: Path, meta: dict) -> None:
        # Atomic publication: a concurrent reader (status/list/_make_room in
        # another process) must never observe a torn meta.json — a partial read parses
        # as no meta, which _status_of treats as terminal and eviction can delete.
        tmp = jd / "meta.json.tmp"
        tmp.write_text(json.dumps(meta))
        tmp.replace(jd / "meta.json")

    @staticmethod
    def _read_envelope(jd: Path) -> dict | None:
        """Parse the final result envelope from result.json, or None if absent/
        partial/non-object. A result that exists but cannot be read is neither: it
        raises ``ResultUnreadable`` (#280), because reporting it as absent turned a done
        job into ``failed`` on every transient read error."""
        try:
            text = (jd / "result.json").read_text()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ResultUnreadable(exc.errno) from None
        text = text.strip()
        if not text:
            return None
        try:
            env = json.loads(text)
        except json.JSONDecodeError:
            return None
        return env if isinstance(env, dict) else None

    @staticmethod
    def _envelope_ok(env: dict) -> bool | None:
        """The stored envelope's producer-declared outcome: its top-level boolean
        ``ok``, or ``None`` when that key is absent or not a real boolean. An
        unclassifiable payload is reported ``None``, never guessed as a failure."""
        ok = env.get("ok")
        return ok if isinstance(ok, bool) else None

    def _mark_done(self, jd: Path, meta: dict, env: dict) -> None:
        """Stamp the terminal ``done`` outcome on first observation: the completion
        clock (drives expiry), ``result_ok`` (the envelope's ``ok`` discriminator) and
        ``terminal_status`` itself, so every later read short-circuits on the stamp and
        never re-reads result.json (#280: re-deriving it turned a read error into
        ``failed``). The clock and ``result_ok`` are guarded by ``completed_epoch`` so
        they are written once and never re-derived — a record already finalized
        (including by a release that predates ``result_ok``) keeps what it has, so that
        field is never backfilled. The marker alone is backfilled onto such a record,
        because it is what keeps the record ``done`` through a later read error."""
        changed = False
        if meta.get("completed_epoch") is None:
            meta["completed_epoch"] = time.time()
            meta["result_ok"] = self._envelope_ok(env)
            changed = True
        if meta.get("terminal_status") != "done":
            meta["terminal_status"] = "done"
            changed = True
        if changed:
            self._write_meta(jd, meta)

    @staticmethod
    def _read_cleanup_manifest(jd: Path) -> list[str]:
        """External paths a job declared it owns, from <job_dir>/cleanup.json.

        The store treats this as opaque caller-declared state: it never learns the
        paths are git worktrees, only that the job asked for them to be removed when
        it is reaped. Missing/garbage manifest -> no declared paths."""
        try:
            data = json.loads((jd / "cleanup.json").read_text())
        except (OSError, json.JSONDecodeError):
            return []
        paths = data.get("paths") if isinstance(data, dict) else None
        return [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []

    @staticmethod
    def _read_activity(jd: Path) -> tuple[int, float | None]:
        """(events_seen, last_event_epoch) from activity.json; (0, None) if absent/
        corrupt. Treated as opaque caller-declared state, like cleanup.json.

        Values are validated, not trusted: a non-int/negative count degrades to 0,
        and an unusable epoch degrades to None — otherwise the downstream
        datetime.fromtimestamp()/int() in _status_dict would raise and take the whole
        job-status API down with a corrupt file. An epoch is unusable if it is
        non-finite (json.loads accepts NaN/Infinity) OR finite but out of range for
        datetime.fromtimestamp() (e.g. 1e308 raises OverflowError/OSError/ValueError
        depending on the platform)."""
        try:
            data = json.loads((jd / "activity.json").read_text())
        except (OSError, json.JSONDecodeError):
            return 0, None
        if not isinstance(data, dict):
            return 0, None
        count = data.get("events_seen")
        epoch = data.get("last_event_epoch")
        count = (
            count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else 0
        )
        is_number = isinstance(epoch, (int, float)) and not isinstance(epoch, bool)
        epoch = epoch if is_number and _usable_epoch(epoch) else None
        return count, epoch

    def _within_cleanup_root(self, path: str) -> bool:
        if self.cleanup_root is None:
            return False
        # The manifest is opaque caller-declared state; a path that cannot be
        # resolved (symlink loop, permission error) is treated as outside the root
        # and refused rather than crashing cleanup.
        try:
            root = Path(self.cleanup_root).resolve()
            target = Path(path).resolve()
        except OSError:
            return False
        if not target.name.startswith(self.cleanup_prefix):
            return False
        return target != root and target.is_relative_to(root)

    def _cleanup_external_paths(self, paths: list[str]) -> list[str]:
        """Remove a reaped job's declared external paths, refusing anything not
        strictly inside ``cleanup_root``. Returns warnings for paths that were
        refused or survived removal (so a caller can surface the leak)."""
        if self.cleanup_root is None:
            return []  # external cleanup not configured; the store made no promise
        warnings: list[str] = []
        for path in paths:
            if not self._within_cleanup_root(path):
                warnings.append(f"refused to remove path outside the cleanup root: {path}")
                continue
            shutil.rmtree(path, ignore_errors=True)
            if Path(path).exists():
                warnings.append(f"could not remove temporary path: {path}")
        return warnings

    def _finalize_cleanup(self, jd: Path, meta: dict, status: str, manifest: list[str]) -> None:
        """Mark the record terminal and remove any external paths it declared,
        recording cleanup warnings in meta so status/result can surface them."""
        warnings = self._cleanup_external_paths(manifest)
        meta["terminal_status"] = status
        meta["completed_epoch"] = time.time()
        if warnings:
            meta["cleanup_warnings"] = warnings
        self._write_meta(jd, meta)

    @staticmethod
    def _rmtree(jd: Path) -> None:
        # A partial failure must leave the record exactly as it was: still visible, and
        # still reporting the outcome it had. So result.json and meta.json go LAST, after
        # every other entry: meta.json is the record's existence marker (a dir without it
        # is invisible to status/list and skipped by the reaper, #306 review), and
        # result.json is what makes a finished job read as done rather than failed (#124).
        # Both must be gone before rmdir (the dir has to be empty), so they are snapshotted
        # first and, if unlinking either or the final rmdir fails, restored atomically (tmp
        # + replace, mirroring _write_meta, so a cross-process reader never sees a torn
        # file). A file that exists but cannot be snapshotted aborts the delete before
        # either goes. The marker is restored first and the result only once the marker is
        # back: a result.json with no marker would be invisible, outliving every retention
        # bound.
        meta = jd / "meta.json"
        result = jd / "result.json"
        core = (result, meta)
        try:
            for child in jd.iterdir():
                if child not in core:
                    child.unlink(missing_ok=True)
        except OSError:
            return  # nothing in core was touched, so the record is intact
        snapshots: dict[Path, bytes] = {}
        for path in core:
            try:
                snapshots[path] = path.read_bytes()
            except FileNotFoundError:
                continue  # absent, so there is nothing to restore
            except OSError:
                return  # a file that cannot be restored must not be deleted
        unlinked: list[Path] = []
        try:
            for path in core:
                path.unlink(missing_ok=True)
                unlinked.append(path)
            jd.rmdir()
        except OSError:
            for path in sorted(unlinked, key=lambda p: p != meta):  # marker first
                if path not in snapshots:
                    continue
                try:
                    tmp = path.with_name(path.name + ".tmp")
                    tmp.write_bytes(snapshots[path])
                    tmp.replace(path)
                except OSError:
                    return  # never restore the result without its marker

    @staticmethod
    def _gone(jd: Path) -> bool:
        """Whether ``jd`` is verifiably absent. A ``stat`` probe, not ``exists()``: since
        Python 3.14 ``exists()`` returns False for an inaccessible-but-present path, which
        would claim a removal that never happened. Only FileNotFoundError proves absence;
        any other stat error means unverified."""
        try:
            jd.stat()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False

    # --------------------------------------------------------------- spawning
    def start(
        self,
        cmd_factory: CmdFactory,
        cwd: str,
        *,
        kind: str,
        extra: dict | None = None,
        write_spec: dict | None = None,
        stdin_text: str | None = None,
    ) -> tuple[str, str]:
        """Spawn ``cmd_factory(job_dir)`` detached and persist its record.

        The command runs with ``cwd=<job_dir>`` (so a relative ``result.json`` lands
        in the record). If ``write_spec`` is given, it is written to
        ``<job_dir>/spec.json`` before the command starts. Returns
        ``(job_id, started_at_iso)``.

        ``stdin_text``, when given, is streamed to the worker over a pipe by a
        daemon thread instead of being persisted anywhere — the transport for a
        bridge whose prompts must stay off disk and off argv (the claude bridge's
        design). With ``None`` (the default) the worker gets ``DEVNULL``,
        byte-identical to the prior behavior.
        """
        return self._locked(
            cwd,
            lambda: self._start_locked(
                cmd_factory,
                cwd,
                kind=kind,
                extra=extra,
                write_spec=write_spec,
                stdin_text=stdin_text,
            ),
        )

    def _start_locked(
        self,
        cmd_factory: CmdFactory,
        cwd: str,
        *,
        kind: str,
        extra: dict | None,
        write_spec: dict | None,
        stdin_text: str | None,
    ) -> tuple[str, str]:
        """``start``'s body, under ``_LOCK`` and the record lock. ``_make_room`` runs
        first and may raise ``_Overrun`` before anything is spawned."""
        self._make_room(cwd)
        job_id = uuid4().hex
        jd = self._job_dir(cwd, job_id)
        jd.mkdir(parents=True, exist_ok=True)
        # Results can contain a diff; keep the workspace tree user-only.
        with contextlib.suppress(OSError):
            self._ws_dir(cwd).chmod(0o700)
        if write_spec is not None:
            (jd / "spec.json").write_text(json.dumps(write_spec))
        cmd = cmd_factory(jd)
        started = time.time()
        log_path = jd / "stderr.log"
        try:
            ef = log_path.open("w")
        except OSError:
            shutil.rmtree(jd, ignore_errors=True)
            raise
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(jd),
                stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE,
                stdout=ef,
                stderr=ef,
                start_new_session=True,
                text=stdin_text is not None,
                encoding="utf-8" if stdin_text is not None else None,
            )
        except BaseException:
            # Nothing was spawned (an OSError, or e.g. a ValueError for a bad argument):
            # drop the log and the dir, then re-raise.
            with contextlib.suppress(OSError):
                ef.close()
            shutil.rmtree(jd, ignore_errors=True)
            raise
        # From here a paid worker exists: every failure until its record is written
        # (closing the log, starting the stdin thread, writing meta.json) rolls it back.
        try:
            ef.close()
            if stdin_text is not None:
                threading.Thread(target=_write_stdin, args=(proc, stdin_text), daemon=True).start()
            meta = {
                "job_id": job_id,
                "kind": kind,
                "pid": proc.pid,
                "owner": _PROCESS_OWNER,
                "started_epoch": started,
                "started_at": datetime.now(UTC).isoformat(),
                "deadline_epoch": started + self.max_seconds,
                "completed_epoch": None,
                "terminal_status": None,
                # Present-and-null marks a record whose delivery is tracked; one without
                # the key predates tracking, and the cap evicts it as it always did.
                "delivered_epoch": None,
                "extra": extra or {},
            }
            self._write_meta(jd, meta)
        except BaseException:
            with contextlib.suppress(OSError):
                ef.close()
            # Recording failed after a successful spawn (disk full, fs error). A paid
            # worker is already running detached; reap its process group so no orphaned
            # worker survives — mirrors the `except BaseException` around Popen above.
            # The wait for it runs with every lock released (#536): the outermost section
            # (`_terminate_overruns`) runs the rollback after it unwinds. jd has no
            # meta.json, so no other section counts, reaps or deletes it meanwhile; one
            # the write published before failing (an interrupt after its rename) is
            # withdrawn here, under the record lock, so that stays true.
            with contextlib.suppress(OSError):
                (jd / "meta.json").unlink(missing_ok=True)
            # `start` always runs inside a section; rolling back here instead would wait
            # out the grace under the locks, which is #536 again.
            pending = getattr(_SECTION, "rollbacks", None)
            assert pending is not None, "start ran outside _terminate_overruns"
            pending.append(functools.partial(self._rollback_unrecorded, proc.pid, jd))
            raise
        return job_id, meta["started_at"]

    def _rollback_unrecorded(self, pid: int, jd: Path) -> None:
        """Stop a worker ``start`` spawned but could not record, then drop its dir.
        Runs with no lock held. The worker may have already registered an external
        worktree in cleanup.json before being killed (and a SIGKILLed worker can't
        self-clean), so the guarded external-path cleanup runs after it is stopped and
        *before* jd goes — otherwise deleting jd destroys the only manifest and leaks
        that worktree. Errors are logged, not raised, so the caller's original
        persistence error is the one that surfaces; on one, jd is kept so its manifest
        is not lost."""
        try:
            _terminate_pid_tree(pid, self.terminate_grace_seconds)
            self._cleanup_external_paths(self._read_cleanup_manifest(jd))
        except Exception:
            logger.exception("rollback of unrecorded job %s failed", jd.name)
            return
        shutil.rmtree(jd, ignore_errors=True)

    # ------------------------------------------------------------ status calc
    @staticmethod
    def _owned(meta: dict) -> bool:
        """Whether THIS process started the job (its worker is our own child)."""
        owner = meta.get("owner")
        return bool(owner) and owner == _PROCESS_OWNER

    def _job_running(self, jd: Path, meta: dict) -> bool:
        """Whether the job's worker is alive AND safe to signal.

        A held per-job lock is authoritative for ANY job: a PID reused by an unrelated
        process after a restart cannot hold it, so such a PID is never mistaken for the
        worker. For a job THIS process started (owned), the PID is our own child, so the
        existence probe (``_is_running``, which reaps) is authoritative — and stays
        correct during the worker's tiny create-then-``flock`` startup window, when the
        lock briefly reads as free. An unowned job is treated as running only while its
        worker still holds the lock; otherwise it is not running, so cancel/timeout
        never signal a stale or reused PID. A pid ``_meta_pid`` rejects is no pid."""
        pid = _meta_pid(meta)
        if pid is None:
            return False
        if _worker_lock_held(jd / "worker.lock") is True:
            return True  # positively verified alive (a reused PID can't hold this lock)
        if self._owned(meta):
            return _is_running(pid)  # our own child: the PID probe is authoritative
        return False  # unowned + no verified lock -> never reported running or signaled

    def _worker_gone(self, jd: Path, meta: dict) -> bool:
        """Whether no worker can still write this job's ``result.json``.

        Stricter than ``not _job_running``: an unowned job whose lock is indeterminate
        (no lock file) reads as not running, so ``_status_of`` calls it ``failed``, yet
        its worker may still finish and turn the record ``done`` (#126). For our own
        job, ``_is_running`` reaps the child, then falls back to a ``kill(0)`` probe of
        the PID. For an unowned one, the lock file must exist and be free AND the PID
        must be dead: a free lock alone is not proof, since a worker that could not take
        its lock runs without it. Either test errs only toward keeping the record, since
        a reused PID reads as alive, and a worker that is gone never comes back. The lock
        is probed, never held: a held lock is how every reader, in any process, tells a
        live worker from a reused PID, so holding it would make them treat a dead job as
        alive and signal its PID. A pid ``_meta_pid`` rejects proves nothing, so the
        worker is never taken as gone.
        """
        pid = _meta_pid(meta)
        if pid is None:
            return False
        if self._owned(meta):
            return not _is_running(pid)
        return _worker_lock_held(jd / "worker.lock") is False and not _pid_alive(pid)

    def _worker_stopped(self, meta: dict) -> bool:
        """Whether a claimed job's worker is positively known to be stopped, so it may be
        finalized by its claim: for our own job, ``_is_running`` (which reaps) says it is
        not running; for an unowned one, its PID is dead. A pid ``_meta_pid`` rejects
        proves nothing.

        Weaker than ``_worker_gone``, which also needs an unowned job's ``worker.lock`` to
        exist and be free: a worker that died before creating its lock never satisfies
        that, and a claimed job, whose claimant has already signalled it, must still be
        finalized then. A dead PID suffices here because a claim's worker was being
        stopped, and a free or absent lock with a live PID is left to ``_status_of``'s
        bounded wait rather than read as stopped."""
        pid = _meta_pid(meta)
        if pid is None:
            return False
        if self._owned(meta):
            return not _is_running(pid)
        return not _pid_alive(pid)

    def _status_of(self, jd: Path, meta: dict) -> str:
        """Compute the live status, finalizing a job that overran once it is stopped.

        Never waits for a worker, since every caller holds ``_LOCK`` and the record
        lock (#531). A running job past its deadline is published in ``_TERMINATING``
        and reported by raising ``_Overrun``; the outermost locked section terminates it
        with the locks released and finalizes it (``_finalize_overrun``) as the old
        in-lock path did. A job a thread of this process is terminating reads as
        ``running``; one it has terminated but not yet stamped (``_OVERRAN``) is
        finalized here the overrun way, by whichever read first can read it.

        A job whose claimant lock is held, in any process, reads ``running``, whether or
        not its claimant could write a claim. A job with a well-formed termination claim
        (see the module docstring) and the lock free is finalized here
        (``_finish_terminated``) once its worker is positively stopped
        (``_worker_stopped``); while it is safe to signal (``_job_running``) this reader
        becomes its claimant and raises ``_Overrun``; otherwise it reads ``running``,
        with nothing stamped, signalled or evicted, until its deadline plus the terminate
        grace has passed, and then as an unclaimed stopped record would (``done`` or an
        unstamped ``failed``, no cleanup). A running job past its
        deadline raises ``_Overrun`` only once this reader holds the claimant lock, and
        reads ``running`` when another holder has it.

        Raises ``ResultUnreadable`` when a stopped worker's result.json exists but cannot
        be read (#280): the job is then neither finalized nor reported, since reading it
        as absent would stamp ``timeout`` or report ``failed`` for a result that is still
        there. A record already stamped terminal never reads the file at all."""
        if jd in _OVERRAN:
            # This process terminated it as an overrun: finalize it that way whatever the
            # worker now reads as, never terminating it again or deriving failed.
            return self._finish_terminated(jd, meta, default="timeout")
        terminal = meta.get("terminal_status")
        if terminal:
            return terminal
        if jd in _TERMINATING:
            return "running"  # a thread is terminating it and will finalize it
        if _worker_lock_held(jd / _TERMINATE_LOCK_NAME) is True:
            # Its claimant, in some process, will finalize it, whether or not it could
            # write its claim (the lock alone carries one it could not write).
            return "running"
        claim = self._claim_of(meta)
        if claim is not None:
            # Its claimant is gone (an indeterminate lock reads free).
            if self._worker_stopped(meta):
                return self._finish_terminated(jd, meta, default="timeout")
            if self._job_running(jd, meta):
                reason: Literal["timeout", "cancelled"] = (
                    "cancelled" if claim[0] == "cancelled" else "timeout"
                )
                self._raise_overrun(jd, meta, reason)
                return "running"  # fell through: another holder has the claimant lock
            # Neither proven stopped nor safe to signal: an unowned worker whose PID is
            # alive but holds no lock, still starting or a reused PID. Stamp, signal and
            # evict nothing until its deadline plus the grace has passed, then derive
            # its state as an unclaimed record's (below), so a reused PID cannot wedge it.
            bound = meta.get("deadline_epoch", float("inf")) + self.terminate_grace_seconds
            if time.time() <= bound:
                return "running"
        elif self._job_running(jd, meta):
            if time.time() > meta.get("deadline_epoch", float("inf")):
                self._raise_overrun(jd, meta, "timeout")
                return "running"  # fell through: another holder has the claimant lock
            return "running"
        env = self._read_envelope(jd)
        if env is not None:
            self._mark_done(jd, meta, env)
            return "done"
        if meta.get("completed_epoch") is None:
            meta["completed_epoch"] = time.time()
            self._write_meta(jd, meta)
        # No envelope at finalization -> "failed", and completed_epoch is now set, so if
        # result.json later materializes (e.g. an unowned worker read as not-running post-
        # restart that then finishes) a subsequent read flips to "done" but _mark_done's
        # guard leaves result_ok unstamped -> null. Safe degradation, not a false outcome;
        # a cancel() during that window repairs it via setdefault.
        return "failed"

    def _raise_overrun(self, jd: Path, meta: dict, reason: Literal["timeout", "cancelled"]) -> None:
        """Become the claimant of a job to terminate and raise ``_Overrun`` with its
        lock; return only when another holder has the lock."""
        fd = self._try_claim(jd, meta, reason)
        if fd is None:
            return
        # Published and owned in one step, so the section that must clear the marker
        # always knows of it.
        _TERMINATING.add(jd)
        owned = getattr(_SECTION, "published", None)
        if owned is not None:
            owned.add(jd)
        raise _Overrun(jd, meta, fd)

    @staticmethod
    def _elapsed_ms(meta: dict) -> int:
        end = meta.get("completed_epoch") or time.time()
        return max(0, int((end - meta.get("started_epoch", end)) * 1000))

    def _deadline_seconds(self, meta: dict) -> int:
        """The window the job was STARTED with (deadline minus start), not the
        current config — so status stays consistent if config later changes."""
        started = meta.get("started_epoch")
        deadline = meta.get("deadline_epoch")
        if started is not None and deadline is not None:
            return max(0, round(deadline - started))
        return self.max_seconds

    def _expires_at(self, meta: dict) -> str | None:
        completed = meta.get("completed_epoch")
        if completed is None:
            return None
        return datetime.fromtimestamp(completed + self.ttl_seconds, UTC).isoformat()

    def _expired(self, meta: dict) -> bool:
        completed = meta.get("completed_epoch")
        if completed is None:
            return False
        return time.time() - completed > self.ttl_seconds

    def _past_retention(self, meta: dict) -> bool:
        """Whether a record whose outcome could not be read is past its retention bound
        (#280): its worker is stopped, so it ages like a finalized one, from its
        completion clock if one was stamped. An unstamped record has none, and its start
        would understate it: a job that ran longer than the TTL would be past retention
        the moment it finished (PR #296 review). Its deadline cannot precede its
        completion, since the store stops a worker past it, so that is the clock, with
        the start only for a record that recorded no deadline. One rule for the reaper
        and for a direct read, so a record the reaper would remove cannot keep raising
        on ``status`` instead."""
        end = meta.get("completed_epoch") or meta.get("deadline_epoch") or meta.get("started_epoch")
        return end is not None and time.time() - end > self.ttl_seconds

    def _status_dict(self, jd: Path, meta: dict, state: str) -> dict:
        elapsed_ms = self._elapsed_ms(meta)
        # Running jobs get a growing poll hint so a polling agent backs off; terminal
        # jobs don't need polling, so the flat base is fine there.
        poll = (
            poll_backoff_ms(elapsed_ms, base=self.poll_after_ms)
            if state == "running"
            else self.poll_after_ms
        )
        events_seen, last_epoch = self._read_activity(jd)
        end = meta.get("completed_epoch") or time.time()
        last_event_at = (
            datetime.fromtimestamp(last_epoch, UTC).isoformat() if last_epoch is not None else None
        )
        event_age_ms = max(0, int((end - last_epoch) * 1000)) if last_epoch is not None else None
        return {
            "job_id": meta.get("job_id", jd.name),
            "kind": meta.get("kind", ""),
            "status": state,
            "started_at": meta.get("started_at", ""),
            "started_epoch": meta.get("started_epoch", 0.0),
            "elapsed_ms": elapsed_ms,
            "deadline_seconds": self._deadline_seconds(meta),
            "completed_epoch": meta.get("completed_epoch"),
            "expires_at": self._expires_at(meta),
            "result_available": state == "done",
            # Producer-declared outcome, surfaced only for a done record and only
            # when it was actually stamped as a real boolean — a malformed or absent
            # stamp (corrupt meta, or a record from before this field) degrades to
            # None rather than a stale/guessed value.
            "result_ok": (
                meta.get("result_ok")
                if state == "done" and isinstance(meta.get("result_ok"), bool)
                else None
            ),
            "poll_after_ms": poll,
            "ttl_seconds": self.ttl_seconds,
            "cleanup_warnings": meta.get("cleanup_warnings", []),
            "extra": meta.get("extra", {}),
            "events_seen": events_seen,
            "last_event_at": last_event_at,
            "event_age_ms": event_age_ms,
        }

    # ----------------------------------------------------------- maintenance
    def _read_live_job(self, cwd: str, job_id: str) -> tuple[Path, dict, str] | None:
        """Read + refresh a single record; drop it if terminal and expired."""
        live, _left = self._read_or_expire(cwd, job_id)
        return live

    def _read_or_expire(self, cwd: str, job_id: str) -> tuple[tuple[Path, dict, str] | None, bool]:
        """``_read_live_job``, plus whether an expired record's cleanup failed. Such a
        record is never served, like any expired one, but its files remain, which a
        caller reporting what it deleted must not call absent (#125)."""
        if not _is_job_id(job_id):
            # A malformed id (wrong shape, traversal, empty) is by construction not a
            # job this store started: report not-found without touching the filesystem.
            # The public callers check it before taking the record lock, which would.
            return None, False
        jd = self._job_dir(cwd, job_id)
        meta = self._read_meta(jd)
        if meta is None:
            return None, False
        try:
            state = self._status_of(jd, meta)
        except ResultUnreadable:
            # Unknowable, not failed: served to no one until it reads back, but held to
            # the same retention bound as any finalized record, so a result that never
            # reads back again cannot outlive what the tool surface discloses.
            if self._past_retention(meta):
                self._rmtree(jd)
                return None, not self._gone(jd)
            raise
        if state in _TERMINAL and self._expired(meta):
            self._rmtree(jd)
            return None, not self._gone(jd)
        return (jd, meta, state), False

    def _reap_workspace(self, cwd: str) -> None:
        ws = self._ws_dir(cwd)
        if not ws.is_dir():
            return
        now = time.time()
        for jd in self._job_dirs(ws):
            try:
                meta = self._read_meta(jd)
            except ResultUnreadable:
                continue  # its age is unknowable, so it is never reaped on this read
            if meta is None:
                continue
            try:
                state = self._status_of(jd, meta)
            except ResultUnreadable:
                # Kept until its retention bound, since nothing has been able to tell
                # whether it is done; past it, it goes like any finalized record.
                if self._past_retention(meta):
                    self._rmtree(jd)
                continue
            if state in _TERMINAL:
                end = meta.get("completed_epoch") or meta.get("started_epoch") or now
                if now - end > self.ttl_seconds:
                    self._rmtree(jd)

    def _evictable(self, meta: dict, state: str | None) -> bool:
        """Whether the count cap may delete this record. Never a running job, never a
        ``done`` result that has not been returned once (#244), and never a record whose
        state could not be read (``None``: it may be exactly such a result); everything
        else terminal is fair game."""
        if state not in _TERMINAL:
            return False
        if state != "done" or "delivered_epoch" not in meta:
            return True  # a terminal error, or a record that predates delivery tracking
        # Returned once, or not: the format is never consulted, because the release that
        # wrote a result can still deliver it from a server sharing this state root, older
        # or newer than this one; the same reason a consume keeps an incompatible result.
        return meta["delivered_epoch"] is not None

    def _make_room(self, cwd: str) -> None:
        """Make room for one more record, or refuse. Runs under ``_LOCK`` before a start
        spawns anything: reap expired records, then evict evictable ones oldest first
        until the workspace holds fewer than ``max_count``. A directory without
        ``meta.json`` is not a record (it may be another process's start mid-spawn), so
        it is neither counted nor deleted. ``start`` holds the workspace's record lock from
        this check until the new record is written, so server processes sharing a state
        root that all take it never overshoot the cap; an older release sharing the root
        does not take it, and can overshoot by one start per process. An overshoot deletes
        nothing. An overrun job met here (by the reap or the count) raises ``_Overrun``
        before anything is evicted, so ``start`` releases the locks, terminates it, and
        runs this again, when it reads as finalized and is evictable like any terminal
        error; a job another thread is terminating reads as ``running``, so it is counted
        as held and never evicted while its worker may live (#531)."""
        self._reap_workspace(cwd)
        records: list[tuple[Path, dict, str | None]] = []
        for jd in self._job_dirs(self._ws_dir(cwd)):
            try:
                meta = self._read_meta(jd)
            except ResultUnreadable:
                # A meta.json that exists but cannot be read is a record (#530): counted
                # as held and never evicted, like an unreadable result below.
                records.append((jd, {}, None))
                continue
            if meta is None:
                continue
            try:
                state: str | None = self._status_of(jd, meta)
            except ResultUnreadable:
                state = None  # counted as held, never evicted: it may be an unreturned result
            records.append((jd, meta, state))
        held = len(records)
        if held < self.max_count:
            return
        records.sort(key=lambda r: r[1].get("started_epoch", 0.0))  # oldest first
        for jd, meta, state in records:
            if held < self.max_count:
                return
            if self._evictable(meta, state):
                self._rmtree(jd)
                if self._gone(jd):
                    held -= 1
        if held >= self.max_count:
            raise JobCapReached(self.max_count, held)

    # -------------------------------------------------------------- public API
    def status(self, cwd: str, job_id: str) -> dict | None:
        if not _is_job_id(job_id):
            return None  # before the lock: a malformed id touches nothing

        def body() -> dict | None:
            live = self._read_live_job(cwd, job_id)
            if live is None:
                return None
            jd, meta, state = live
            return self._status_dict(jd, meta, state)

        return self._locked(cwd, body)

    def result_payload(self, cwd: str, job_id: str) -> tuple[dict | None, dict | None]:
        """Return (status_dict, result_envelope). Read-only.

        status_dict is None when the job does not exist. result_envelope is the
        parsed result.json (only when status == done), else None. Deletion is a
        separate, explicit step — ``discard`` — so a caller can validate the
        payload it was handed before destroying the only copy of it (#306).
        Raises ``ResultUnreadable`` when either read (the status, then the payload)
        finds a result that exists but cannot be opened (#280), as ``status``,
        ``list_jobs`` and ``cancel`` do; ``discard`` reports it as DELETE_FAILED.
        """
        if not _is_job_id(job_id):
            return None, None  # before the lock: a malformed id touches nothing

        def body() -> tuple[dict | None, dict | None]:
            live = self._read_live_job(cwd, job_id)
            if live is None:
                return None, None
            jd, meta, state = live
            rec = self._status_dict(jd, meta, state)
            if state != "done":
                return rec, None
            return rec, self._read_envelope(jd)

        return self._locked(cwd, body)

    def mark_delivered(self, cwd: str, job_id: str) -> bool:
        """Stamp a ``done`` record as returned once, which lets the count cap evict it
        (#244). Call it only after a stored result was validated and handed back: it
        records that amicus returned the result, never that the client received it.
        Returns True only when this call wrote the stamp; a missing, non-``done``,
        untracked or already-stamped record is left unchanged."""
        if not _is_job_id(job_id):
            return False  # before the lock: a malformed id touches nothing

        def body() -> bool:
            live = self._read_live_job(cwd, job_id)
            if live is None:
                return False
            jd, meta, state = live
            if state != "done" or "delivered_epoch" not in meta:
                return False
            if meta["delivered_epoch"] is not None:
                return False
            meta["delivered_epoch"] = time.time()
            self._write_meta(jd, meta)
            return True

        return self._locked(cwd, body)

    def discard(self, cwd: str, job_id: str, *, expected: str = "done") -> DiscardOutcome:
        """Delete a terminal job record, but only in the state the caller names.

        A compare-and-delete: ``expected`` is the terminal state the caller read
        (``done`` by default), and the record is deleted only if a fresh read under
        ``_LOCK`` still finds it. So a caller that read ``failed`` never deletes a
        result that appeared since (#126). ``failed`` is derived rather than stamped,
        so it must also be final: a ``failed`` record is deleted only once its worker
        is verifiably gone (``_worker_gone``), and is otherwise STATE_CHANGED.
        The outcome is discriminated so callers never infer it from a follow-up
        ``status`` read: MISSING means there was no record to delete (already
        discarded, expired, or evicted), STATE_CHANGED means the record exists but
        is not in the named state (never deleted), and DELETE_FAILED means removal
        failed or could not be verified. The record is then left as it was
        (``_rmtree`` restores it) for a retry or the TTL reaper; an expired record
        whose cleanup failed is no longer served but its files remain (#125).
        Verification is ``_gone``'s ``stat`` probe, so an unverifiable removal is
        never REMOVED.
        One caller wins across server processes too: the read and the delete both
        run under the workspace's record lock, so a second process sharing the
        state root finds the record gone (MISSING), never half-deleted (#237). An
        older release sharing the root does not take that lock.
        """
        if expected not in _TERMINAL:
            raise ValueError(f"expected must be a terminal state, not {expected!r}")
        if not _is_job_id(job_id):
            return DiscardOutcome.MISSING  # before the lock: a malformed id touches nothing

        def body() -> DiscardOutcome:
            try:
                live, left = self._read_or_expire(cwd, job_id)
                if live is None:
                    return DiscardOutcome.DELETE_FAILED if left else DiscardOutcome.MISSING
                jd, meta, state = live
                if state != expected:
                    return DiscardOutcome.STATE_CHANGED
                # Prove a failed job's worker gone, THEN read again: a worker running
                # without its lock can write result.json and exit after the first read, and
                # only once it is gone can no result appear (PR #238 review).
                if state == "failed" and (
                    not self._worker_gone(jd, meta) or self._status_of(jd, meta) != "failed"
                ):
                    return DiscardOutcome.STATE_CHANGED
            except ResultUnreadable:
                # Either read found a result that could not be read back (#280): the state
                # the caller named is not verifiable, so nothing is deleted. DELETE_FAILED
                # rather than STATE_CHANGED, because the record is left exactly as it was
                # for a retry, which is what that outcome promises.
                return DiscardOutcome.DELETE_FAILED
            self._rmtree(jd)
            return DiscardOutcome.REMOVED if self._gone(jd) else DiscardOutcome.DELETE_FAILED

        return self._locked(cwd, body)

    def cancel(self, cwd: str, job_id: str) -> dict | None:
        """Cancel a running job as its termination claimant (see the module docstring).

        Under the locks, a running job is claimed with reason ``cancelled``; the claimant
        terminates it with every lock released and then finalizes it. When another
        holder has the claimant lock (a peer process, or a thread here terminating it as
        an overrun), this cancel signals nothing while that holder keeps it: it waits,
        with every lock released, at most the terminate grace plus one second for the lock
        to come free, then returns the job as a fresh locked read gives it, ``running``
        if the holder still has it. If that holder went away leaving the worker running,
        that read finds the claim's lock free and the worker live, so this cancel takes
        over as claimant and stops it (by the claim's reason), which can take one further
        terminate grace."""
        if not _is_job_id(job_id):
            return None  # before the lock: a malformed id touches nothing
        jd = self._job_dir(cwd, job_id)

        def read() -> tuple[Path, dict, str] | None:
            try:
                return self._read_live_job(cwd, job_id)
            except MetaUnreadable as exc:
                # A pending overrun's worker was signalled by its termination, though
                # its record cannot be read now; anything else was never signalled.
                exc.signalled = jd in _OVERRAN
                raise

        def first() -> dict | tuple[dict, int | None] | None:
            live = read()
            if live is None:
                return None
            _, meta, state = live
            if state in _TERMINAL:
                return self._status_dict(jd, meta, state)
            if jd in _TERMINATING:
                return meta, None  # a thread here is terminating it as an overrun
            return meta, self._try_claim(jd, meta, "cancelled")

        # An overrun job is terminated and finalized (timeout, or done) here, so it
        # reads terminal and is returned as such, as it was before #531.
        found = self._locked(cwd, first)
        if not isinstance(found, tuple):
            return found
        meta, claim_fd = found
        if claim_fd is None:
            # Another claimant is stopping it: signal nothing, and wait for it with
            # every lock released, never for longer than its grace allows.
            give_up = time.monotonic() + self.terminate_grace_seconds + 1.0
            while time.monotonic() < give_up and (
                _worker_lock_held(jd / _TERMINATE_LOCK_NAME) is True or jd in _TERMINATING
            ):
                time.sleep(0.05)
            live = self._locked(cwd, read)
            return None if live is None else self._status_dict(*live)
        try:
            # Terminate with the lock released: the graceful-shutdown grace wait must
            # not block status/list/result calls for every workspace. Liveness stays
            # lock-aware throughout, so a worker that exits mid-grace (and a PID then
            # reused) is never signaled.
            _terminate_pid_tree(
                _meta_pid(meta),
                self.terminate_grace_seconds,
                is_alive=lambda m=meta: self._job_running(jd, m),
            )
            with _LOCK, self._record_lock(cwd):
                # Terminated as an overrun by this process: finalize it as that, never
                # as cancelled, as the cancel would have found it before #531.
                default: Literal["timeout", "cancelled"] = (
                    "timeout" if jd in _TERMINATING or jd in _OVERRAN else "cancelled"
                )
                # Re-validate: during the unlocked grace window the record may have
                # been consumed/evicted, finalized by another path, or the worker may
                # have finished on its own. Re-read fresh state and never clobber it.
                try:
                    meta = self._read_meta(jd)
                except MetaUnreadable as exc:
                    exc.signalled = True  # the worker was signalled before this read failed
                    raise
                if meta is None:
                    _OVERRAN.discard(jd)
                    return None  # consumed or expired while we waited
                # A stamped record is authoritative and its file is never read. An
                # unstamped one whose result cannot be read back propagates
                # ResultUnreadable (#280): nothing is written, the claim is released
                # below, and the next read finalizes it.
                env = self._read_envelope(jd) if not meta.get("terminal_status") else None
                if env is not None:
                    # The worker completed during the window: preserve its result rather
                    # than masking it, stamping its outcome if this done-transition is
                    # the record's first (setdefault: a prior _status_of finalization
                    # may already have recorded it).
                    meta["completed_epoch"] = meta.get("completed_epoch") or time.time()
                    meta.setdefault("result_ok", self._envelope_ok(env))
                    meta["terminal_status"] = "done"
                    meta.pop("terminating", None)
                    self._write_meta(jd, meta)
                    _OVERRAN.discard(jd)
                    return self._status_dict(jd, meta, "done")
                # Otherwise its stamp, or the claim's reason with the declared paths
                # cleaned up (the manifest re-read now, so a worktree declared after
                # cancellation began is not leaked).
                return self._status_dict(jd, meta, self._finish_terminated(jd, meta, default))
        finally:
            _release_claim(claim_fd)

    def list_jobs(self, cwd: str) -> list[dict]:
        return self._locked(cwd, lambda: self._list_jobs_locked(cwd))

    def _list_jobs_locked(self, cwd: str) -> list[dict]:
        self._reap_workspace(cwd)
        ws = self._ws_dir(cwd)
        summaries: list[dict] = []
        for jd in self._job_dirs(ws):
            meta = self._read_meta(jd)  # MetaUnreadable propagates, as for a result
            if meta is None:
                continue
            state = self._status_of(jd, meta)
            summaries.append(self._status_dict(jd, meta, state))
        summaries.sort(
            key=lambda s: (s["started_epoch"], s["job_id"]), reverse=True
        )  # newest first, id breaks ties (#249)
        return summaries

    def start_idempotent(
        self,
        cmd_factory: CmdFactory,
        cwd: str,
        *,
        kind: str,
        tool: str,
        key: str,
        arg_hash: str,
        extra: dict | None = None,
        write_spec: dict | None = None,
        stdin_text: str | None = None,
        lock_timeout: float | None = None,
    ) -> dict:
        """Deduplicated :meth:`start`. Reserves ``(tool, key)`` in the workspace index;
        on a first reservation it spawns the job and publishes the id, otherwise it
        classifies the existing entry. Returns one of:

        - ``{"kind": "created", "job_id", "started_at"}`` — a new paid job was spawned.
        - ``{"kind": "replay", "job_id"}`` — an existing job for this key+args; caller
          should await/return it (sync) or return its real handle (async).
        - ``{"kind": "conflict"}`` — same key, different effective arguments.
        - ``{"kind": "unavailable"}`` — a prior run for this key+args completed but its
          result is gone (consumed or evicted) within the dedup window.
        - ``{"kind": "in_progress"}`` — a concurrent reservation for this key is still
          being published, OR (with ``lock_timeout``) coordination was contended and the
          bounded lock acquisition timed out; retry either way.
        - ``{"kind": "io_error"}`` — reading the existing entry raised a transient
          ``OSError`` (the record may be intact); retry the same key rather than starting
          a new paid run under a fresh one.

        ``extra`` is opaque caller metadata persisted on the record like :meth:`start`'s
        ``extra``, merged with the store-owned ``idempotency_key_digest`` entry (the
        digest wins a key collision; the caller's dict is not mutated).

        The whole reserve→spawn→publish critical section runs under both the process
        ``_LOCK`` and the index's cross-process flock; cross-process exclusivity on the
        reservation itself comes from ``O_EXCL``.

        ``lock_timeout`` (seconds) bounds *lock acquisition only*, not the critical
        section. When set, both the process lock and the flock are acquired under a
        single shared deadline; if either cannot be taken in time — a sibling holds the
        flock, or a peer thread holds ``_LOCK`` — this returns ``in_progress`` rather than
        blocking a worker indefinitely (see #199). ``None`` keeps the original unbounded
        blocking acquisition. A non-finite or negative value is a ``ValueError``.
        """
        if lock_timeout is not None and (not math.isfinite(lock_timeout) or lock_timeout < 0):
            raise ValueError(f"lock_timeout must be finite and non-negative, got {lock_timeout!r}")
        deadline = None if lock_timeout is None else time.monotonic() + lock_timeout

        # An overrun job met by the index's resolve or by start's _make_room unwinds
        # this whole section, releasing the index flock too, and the reservation
        # with it (start's except below); the retry reserves afresh (#531).
        def attempt() -> dict:
            if deadline is None:
                _LOCK.acquire()
            elif not _LOCK.acquire(timeout=max(0.0, deadline - time.monotonic())):
                # A peer thread holds _LOCK (itself likely stuck on the flock); don't pile up
                # this worker behind it — degrade to a retryable in_progress.
                return {"kind": idempotency.IN_PROGRESS}
            try:
                index = self._idem_index(cwd)

                def resolve(job_id: str) -> idempotency.JobFacts | None:
                    return self._resolve_job_facts(cwd, job_id)

                # Hold the index's cross-process lock across sweep → reserve → spawn →
                # publish so a stale-entry reclaim (unlink + re-create) or a late publish
                # cannot interleave with another process and let two callers both win. The
                # record lock is taken next, under what is left of the same deadline, so the
                # resolve and start inside reuse it rather than wait unbounded (#237). Both
                # flocks are taken on `with` entry, so a bounded LockTimeout surfaces here;
                # nothing inside the body raises LockTimeout, so catching it is unambiguous.
                def lock_wait() -> float | None:
                    return None if deadline is None else max(0.0, deadline - time.monotonic())

                try:
                    with (
                        index.lock(timeout=lock_wait()),
                        self._record_lock(cwd, timeout=lock_wait()),
                    ):
                        index.sweep(resolve)  # bounded maintenance: drop entries past horizon
                        outcome = index.reserve(tool, key, arg_hash, resolve)
                        if outcome.kind != idempotency.WON:
                            if outcome.kind == idempotency.REPLAY:
                                return {"kind": "replay", "job_id": outcome.job_id}
                            return {
                                "kind": outcome.kind
                            }  # conflict|unavailable|in_progress|io_error
                        try:
                            job_id, started_at = self.start(
                                cmd_factory,
                                cwd,
                                kind=kind,
                                stdin_text=stdin_text,
                                # Caller extra is opaque record metadata, same as start()'s;
                                # the digest is protocol data the store owns, so it wins any
                                # key collision.
                                extra={
                                    **(extra or {}),
                                    "idempotency_key_digest": idempotency.key_digest(tool, key),
                                },
                                write_spec=write_spec,
                            )
                        except BaseException:
                            # Spawn failed after we won the reservation: drop it so a clean
                            # retry is a fresh miss rather than a phantom in-progress.
                            index.remove(outcome.path)
                            raise
                        try:
                            index.publish(outcome, job_id)
                        except Exception:
                            # The worker is already spawned and spend is committed, so a
                            # publish failure must NOT surface as "failed to start" — that is
                            # false, and a retry would spawn a second paid run. Hand back the
                            # real running handle (the caller uses it and won't retry) and
                            # leave the un-promoted reservation to fail closed (in_progress
                            # until the horizon) for any other caller reusing this key (#200).
                            # Never log the raw key; job_id is a random handle, safe to log.
                            logger.exception(
                                "idempotency publish failed after spawn; returning running job %s",
                                job_id,
                            )
                        return {"kind": "created", "job_id": job_id, "started_at": started_at}
                except idempotency.LockTimeout:
                    return {"kind": idempotency.IN_PROGRESS}
            finally:
                _LOCK.release()

        return self._terminate_overruns(attempt)
