"""An overrun job is terminated with the store's locks released (#531).

``_terminate_pid_tree`` waits up to the terminate grace for a worker to exit. Run under
the process-wide ``_LOCK`` (or a workspace's record flock), that wait blocks every
workspace this server serves, so every public entry point that finds an overrun job
terminates it unlocked and re-validates the record before finalizing it.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from amicus.jobs import idempotency
from amicus.jobs import store as job_store
from amicus.jobs.store import DiscardOutcome, JobStore, MetaUnreadable, ResultUnreadable

_SLEEP = "import time; time.sleep(30)"
_WAIT = 10.0  # generous bound on an event that should fire at once


@pytest.fixture(autouse=True)
def _fresh_process_sets():
    """``_TERMINATING`` and ``_OVERRAN`` are process-wide; a test that leaves a job
    pending on purpose must not leak it into the next."""
    yield
    job_store._TERMINATING.clear()
    job_store._OVERRAN.clear()


def _store(tmp_path, **kw) -> JobStore:
    opts = {"ttl_seconds": 3600, "max_seconds": 60, "max_count": 50}
    opts.update(kw)
    return JobStore(root=tmp_path / "jobs", **opts)


def _factory(code: str):
    return lambda _jd: [sys.executable, "-c", code]


def _overrun_job(store: JobStore, cwd: str) -> tuple[str, int]:
    job_id, _ = store.start(_factory(_SLEEP), cwd, kind="k")
    jd = store._job_dir(cwd, job_id)
    meta = store._read_meta(jd)
    meta["deadline_epoch"] = time.time() - 1  # already overran
    store._write_meta(jd, meta)
    return job_id, meta["pid"]


def _bounded(fn):
    """Run ``fn`` on its own thread and require it to finish within ``_WAIT``, so a call
    that blocks on the store's locks fails the test instead of hanging the suite."""
    out: list = []

    def run() -> None:
        try:
            out.append((True, fn()))
        except BaseException as exc:
            out.append((False, exc))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(_WAIT)
    assert not t.is_alive(), "store call blocked while a termination was in its grace"
    ok, value = out[0]
    if not ok:
        raise value
    return value


def _deny_result_read(monkeypatch, jd) -> None:
    """result.json is present but its open fails, as a permission blip would."""
    real_read_text = Path.read_text

    def denied(self, *args, **kwargs):
        if self == jd / "result.json":
            raise PermissionError("result read denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)


def _flock_free(path) -> bool:
    """Can a separate file descriptor take this flock right now? No lock dir yet means
    nobody holds it."""
    if not path.parent.is_dir():
        return True
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def _locks_free(store: JobStore, cwd: str) -> bool:
    """From another thread: are ``_LOCK``, the record flock and the index flock free?"""
    ws = store._ws_dir(cwd)
    if not (_flock_free(ws / ".records.lock") and _flock_free(ws / ".idem" / ".lock")):
        return False
    seen: list[bool] = []

    def probe() -> None:
        got = job_store._LOCK.acquire(timeout=0)
        if got:
            seen.append(not job_store._RECORD_LOCKS)
            job_store._LOCK.release()
        else:
            seen.append(False)

    t = threading.Thread(target=probe)
    t.start()
    t.join(_WAIT)
    return seen == [True]


def test_status_in_another_workspace_finishes_during_termination_grace(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd_a, cwd_b = str(tmp_path / "a"), str(tmp_path / "b")
    job_a, pid_a = _overrun_job(store, cwd_a)
    job_b, _ = store.start(_factory(_SLEEP), cwd_b, kind="k")
    entered, release = threading.Event(), threading.Event()

    def fake_terminate(pid, grace_seconds, **kwargs):
        entered.set()
        release.wait()  # inside the grace period until the test has looked, no timeout
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    results: dict[str, dict | None] = {}
    t_a = threading.Thread(target=lambda: results.__setitem__("a", store.status(cwd_a, job_a)))
    t_b = threading.Thread(target=lambda: results.__setitem__("b", store.status(cwd_b, job_b)))
    try:
        t_a.start()
        assert entered.wait(_WAIT)
        t_b.start()
        t_b.join(_WAIT)
        finished_during_grace = not t_b.is_alive()
    finally:
        release.set()
        t_a.join(_WAIT)
        t_b.join(_WAIT)
        store.cancel(cwd_b, job_b)
        job_store._kill_pid_tree(pid_a)
    assert finished_during_grace
    assert results["b"]["status"] == "running"
    assert results["a"]["status"] == "timeout"


def _start_idempotent(store, cwd):
    out = store.start_idempotent(
        _factory("pass"), cwd, kind="k", tool="t", key="k1", arg_hash=idempotency.arg_hash({})
    )
    assert out["kind"] == "created"


_ENTRY_POINTS = {
    "status": lambda s, c, j: s.status(c, j),
    "result_payload": lambda s, c, j: s.result_payload(c, j),
    "mark_delivered": lambda s, c, j: s.mark_delivered(c, j),
    "discard": lambda s, c, j: s.discard(c, j, expected="timeout"),
    "cancel": lambda s, c, j: s.cancel(c, j),
    "list_jobs": lambda s, c, j: s.list_jobs(c),
    "start": lambda s, c, j: s.start(_factory("pass"), c, kind="k"),
    "start_idempotent": lambda s, c, j: _start_idempotent(s, c),
}


@pytest.mark.parametrize("entry", sorted(_ENTRY_POINTS))
def test_every_entry_point_terminates_an_overrun_job_unlocked(tmp_path, monkeypatch, entry):
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    calls: list[bool] = []

    def fake_terminate(pid, grace_seconds, **kwargs):
        calls.append(_locks_free(store, cwd))
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    try:
        _ENTRY_POINTS[entry](store, cwd, job_id)
    finally:
        job_store._kill_pid_tree(pid)
    assert calls == [True]
    if entry != "discard":  # discard(expected="timeout") deletes the finalized record
        assert store._read_meta(store._job_dir(cwd, job_id))["terminal_status"] == "timeout"


def test_overrun_record_removed_during_grace_reads_missing(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)

    def fake_terminate(pid, grace_seconds, **kwargs):
        job_store._kill_pid_tree(pid)
        store._rmtree(jd)  # consumed / evicted by another process meanwhile

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    assert store.status(cwd, job_id) is None
    assert store.list_jobs(cwd) == []
    assert not job_store._OVERRAN  # confirmed gone: not left pending


def test_overrun_result_written_during_grace_is_done(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)

    def fake_terminate(pid, grace_seconds, **kwargs):
        (jd / "result.json").write_text('{"ok": true, "tool": "t"}')
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    st = store.status(cwd, job_id)
    assert st["status"] == "done" and st["result_ok"] is True


def test_overrun_finalized_elsewhere_during_grace_is_not_overwritten(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)

    def fake_terminate(pid, grace_seconds, **kwargs):
        job_store._kill_pid_tree(pid)
        meta = store._read_meta(jd)  # another server process stamped it meanwhile
        meta["terminal_status"] = "cancelled"
        meta["completed_epoch"] = time.time()
        store._write_meta(jd, meta)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    assert store.status(cwd, job_id)["status"] == "cancelled"


def test_concurrent_readers_of_one_overrun_job_terminate_it_once(tmp_path, monkeypatch):
    # While one thread terminates it, another reads the job as still running (never as
    # failed, never evictable), and only the terminating thread finalizes it.
    store = _store(tmp_path, max_count=1)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def fake_terminate(pid, grace_seconds, **kwargs):
        calls.append(pid)
        entered.set()
        release.wait()  # held until the test has made its checks, no timeout
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    first: list[dict | None] = []
    t = threading.Thread(target=lambda: first.append(store.status(cwd, job_id)))
    try:
        t.start()
        assert entered.wait(_WAIT)
        assert _bounded(lambda: store.status(cwd, job_id))["status"] == "running"
        assert [s["status"] for s in _bounded(lambda: store.list_jobs(cwd))] == ["running"]
        with pytest.raises(job_store.JobCapReached):  # held, not evicted, mid-termination
            _bounded(lambda: store.start(_factory("pass"), cwd, kind="k"))
        discarded = _bounded(lambda: store.discard(cwd, job_id, expected="failed"))
        assert discarded is DiscardOutcome.STATE_CHANGED
    finally:
        release.set()
        t.join(_WAIT)
        job_store._kill_pid_tree(pid)
    assert first[0]["status"] == "timeout"
    assert calls == [pid]
    assert store.status(cwd, job_id)["status"] == "timeout"


def test_make_room_terminates_then_evicts_an_overrun_job(tmp_path, monkeypatch):
    # At the cap, an overrun job is terminated unlocked, finalized as timeout, and then
    # evicted like any terminal error, so the start goes ahead.
    store = _store(tmp_path, max_count=1)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)

    def fake_terminate(pid, grace_seconds, **kwargs):
        assert _locks_free(store, cwd)
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    new_id, _ = store.start(_factory("pass"), cwd, kind="k")
    assert store.status(cwd, job_id) is None
    assert store.status(cwd, new_id) is not None


def test_termination_error_releases_the_job(tmp_path, monkeypatch):
    # A termination that raises must not leave the job marked as being terminated, or
    # this process would read it as running forever.
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)

    def boom(pid, grace_seconds, **kwargs):
        raise RuntimeError("signal failed")

    monkeypatch.setattr(job_store, "_terminate_pid_tree", boom)
    try:
        with pytest.raises(RuntimeError):
            store.status(cwd, job_id)
        assert not job_store._TERMINATING
        # The worker is still alive and overrun, so the next read terminates it again.
        monkeypatch.setattr(job_store, "_terminate_pid_tree", lambda *a, **k: None)
        assert store.status(cwd, job_id)["status"] == "timeout"
    finally:
        job_store._kill_pid_tree(pid)


def _declare(store: JobStore, cwd: str, job_id: str, root) -> object:
    wt = root / "wt-leak"
    wt.mkdir()
    (store._job_dir(cwd, job_id) / "cleanup.json").write_text(
        '{"paths": ["%s"]}' % wt  # noqa: UP031
    )
    return wt


def test_overrun_is_finalized_even_when_the_retry_gives_up(tmp_path, monkeypatch):
    # start_idempotent's retry runs under what is left of lock_timeout; here the index
    # flock is held when it retries, so it returns in_progress without revisiting the
    # job. The job is still stamped timeout, with its declared paths cleaned up.
    root = tmp_path / "wtroot"
    root.mkdir()
    store = _store(tmp_path, cleanup_root=root, cleanup_prefix="wt-")
    cwd = str(tmp_path / "w")
    job_id, pid = _overrun_job(store, cwd)
    wt = _declare(store, cwd, job_id, root)
    idx = store._ws_dir(cwd) / ".idem" / ".lock"
    blocker: list[int] = []

    def fake_terminate(pid, grace_seconds, **kwargs):
        job_store._kill_pid_tree(pid)
        fd = os.open(idx, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)  # a peer process takes the index meanwhile
        blocker.append(fd)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    try:
        out = store.start_idempotent(
            _factory("pass"),
            cwd,
            kind="k",
            tool="t",
            key="k1",
            arg_hash=idempotency.arg_hash({}),
            lock_timeout=0.0,
        )
    finally:
        for fd in blocker:
            os.close(fd)
        job_store._kill_pid_tree(pid)
    assert out == {"kind": idempotency.IN_PROGRESS}
    meta = store._read_meta(store._job_dir(cwd, job_id))
    assert meta["terminal_status"] == "timeout"
    assert not wt.exists()
    assert not job_store._TERMINATING


def test_cancel_during_overrun_termination_finalizes_timeout(tmp_path, monkeypatch):
    # A cancel that lands while another thread terminates the overrun job must not
    # stamp it cancelled: it timed out, as a cancel serialized behind it used to see.
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    entered, release = threading.Event(), threading.Event()
    real_pid = pid

    paused: list[int] = []

    def fake_terminate(pid, grace_seconds, **kwargs):
        if not paused:  # the overrun termination stays paused, no timeout
            paused.append(pid)
            entered.set()
            release.wait()
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    first: list[dict | None] = []
    t = threading.Thread(target=lambda: first.append(store.status(cwd, job_id)))
    try:
        t.start()
        assert entered.wait(_WAIT)
        cancelled = _bounded(lambda: store.cancel(cwd, job_id))
    finally:
        release.set()
        t.join(_WAIT)
        job_store._kill_pid_tree(real_pid)
    assert cancelled["status"] == "timeout"
    assert first[0]["status"] == "timeout"
    assert not job_store._TERMINATING


def _overrun_unreadable(store, cwd, monkeypatch, calls):
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)

    def fake_terminate(pid, grace_seconds, **kwargs):
        calls.append(pid)
        (jd / "result.json").write_text('{"ok": true, "tool": "t"}')
        job_store._kill_pid_tree(pid)
        _deny_result_read(monkeypatch, jd)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    return job_id, pid, jd


def _assert_unstamped_and_kept(store, jd):
    meta = store._read_meta(jd)
    assert meta is not None and meta.get("terminal_status") is None
    assert not job_store._TERMINATING
    assert jd in job_store._OVERRAN  # still pending: a later read finalizes it
    assert len(job_store._OVERRAN) == 1


def test_start_at_cap_counts_an_unreadable_overrun_as_held(tmp_path, monkeypatch):
    store = _store(tmp_path, max_count=1)
    cwd = str(tmp_path)
    calls: list[int] = []
    _job_id, pid, jd = _overrun_unreadable(store, cwd, monkeypatch, calls)
    try:
        with pytest.raises(job_store.JobCapReached):
            store.start(_factory("pass"), cwd, kind="k")
    finally:
        job_store._kill_pid_tree(pid)
    assert calls == [pid]
    _assert_unstamped_and_kept(store, jd)


def test_discard_of_an_unreadable_overrun_is_delete_failed(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path)
    calls: list[int] = []
    job_id, pid, jd = _overrun_unreadable(store, cwd, monkeypatch, calls)
    try:
        assert store.discard(cwd, job_id, expected="timeout") is DiscardOutcome.DELETE_FAILED
    finally:
        job_store._kill_pid_tree(pid)
    assert calls == [pid]
    _assert_unstamped_and_kept(store, jd)


def test_status_of_an_unreadable_overrun_raises_result_unreadable(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path)
    calls: list[int] = []
    job_id, pid, jd = _overrun_unreadable(store, cwd, monkeypatch, calls)
    try:
        with pytest.raises(job_store.ResultUnreadable):
            store.status(cwd, job_id)
    finally:
        job_store._kill_pid_tree(pid)
    assert calls == [pid]
    _assert_unstamped_and_kept(store, jd)


def test_a_worker_surviving_termination_is_finalized_not_retried(tmp_path, monkeypatch):
    # A termination that leaves the worker running and its result unreadable must not
    # loop: the retry finalizes from what it can read, as the in-lock path did.
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)
    calls: list[int] = []

    def fake_terminate(pid, grace_seconds, **kwargs):  # signals nothing
        calls.append(pid)
        (jd / "result.json").write_text('{"ok": true, "tool": "t"}')
        _deny_result_read(monkeypatch, jd)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    try:
        with pytest.raises(job_store.ResultUnreadable):
            _bounded(lambda: store.status(cwd, job_id))
    finally:
        job_store._kill_pid_tree(pid)
    assert calls == [pid]
    _assert_unstamped_and_kept(store, jd)


def _cleanup_store(tmp_path):
    root = tmp_path / "wtroot"
    root.mkdir()
    return _store(tmp_path, cleanup_root=root, cleanup_prefix="wt-"), root


def test_overrun_meta_unreadable_at_finalize_still_times_out(tmp_path, monkeypatch):
    # The finalize read of meta.json fails once (EIO): the record is not taken as gone,
    # nothing is stamped, and the next read finalizes it as timeout with its cleanup.
    store, root = _cleanup_store(tmp_path)
    cwd = str(tmp_path / "w")
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)
    wt = _declare(store, cwd, job_id, root)
    real_read_text = Path.read_text
    armed: list[bool] = []
    stamped_when_failed: list[object] = []
    calls: list[int] = []

    def flaky(self, *args, **kwargs):
        if armed and self == jd / "meta.json":
            armed.clear()
            stamped_when_failed.append(json.loads(real_read_text(self))["terminal_status"])
            raise OSError(errno.EIO, "meta read failed")
        return real_read_text(self, *args, **kwargs)

    def fake_terminate(pid, grace_seconds, **kwargs):
        calls.append(pid)
        job_store._kill_pid_tree(pid)  # stopped, no result
        armed.append(True)

    monkeypatch.setattr(Path, "read_text", flaky)
    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    try:
        # The retried body reads meta.json fine and finalizes the pending job itself.
        first = _bounded(lambda: store.status(cwd, job_id))
        st = _bounded(lambda: store.status(cwd, job_id))
    finally:
        job_store._kill_pid_tree(pid)
    assert stamped_when_failed == [None]
    assert first["status"] == "timeout"
    assert st["status"] == "timeout"
    assert not wt.exists()
    assert calls == [pid]
    assert not job_store._OVERRAN


def test_overrun_result_unreadable_then_absent_times_out_on_another_thread(tmp_path, monkeypatch):
    # result.json cannot be read at finalize (nor by the retried body), then reads back
    # absent: a later call on another thread finalizes timeout with cleanup, not failed.
    store, root = _cleanup_store(tmp_path)
    cwd = str(tmp_path / "w")
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)
    wt = _declare(store, cwd, job_id, root)
    calls: list[int] = []
    deny = pytest.MonkeyPatch()

    def fake_terminate(pid, grace_seconds, **kwargs):
        calls.append(pid)
        job_store._kill_pid_tree(pid)
        _deny_result_read(deny, jd)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    try:
        with pytest.raises(ResultUnreadable):
            _bounded(lambda: store.status(cwd, job_id))
        assert store._read_meta(jd)["terminal_status"] is None
    finally:
        deny.undo()
        job_store._kill_pid_tree(pid)
    st = _bounded(lambda: store.status(cwd, job_id))
    assert st["status"] == "timeout"
    assert not wt.exists()
    assert calls == [pid]
    assert not job_store._OVERRAN


def _deny_meta_read(mp, jd) -> None:
    real_read_text = Path.read_text

    def denied(self, *args, **kwargs):
        if self == jd / "meta.json":
            raise OSError(errno.EIO, "meta read failed")
        return real_read_text(self, *args, **kwargs)

    mp.setattr(Path, "read_text", denied)


@pytest.mark.parametrize("entry", ["status", "cancel"])
def test_overrun_meta_unreadable_until_later_stays_pending(tmp_path, monkeypatch, entry):
    # meta.json stays unreadable through the finalize read and the retried body: the call
    # reports MetaUnreadable (signalled, for a cancel: the overrun termination signalled
    # the worker), nothing is stamped, and once readable the job is a timeout with cleanup.
    store, root = _cleanup_store(tmp_path)
    cwd = str(tmp_path / "w")
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)
    wt = _declare(store, cwd, job_id, root)
    calls: list[int] = []
    deny = pytest.MonkeyPatch()

    def fake_terminate(pid, grace_seconds, **kwargs):
        calls.append(pid)
        job_store._kill_pid_tree(pid)
        _deny_meta_read(deny, jd)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    call = getattr(store, entry)
    try:
        with pytest.raises(MetaUnreadable) as info:
            _bounded(lambda: call(cwd, job_id))
    finally:
        deny.undo()
        job_store._kill_pid_tree(pid)
    assert info.value.signalled is (entry == "cancel")
    assert store._read_meta(jd)["terminal_status"] is None
    assert jd in job_store._OVERRAN
    st = _bounded(lambda: call(cwd, job_id))
    assert st["status"] == "timeout"
    assert not wt.exists()
    assert calls == [pid]
    assert not job_store._OVERRAN


def test_cancel_racing_an_overrun_marks_an_unreadable_meta_signalled(tmp_path, monkeypatch):
    # cancel's phase 2 meets a job another thread is terminating as an overrun, and its
    # finalize read of meta.json fails: the cancel did signal the worker, so it says so.
    store = _store(tmp_path)
    cwd = str(tmp_path)
    job_id, pid = _overrun_job(store, cwd)
    jd = store._job_dir(cwd, job_id)
    entered, release = threading.Event(), threading.Event()
    paused: list[int] = []
    deny = pytest.MonkeyPatch()

    def fake_terminate(pid, grace_seconds, **kwargs):
        if not paused:  # the overrun termination stays paused, no timeout
            paused.append(pid)
            entered.set()
            release.wait()
            return
        job_store._kill_pid_tree(pid)  # the cancel's own termination
        _deny_meta_read(deny, jd)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    t = threading.Thread(target=lambda: store.status(cwd, job_id), daemon=True)
    try:
        t.start()
        assert entered.wait(_WAIT)
        with pytest.raises(MetaUnreadable) as info:
            _bounded(lambda: store.cancel(cwd, job_id))
    finally:
        deny.undo()
        release.set()
        t.join(_WAIT)
        job_store._kill_pid_tree(pid)
    assert info.value.signalled is True


def _failing_meta_write(monkeypatch, store: JobStore) -> None:
    """The first meta.json write after a spawn fails, as a full disk would."""

    def boom(jd, meta):
        raise OSError(errno.ENOSPC, "no space left")

    monkeypatch.setattr(store, "_write_meta", boom)


@pytest.mark.parametrize("idempotent", [False, True])
def test_start_rollback_terminates_the_unrecorded_worker_unlocked(
    tmp_path, monkeypatch, idempotent
):
    """#536: a start whose meta.json write fails stops its worker with every lock
    released, so a status lookup in another workspace finishes inside the grace, and
    an idempotent retry is a fresh miss rather than in_progress."""
    store = _store(tmp_path)
    cwd_a, cwd_b = str(tmp_path / "a"), str(tmp_path / "b")
    job_b, _ = store.start(_factory(_SLEEP), cwd_b, kind="k")
    _failing_meta_write(monkeypatch, store)
    entered, release = threading.Event(), threading.Event()
    seen: dict[str, object] = {}

    def fake_terminate(pid, grace_seconds, **kwargs):
        seen["locks_free"] = _locks_free(store, cwd_a)
        seen["job_dirs"] = [d.name for d in store._job_dirs(store._ws_dir(cwd_a))]
        entered.set()
        release.wait()
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)

    def start_a():
        if idempotent:
            return store.start_idempotent(
                _factory(_SLEEP), cwd_a, kind="k", tool="t", key="key", arg_hash="h"
            )
        return store.start(_factory(_SLEEP), cwd_a, kind="k")

    errors: list[BaseException] = []

    def run_a():
        try:
            start_a()
        except BaseException as exc:
            errors.append(exc)

    t_a = threading.Thread(target=run_a)
    try:
        t_a.start()
        assert entered.wait(_WAIT)
        status_b = _bounded(lambda: store.status(cwd_b, job_b))
        if idempotent:
            # The reservation is gone while the first worker is still in its grace.
            monkeypatch.setattr(store, "_write_meta", JobStore._write_meta)
            seen["retried"] = _bounded(
                lambda: store.start_idempotent(
                    _factory("pass"), cwd_a, kind="k", tool="t", key="key", arg_hash="h"
                )
            )
    finally:
        release.set()
        t_a.join(_WAIT)
        monkeypatch.undo()
        store.cancel(cwd_b, job_b)
    assert seen["locks_free"] is True
    assert len(seen["job_dirs"]) == 1  # the dir is still there for the manifest read
    assert status_b["status"] == "running"
    assert len(errors) == 1 and isinstance(errors[0], OSError)
    if idempotent:
        assert seen["retried"]["kind"] == "created"
        assert len(store._job_dirs(store._ws_dir(cwd_a))) == 1  # only the retry's
    else:
        assert store._job_dirs(store._ws_dir(cwd_a)) == []


def test_start_rollback_cleans_declared_paths_before_dropping_the_dir(tmp_path, monkeypatch):
    """The manifest is read after the worker is stopped: a path it declares as it
    dies is still cleaned up, and the job dir goes after."""
    root = tmp_path / "wt"
    root.mkdir()
    store = _store(tmp_path, cleanup_root=root)
    cwd = str(tmp_path / "a")
    _failing_meta_write(monkeypatch, store)
    declared = root / "late"

    def fake_terminate(pid, grace_seconds, **kwargs):
        job_store._kill_pid_tree(pid)
        (jd,) = store._job_dirs(store._ws_dir(cwd))
        declared.mkdir()
        (jd / "cleanup.json").write_text(json.dumps({"paths": [str(declared)]}))

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    with pytest.raises(OSError):
        store.start(_factory(_SLEEP), cwd, kind="k")
    assert not declared.exists()
    assert store._job_dirs(store._ws_dir(cwd)) == []


def test_start_rollback_keeps_the_dir_when_cleanup_raises(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path / "a")
    _failing_meta_write(monkeypatch, store)

    def bad_manifest(jd):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    monkeypatch.setattr(store, "_read_cleanup_manifest", bad_manifest)
    with pytest.raises(OSError, match="no space"):
        store.start(_factory(_SLEEP), cwd, kind="k")
    assert len(store._job_dirs(store._ws_dir(cwd))) == 1


def test_start_rollback_runs_on_the_store_that_queued_it(tmp_path, monkeypatch):
    """A start nested in another store's section rolls back with its own settings."""
    root = tmp_path / "wt"
    root.mkdir()
    outer, inner = _store(tmp_path / "o"), _store(tmp_path / "i", cleanup_root=root)
    cwd = str(tmp_path / "a")
    _failing_meta_write(monkeypatch, inner)
    declared = root / "late"

    def fake_terminate(pid, grace_seconds, **kwargs):
        job_store._kill_pid_tree(pid)
        (jd,) = inner._job_dirs(inner._ws_dir(cwd))
        declared.mkdir()
        (jd / "cleanup.json").write_text(json.dumps({"paths": [str(declared)]}))

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)

    def body():
        inner.start(_factory(_SLEEP), cwd, kind="k")

    with pytest.raises(OSError):
        outer._locked(cwd, body)
    assert not declared.exists()


def test_start_rollback_withdraws_a_published_meta_under_the_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    cwd = str(tmp_path / "a")
    real_write = JobStore._write_meta

    def publish_then_fail(jd, meta):
        real_write(jd, meta)
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "_write_meta", publish_then_fail)
    seen: list[bool] = []

    def fake_terminate(pid, grace_seconds, **kwargs):
        (jd,) = store._job_dirs(store._ws_dir(cwd))
        seen.append((jd / "meta.json").exists())
        job_store._kill_pid_tree(pid)

    monkeypatch.setattr(job_store, "_terminate_pid_tree", fake_terminate)
    with pytest.raises(KeyboardInterrupt):
        store.start(_factory(_SLEEP), cwd, kind="k")
    assert seen == [False]
    assert store._job_dirs(store._ws_dir(cwd)) == []


def test_an_interrupted_rollback_does_not_skip_the_rest(tmp_path):
    """An interrupt in one queued rollback still runs the others, releases the
    section's published markers, and is re-raised."""
    store = _store(tmp_path)
    marker = tmp_path / "job"
    ran: list[str] = []

    def interrupted():
        ran.append("interrupted")
        raise KeyboardInterrupt

    def attempt():
        job_store._SECTION.rollbacks.extend([interrupted, lambda: ran.append("next")])
        job_store._SECTION.published.add(marker)
        job_store._TERMINATING.add(marker)
        raise OSError(errno.ENOSPC, "no space left")

    with pytest.raises(KeyboardInterrupt):
        store._terminate_overruns(attempt)
    assert ran == ["interrupted", "next"]
    assert marker not in job_store._TERMINATING
