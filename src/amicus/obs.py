"""Diagnostic logging: stderr (plus an optional file), never stdout.

Every handler installed here renders under one policy: an exception's own text never
reaches the output. Not its ``str()``, not its ``__notes__``, not a rendered traceback —
only its type and the source locations it passed through.

The reason is AGENTS.md rule 18. An exception raised deep in a backend adapter can embed
the text that provoked it, and that text may be an ``INPUT_FIELDS`` prompt input, which
rule 18 forbids writing to a log. Nothing at the logging boundary can tell a prompt-bearing
message from an innocent one, and the SDK's ``exc_summary``/``redact_text`` cannot help:
they mask *secrets* and control characters, which is a different question. So the policy
withholds the whole category rather than guessing case by case, and it is enforced where
output is produced rather than at each call site, because the call sites include the SDK's
own: ``amicus.sdk.core.runtime`` logs ``("stdout capture failed: %s", exc, exc_info=True)``.
That reaches these handlers only in a process that has called ``configure``, and both
processes that run amicus code do: the server in ``server.main``, and the job worker as the
first thing ``_worker.main`` does, before even its argument checks (#128). The worker is the
one that matters most here, because its stdout and stderr are both the job's own
``stderr.log`` on disk.

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
# Third-party loggers whose records reach this process's stderr (issue #79). See
# `_own_dependency_loggers`.
DEPENDENCY_LOGGER_NAMES = ("fastmcp", "mcp")
FASTMCP_SERVER_LOGGER_NAME = "fastmcp.server.server"
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
# through types this module has never seen. Everything under `amicus` logs only these.
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


# Issue #79. FastMCP logs a rejected `tools/call` on `fastmcp.server.server` as
# ("Invalid arguments for tool %r: %s", name, detail), where `detail` is pydantic's error
# list and each error's `input` is the rejected value itself. For a missing required
# argument that `input` is the whole argument dict, so a valid prompt field sent beside the
# omission would be logged verbatim.
EXTRA_ARGUMENT_TYPES = frozenset({"unexpected_keyword_argument", "extra_forbidden"})
_MAX_ARGUMENT_ERRORS = 10
_DETAIL_WITHHELD = "<detail withheld>"
# pydantic's own error types are lowercase snake_case. A `PydanticCustomError` may carry any
# string at all as its type, so anything outside this shape is not echoed.
_ERROR_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}")
# The shape of a declared parameter or tool name.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _identifier(value: object) -> str:
    """``value`` when it is a plain ``str`` with an identifier's shape, else ``<unknown>``.

    ``type(...) is str`` rather than ``isinstance``: a ``str`` subclass can override the
    ``__format__`` that interpolation calls."""
    if type(value) is str and _IDENTIFIER.fullmatch(value):
        return value
    return _UNKNOWN


def _argument_error(err: object) -> str:
    """One pydantic error as ``type at field``."""
    if not isinstance(err, Mapping):
        return f"{_UNKNOWN} at {_UNKNOWN}"
    raw_type = err.get("type")
    error_type = raw_type if type(raw_type) is str and _ERROR_TYPE.fullmatch(raw_type) else None
    field = _UNKNOWN
    loc = err.get("loc")
    if (
        error_type is not None
        and error_type not in EXTRA_ARGUMENT_TYPES
        and type(loc) in (tuple, list)
        and loc
    ):
        field = _identifier(loc[0])
    return f"{error_type or _UNKNOWN} at {field}"


# FastMCP 4.0.4 redacts this record upstream (PrefectHQ/fastmcp#5106): where it logged
# pydantic's error list it now logs ``{"error_count": N, "error_types": [...]}``, built with
# ``include_input=False``/``include_context=False`` and every non-builtin type collapsed to
# ``custom_error``. That summary carries no ``loc``, so no field name survives to render.
# Both shapes are installable under this package's ``fastmcp>=4.0,<4.1`` floor, so both are
# read here; if that floor ever rises to ``>=4.0.4``, every list-shape path below becomes
# unreachable and goes in that same change: the list branch of ``summarize_argument_errors``,
# ``_argument_error`` and ``EXTRA_ARGUMENT_TYPES`` (used only by it), the list arm of
# ``_is_argument_record``, and the list-shape cases in ``tests/test_fastmcp_argument_log.py``.
# ``_ERROR_TYPE``, ``_identifier`` and ``_MAX_ARGUMENT_ERRORS`` stay: both shapes use them.
# The count and the types are re-checked rather than trusted, because this module echoes only
# shapes it has checked itself -- the same reason the list branch re-checks a ``type``
# pydantic also produced.
_SUMMARY_KEYS = ("error_count", "error_types")


def _summarized_argument_errors(detail: Mapping[object, object]) -> str:
    """FastMCP's own ``{"error_count", "error_types"}`` summary as ``N error(s): type, ...``."""
    count = detail.get("error_count")
    # `type(...) is int` rather than `isinstance`: `True` is an `int`, and would render as
    # `True error(s)`.
    if type(count) is not int or count < 0:
        return _DETAIL_WITHHELD
    error_types = detail.get("error_types")
    # Exactly a `list` or `tuple`: a bare `str` would otherwise render character by
    # character, and a subclass could override `__getitem__`.
    if type(error_types) not in (tuple, list):
        return _DETAIL_WITHHELD
    assert isinstance(error_types, tuple | list)  # narrowed by the check above
    shown = ", ".join(
        raw if type(raw) is str and _ERROR_TYPE.fullmatch(raw) else _UNKNOWN
        for raw in error_types[:_MAX_ARGUMENT_ERRORS]
    )
    more = ", ..." if len(error_types) > _MAX_ARGUMENT_ERRORS else ""
    # Upstream dedupes the types, so their number is not the error count and an empty list
    # is possible; the count is rendered from `error_count` alone.
    return f"{count} error(s): {shown or _UNKNOWN}{more}"


def summarize_argument_errors(detail: object) -> str:
    """pydantic's argument errors as ``N error(s): type at field, ...``, never a value the
    caller sent.

    Two things of each error survive: its ``type``, and the top-level component of its
    ``loc`` when the type says that component names a declared parameter. ``input`` is the
    rejected value, ``ctx`` can carry it, and ``msg`` can echo it through a validator's own
    text, so none of the three is read. The ``loc`` is withheld for an extra-key error,
    where it IS the key the client sent, and every component below the top level is
    dropped, because inside an open-keyed mapping a component can be a client's key under
    any error type.

    FastMCP's own summary mapping is rendered without a field, because it carries none.
    Anything else is withheld whole: FastMCP's remaining branch logs ``str(e)``, which
    embeds pydantic's own rendering, input values included."""
    if isinstance(detail, Mapping):
        if all(key in detail for key in _SUMMARY_KEYS):
            return _summarized_argument_errors(detail)
        return _DETAIL_WITHHELD
    if type(detail) is not list or not detail:
        return _DETAIL_WITHHELD
    shown = ", ".join(_argument_error(err) for err in detail[:_MAX_ARGUMENT_ERRORS])
    more = ", ..." if len(detail) > _MAX_ARGUMENT_ERRORS else ""
    return f"{len(detail)} error(s): {shown}{more}"


_INVALID_ARGUMENTS = "Invalid arguments for tool %s: %s"
_RECORD_WITHHELD = "<unaudited fastmcp.server.server record withheld>"
# The f-string records `fastmcp.server.server` writes around a failed call. A tool or prompt
# record is written only after the name was looked up, so an identifier-shaped name in it is
# a declared one and is kept. A resource URI is the client's own text, so it never is.
_NAMED_FAILURE = re.compile(
    rf"(?:Error calling tool|Error rendering prompt) '{_IDENTIFIER.pattern}'"
)
_RESOURCE_FAILURE = "Error reading resource "


def _is_argument_record(record: logging.LogRecord) -> bool:
    """FastMCP's argument-validation record, recognised by its text OR by its shape.

    The shape test is what keeps a reworded template in a later 4.0.x release from passing
    through: a two-argument record whose second argument is an error list, or FastMCP's own
    summary mapping, is rewritten whatever its message says."""
    args = record.args
    if type(args) is not tuple or len(args) != 2:
        return False
    msg = record.msg
    if type(msg) is str and msg.startswith("Invalid arguments for tool"):
        return True
    detail = args[1]
    if isinstance(detail, Mapping):
        return all(key in detail for key in _SUMMARY_KEYS)
    return type(detail) is list and bool(detail) and all(isinstance(e, Mapping) for e in detail)


def _rewrite_fastmcp_server_record(record: logging.LogRecord) -> None:
    if _is_argument_record(record):
        assert type(record.args) is tuple  # narrowed by `_is_argument_record`
        name, detail = record.args
        record.msg = _INVALID_ARGUMENTS
        record.args = (_identifier(name), summarize_argument_errors(detail))
        return
    msg = record.msg
    if type(msg) is str and not record.args:
        if _NAMED_FAILURE.fullmatch(msg):
            return
        if msg.startswith(_RESOURCE_FAILURE):
            record.msg = f"{_RESOURCE_FAILURE}{_UNKNOWN}"
            return
    # Anything this module has not audited keeps its level, logger name and exception (which
    # the formatter renders as type and frames) and loses its message.
    record.msg = _RECORD_WITHHELD
    record.args = None


class FastMCPServerRecordFilter(logging.Filter):
    """Rewrites every record `fastmcp.server.server` emits before any handler sees it.

    A LOGGER filter, installed on the logger the record starts on, rather than a handler
    filter: it runs once, ahead of every handler the record reaches — amicus's, any FastMCP
    reinstalls, or pytest's — and it is not removed when a handler is replaced. It never
    drops a record and never raises: a record it cannot rewrite is withheld."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            _rewrite_fastmcp_server_record(record)
        except Exception:
            record.msg = _RECORD_WITHHELD
            record.args = None
        return True


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


def _remove_handlers(target: logging.Logger) -> None:
    """Detach every handler on ``target``, closing only the ones this module installed.

    A handler another library attached, FastMCP's rich handlers or pytest's capture handler,
    is not amicus's to close: detaching it is enough to stop it writing here, and closing it
    would leave its owner holding a dead handler."""
    for handler in target.handlers[:]:
        target.removeHandler(handler)
        if isinstance(handler, PolicyStreamHandler | PolicyFileHandler):
            with contextlib.suppress(Exception):
                handler.close()


def _own_dependency_loggers(formatter: logging.Formatter, level: int) -> None:
    """Route `fastmcp` and `mcp` to stderr through the policy formatter, never below WARNING.

    Left alone, neither goes through the policy. `import fastmcp` installs FastMCP's own
    rich handlers on `fastmcp`, and `mcp` has none, so its WARNING records fall through to
    `logging.lastResort`; both render an exception's own text, which the policy withholds.
    Taking the handlers over closes that exception-text route for both libraries.

    What it does NOT do is make every dependency record safe. The policy passes a message
    string through unchanged, and both libraries build some messages with f-strings, so a
    value interpolated into one of those is written as it stands. Three limits follow from
    that. The floor is never below WARNING, whatever `AMICUS_LOG_LEVEL` says, because the
    `mcp` stdio runner logs a whole inbound frame at DEBUG. The floor is on each handler as
    well as each logger, because a logger filter can lower a record's level after the logger
    admitted it: FastMCP clamps `fastmcp.server.context.to_client`, which carries the text of
    every message a tool sends its client, to DEBUG. Neither logger is attached to
    `AMICUS_LOG_FILE`, so no record that today reaches only stderr is copied to disk. And
    the one record known to carry prompt text, FastMCP's argument-validation warning, is
    rewritten at its source by `FastMCPServerRecordFilter`.

    `fastmcp.settings.log_enabled` is switched off afterwards because it is the only switch
    FastMCP's `configure_logging` honours: that function removes every handler on
    `fastmcp` and installs its own, and `run(log_level=...)` reaches it through
    `temporary_log_level`."""
    import fastmcp  # noqa: PLC0415 - deferred; the job worker configures too (#128)

    for name in DEPENDENCY_LOGGER_NAMES:
        target = logging.getLogger(name)
        target.setLevel(level)
        target.propagate = False
        _remove_handlers(target)
        handler = PolicyStreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        target.addHandler(handler)
    fastmcp.settings.log_enabled = False
    server = logging.getLogger(FASTMCP_SERVER_LOGGER_NAME)
    if not any(isinstance(f, FastMCPServerRecordFilter) for f in server.filters):
        server.addFilter(FastMCPServerRecordFilter())


def configure(settings: Settings, *, force: bool = False) -> logging.Logger:
    """Configure the amicus logger, under which the SDK logs as ``amicus.sdk.*``, and take
    over the fastmcp and mcp ones for stderr (issue #79), once (idempotent unless ``force``)."""
    global _configured  # noqa: PLW0603
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if _configured and not force:
        return logger
    formatter = PolicyFormatter(_LOG_FORMAT)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    _remove_handlers(logger)
    stderr_handler = PolicyStreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    if settings.log_file:
        try:
            file_handler = PolicyFileHandler(settings.log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            logger.warning(
                "could not open AMICUS_LOG_FILE %r; logging to stderr only", settings.log_file
            )
    level = max(logging.getLevelNamesMapping()[settings.log_level], logging.WARNING)
    _own_dependency_loggers(formatter, level)
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
