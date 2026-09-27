"""The #152 leak guard: each kind of state it compares is seen when it changes, what it
deliberately ignores is not, and end to end it fails the test that leaks — not the one after.

Every mutation here is undone before the test returns, so the guard running around these
tests themselves stays quiet; the end-to-end cases leak in a child pytest instead."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.conftest import spawned_server_env
from tests.support import state_guard

from amicus import _worker, obs

REPO = Path(__file__).resolve().parents[1]


def _leaks_while(mutate, undo) -> list[str]:
    before = state_guard.snapshot()
    mutate()
    try:
        return state_guard.leaks(before, state_guard.snapshot())
    finally:
        undo()


def test_an_unchanged_process_has_no_leaks():
    assert state_guard.leaks(state_guard.snapshot(), state_guard.snapshot()) == []


def test_the_146_leak_is_seen_on_the_amicus_logger():
    target = logging.getLogger(obs.ROOT_LOGGER_NAME)
    handler = logging.NullHandler()

    def mutate():
        target.propagate = False
        target.addHandler(handler)

    def undo():
        target.removeHandler(handler)
        target.propagate = True

    assert _leaks_while(mutate, undo) == [
        "logger 'amicus' changed: level, propagate, disabled, handlers or filters"
    ]


def test_a_logger_the_test_created_and_configured_is_a_leak():
    name = "state_guard_third_party.probe"
    assert name not in logging.Logger.manager.loggerDict
    handler = logging.NullHandler()

    def mutate():
        logging.getLogger(name).addHandler(handler)

    def undo():
        logging.getLogger(name).removeHandler(handler)
        del logging.Logger.manager.loggerDict[name]

    assert _leaks_while(mutate, undo) == [
        f"logger {name!r} changed: level, propagate, disabled, handlers or filters"
    ]


def test_a_deleted_logger_is_a_leak():
    # getLogger would hand the next test a fresh, unconfigured `mcp` in its place.
    logging.getLogger("mcp")
    saved = {}

    def mutate():
        saved["mcp"] = logging.Logger.manager.loggerDict.pop("mcp")

    def undo():
        logging.Logger.manager.loggerDict["mcp"] = saved["mcp"]

    assert _leaks_while(mutate, undo) == ["logger 'mcp' removed"]


def test_a_logger_the_test_created_and_left_at_its_defaults_is_not_a_leak():
    name = "state_guard_third_party.quiet_probe"

    def undo():
        del logging.Logger.manager.loggerDict[name]

    assert _leaks_while(lambda: logging.getLogger(name), undo) == []


def test_fastmcps_first_use_logger_exists_before_any_snapshot():
    # FastMCP clamps `to_client` on first import; state_guard imports it, so no test that
    # happens to import it first is blamed for the library's own setup.
    to_client = logging.Logger.manager.loggerDict.get("fastmcp.server.context.to_client")
    assert isinstance(to_client, logging.Logger)
    assert any(type(f).__name__ == "_ClampedLogFilter" for f in to_client.filters)


def test_an_existing_third_party_logger_changing_is_a_leak():
    target = logging.getLogger("mcp")
    level = target.level

    def undo():
        target.setLevel(level)

    assert _leaks_while(lambda: target.setLevel(logging.CRITICAL + 1), undo) == [
        "logger 'mcp' changed: level, propagate, disabled, handlers or filters"
    ]


def test_a_pytest_capture_handler_is_not_a_leak(caplog):
    # caplog's handler sits on the root logger for this test's phases; comparing it would
    # flag every test that asks for caplog.
    root = logging.getLogger()
    assert caplog.handler in root.handlers  # control: there is one to leave out
    handlers = state_guard.snapshot().loggers["<root>"][3]
    assert caplog.handler not in handlers
    assert not any(state_guard._is_pytest_handler(h) for h in handlers)


def test_a_direct_environment_write_is_named_without_its_value():
    key, value = "AMICUS_STATE_GUARD_PROBE", "sk-not-a-real-credential"

    def mutate():
        os.environ[key] = value

    def undo():
        del os.environ[key]

    leaks = _leaks_while(mutate, undo)
    assert leaks == [f"os.environ[{key!r}] changed"]
    assert value not in "".join(leaks)


def test_pytests_own_current_test_variable_is_ignored():
    before = state_guard.snapshot()
    saved = os.environ.get("PYTEST_CURRENT_TEST")
    os.environ["PYTEST_CURRENT_TEST"] = "something else (call)"
    try:
        assert state_guard.leaks(before, state_guard.snapshot()) == []
    finally:
        if saved is None:
            del os.environ["PYTEST_CURRENT_TEST"]
        else:
            os.environ["PYTEST_CURRENT_TEST"] = saved


def test_a_changed_working_directory_is_a_leak(tmp_path):
    saved = Path.cwd()
    leaks = _leaks_while(lambda: os.chdir(tmp_path), lambda: os.chdir(saved))
    assert leaks == [f"working directory: {saved} -> {tmp_path}"]


def test_a_vanished_working_directory_is_reported_rather_than_raising(tmp_path):
    saved = Path.cwd()
    doomed = tmp_path / "doomed"
    doomed.mkdir()

    def mutate():
        os.chdir(doomed)
        doomed.rmdir()

    leaks = _leaks_while(mutate, lambda: os.chdir(saved))
    assert leaks == [f"working directory: {saved} -> <cwd no longer exists>"]


def test_a_changed_sys_path_is_a_leak():
    probe = "/nonexistent/state-guard-probe"
    leaks = _leaks_while(lambda: sys.path.append(probe), lambda: sys.path.remove(probe))
    assert leaks == ["sys.path changed"]


def test_a_changed_signal_handler_is_a_leak():
    saved = signal.getsignal(signal.SIGTERM)

    def mutate():
        signal.signal(signal.SIGTERM, lambda signum, frame: None)

    leaks = _leaks_while(mutate, lambda: signal.signal(signal.SIGTERM, saved))
    assert leaks == ["handler for SIGTERM changed"]


def test_a_disabled_logging_level_is_a_leak():
    leaks = _leaks_while(lambda: logging.disable(logging.INFO), lambda: logging.disable(0))
    assert leaks == ["logging.disable level changed"]


def test_obs_configured_changing_is_a_leak():
    saved = obs._configured

    def mutate():
        obs._configured = not saved

    def undo():
        obs._configured = saved

    assert _leaks_while(mutate, undo) == ["obs._configured changed"]


def test_a_fastmcp_setting_changing_is_a_leak():
    import fastmcp

    saved = fastmcp.settings.log_enabled

    def mutate():
        fastmcp.settings.log_enabled = not saved

    def undo():
        fastmcp.settings.log_enabled = saved

    assert _leaks_while(mutate, undo) == ["fastmcp.settings.log_enabled changed"]


def test_a_held_job_lock_is_a_leak():
    fd = os.open(os.devnull, os.O_RDONLY)

    def undo():
        _worker._held_locks.remove(fd)
        os.close(fd)

    assert _leaks_while(lambda: _worker._held_locks.append(fd), undo) == [
        "_worker._held_locks changed (a job-lock descriptor left open)"
    ]


# End to end, in a child pytest with only the guard's two hooks: a test that configures
# logging and restores nothing, which is #146 exactly as it shipped, followed by a clean one.
_CHILD_CONFTEST = """\
from tests.conftest import pytest_runtest_setup, pytest_runtest_teardown  # noqa: F401
"""

_CHILD_TESTS = """\
from amicus import config, obs


def test_configures_logging_and_restores_nothing():
    obs.configure(config.settings({}))


def test_a_clean_test_after_it():
    pass
"""


def _run_child(tmp_path, tests: str = _CHILD_TESTS) -> subprocess.CompletedProcess[str]:
    (tmp_path / "conftest.py").write_text(_CHILD_CONFTEST)
    (tmp_path / "test_child.py").write_text(textwrap.dedent(tests))
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    # The child runs its own options: an inherited PYTEST_ADDOPTS such as -x would stop it
    # after the leaking test, before the clean one could show it is not blamed.
    env = {k: v for k, v in spawned_server_env().items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rA", "test_child.py"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_the_guard_fails_the_leaking_test_and_not_the_one_after_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-x")  # control: an inherited option must not reach it
    run = _run_child(tmp_path)
    out = run.stdout
    assert run.returncode == 1, out + run.stderr
    assert "2 passed, 1 error" in out, out  # the call passes; its teardown errors
    assert "ERROR at teardown of test_configures_logging_and_restores_nothing" in out, out
    assert "PASSED test_child.py::test_a_clean_test_after_it" in out, out
    assert "logger 'amicus' changed" in out, out
    assert "obs._configured changed" in out, out
    assert "logger 'mcp' changed" in out, out


def test_the_child_passes_once_the_leak_is_restored(tmp_path):
    # Control: the same child, with the leaking test undoing what it did, is clean. So the
    # failure above is the leak, not something about running the guard in a child.
    restored = _CHILD_TESTS.replace(
        "    obs.configure(config.settings({}))\n",
        "    from tests.conftest import restored_dependency_logging\n\n"
        "    with restored_dependency_logging():\n"
        "        obs.configure(config.settings({}))\n",
    )
    assert restored != _CHILD_TESTS
    run = _run_child(tmp_path, restored)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "2 passed" in run.stdout, run.stdout
