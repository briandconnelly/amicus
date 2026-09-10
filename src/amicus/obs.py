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

Closing it takes more than suppressing tracebacks, because ``logging`` will render an
exception through several shapes that never look like one: as the message itself
(``log.error(exc)``), as an argument (``log.error("%s", exc)``), inside a mapping, or
inside a container whose ``repr`` renders each element's. So the policy is stated over
VALUES rather than over exceptions: an exception renders as its type, a ``_RENDERABLE``
scalar renders as itself, and anything else renders as its own type name. That is why the
rule is enforceable at all — it does not depend on recognizing every wrapper an exception
might arrive in.

What the policy is NOT: a guarantee that no prompt input can ever be logged. A call site
that interpolates a prompt field itself (``log.error("failed: %s", question)``) still
would, and nothing here would catch it — the formatter sees a string and cannot know where
it came from. Rule 18 binds the author for that case; ``tests/test_log_redaction.py``
asserts the one mechanical part of it that can be checked (no ``exc_summary`` in a logging
call). Nor does it establish PROVENANCE: the type and frame filters below check shape and
whether a file exists, not where a name came from, and each says so where it is defined.
What IS structurally closed is the exception-text family, which is what carried prompt
inputs into the log unnoticed (issue #39)."""

from __future__ import annotations

import contextlib
import copy
import logging
import re
import sys
import traceback
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from types import TracebackType

    from amicus.config import Settings

ROOT_LOGGER_NAME = "amicus"
LIBRARY_LOGGER_NAME = "pontonier"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False

# Bounds on a rendered chain. These cap OUTPUT and retained memory, and they are checked
# before every append, so `_MAX_LINES` is a hard ceiling rather than a target. What they
# do NOT bound is the walk itself: reaching a traceback's innermost frame — the raise
# site, the frame worth having — means visiting every frame above it, so `_frame_locations`
# is O(depth) in time while holding only `_MAX_FRAMES` of them. Depth is bounded in turn by
# the interpreter's own recursion limit, and 5,000 frames render in ~3ms. The `seen` set
# terminates a `__cause__`/`__context__` cycle; `_MAX_CHAIN` caps an acyclic but long one.
_MAX_CHAIN = 5
_MAX_FRAMES = 20
_MAX_GROUP_CHILDREN = 10
_MAX_LINES = 200

# Values that may be rendered into a message as themselves. Everything else is replaced by
# its type, because an arbitrary object's `__str__`/`__repr__` can reach an exception it
# holds (a list of exceptions renders each one's message) and no scrub can chase that
# through types this module has never seen. Both `amicus` and `pontonier` log only these.
_RENDERABLE = (str, int, float, bool, type(None))

# Stands in for any location or type name the policy declines to render.
_UNKNOWN = "<unknown>"

# Stands in for a whole message the policy left uninterpolatable.
_UNRENDERABLE = "<message not rendered>"

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


def safe_type_name(exc: BaseException) -> str:
    """The exception's type, qualified when it is not a builtin. Never its instance.

    Public so a call site that names an exception type in its own message uses the same
    filter the formatter would (`amicus.tools._guard`).

    The filter is on SHAPE, not provenance: `__qualname__` and `__module__` are ordinary
    writable attributes, so a class built at run time whose name happens to look like an
    identifier is rendered like any other. That is the residual assumption — that a type
    name comes from loaded code — and it is stated rather than claimed away."""
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


def _location(filename: str, lineno: int | None, name: str | None) -> str:
    """A frame's position, or ``<unknown>`` when it cannot be shown safely.

    Two filters, and neither establishes provenance — they are stated as what they are.
    The filename must resolve to a file that exists on disk, which rejects the run-time
    compiler's free-form filename (`exec(compile(src, "<anything>", ...))`) but does not
    prove the code was READ from that file. The function name must have the shape of a
    name from loaded code, which rejects arbitrary text but accepts an identifier-shaped
    name a generated code object was given. The residual assumption is that a frame's
    filename and function name come from code on disk rather than from caller input; no
    path in this repository builds a code object from a prompt.

    The source LINE is never rendered, and never read: `_frame_locations` walks raw frames
    instead of building a `StackSummary`, so `linecache` is not consulted at all."""
    safe = _safe_name(name)
    try:
        path = Path(filename or "")
        on_disk = path.is_absolute() and path.is_file()
    except (OSError, ValueError):  # a filename the OS will not even accept as a path
        on_disk = False
    if not on_disk or safe is None:
        return _UNKNOWN
    return f"{filename}:{lineno} in {safe}"


def _frame_locations(tb: TracebackType | None) -> list[str]:
    """The innermost `_MAX_FRAMES` locations of ``tb``, nearest the raise site last."""
    if tb is None:
        return []
    try:
        # A bounded deque rather than a list: a deep traceback is walked (there is no way
        # to reach its innermost frame otherwise) but only the tail is ever retained.
        kept: deque[tuple[str, int, str]] = deque(maxlen=_MAX_FRAMES)
        for frame, lineno in traceback.walk_tb(tb):
            code = frame.f_code
            kept.append((code.co_filename, lineno, code.co_name))
    except Exception:
        return [_UNKNOWN]
    return [_location(filename, lineno, name) for filename, lineno, name in kept]


def _render_exception(
    exc: BaseException, lines: list[str], seen: set[int], indent: str, depth: int
) -> None:
    """Append the type-and-location rendering of ``exc`` and its chain to ``lines``.

    Every append is guarded by the `_MAX_LINES` ceiling, so the cap holds across the
    recursion into an `ExceptionGroup`'s children as well as along a `__cause__` chain."""
    current: BaseException | None = exc
    while current is not None:
        if len(lines) >= _MAX_LINES:
            return
        if depth >= _MAX_CHAIN or id(current) in seen:
            lines.append(f"{indent}... truncated")
            return
        seen.add(id(current))
        lines.append(f"{indent}{safe_type_name(current)}")
        for location in _frame_locations(current.__traceback__):
            if len(lines) >= _MAX_LINES:
                return
            lines.append(f"{indent}  at {location}")
        children = getattr(current, "exceptions", None)
        if isinstance(current, BaseExceptionGroup) and children:
            # `.exceptions` is a tuple, so this slices without copying the whole group.
            for child in children[:_MAX_GROUP_CHILDREN]:
                if len(lines) >= _MAX_LINES:
                    return
                _render_exception(child, lines, seen, indent + "  ", depth + 1)
        # `__cause__` (an explicit `raise ... from ...`) wins; an implicit `__context__` is
        # rendered only when the raiser did not suppress it, mirroring the stdlib's own rule.
        following = current.__cause__
        if following is None and not current.__suppress_context__:
            following = current.__context__
        if following is None:
            return
        if len(lines) >= _MAX_LINES:
            return
        lines.append(f"{indent}caused by:")
        current, depth = following, depth + 1


def _safe_value(value: object) -> object:
    """One value, rendered under the policy.

    An exception becomes its type. A `_RENDERABLE` scalar passes through. Everything else
    becomes its own type name in angle brackets, because interpolating it would call its
    `__str__`/`__repr__` — and a container's repr renders each element's, which is how a
    plain `logger.error("%s", [exc])` would otherwise print the exception's message."""
    if isinstance(value, BaseException):
        return safe_type_name(value)
    if isinstance(value, _RENDERABLE):
        return value
    cls_name = _safe_name(getattr(type(value), "__name__", None))
    return f"<{cls_name or 'unknown'}>"


def _safe_args(
    args: tuple[object, ...] | Mapping[str, object] | None,
) -> tuple[object, ...] | Mapping[str, object] | None:
    """Every message argument, rendered under the policy.

    `Mapping` rather than `dict`: `logging` accepts any mapping as a single argument for
    `%(name)s` interpolation, and a `UserDict` is not a `dict`."""
    if args is None:
        return None
    if isinstance(args, Mapping):
        return {key: _safe_value(value) for key, value in args.items()}
    if isinstance(args, tuple):
        return tuple(_safe_value(arg) for arg in args)
    return (_safe_value(args),)


def _safe_msg(msg: object) -> object:
    """The message itself, which `logging` does not require to be a string: `.error(exc)`
    stores the exception as `record.msg`, and `getMessage` renders it with `str()`."""
    return msg if isinstance(msg, str) else _safe_value(msg)


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
        scrubbed.msg = _safe_msg(record.msg)
        scrubbed.args = _safe_args(record.args)
        scrubbed.exc_info = None
        scrubbed.exc_text = None
        scrubbed.stack_info = None
        try:
            text = super().format(scrubbed)
        except Exception:
            # `"%d" % "<list>"` raises. Falling through to `handleError` would drop the
            # record entirely and hand the raw message to the stdlib's own stderr dump, so
            # keep the line and lose only its body.
            scrubbed.msg = _UNRENDERABLE
            scrubbed.args = None
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
