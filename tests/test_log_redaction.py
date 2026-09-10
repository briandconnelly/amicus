"""AGENTS.md rule 18 at the log boundary: no exception's own text — its `str()`, its
notes, or a rendered traceback — reaches either handler `obs.configure` installs.

The guarantee is scoped and stated honestly. It covers the handlers this server owns, so
it holds for every call site that logs through them, amicus's own and `pontonier`'s alike
(`obs.configure` attaches handlers to both logger names and turns propagation off). It is
NOT a guarantee that no prompt input can ever be logged: a call site that interpolates a
prompt field itself (`log.error("failed: %s", question)`) still would, and nothing here
stops it. What is structurally closed is the exception-text family, which is what carried
prompt inputs into the log unnoticed (issue #39).

Every positive assertion below is paired with a mutation control that restores the old
behaviour and proves the assertion fails against it, so a test that could not catch the
leak cannot pass as though it had."""

from __future__ import annotations

import ast
import io
import logging
import sys
from collections import UserDict
from pathlib import Path

import pytest

from amicus import config, obs

# Assembled from fragments so the literal never appears on any source line in this file.
# A frame's source line is not rendered (see obs._exception_lines), and this construction
# is what keeps that assertion honest: were source lines restored, the marker still could
# not reach the log by way of this module's own text.
MARKER = "PROMPT" + "MARKER" + "39"

LIBRARY_LOGGER = "pontonier"
POLICY_HANDLERS = (obs.PolicyStreamHandler, obs.PolicyFileHandler)


def _message() -> str:
    return f"backend blew up while handling {MARKER}"


@pytest.fixture
def logs(tmp_path, clean_env, monkeypatch):
    """Configure obs onto a captured stderr and a real on-disk log file, and read both
    back. The file handler is a genuine `FileHandler` on `tmp_path`, not an in-memory
    stand-in: the disk path is the one AGENTS.md rule 18 names."""
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    log_file = tmp_path / "amicus.log"
    settings = config.settings({"AMICUS_LOG_FILE": str(log_file), "AMICUS_LOG_LEVEL": "DEBUG"})
    configured = obs.configure(settings, force=True)

    ours = tuple(configured.handlers)

    class Sink:
        logger = configured
        # Only the handlers `obs.configure` installed. Read from here, never from
        # `logger.handlers`: pytest's logging plugin appends its own capture handler to a
        # non-propagating logger so `caplog` still sees its records, and that handler
        # formats with the stdlib default — the very behaviour under test.
        handlers = ours

        def logger_for(self, name: str) -> logging.Logger:
            """A child logger with any FOREIGN handler removed.

            pytest's logging plugin attaches its own `LogCaptureHandler` to loggers under
            a `propagate = False` parent so `caplog` still sees them. That handler formats
            with the stdlib default, which is exactly the behaviour under test, so leaving
            it attached would let it — not amicus — produce the output being asserted on.
            The guarantee this module pins is scoped to the handlers `obs.configure`
            installs, so the assertions must see only those."""
            child = logging.getLogger(name)
            # The child AND the configured ancestor its records propagate to: pytest
            # appends its capture handler to whichever of them it reaches.
            for target in (child, configured, logging.getLogger(LIBRARY_LOGGER)):
                for handler in target.handlers[:]:
                    if not isinstance(handler, POLICY_HANDLERS):
                        target.removeHandler(handler)
            return child

        def read(self) -> tuple[str, str]:
            # Both logger trees: `obs.configure` gives each its own handler instances,
            # pointing at the same stderr object and the same file.
            for name in (obs.ROOT_LOGGER_NAME, LIBRARY_LOGGER):
                for handler in logging.getLogger(name).handlers:
                    if isinstance(handler, POLICY_HANDLERS):
                        handler.flush()
            return stderr.getvalue(), log_file.read_text(encoding="utf-8")

    yield Sink()
    # BOTH trees: `obs.configure` gives `pontonier` its own handler instances, and leaving
    # them attached leaves an open file handle on `tmp_path` and points any later
    # `pontonier` record at a `StringIO` belonging to a finished test.
    for name in (obs.ROOT_LOGGER_NAME, LIBRARY_LOGGER):
        target = logging.getLogger(name)
        for handler in target.handlers[:]:
            target.removeHandler(handler)
            handler.close()
    obs._configured = False


def _both(sink) -> list[str]:
    return list(sink.read())


# --- the guard's own path, end to end -------------------------------------------------


async def test_guarded_tool_exception_text_reaches_neither_handler(logs):
    """The mandated regression: a guarded tool raises an exception whose message carries a
    synthetic prompt marker. The marker must appear in neither handler, while the log still
    says which tool failed, with which exception type, at which source location."""
    from amicus.tools._guard import guard

    settings = config.settings({})

    @guard("probe", settings)
    async def probe(backend: str | None = None) -> dict:
        raise RuntimeError(_message())

    envelope = await probe(backend="codex")

    for text in _both(logs):
        assert MARKER not in text
    stderr, disk = logs.read()
    for text in (stderr, disk):
        assert "probe failed unexpectedly" in text
        assert "RuntimeError" in text
        assert "test_log_redaction.py" in text  # the frame location survives
        assert "in probe" in text
    # The client-facing envelope is unchanged by this fix.
    assert envelope.is_error is True
    err = envelope.structured_content["error"]
    assert err["code"] == "internal_error"
    assert err["message"] == "probe failed unexpectedly: RuntimeError"
    assert MARKER not in err["message"]


async def test_restoring_exc_summary_in_the_guard_message_fails_the_assertion(logs):
    """Mutation control for the message-side leak the issue did not name: with
    `exc_summary(exc)` interpolated the way the guard used to do it, the marker lands in
    both handlers. This is the instrument proving the test above can fail."""
    from pontonier.core.redaction import exc_summary

    try:
        raise RuntimeError(_message())
    except RuntimeError as exc:
        logs.logger_for("amicus.mutation").error(
            "%s failed unexpectedly: %s", "probe", exc_summary(exc)
        )
    for text in _both(logs):
        assert MARKER in text, "control did not reproduce the leak; the test proves nothing"


def test_restoring_the_plain_formatter_fails_the_traceback_assertion(logs, tmp_path):
    """Mutation control for the traceback leak the issue does name: swap the policy
    formatter back for the plain one and the rendered traceback carries the marker."""
    plain = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logs.handlers:
        handler.setFormatter(plain)
    try:
        raise RuntimeError(_message())
    except RuntimeError:
        logs.logger_for("amicus.mutation").exception("boom")
    for text in _both(logs):
        assert MARKER in text, "control did not reproduce the leak; the test proves nothing"


# --- the formatter's policy, case by case ---------------------------------------------


def test_an_exception_passed_as_a_message_argument_renders_as_its_type(logs):
    """`pontonier.core.runtime` logs `("...: %s", exc, exc_info=True)` through these very
    handlers, so this is a live path, not a hypothetical future mistake."""
    try:
        raise ValueError(_message())
    except ValueError as exc:
        logs.logger_for("pontonier.probe").error("stdout capture failed: %s", exc, exc_info=True)
    for text in _both(logs):
        assert MARKER not in text
        assert "stdout capture failed: ValueError" in text


def test_a_cached_exc_text_is_discarded_rather_than_appended(logs):
    """`logging.Formatter.format` appends `record.exc_text` verbatim whenever it is set,
    calling `formatException` only when it is empty — so an override of `formatException`
    alone is bypassed by a record that already carries rendered text."""
    record = logging.LogRecord("amicus.probe", logging.ERROR, __file__, 1, "boom", None, None)
    record.exc_text = f"Traceback (most recent call last):\nRuntimeError: {_message()}"
    logs.logger.handle(record)
    for text in _both(logs):
        assert MARKER not in text
        assert "boom" in text


def test_stack_info_is_suppressed(logs):
    record = logging.LogRecord("amicus.probe", logging.ERROR, __file__, 1, "boom", None, None)
    record.stack_info = f"Stack (most recent call last):\n  {_message()}"
    logs.logger.handle(record)
    for text in _both(logs):
        assert MARKER not in text


def test_exception_notes_never_render(logs):
    """`add_note` text is exception-owned text like any other and may be caller-derived."""
    try:
        exc = RuntimeError("outer")
        exc.add_note(_message())
        raise exc
    except RuntimeError:
        logs.logger_for("amicus.probe").exception("boom")
    for text in _both(logs):
        assert MARKER not in text
        assert "RuntimeError" in text


def test_a_chained_cause_renders_its_type_without_its_text(logs):
    try:
        try:
            raise ValueError(_message())
        except ValueError as inner:
            raise RuntimeError("outer failed") from inner
    except RuntimeError:
        logs.logger_for("amicus.probe").exception("boom")
    for text in _both(logs):
        assert MARKER not in text
        assert "outer failed" not in text  # the outer's own text is withheld too
        assert "RuntimeError" in text and "ValueError" in text


def test_an_exception_group_renders_child_types_without_child_text(logs):
    try:
        raise ExceptionGroup("group", [ValueError(_message()), KeyError(_message())])
    except ExceptionGroup:
        logs.logger_for("amicus.probe").exception("boom")
    for text in _both(logs):
        assert MARKER not in text
        assert "ExceptionGroup" in text
        assert "ValueError" in text and "KeyError" in text


def test_a_cyclic_chain_terminates(logs):
    """A `__cause__` cycle must not hang the formatter."""
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    logs.logger_for("amicus.probe").error("boom", exc_info=(type(first), first, None))
    for text in _both(logs):
        assert "RuntimeError" in text


def test_a_hostile_str_is_not_what_gets_rendered(logs):
    """What `str(exc)` would have produced never appears, however the exception spells it."""

    class Hostile(RuntimeError):
        def __str__(self) -> str:
            return _message()

    try:
        raise Hostile()
    except Hostile:
        logs.logger_for("amicus.probe").exception("boom")
    for text in _both(logs):
        assert MARKER not in text
        assert "Hostile" in text


def test_the_formatter_never_calls_exception_str(logs):
    """Stronger than "the text is absent": the policy must not reach for `str(exc)` at
    all, so an exception whose `__str__` raises cannot break logging either.

    Asserted against `PolicyFormatter` directly rather than through a logger, because
    pytest's own log capture renders captured records for its report and calls `__str__`
    itself — that call is pytest's, and routing through a logger would attribute it here."""
    calls: list[int] = []

    class Hostile(RuntimeError):
        def __str__(self) -> str:
            calls.append(1)
            raise AssertionError("__str__ must not be called")

    try:
        raise Hostile()
    except Hostile as exc:
        record = logging.LogRecord(
            "amicus.probe",
            logging.ERROR,
            __file__,
            1,
            "boom",
            None,
            (type(exc), exc, exc.__traceback__),
        )
    rendered = obs.PolicyFormatter(obs._LOG_FORMAT).format(record)
    assert calls == []
    assert "Hostile" in rendered


def test_a_frame_from_generated_code_is_placeheld(logs):
    """A frame whose file is not a real file on disk (exec'd or otherwise synthesized)
    has a filename the runtime, not the repository, chose. Its location is replaced
    rather than rendered."""
    namespace: dict = {}
    exec(compile("def boom():\n    raise RuntimeError('x')\n", f"<{MARKER}>", "exec"), namespace)
    try:
        namespace["boom"]()
    except RuntimeError:
        logs.logger_for("amicus.probe").exception("boom")
    for text in _both(logs):
        assert MARKER not in text
        assert "<unknown>" in text


def test_the_log_still_carries_enough_to_debug(logs):
    """Guards the other direction: emitting nothing at all would pass every assertion
    above, so pin what a live-server operator keeps."""
    try:
        raise RuntimeError(_message())
    except RuntimeError:
        logs.logger_for("amicus.probe").exception("tool %s failed", "amicus_consult")
    for text in _both(logs):
        assert "amicus.probe" in text  # logger name
        assert "ERROR" in text  # level
        assert "tool amicus_consult failed" in text  # the call site's own literal
        assert "RuntimeError" in text  # the exception type
        assert "test_log_redaction.py" in text  # file
        assert "in test_the_log_still_carries_enough_to_debug" in text  # function


# --- the handler-error fallback --------------------------------------------------------


def test_a_handler_error_does_not_dump_the_record(logs, monkeypatch):
    """`logging.Handler.handleError` writes `record.msg` and `record.args` straight to
    `sys.stderr`, around the formatter, whenever `emit` raises. Both handler classes must
    refuse that.

    Driven by handing the record to amicus's handlers directly. Going through a logger
    would also reach pytest's capture handler, whose own `handleError` re-raises."""
    record = logging.LogRecord(
        "amicus.probe", logging.ERROR, __file__, 1, "failed: %s", (MARKER,), None
    )
    # Re-point sys.stderr here, not in the fixture: pytest reinstalls its own capture
    # object at the start of the call phase, and `handleError` resolves `sys.stderr` when
    # it runs rather than holding the reference the handler was built with.
    fallback = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fallback)
    for handler in logs.handlers:
        monkeypatch.setattr(handler, "format", lambda _record: 1 / 0)
        handler.handle(record)
    stderr = fallback.getvalue()
    assert MARKER not in stderr
    assert "logging error" in stderr.lower()


def test_the_stdlib_handler_error_would_have_dumped_it(logs, monkeypatch):
    """Mutation control: the stdlib implementation these handlers override does print the
    record's message and arguments, so the assertion above is testing something real."""
    record = logging.LogRecord(
        "amicus.probe", logging.ERROR, __file__, 1, "failed: %s", (MARKER,), None
    )
    fallback = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fallback)
    try:
        raise RuntimeError("emit failed")
    except RuntimeError:
        logging.Handler.handleError(logs.handlers[0], record)
    assert MARKER in fallback.getvalue(), (
        "control did not reproduce the dump; the test proves nothing"
    )


# --- the call-site rule ----------------------------------------------------------------


LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})

# Resolved from this file, not from the working directory, so the scan cannot silently
# inspect nothing because pytest was invoked from elsewhere.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "amicus"


def _pre_stringified_type_name(node: ast.AST) -> bool:
    """`type(exc).__name__` — a class name read directly rather than through the filter.

    `__name__` is writable, so a forged one can carry a newline and forge a whole log
    line. `obs.safe_type_name` rejects that shape; a bare read hands the formatter an
    ordinary string, which the value policy passes through untouched."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
    )


def _exc_summary_in_logging_calls(root: Path) -> tuple[list[str], int]:
    """Return `(offenders, files_scanned)` for every `*.py` under ``root``.

    ONE implementation, used for both the repository scan and its planted control, so the
    control exercises the instrument the guarantee actually rests on rather than a second
    hand-written copy of it."""
    offenders: list[str] = []
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in LOG_METHODS:
                continue
            for inner in ast.walk(node):
                if _pre_stringified_type_name(inner) or (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name | ast.Attribute)
                    and (
                        getattr(inner.func, "id", None) == "exc_summary"
                        or getattr(inner.func, "attr", None) == "exc_summary"
                    )
                ):
                    offenders.append(f"{path}:{node.lineno}")
    return offenders, scanned


def test_no_logging_call_in_the_package_renders_an_exception_itself():
    """Two call-site shapes the formatter cannot catch, because both hand it an ordinary
    `str`, which the value policy passes through: `exc_summary(exc)`, which sanitizes
    secrets and control characters but not prompt inputs, and `type(exc).__name__`, which
    skips the shape filter. Both are asserted against the source instead."""
    offenders, scanned = _exc_summary_in_logging_calls(PACKAGE_ROOT)
    assert scanned > 20, f"the scan inspected {scanned} files; it is not reaching the package"
    assert offenders == [], f"a logging call renders an exception itself: {offenders}"


def test_the_call_site_scan_detects_a_planted_violation(tmp_path):
    """Mutation control for the scan above, run through the SAME function: a known-positive
    source tree must be flagged, so an empty result is evidence of compliance rather than of
    a broken instrument."""
    planted = tmp_path / "amicus" / "planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "import logging\nfrom pontonier.core.redaction import exc_summary\n"
        "def f(exc):\n    logging.getLogger('x').warning('boom: %s', exc_summary(exc))\n"
        "def g(exc):\n    logging.getLogger('x').warning('boom: %s', type(exc).__name__)\n",
        encoding="utf-8",
    )
    offenders, scanned = _exc_summary_in_logging_calls(tmp_path)
    assert scanned == 1
    assert [o.rsplit(":", 1)[1] for o in offenders] == ["4", "6"]


# --- shapes that carry an exception without looking like one ---------------------------


def test_an_exception_logged_as_the_message_itself_renders_as_its_type(logs):
    """`logging` does not require `msg` to be a string. `log.error(exc)` stores the
    exception on the record and `getMessage()` renders it with `str()`."""
    logs.logger_for("amicus.probe").error(ValueError(_message()))
    for text in _both(logs):
        assert MARKER not in text
        assert "ValueError" in text


def test_a_non_dict_mapping_argument_is_scrubbed(logs):
    """`logging` accepts any mapping for `%(name)s` interpolation, not only a `dict`."""
    logs.logger_for("amicus.probe").error(
        "capture failed: %(why)s", UserDict({"why": ValueError(_message())})
    )
    for text in _both(logs):
        assert MARKER not in text
        assert "capture failed: ValueError" in text


def test_an_exception_inside_a_container_argument_is_not_rendered(logs):
    """A container's `repr` renders each element's, so `[exc]` prints the message that
    `%s` on the exception alone would have printed."""
    logs.logger_for("amicus.probe").error("failures: %s", [ValueError(_message())])
    for text in _both(logs):
        assert MARKER not in text
        assert "failures: <list>" in text


def test_an_arbitrary_object_renders_as_its_type(logs):
    """The policy is stated over values, not over exceptions: anything that is not a
    renderable scalar is replaced, which is what makes the container case above closed
    rather than one more wrapper to enumerate."""

    class Holder:
        def __repr__(self) -> str:
            return _message()

    logs.logger_for("amicus.probe").error("held: %s", Holder())
    for text in _both(logs):
        assert MARKER not in text
        assert "held: <Holder>" in text


def test_a_message_that_cannot_be_interpolated_keeps_its_line(logs):
    """Replacing a value can break the caller's own format spec (`%d` against `<list>`).
    The line survives with its body replaced, rather than falling through to the stdlib's
    `handleError`, which would dump the raw message and arguments."""
    logs.logger_for("amicus.probe").error("count: %d", [ValueError(_message())])
    for text in _both(logs):
        assert MARKER not in text
        assert "message not rendered" in text
        assert "amicus.probe" in text


# --- the bounds actually bind -----------------------------------------------------------


def test_the_line_cap_is_a_ceiling_across_group_recursion():
    """A wide, deep ExceptionGroup renders through the recursive path, where a cap checked
    only at the top of the loop would be exceeded by each child's frame batch."""

    def build(depth: int, width: int) -> BaseException:
        if depth == 0:
            return ValueError("leaf")
        return ExceptionGroup(f"g{depth}", [build(depth - 1, width) for _ in range(width)])

    lines: list[str] = []
    obs._render_exception(build(3, 10), lines, set(), "", 0)
    assert len(lines) <= obs._MAX_LINES


def test_only_the_innermost_frames_are_retained():
    """A deep traceback is walked — there is no way to reach the raise site otherwise —
    but only `_MAX_FRAMES` of it is ever held or rendered."""

    def recurse(n: int) -> None:
        if n:
            recurse(n - 1)
            return
        raise RuntimeError("deep")

    try:
        recurse(200)
    except RuntimeError as exc:
        locations = obs._frame_locations(exc.__traceback__)
    assert len(locations) == obs._MAX_FRAMES
    # The tail is kept, so the raise site is the last entry.
    assert "in recurse" in locations[-1]


def test_a_forged_type_name_cannot_forge_a_log_line(logs):
    """`__name__` and `__qualname__` are writable. A name carrying a newline would, read
    directly, arrive as an ordinary string and append a whole fabricated record."""

    class Forged(RuntimeError):
        pass

    Forged.__name__ = f"RuntimeError\n2026-01-01 00:00:00 ERROR amicus: {MARKER}"
    Forged.__qualname__ = Forged.__name__
    assert obs.safe_type_name(Forged()) == "<unknown>"

    try:
        raise Forged()
    except Forged:
        logs.logger_for("amicus.probe").exception("boom")
    for text in _both(logs):
        assert MARKER not in text
        assert "<unknown>" in text


def test_the_unfiltered_read_would_have_forged_it(logs):
    """Mutation control: the same forged name read the way the call sites used to read it
    lands in both handlers, newline and all."""

    class Forged(RuntimeError):
        pass

    Forged.__name__ = f"RuntimeError\n2026-01-01 00:00:00 ERROR amicus: {MARKER}"
    logs.logger_for("amicus.probe").error("failed: %s", type(Forged()).__name__)
    for text in _both(logs):
        assert MARKER in text, "control did not reproduce the forgery; the test proves nothing"
