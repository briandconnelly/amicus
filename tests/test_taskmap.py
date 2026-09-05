"""The persisted task_id -> job_id map (ADR 0004)."""

from __future__ import annotations

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
