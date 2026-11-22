"""Write a delegate's diff to one new file the caller names (#556, ADR 0054).

The parent is resolved, then opened one component at a time from `/` without following a
symlink, and each opened directory is compared by identity with the job store root, so a
component swapped after resolution is refused rather than followed. The file is created
relative to that opened directory, never overwrites anything, and is never placed in or under
the job store. Nothing here logs, and no exception message carries the diff or the path
(AGENTS.md rule 18).

This module never unlinks, removes or renames anything. A name can be swapped between any
check and an unlink by name, so cleanup by name could delete a file this call did not
create. Instead, a file this call created and could not finish is emptied through the
descriptor the call still holds, which can only reach the inode it created, and is left
wherever its name now is; ``ExportFailed.left`` says what remains."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import stat
from pathlib import Path
from typing import Literal, NamedTuple

RefusalReason = Literal[
    "not_absolute",
    "not_a_file_name",
    "exists",
    "parent_missing",
    "inside_job_store",
    "not_writable",
]

_REFUSAL_TEXT: dict[str, str] = {
    "not_absolute": "the path is not absolute",
    "not_a_file_name": "the path does not end in a file name",
    "exists": "something already exists at the path",
    "parent_missing": "the path's parent directory does not exist",
    "inside_job_store": "the path lies in or under the job store",
    "not_writable": "the path's parent directory is not writable by the server",
}
# A directory is opened for search only where the platform can (O_PATH on Linux, O_SEARCH on
# macOS), so a search-only ancestor such as a 0711 /home does not refuse a writable
# destination; elsewhere read access is needed. fstat, and openat and lstat
# relative to such a handle, all work on both.
_SEARCH = getattr(os, "O_PATH", 0) or getattr(os, "O_SEARCH", 0) or os.O_RDONLY
_DIR = _SEARCH | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW_DIR = _DIR | os.O_NOFOLLOW


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


ExportLeft = Literal["nothing", "empty_file", "partial_file"]

_FAILED_TEXT: dict[ExportLeft, str] = {
    "nothing": "the export file could not be created",
    "empty_file": "the export file could not be completed and was emptied",
    "partial_file": "the export file could not be completed or emptied",
}


class ExportFailed(Exception):
    """The file could not be completed. ``left`` says what this call left behind: no file
    (``nothing``), the file it created, emptied, wherever its name now is (``empty_file``:
    the path may since hold another file or none), or a file it could not empty
    (``partial_file``). ``partial_file`` also covers a file whose final
    close failed, which may therefore be complete."""

    def __init__(self, errno_: int | None = None, *, left: ExportLeft = "nothing") -> None:
        super().__init__(_FAILED_TEXT[left] + (f" (errno {errno_})" if errno_ is not None else ""))
        self.errno = errno_
        self.left: ExportLeft = left


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in text)


def _identity(st: os.stat_result) -> tuple[int, int]:
    return (st.st_dev, st.st_ino)


def _store_identity(root: str) -> tuple[int, int] | None:
    try:
        return _identity(Path(root).stat())
    except OSError:
        return None


def _open_parent(resolved: str, store: tuple[int, int] | None) -> int:
    """An fd for ``resolved``, opened component by component without following a link, and
    refused when any directory on the way is the job store root."""
    fd = os.open("/", _DIR)
    try:
        for part in Path(resolved).parts[1:]:
            if store is not None and _identity(os.fstat(fd)) == store:
                raise ExportRefused("inside_job_store")
            try:
                nxt = os.open(part, _NOFOLLOW_DIR, dir_fd=fd)
            except FileNotFoundError:
                raise ExportRefused("parent_missing") from None
            except PermissionError:
                raise ExportRefused("not_writable") from None
            except OSError as exc:
                # A component that is a link was swapped in after resolution: refuse it.
                try:
                    is_link = stat.S_ISLNK(os.lstat(part, dir_fd=fd).st_mode)
                except OSError:
                    is_link = False
                if is_link or exc.errno == errno.ELOOP:
                    raise ExportRefused("not_writable") from None
                raise ExportRefused("parent_missing") from None
            os.close(fd)
            fd = nxt
        if store is not None and _identity(os.fstat(fd)) == store:
            raise ExportRefused("inside_job_store")
    except BaseException:
        os.close(fd)
        raise
    return fd


def write_diff_file(path: str, diff: str, *, job_store_root: str) -> DiffExport:
    """Create ``path`` new, mode 0o600, holding ``diff``'s UTF-8 bytes exactly."""
    if not Path(path).is_absolute():
        raise ExportRefused("not_absolute")
    parent, name = os.path.split(path)
    if name in ("", ".", "..") or _has_surrogate(name):
        raise ExportRefused("not_a_file_name")
    if _has_surrogate(parent):
        # No directory on the server's filesystem can be named by a lone surrogate.
        raise ExportRefused("parent_missing")
    try:
        data = diff.encode("utf-8")
    except UnicodeEncodeError:
        raise ExportFailed() from None
    resolved_parent = os.path.realpath(parent)
    store_root = os.path.realpath(job_store_root)
    if _inside(resolved_parent, store_root):
        raise ExportRefused("inside_job_store")
    parent_fd = _open_parent(resolved_parent, _store_identity(store_root))
    try:
        return _create(parent_fd, name, path, data)
    finally:
        os.close(parent_fd)


def _create(parent_fd: int, name: str, path: str, data: bytes) -> DiffExport:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    except FileExistsError:
        raise ExportRefused("exists") from None
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG:
            raise ExportRefused("not_a_file_name") from None
        if exc.errno in (errno.ELOOP, errno.EISDIR):
            raise ExportRefused("exists") from None
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            raise ExportRefused("not_writable") from None
        raise ExportFailed(exc.errno) from None
    try:
        created = _identity(os.fstat(fd))
        # The umask may have narrowed the mode, never widened it; pin it exactly.
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(errno.EIO, "short write")
            view = view[written:]
        os.fsync(fd)
        # The caller's path must still name this file: an unlink, a rename or a retargeted
        # parent link during the write would leave the export somewhere else. The
        # descriptor stays open through this check so a mismatch can still empty the file.
        try:
            same = _identity(os.lstat(path)) == created
        except OSError:
            same = False
        if not same:
            raise OSError(errno.ESTALE, "the path no longer names the export")
    except OSError as exc:
        left = _empty(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
        raise ExportFailed(exc.errno, left=left) from None
    except BaseException:
        with contextlib.suppress(BaseException):
            _empty(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
        raise
    try:
        os.close(fd)
    except OSError as exc:
        # Too late to empty it: the complete export stays at the path.
        raise ExportFailed(exc.errno, left="partial_file") from None
    return DiffExport(path=path, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def _empty(fd: int) -> ExportLeft:
    """Empty the file this call created through its own descriptor, never by name."""
    try:
        os.ftruncate(fd, 0)
        os.fsync(fd)
    except OSError:
        return "partial_file"
    return "empty_file"
