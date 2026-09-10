"""Diagnostic logging: stderr (plus an optional file), never stdout.

Every handler installed here renders under one policy: an exception's own text never
reaches the output. Not its ``str()``, not its ``__notes__``, not a rendered traceback —
only its type and the source locations it passed through.

The reason is AGENTS.md rule 18. An exception raised deep in a backend adapter can embed
the text that provoked it, and that text may be an ``INPUT_FIELDS`` prompt input, which
rule 18 forbids writing to a log. Nothing at the logging boundary can tell a prompt-bearing
message from an innocent one, and ``pontonier``'s ``exc_summary``/``redact_text`` cannot
help: they mask *secrets* and control characters, which is a different question. So the
policy withholds the whole category rather than guessing case by case, and it is enforced
where output is produced rather than at each call site, because the call sites include
``pontonier``'s own — `runtime.py` logs ``("stdout capture failed: %s", exc,
exc_info=True)`` through these handlers, and this package does not own that line.

What the policy is NOT: a guarantee that no prompt input can ever be logged. A call site
that interpolates a prompt field itself (``log.error("failed: %s", question)``) still
would, and nothing here would catch it — the formatter sees a string and cannot know where
it came from. Rule 18 binds the author for that case; ``tests/test_log_redaction.py``
asserts the one mechanical part of it that can be checked (no ``exc_summary`` in a logging
call). What IS structurally closed is the exception-text family, which is what carried
prompt inputs into the log unnoticed (issue #39)."""

from __future__ import annotations

import contextlib
import copy
import logging
import re
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping
    from types import TracebackType

    from amicus.config import Settings

ROOT_LOGGER_NAME = "amicus"
LIBRARY_LOGGER_NAME = "pontonier"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False

# Bounds on a rendered chain. A traceback is diagnostic, not an audit trail, and an
# unbounded walk over attacker-shaped `__cause__` links is a denial-of-service surface on
# the error path. The `seen` set below already terminates a cycle; these cap the honest
# but enormous case (deep recursion, a wide ExceptionGroup) as well.
_MAX_CHAIN = 5
_MAX_FRAMES = 20
_MAX_GROUP_CHILDREN = 10
_MAX_LINES = 200

# Stands in for any location or type name the policy declines to render.
_UNKNOWN = "<unknown>"

# A name the runtime read out of loaded code: a module path, a qualname (which carries
# `<locals>` for a class defined in a function), or a code object's name. Anything outside
# this shape was not written in a source file the way these normally are, so it is
# replaced rather than echoed. Bounded so a synthesized name cannot pad the log either.
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.<>]{1,128}")

_HANDLER_ERROR_NOTICE = "--- amicus logging error: record suppressed (AGENTS.md rule 18) ---\n"


def _safe_name(name: str | None) -> str | None:
    """Return ``name`` when it has the shape of a name read out of loaded code."""
    if name and _SAFE_NAME.fullmatch(name):
        return name
    return None


def _type_name(exc: BaseException) -> str:
    """The exception's type, qualified when it is not a builtin. Never its instance."""
    cls = type(exc)
    qualname = getattr(cls, "__qualname__", None) or getattr(cls, "__name__", None)
    module = getattr(cls, "__module__", None)
    safe = _safe_name(qualname)
    if safe is None:
        return _UNKNOWN
    if module in (None, "builtins"):
        return safe
    prefix = _safe_name(module)
    return f"{prefix}.{safe}" if prefix else safe


def _location(frame: traceback.FrameSummary) -> str:
    """A frame's position, or ``<unknown>`` when its file is not one on disk.

    A frame's filename and function name are chosen by whoever compiled the code. For code
    imported from a file, that is the repository or an installed dependency, and echoing it
    is safe. For code compiled at run time the filename is whatever string the compiler was
    handed (`exec(compile(src, name, ...))`), so it is not source text and gets replaced.
    The source LINE is never rendered for either: `StackSummary.extract` is called with
    `lookup_lines=False` so it is not even read off disk."""
    filename = frame.filename or ""
    name = _safe_name(frame.name)
    try:
        path = Path(filename)
        on_disk = path.is_absolute() and path.is_file()
    except (OSError, ValueError):  # a filename the OS will not even accept as a path
        on_disk = False
    if not on_disk or name is None:
        return _UNKNOWN
    return f"{filename}:{frame.lineno} in {name}"


def _frame_locations(tb: TracebackType | None) -> list[str]:
    if tb is None:
        return []
    try:
        frames = traceback.StackSummary.extract(
            traceback.walk_tb(tb), lookup_lines=False, capture_locals=False
        )
    except Exception:
        return [_UNKNOWN]
    return [_location(frame) for frame in frames[-_MAX_FRAMES:]]


def _render_exception(
    exc: BaseException, lines: list[str], seen: set[int], indent: str, depth: int
) -> None:
    """Append the type-and-location rendering of ``exc`` and its chain to ``lines``."""
    current: BaseException | None = exc
    while current is not None:
        if len(lines) >= _MAX_LINES or depth >= _MAX_CHAIN or id(current) in seen:
            lines.append(f"{indent}... truncated")
            return
        seen.add(id(current))
        lines.append(f"{indent}{_type_name(current)}")
        lines.extend(f"{indent}  at {loc}" for loc in _frame_locations(current.__traceback__))
        children = getattr(current, "exceptions", None)
        if isinstance(current, BaseExceptionGroup) and children:
            for child in list(children)[:_MAX_GROUP_CHILDREN]:
                _render_exception(child, lines, seen, indent + "  ", depth + 1)
        # `__cause__` (an explicit `raise ... from ...`) wins; an implicit `__context__` is
        # rendered only when the raiser did not suppress it, mirroring the stdlib's own rule.
        following = current.__cause__
        if following is None and not current.__suppress_context__:
            following = current.__context__
        if following is None:
            return
        lines.append(f"{indent}caused by:")
        current, depth = following, depth + 1


def _safe_args(
    args: tuple[object, ...] | Mapping[str, object] | None,
) -> tuple[object, ...] | Mapping[str, object] | None:
    """Replace every exception passed as a message argument with its type name.

    `pontonier.core.runtime` logs `("stdout capture failed: %s", exc, exc_info=True)`, so
    the `%s` would render `str(exc)` into the message itself, where suppressing the
    traceback does not reach it."""
    if isinstance(args, dict):
        return {
            key: _type_name(value) if isinstance(value, BaseException) else value
            for key, value in args.items()
        }
    if isinstance(args, tuple):
        return tuple(_type_name(a) if isinstance(a, BaseException) else a for a in args)
    return args


class PolicyFormatter(logging.Formatter):
    """Renders a record under the module's exception-text policy.

    `format` is overridden rather than `formatException` alone, because
    `logging.Formatter.format` appends `record.exc_text` verbatim whenever it is set and
    calls `formatException` only when it is empty — so a record that arrives with rendered
    text already cached (a second handler formatting the same record, or a caller setting
    it directly) would bypass a `formatException`-only override entirely. `stack_info`
    likewise arrives as an already-rendered string, so it is dropped rather than parsed."""

    def format(self, record: logging.LogRecord) -> str:
        # A record is shared by every handler on the logger; mutating it here would leak
        # this formatter's edits into whatever formats it next.
        scrubbed = copy.copy(record)
        scrubbed.args = _safe_args(record.args)
        scrubbed.exc_info = None
        scrubbed.exc_text = None
        scrubbed.stack_info = None
        text = super().format(scrubbed)
        exc_info = record.exc_info
        if exc_info and isinstance(exc_info, tuple) and isinstance(exc_info[1], BaseException):
            lines: list[str] = []
            _render_exception(exc_info[1], lines, set(), "", 0)
            text = f"{text}\n" + "\n".join(lines)
        return text


def _report_handler_error() -> None:
    """`logging.Handler.handleError` writes `record.msg` and `record.args` straight to
    stderr, around the formatter, whenever `emit` raises. Say that something failed and
    nothing about what it was."""
    with contextlib.suppress(Exception):
        sys.stderr.write(_HANDLER_ERROR_NOTICE)


class PolicyStreamHandler(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        del record  # deliberately unread: the record is what must not be printed
        _report_handler_error()


class PolicyFileHandler(logging.FileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        del record  # deliberately unread: the record is what must not be printed
        _report_handler_error()


def configure(settings: Settings, *, force: bool = False) -> logging.Logger:
    """Configure the amicus and pontonier loggers once (idempotent unless ``force``)."""
    global _configured  # noqa: PLW0603
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if _configured and not force:
        return logger
    formatter = PolicyFormatter(_LOG_FORMAT)
    for name in (ROOT_LOGGER_NAME, LIBRARY_LOGGER_NAME):
        target = logging.getLogger(name)
        target.setLevel(settings.log_level)
        target.propagate = False
        for handler in target.handlers[:]:
            target.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        stderr_handler = PolicyStreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        target.addHandler(stderr_handler)
        if settings.log_file:
            try:
                file_handler = PolicyFileHandler(settings.log_file, encoding="utf-8")
                file_handler.setFormatter(formatter)
                target.addHandler(file_handler)
            except OSError:
                target.warning(
                    "could not open AMICUS_LOG_FILE %r; logging to stderr only", settings.log_file
                )
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
