"""AGENTS.md rule 18 against FastMCP's own argument-validation record (issue #79).

When a `tools/call` fails argument validation, FastMCP logs pydantic's error list on the
`fastmcp.server.server` logger, and each error's `input` is the rejected value itself. For a
missing required argument that `input` is the whole argument dict, so a VALID prompt field
sent beside the omission was logged verbatim. amicus's `obs` handlers never saw the record:
it went out through FastMCP's own handlers.

The leak lives in how the server process's handlers are wired, so an in-process capture can
pass while the real server still leaks. The end-to-end assertion therefore reads the stderr
of a real `amicus.server` stdio subprocess, and it carries positive controls — the rewritten
records must be on that same stderr — so a silent or unread stderr cannot pass. The
in-process tests below pin the pieces: the summary, the record filter, and the dependency
logger configuration `obs.configure` installs."""

from __future__ import annotations

import importlib
import io
import json
import logging
import subprocess
import sys
import tempfile
from typing import Any

import fastmcp
import pytest
from fastmcp.utilities.logging import configure_logging, temporary_log_level
from tests.conftest import spawned_server_env

from amicus import config, obs

# Assembled from fragments so the literal never appears on a source line a traceback could
# render.
MARKER = "PROMPT" + "MARKER" + "79"

_HANDSHAKE_ERA = "2025-11-25"
POLICY_HANDLERS = (obs.PolicyStreamHandler, obs.PolicyFileHandler)
WITHHELD_RECORD = "<unaudited fastmcp.server.server record withheld>"

# (label, tool, arguments). Every one leaked before the fix. A key is its own case because
# for an unknown key pydantic's `loc` IS the key the client sent, so dropping `input` alone
# would still have logged it.
LEAKING_CALLS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("unknown key", "amicus_backends", {"prompt": MARKER}),
    ("the prompt text as a key", "amicus_backends", {MARKER: 1}),
    ("wrong type", "amicus_consult", {"backend": "codex", "question": [MARKER]}),
    (
        "missing required beside a valid prompt field",
        "amicus_consult",
        {"backend": "codex", "extra_context": MARKER},
    ),
)

# What the rewritten records say for those calls: which tool, and why, and nothing sent.
EXPECTED_RECORDS = (
    "Invalid arguments for tool amicus_backends: "
    "1 error(s): unexpected_keyword_argument at <unknown>",
    "Invalid arguments for tool amicus_consult: 1 error(s): string_type at question",
    "Invalid arguments for tool amicus_consult: 1 error(s): missing_argument at question",
)


def _is_pytest_handler(handler: logging.Handler) -> bool:
    return type(handler).__module__.startswith("_pytest")


def _serve(calls: tuple[tuple[str, str, dict[str, Any]], ...], env: dict[str, str]):
    """Run one real stdio server session, send every call, and return (responses, stderr)."""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err:
        proc = subprocess.Popen(
            (sys.executable, "-m", "amicus.server"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            env=env,
            text=True,
            encoding="utf-8",
        )
        stdin, stdout = proc.stdin, proc.stdout
        assert stdin is not None
        assert stdout is not None
        try:

            def send(message: dict[str, Any]) -> None:
                stdin.write(json.dumps(message) + "\n")
                stdin.flush()

            send(
                {
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _HANDSHAKE_ERA,
                        "capabilities": {},
                        "clientInfo": {"name": "amicus-test-79", "version": "0"},
                    },
                }
            )
            stdout.readline()
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            responses = []
            for request_id, (_, tool, arguments) in enumerate(calls, start=1):
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments},
                    }
                )
                responses.append(json.loads(stdout.readline()))
            stdin.close()
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        err.seek(0)
        return responses, err.read()


@pytest.mark.parametrize("level", ["WARNING", "DEBUG"])
def test_no_rejected_argument_reaches_the_real_servers_stderr_or_log_file(tmp_path, level):
    log_file = tmp_path / "amicus.log"
    env = spawned_server_env() | {"AMICUS_LOG_LEVEL": level, "AMICUS_LOG_FILE": str(log_file)}
    responses, stderr = _serve(LEAKING_CALLS, env)
    for (label, _, _), response in zip(LEAKING_CALLS, responses, strict=True):
        result = response["result"]
        assert result["isError"] is True, label
        assert result["structuredContent"]["error"]["code"] == "invalid_arguments", label
    on_disk = log_file.read_text(encoding="utf-8")
    assert MARKER not in stderr
    assert MARKER not in on_disk
    # Positive controls: the rewritten records ARE on the stderr read above.
    for record in EXPECTED_RECORDS:
        assert record in stderr
    # FastMCP's records are never copied to the file (`obs._own_dependency_loggers`)...
    assert "Invalid arguments" not in on_disk
    if level == "DEBUG":
        # ...and the file read above is the one amicus writes: its own start line is there.
        assert "starting (stdio)" in on_disk


# --- the summary that replaces pydantic's error list -----------------------------------


def _error(type_: str, loc: object, input_: object = MARKER) -> dict[str, Any]:
    """One pydantic error dict as FastMCP logs it, with the marker in every field the
    summary must not read."""
    return {
        "type": type_,
        "loc": loc,
        "msg": f"Value error, {MARKER}",
        "input": input_,
        "ctx": {"error": MARKER},
    }


def test_the_summary_keeps_each_errors_type_and_declared_field():
    summary = obs.summarize_argument_errors(
        [
            _error("missing_argument", ("question",), {"extra_context": MARKER}),
            _error("string_type", ("question",), [MARKER]),
        ]
    )
    assert summary == "2 error(s): missing_argument at question, string_type at question"


@pytest.mark.parametrize("type_", ["unexpected_keyword_argument", "extra_forbidden"])
def test_the_summary_withholds_a_client_chosen_key(type_):
    summary = obs.summarize_argument_errors([_error(type_, (MARKER,))])
    assert summary == f"1 error(s): {type_} at <unknown>"


def test_the_summary_renders_only_the_top_level_field():
    # Below the top level a `loc` component can be a key the client chose even for an error
    # type that is not an extra-key type (an open-keyed mapping parameter).
    summary = obs.summarize_argument_errors([_error("int_type", ("backend_options", MARKER, 0))])
    assert summary == "1 error(s): int_type at backend_options"


class _HostileStr(str):
    def __format__(self, spec: str) -> str:
        return MARKER


@pytest.mark.parametrize(
    ("type_", "loc", "expected"),
    [
        ("value error\nforged", ("question",), "<unknown> at <unknown>"),
        ("x" * 65, ("question",), "<unknown> at <unknown>"),
        ("Value_Error", ("question",), "<unknown> at <unknown>"),
        ("string_type", ("two words",), "string_type at <unknown>"),
        ("string_type", (0,), "string_type at <unknown>"),
        ("string_type", (_HostileStr("question"),), "string_type at <unknown>"),
        ("string_type", "question", "string_type at <unknown>"),
    ],
)
def test_the_summary_echoes_nothing_outside_its_shapes(type_, loc, expected):
    assert obs.summarize_argument_errors([_error(type_, loc)]) == f"1 error(s): {expected}"


def test_the_summary_is_capped_and_says_how_many_there_were():
    summary = obs.summarize_argument_errors(
        [_error("missing_argument", (f"p{i}",)) for i in range(25)]
    )
    assert summary.startswith("25 error(s): missing_argument at p0, ")
    assert summary.endswith("missing_argument at p9, ...")
    assert summary.count(" at ") == 10


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        # FastMCP's other branch logs `str(e)`, which embeds pydantic's own rendering.
        (f"1 validation error input_value={MARKER!r}", "<detail withheld>"),
        ({"loc": MARKER}, "<detail withheld>"),
        (None, "<detail withheld>"),
        ([], "<detail withheld>"),
        ([MARKER], "1 error(s): <unknown> at <unknown>"),
    ],
)
def test_the_summary_withholds_a_detail_it_cannot_parse(detail, expected):
    assert obs.summarize_argument_errors(detail) == expected


# --- the record filter on fastmcp.server.server ----------------------------------------


def _record(msg: str, args: tuple[object, ...] | None = None) -> logging.LogRecord:
    return logging.LogRecord(
        obs.FASTMCP_SERVER_LOGGER_NAME, logging.WARNING, __file__, 1, msg, args, None
    )


def _filtered(record: logging.LogRecord) -> str:
    assert obs.FastMCPServerRecordFilter().filter(record) is True  # it never drops a record
    return record.getMessage()


def test_the_validation_record_is_rewritten_at_its_source():
    detail = [_error("missing_argument", ("question",), {"extra_context": MARKER})]
    text = _filtered(_record("Invalid arguments for tool %r: %s", ("amicus_consult", detail)))
    assert text == EXPECTED_RECORDS[2]


def test_a_reworded_template_is_still_recognised_by_its_shape():
    detail = [_error("string_type", ("question",))]
    text = _filtered(_record("Tool %r rejected its arguments (%s)", ("amicus_consult", detail)))
    assert text == EXPECTED_RECORDS[1]


def test_the_str_detail_branch_is_withheld():
    detail = f"1 validation error input_value={MARKER!r}"
    text = _filtered(_record("Invalid arguments for tool %r: %s", ("amicus_consult", detail)))
    assert text == "Invalid arguments for tool amicus_consult: <detail withheld>"


def test_a_tool_name_outside_the_identifier_shape_is_not_echoed():
    text = _filtered(_record("Invalid arguments for tool %r: %s", (f"x\n{MARKER}", [])))
    assert text == "Invalid arguments for tool <unknown>: <detail withheld>"


@pytest.mark.parametrize(
    "msg", ["Error calling tool 'amicus_consult'", "Error rendering prompt 'triage'"]
)
def test_a_failure_naming_a_declared_tool_or_prompt_keeps_its_name(msg):
    assert _filtered(_record(msg)) == msg


def test_a_resource_failure_never_echoes_the_uri():
    text = _filtered(_record(f"Error reading resource 'amicus://{MARKER}'"))
    assert text == "Error reading resource <unknown>"


@pytest.mark.parametrize(
    "record",
    [
        _record(f"Error calling tool '{MARKER} x'"),
        _record("something new: %s", (MARKER,)),
        _record(f"an f-string carrying {MARKER}"),
    ],
)
def test_an_unaudited_record_keeps_its_level_and_logger_but_not_its_message(record):
    assert _filtered(record) == WITHHELD_RECORD
    assert record.levelno == logging.WARNING
    assert record.name == obs.FASTMCP_SERVER_LOGGER_NAME


def test_the_filter_withholds_rather_than_raises(monkeypatch):
    def boom(detail: object) -> str:
        raise RuntimeError(MARKER)

    monkeypatch.setattr(obs, "summarize_argument_errors", boom)
    detail = [_error("missing_argument", ("question",))]
    text = _filtered(_record("Invalid arguments for tool %r: %s", ("amicus_consult", detail)))
    assert text == WITHHELD_RECORD


# --- the dependency loggers obs.configure takes over -----------------------------------


@pytest.fixture
def configured(tmp_path, clean_env, monkeypatch):
    """`obs.configure` at DEBUG with a real log file and stderr captured. The autouse
    `_restore_dependency_logging` fixture in conftest puts the dependency loggers back."""
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    log_file = tmp_path / "amicus.log"
    settings = config.settings({"AMICUS_LOG_FILE": str(log_file), "AMICUS_LOG_LEVEL": "DEBUG"})
    obs.configure(settings, force=True)

    class Sink:
        def read(self) -> tuple[str, str]:
            for name in (
                *obs.DEPENDENCY_LOGGER_NAMES,
                obs.ROOT_LOGGER_NAME,
                obs.LIBRARY_LOGGER_NAME,
            ):
                for handler in logging.getLogger(name).handlers:
                    if isinstance(handler, POLICY_HANDLERS):
                        handler.flush()
            return stderr.getvalue(), log_file.read_text(encoding="utf-8")

    yield Sink()
    for name in (obs.ROOT_LOGGER_NAME, obs.LIBRARY_LOGGER_NAME):
        target = logging.getLogger(name)
        for handler in target.handlers[:]:
            target.removeHandler(handler)
            handler.close()
    obs._configured = False


def _ours(name: str) -> list[logging.Handler]:
    return [h for h in logging.getLogger(name).handlers if not _is_pytest_handler(h)]


def test_the_dependency_loggers_write_only_to_stderr_through_the_policy(configured):
    for name in obs.DEPENDENCY_LOGGER_NAMES:
        handlers = _ours(name)
        assert [type(h) for h in handlers] == [obs.PolicyStreamHandler], name
        assert logging.getLogger(name).propagate is False
        # DEBUG was asked for; the floor holds on the logger AND on its handler.
        assert logging.getLogger(name).level == logging.WARNING
        assert handlers[0].level == logging.WARNING
    assert fastmcp.settings.log_enabled is False


def test_no_foreign_handler_survives_under_the_dependency_loggers(configured):
    for name, logger in logging.root.manager.loggerDict.items():
        if not isinstance(logger, logging.Logger):
            continue
        if name.split(".")[0] not in obs.DEPENDENCY_LOGGER_NAMES:
            continue
        for handler in logger.handlers:
            assert _is_pytest_handler(handler) or isinstance(handler, obs.PolicyStreamHandler), (
                name,
                handler,
            )


def test_configuring_again_installs_one_filter_and_one_handler(configured):
    obs.configure(config.settings({"AMICUS_LOG_LEVEL": "DEBUG"}), force=True)
    server = logging.getLogger(obs.FASTMCP_SERVER_LOGGER_NAME)
    assert sum(isinstance(f, obs.FastMCPServerRecordFilter) for f in server.filters) == 1
    for name in obs.DEPENDENCY_LOGGER_NAMES:
        assert len(_ours(name)) == 1, name


def test_fastmcp_cannot_reinstall_its_own_handlers(configured):
    # `configure_logging` removes every handler on `fastmcp` and installs its own rich ones,
    # and `run(log_level=...)` reaches it through `temporary_log_level`.
    configure_logging(level="DEBUG")
    with temporary_log_level("DEBUG"):
        assert [type(h) for h in _ours("fastmcp")] == [obs.PolicyStreamHandler]
    assert [type(h) for h in _ours("fastmcp")] == [obs.PolicyStreamHandler]


def test_an_mcp_exception_renders_as_its_type_not_its_text(configured):
    try:
        raise ValueError(f"handler failed on {MARKER}")
    except ValueError:
        logging.getLogger("mcp.server.runner").exception("modern request handler raised")
    stderr, on_disk = configured.read()
    assert "modern request handler raised" in stderr  # positive control: stderr is read
    assert "ValueError" in stderr
    assert MARKER not in stderr
    assert "modern request handler raised" not in on_disk


def test_nothing_below_warning_reaches_stderr_even_at_debug(configured):
    importlib.import_module("fastmcp.server.context")  # attaches FastMCP's to_client clamp
    to_client = logging.getLogger("fastmcp.server.context.to_client")
    assert any(type(f).__name__ == "_ClampedLogFilter" for f in to_client.filters)
    runner = logging.getLogger("mcp.server.runner")
    # The mcp stdio runner logs a whole inbound frame at DEBUG.
    runner.debug(
        "dropped a frame received before the first request: %r",
        {"params": {"arguments": {"question": MARKER}}},
    )
    # FastMCP logs every message a tool sends its client as a preformatted string, then
    # clamps the record to DEBUG after the logger has admitted it.
    to_client.warning(f"Sending WARNING to client: {MARKER}")
    runner.warning("dropped %r: malformed params", "tools/call")
    stderr, _ = configured.read()
    assert "dropped 'tools/call': malformed params" in stderr  # positive control
    assert MARKER not in stderr
