"""Write a delegate's diff to one new file the caller names (#556, ADR 0054).

The file is created anchored to its opened, resolved parent directory, never overwrites
anything, and is never placed in or under the job store. A file this call created and
could not finish is removed by this call. Nothing here logs, and no exception message
carries the diff or the path (AGENTS.md rule 18)."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
from pathlib import Path
from typing import Literal, NamedTuple

RefusalReason = Literal[
    "not_absolute", "exists", "parent_missing", "inside_job_store", "not_writable"
]

_REFUSAL_TEXT: dict[str, str] = {
    "not_absolute": "the path is not absolute",
    "exists": "something already exists at the path",
    "parent_missing": "the path's parent directory does not exist",
    "inside_job_store": "the path lies in or under the job store",
    "not_writable": "the path's parent directory is not writable by the server",
}


class DiffExport(NamedTuple):
    path: str
    bytes: int
    sha256: str  # hex digest of the bytes written


class ExportRefused(Exception):
    """The destination was refused; nothing was created."""

    reason: RefusalReason

    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(_REFUSAL_TEXT[reason])
        self.reason = reason


class ExportFailed(Exception):
    """The file was created and could not be completed; this call removed it."""

    def __init__(self, errno_: int | None = None) -> None:
        super().__init__(
            "the export file could not be completed and was removed"
            + (f" (errno {errno_})" if errno_ is not None else "")
        )
        self.errno = errno_


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def write_diff_file(path: str, diff: str, *, job_store_root: str) -> DiffExport:
    """Create ``path`` new, mode 0o600, holding ``diff``'s UTF-8 bytes exactly."""
    if not Path(path).is_absolute():
        raise ExportRefused("not_absolute")
    parent, name = os.path.split(path)
    if name in ("", ".", ".."):
        raise ExportRefused("exists")
    resolved_parent = os.path.realpath(parent)
    if _inside(resolved_parent, os.path.realpath(job_store_root)):
        raise ExportRefused("inside_job_store")
    try:
        parent_fd = os.open(resolved_parent, os.O_RDONLY | os.O_DIRECTORY)
    except (FileNotFoundError, NotADirectoryError):
        raise ExportRefused("parent_missing") from None
    except PermissionError:
        raise ExportRefused("not_writable") from None
    try:
        return _create(parent_fd, name, path, diff.encode("utf-8"))
    finally:
        os.close(parent_fd)


def _create(parent_fd: int, name: str, path: str, data: bytes) -> DiffExport:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    except FileExistsError:
        raise ExportRefused("exists") from None
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EISDIR):
            raise ExportRefused("exists") from None
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            raise ExportRefused("not_writable") from None
        raise ExportFailed(exc.errno) from None
    try:
        try:
            # The umask may have narrowed the mode, never widened it; pin it exactly.
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(errno.EIO, "short write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=parent_fd)
        raise ExportFailed(exc.errno) from None
    return DiffExport(path=path, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
