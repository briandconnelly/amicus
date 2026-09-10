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
import traceback
from pathlib import Path

import pytest

from amicus import config, obs

# Assembled from fragments so the literal never appears on any source line in this file.
# A frame's source line is not rendered (see obs._exception_lines), and this construction
# is what keeps that assertion honest: were source lines restored, the marker still could
# not reach the log by way of this module's own text.
MARKER = "PROMPT" + "MARKER" + "39"


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
            for handler in child.handlers[:]:
                if handler not in ours:
                    child.removeHandler(handler)
            return child

        def read(self) -> tuple[str, str]:
            for handler in ours:
                handler.flush()
            return stderr.getvalue(), log_file.read_text(encoding="utf-8")

    yield Sink()
    logger = configured
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
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


def test_no_logging_call_in_the_package_passes_exc_summary():
    """`exc_summary` sanitizes secrets and control characters, not prompt inputs, so it is
    safe for a client-facing envelope and never for a log. The formatter cannot catch it —
    a call site that pre-stringifies hands the formatter an ordinary `str` — so the rule
    is asserted against the source instead."""
    offenders = []
    for path in sorted(Path("src/amicus").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in LOG_METHODS:
                continue
            for arg in ast.walk(node):
                if (
                    isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Name | ast.Attribute)
                    and (
                        getattr(arg.func, "id", None) == "exc_summary"
                        or getattr(arg.func, "attr", None) == "exc_summary"
                    )
                ):
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], f"exc_summary passed to a logging call: {offenders}"


def test_the_call_site_rule_detects_a_planted_violation(tmp_path):
    """Mutation control for the scan above: a known-positive source file must be flagged,
    so an empty result is evidence of compliance rather than of a broken instrument."""
    planted = tmp_path / "amicus" / "planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "import logging\nfrom pontonier.core.redaction import exc_summary\n"
        "def f(exc):\n    logging.getLogger('x').warning('boom: %s', exc_summary(exc))\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"), filename=str(planted))
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LOG_METHODS
        and any(
            isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "exc_summary"
            for inner in ast.walk(node)
        )
    ]
    assert len(hits) == 1


# --- the policy's own defensive paths --------------------------------------------------


def test_a_type_whose_name_is_not_name_shaped_is_replaced():
    """`_type_name` reads `__qualname__` and `__module__` off the class. Both are ordinary
    writable attributes, so a class built at run time can carry anything there."""

    class Forged(RuntimeError):
        pass

    Forged.__qualname__ = f"pwned {MARKER}"
    exc = Forged()
    assert obs._type_name(exc) == "<unknown>"

    Forged.__qualname__ = "Forged"
    Forged.__module__ = f"pwned {MARKER}"
    # An unusable module is dropped; the type's own name still reaches the log.
    assert obs._type_name(Forged()) == "Forged"


def test_a_frame_the_os_rejects_as_a_path_is_replaced():
    """A filename need not be a usable path at all; `Path.is_file()` raises on some."""
    frame = traceback.FrameSummary(f"/no/such\x00/{MARKER}", 1, "f")
    assert obs._location(frame) == "<unknown>"


def test_a_frame_whose_function_name_is_not_name_shaped_is_replaced():
    frame = traceback.FrameSummary(__file__, 1, f"pwned {MARKER}")
    assert obs._location(frame) == "<unknown>"


def test_an_unwalkable_traceback_yields_a_placeholder_rather_than_raising():
    """A broken traceback must not take the logger down with it."""
    assert obs._frame_locations(object()) == ["<unknown>"]  # type: ignore[arg-type]


def test_dict_style_message_arguments_are_scrubbed_too(logs):
    """`logging` accepts a single mapping as `args`, interpolated with `%(name)s`."""
    try:
        raise ValueError(_message())
    except ValueError as exc:
        logs.logger_for("amicus.probe").error("capture failed: %(why)s", {"why": exc})
    for text in _both(logs):
        assert MARKER not in text
        assert "capture failed: ValueError" in text
