"""The diff export's file writer (#556, ADR 0054): one new file, never an overwrite."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import threading
from pathlib import Path

import pytest

from amicus.jobs import export
from amicus.jobs.export import DiffExport, ExportFailed, ExportRefused, write_diff_file

DIFF = "diff --git a/x.txt b/x.txt\n--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n-old\n+new\n"


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    return root


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    d = tmp_path / "scratch"
    d.mkdir()
    return d


def _refused(path: str, store_root: Path, diff: str = DIFF) -> str:
    with pytest.raises(ExportRefused) as info:
        write_diff_file(path, diff, job_store_root=str(store_root))
    return info.value.reason


def test_writes_a_new_file_with_exact_bytes_and_mode(scratch: Path, store_root: Path) -> None:
    target = scratch / "out.patch"
    result = write_diff_file(str(target), DIFF, job_store_root=str(store_root))
    data = DIFF.encode("utf-8")
    assert target.read_bytes() == data
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert result == DiffExport(
        path=str(target), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )


def test_bytes_are_exact_for_awkward_content(scratch: Path, store_root: Path) -> None:
    diff = (
        "diff --git a/café.txt b/café.txt\r\n--- a/café.txt\r\n"
        "+++ b/café.txt\r\n@@ -1 +1 @@\r\n-a  \r\n+b\t \n\\ No newline at end of file"
    )
    target = scratch / "awkward.patch"
    result = write_diff_file(str(target), diff, job_store_root=str(store_root))
    assert target.read_bytes() == diff.encode("utf-8")
    assert result.bytes == len(diff.encode("utf-8"))
    assert result.sha256 == hashlib.sha256(diff.encode("utf-8")).hexdigest()


def test_relative_path_is_refused(store_root: Path) -> None:
    assert _refused("out.patch", store_root) == "not_absolute"


def test_existing_file_is_refused_and_unchanged(scratch: Path, store_root: Path) -> None:
    target = scratch / "out.patch"
    target.write_bytes(b"keep")
    assert _refused(str(target), store_root) == "exists"
    assert target.read_bytes() == b"keep"


def test_symlinked_final_component_is_refused(scratch: Path, store_root: Path) -> None:
    victim = scratch / "victim"
    victim.write_bytes(b"keep")
    link = scratch / "link.patch"
    link.symlink_to(victim)
    assert _refused(str(link), store_root) == "exists"
    assert victim.read_bytes() == b"keep"
    dangling = scratch / "dangling.patch"
    dangling.symlink_to(scratch / "nowhere")
    assert _refused(str(dangling), store_root) == "exists"
    assert not (scratch / "nowhere").exists()


def test_missing_parent_is_refused_and_not_created(scratch: Path, store_root: Path) -> None:
    target = scratch / "missing" / "out.patch"
    assert _refused(str(target), store_root) == "parent_missing"
    assert not (scratch / "missing").exists()


def test_path_under_the_job_store_is_refused(store_root: Path) -> None:
    sub = store_root / "jobs"
    sub.mkdir()
    assert _refused(str(store_root / "out.patch"), store_root) == "inside_job_store"
    assert _refused(str(sub / "out.patch"), store_root) == "inside_job_store"
    assert list(sub.iterdir()) == []


def test_symlinked_parent_into_the_job_store_is_refused(scratch: Path, store_root: Path) -> None:
    link = scratch / "sneaky"
    link.symlink_to(store_root, target_is_directory=True)
    assert _refused(str(link / "out.patch"), store_root) == "inside_job_store"
    assert list(store_root.iterdir()) == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores modes")
def test_read_only_parent_is_refused(scratch: Path, store_root: Path) -> None:
    ro = scratch / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        assert _refused(str(ro / "out.patch"), store_root) == "not_writable"
    finally:
        ro.chmod(0o700)
    assert list(ro.iterdir()) == []


def test_scratch_directory_outside_any_repository_is_accepted(
    scratch: Path, store_root: Path
) -> None:
    target = scratch / "deep" / "out.patch"
    target.parent.mkdir()
    write_diff_file(str(target), DIFF, job_store_root=str(store_root))
    assert target.read_bytes() == DIFF.encode("utf-8")


def test_failed_write_removes_the_file(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write
    calls = {"n": 0}

    def failing(fd: int, data: bytes) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            return real_write(fd, bytes(data[:5]))
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(export.os, "write", failing)
    target = scratch / "out.patch"
    with pytest.raises(ExportFailed) as info:
        write_diff_file(str(target), DIFF, job_store_root=str(store_root))
    monkeypatch.undo()
    assert not target.exists()
    assert str(target) not in str(info.value)
    assert DIFF not in str(info.value)


def test_short_writes_complete(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write

    def short(fd: int, data: bytes) -> int:
        return real_write(fd, bytes(data[:3]))

    monkeypatch.setattr(export.os, "write", short)
    target = scratch / "out.patch"
    result = write_diff_file(str(target), DIFF, job_store_root=str(store_root))
    monkeypatch.undo()
    assert target.read_bytes() == DIFF.encode("utf-8")
    assert result.bytes == len(DIFF.encode("utf-8"))


def test_racing_writers_yield_one_file_and_one_refusal(scratch: Path, store_root: Path) -> None:
    target = scratch / "race.patch"
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def run(diff: str) -> None:
        barrier.wait()
        try:
            write_diff_file(str(target), diff, job_store_root=str(store_root))
            outcomes.append("written")
        except ExportRefused as exc:
            outcomes.append(exc.reason)

    threads = [threading.Thread(target=run, args=(d,)) for d in (DIFF, DIFF + "+more\n")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["exists", "written"]
    assert target.read_bytes() in (DIFF.encode(), (DIFF + "+more\n").encode())


def test_refusal_messages_carry_no_path(scratch: Path, store_root: Path) -> None:
    target = scratch / "out.patch"
    target.write_bytes(b"x")
    with pytest.raises(ExportRefused) as info:
        write_diff_file(str(target), DIFF, job_store_root=str(store_root))
    assert str(scratch) not in str(info.value)
