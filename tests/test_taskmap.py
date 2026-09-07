"""The persisted task_id -> job_id map (ADR 0004)."""

from __future__ import annotations

import threading

from amicus.jobs.taskmap import TaskJobMap


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
