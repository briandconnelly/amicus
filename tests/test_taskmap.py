"""The persisted task_id -> job_id map (ADR 0004)."""

from __future__ import annotations

import threading

from amicus.jobs.taskmap import MAX_ENTRIES, TaskJobMap


def test_record_and_lookup_survive_a_reopen(tmp_path):
    path = tmp_path / "tasks.json"
    m = TaskJobMap(path)
    assert m.job_for("t1") is None and m.entries() == {}
    m.record("t1", "j1")
    m.record("t2", "j2")
    again = TaskJobMap(path)
    assert again.job_for("t1") == "j1" and again.task_for("j2") == "t2"
    assert again.task_for("nope") is None
    assert again.entries() == {"t1": "j1", "t2": "j2"}


def test_corrupt_or_missing_file_reads_as_empty(tmp_path):
    path = tmp_path / "nested" / "tasks.json"
    assert TaskJobMap(path).entries() == {}
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    assert TaskJobMap(path).entries() == {}
    TaskJobMap(path).record("t", "j")
    assert TaskJobMap(path).job_for("t") == "j"
    assert not list(path.parent.glob("*.tmp"))


def test_record_survives_concurrent_writers(tmp_path):
    """N threads calling record() on one TaskJobMap concurrently must all survive: a
    tasked call's task_id -> job_id mapping is this task's entire recovery guarantee,
    and losing an entry under concurrency means amicus_job_list(task_id=...) comes back
    empty for a job that is still running and still spending money."""
    task_map = TaskJobMap(tmp_path / "tasks.json")
    n = 200
    barrier = threading.Barrier(n)

    def _record(i: int) -> None:
        barrier.wait()
        task_map.record(f"task-{i}", f"job-{i}")

    threads = [threading.Thread(target=_record, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = task_map.entries()
    assert len(entries) == n
    assert entries == {f"task-{i}": f"job-{i}" for i in range(n)}


def test_map_does_not_grow_without_bound(tmp_path):
    """Recording well past MAX_ENTRIES must never leave the file holding more than
    MAX_ENTRIES mappings — the whole point of pruning is that the read-modify-write cost
    and the lock hold time around it stop growing on a long-running server."""
    task_map = TaskJobMap(tmp_path / "tasks.json")
    overflow = 50
    for i in range(MAX_ENTRIES + overflow):
        task_map.record(f"task-{i}", f"job-{i}")

    entries = task_map.entries()
    assert len(entries) == MAX_ENTRIES


def test_pruning_keeps_the_most_recently_recorded_entries(tmp_path):
    """Pruning must evict the OLDEST entries, never a recently-recorded one: a client
    that just started a paid job must still be able to recover it via
    amicus_job_list(task_id=...) even while the map is at capacity."""
    task_map = TaskJobMap(tmp_path / "tasks.json")
    overflow = 50
    total = MAX_ENTRIES + overflow
    for i in range(total):
        task_map.record(f"task-{i}", f"job-{i}")

    entries = task_map.entries()
    # The earliest-recorded entries are gone...
    for i in range(overflow):
        assert f"task-{i}" not in entries
    # ...but every entry recorded within the last MAX_ENTRIES record() calls survived,
    # proving pruning never evicts a mapping for a job that could still be live.
    for i in range(overflow, total):
        assert entries[f"task-{i}"] == f"job-{i}"
