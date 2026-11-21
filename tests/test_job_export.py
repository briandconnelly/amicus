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


# --- fix round 1 -------------------------------------------------------------------------


def test_a_parent_swapped_for_a_symlink_after_resolution_is_refused(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The resolution saw a plain path; by the open, a component is a link into the store.
    link = scratch / "swapped"
    link.symlink_to(store_root, target_is_directory=True)
    monkeypatch.setattr(export.os.path, "realpath", str)
    assert _refused(str(link / "out.patch"), store_root) == "not_writable"
    monkeypatch.undo()
    assert list(store_root.iterdir()) == []


def test_the_store_reached_through_dot_dot_is_refused_by_identity(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unresolved, the string is not under the store; the opened directory's identity is.
    monkeypatch.setattr(export.os.path, "realpath", str)
    path = str(scratch / ".." / store_root.name / "out.patch")
    assert _refused(path, store_root) == "inside_job_store"
    monkeypatch.undo()
    assert list(store_root.iterdir()) == []


def test_the_store_reached_through_aliases_is_refused(
    tmp_path: Path, scratch: Path, store_root: Path
) -> None:
    ancestor = scratch / "anc"
    ancestor.symlink_to(tmp_path, target_is_directory=True)
    assert _refused(str(ancestor / "state" / "out.patch"), store_root) == "inside_job_store"
    (store_root / "jobs").mkdir()
    dotted = str(store_root / "jobs" / ".." / "jobs" / "out.patch")
    assert _refused(dotted, store_root) == "inside_job_store"


def test_the_system_temp_dir_behind_a_symlink_is_accepted(store_root: Path) -> None:
    # On macOS /tmp and $TMPDIR resolve through /private; resolution happens first.
    import tempfile
    import uuid

    for base in {tempfile.gettempdir(), "/tmp"}:
        if not Path(base).is_dir():
            continue
        target = Path(base) / f"amicus-export-{uuid.uuid4().hex}.patch"
        try:
            write_diff_file(str(target), DIFF, job_store_root=str(store_root))
            assert target.read_bytes() == DIFF.encode()
        finally:
            target.unlink(missing_ok=True)


@pytest.mark.parametrize("suffix", ["", "/", "/.", "/.."])
def test_a_path_without_a_file_name_is_refused(
    scratch: Path, store_root: Path, suffix: str
) -> None:
    path = str(scratch / "dir") + suffix if suffix else str(scratch) + "/"
    (scratch / "dir").mkdir(exist_ok=True)
    assert _refused(path, store_root) == "not_a_file_name"


def test_an_existing_directory_is_exists(scratch: Path, store_root: Path) -> None:
    (scratch / "d").mkdir()
    assert _refused(str(scratch / "d"), store_root) == "exists"


def test_an_unencodable_diff_fails_and_leaves_nothing(scratch: Path, store_root: Path) -> None:
    target = scratch / "bad.patch"
    with pytest.raises(ExportFailed):
        write_diff_file(str(target), "+\ud800\n", job_store_root=str(store_root))
    assert not target.exists()


def test_a_lone_surrogate_in_the_file_name_is_not_a_file_name(
    scratch: Path, store_root: Path
) -> None:
    assert _refused(str(scratch) + "/\ud800.patch", store_root) == "not_a_file_name"


def test_a_lone_surrogate_in_the_parent_is_parent_missing(scratch: Path, store_root: Path) -> None:
    assert _refused(str(scratch) + "/\ud800/out.patch", store_root) == "parent_missing"


# --- fix round 3 -------------------------------------------------------------------------


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores modes")
@pytest.mark.parametrize("mode", [0o311, 0o111])
def test_a_search_only_ancestor_does_not_block_the_export(
    scratch: Path, store_root: Path, mode: int
) -> None:
    ancestor = scratch / "searchonly"
    (ancestor / "inner").mkdir(parents=True)
    ancestor.chmod(mode)
    try:
        target = ancestor / "inner" / "out.patch"
        write_diff_file(str(target), DIFF, job_store_root=str(store_root))
        assert target.read_bytes() == DIFF.encode()
    finally:
        ancestor.chmod(0o700)


def test_an_overlong_file_name_is_not_a_file_name(scratch: Path, store_root: Path) -> None:
    name = "n" * 256
    try:
        (scratch / name).touch()
    except OSError:
        pass
    else:
        pytest.skip("this filesystem accepts a 256-byte name")
    assert _refused(str(scratch / name), store_root) == "not_a_file_name"
    assert _refused(str(scratch / name / "out.patch"), store_root) == "parent_missing"


# --- a failed export is emptied through its descriptor, never unlinked --------------------


def _fail(target: Path, store_root: Path) -> ExportFailed:
    with pytest.raises(ExportFailed) as info:
        write_diff_file(str(target), DIFF, job_store_root=str(store_root))
    return info.value


def test_a_failed_write_leaves_an_empty_file(
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
    exc = _fail(scratch / "out.diff", store_root)
    monkeypatch.undo()
    assert calls["n"] == 2
    assert exc.left == "empty_file" and exc.errno == errno.ENOSPC
    assert (scratch / "out.diff").read_bytes() == b""
    assert DIFF not in str(exc)


def test_a_failed_export_never_unlinks_or_removes_anything(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removals: list[tuple[object, ...]] = []
    for fn in ("unlink", "remove", "rmdir"):
        monkeypatch.setattr(export.os, fn, lambda *a, **k: removals.append(a))

    def full(fd: int, data: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(export.os, "write", full)
    _fail(scratch / "out.diff", store_root)
    monkeypatch.undo()
    assert removals == []


def test_a_file_swapped_in_under_the_name_is_untouched(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = scratch / "out.diff"

    def swap_then_fail(fd: int, data: bytes) -> int:
        target.rename(scratch / "moved.diff")
        (scratch / "theirs.tmp").write_bytes(b"theirs")
        (scratch / "theirs.tmp").rename(target)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(export.os, "write", swap_then_fail)
    exc = _fail(target, store_root)
    monkeypatch.undo()
    assert target.read_bytes() == b"theirs"
    assert (scratch / "moved.diff").read_bytes() == b""
    assert exc.left == "empty_file"


def test_a_path_that_stops_naming_the_export_empties_it(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = scratch / "out.diff"
    real_fsync = os.fsync
    moved = {"done": False}

    def fsync_then_move(fd: int) -> None:
        real_fsync(fd)
        if not moved["done"]:
            moved["done"] = True
            target.rename(scratch / "moved.diff")

    monkeypatch.setattr(export.os, "fsync", fsync_then_move)
    exc = _fail(target, store_root)
    monkeypatch.undo()
    assert exc.errno == errno.ESTALE and exc.left == "empty_file"
    assert (scratch / "moved.diff").read_bytes() == b""
    assert not target.exists()


def test_a_parent_renamed_during_the_write_empties_the_export(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = scratch / "p"
    parent.mkdir()
    real_write = os.write

    def rename_then_write(fd: int, data: bytes) -> int:
        if parent.exists():
            parent.rename(scratch / "q")
        return real_write(fd, data)

    monkeypatch.setattr(export.os, "write", rename_then_write)
    exc = _fail(parent / "out.diff", store_root)
    monkeypatch.undo()
    assert exc.left == "empty_file"
    assert (scratch / "q" / "out.diff").read_bytes() == b""


def test_a_file_that_cannot_be_emptied_is_partial(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(fd: int, data: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    def no_truncate(fd: int, length: int) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(export.os, "write", full)
    monkeypatch.setattr(export.os, "ftruncate", no_truncate)
    exc = _fail(scratch / "out.diff", store_root)
    monkeypatch.undo()
    assert exc.left == "partial_file" and exc.errno == errno.ENOSPC


def _open_create_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = os.open

    def open_(path, flags, *args, **kwargs):
        if path == "out.diff" and flags & os.O_CREAT:
            raise OSError(errno.EIO, "I/O error")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(export.os, "open", open_)


def test_a_create_failure_that_is_not_a_refusal_leaves_nothing(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _open_create_fails(monkeypatch)
    exc = _fail(scratch / "out.diff", store_root)
    monkeypatch.undo()
    assert exc.left == "nothing" and exc.errno == errno.EIO
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("left", ["nothing", "empty_file", "partial_file"])
def test_no_failure_message_carries_the_path(
    scratch: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch, left: str
) -> None:
    def full(fd: int, data: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    if left == "nothing":
        _open_create_fails(monkeypatch)
    else:
        monkeypatch.setattr(export.os, "write", full)
    if left == "partial_file":
        monkeypatch.setattr(
            export.os, "ftruncate", lambda *a: (_ for _ in ()).throw(OSError(errno.EIO, "x"))
        )
    exc = _fail(scratch / "out.diff", store_root)
    monkeypatch.undo()
    assert exc.left == left
    assert str(scratch) not in str(exc) and "out.diff" not in str(exc)
    assert DIFF not in str(exc)
