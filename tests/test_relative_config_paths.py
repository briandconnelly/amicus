"""A configured path must not depend on the process cwd (#173).

The server and every job worker resolve configuration separately, and a worker runs with
``cwd=<job_dir>`` (`JobStore.start`), so a relative value names one place to the server and
another to the worker. Each case here first makes the relative value GOOD from the current
cwd, which is the case that used to pass, and only then asserts it is refused.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from amicus import config

_BACKENDS = [
    ("codex", "AMICUS_CODEX_BIN", "codex_bin", "CodexBinary"),
    ("kimi", "AMICUS_KIMI_BIN", "kimi_bin", "KimiBinary"),
    ("claude", "AMICUS_CLAUDE_BIN", "claude_bin", "ClaudeBinary"),
]


def _modules(backend: str):
    return (
        importlib.import_module(f"amicus.backends.{backend}.binary"),
        importlib.import_module(f"amicus.backends.{backend}.config"),
    )


@pytest.mark.parametrize(("backend", "env_var", "resolve", "resolver"), _BACKENDS)
def test_a_relative_bin_override_is_refused_even_where_it_resolves(
    tmp_path, monkeypatch, backend, env_var, resolve, resolver
):
    binary, cfg_mod = _modules(backend)
    exe = tmp_path / "relative-secret-name"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    # Control: from this cwd the relative token IS an executable file, so only the new
    # check can refuse it, and the absolute spelling of the same file is accepted.
    assert binary._is_executable_file(Path(exe.name))
    absolute = cfg_mod.load_config({env_var: str(exe)})
    assert getattr(binary, resolve)(absolute) == str(exe)

    relative = cfg_mod.load_config({env_var: exe.name})
    with pytest.raises(binary.BinaryNotFoundError) as exc:
        getattr(binary, resolve)(relative)
    message = str(exc.value)
    assert env_var in message and "absolute path" in message
    assert exe.name not in message, "the override's value is never echoed"
    assert getattr(binary, resolver)(relative).resolve() is None
    assert "absolute path" in (getattr(binary, resolver)(relative).override_error() or "")


def test_a_relative_state_dir_is_fatal_not_a_silent_move_to_the_default(clean_env):
    """An operator who named a directory chose where whole answers are kept. Falling back
    to the default would persist them somewhere they did not choose, and only a client that
    reads `config_errors` would ever know, so the error is fatal as well as reported."""
    s = config.settings({"AMICUS_STATE_DIR": "relative-secret-name/jobs"})
    [error] = s.config_errors
    assert s.fatal_errors == (error,)
    assert "AMICUS_STATE_DIR" in error and "absolute path" in error
    assert "relative-secret-name" not in error, "the value is never echoed"
    assert s.state_dir.is_absolute(), "whatever an embedder does, no cwd-relative store"


def test_main_refuses_to_start_on_a_relative_state_dir(clean_env, monkeypatch, capsys):
    from amicus import server

    started = []

    class FakeApp:
        def run(self):
            started.append("run")

    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp())
    # Control: with an absolute directory main() reaches the transport loop.
    monkeypatch.setenv("AMICUS_STATE_DIR", "/nonexistent/amicus-test-state")
    server.main()
    assert started == ["run"]

    monkeypatch.setenv("AMICUS_STATE_DIR", "relative-secret-name/jobs")
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 1 and started == ["run"], "the app must never run"
    err = capsys.readouterr().err
    assert "AMICUS_STATE_DIR" in err and "absolute path" in err
    assert "relative-secret-name" not in err


def test_an_absolute_or_home_relative_state_dir_is_accepted(clean_env, tmp_path):
    for value, want in ((str(tmp_path), tmp_path), ("~/x", Path("~/x").expanduser())):
        s = config.settings({"AMICUS_STATE_DIR": value})
        assert s.state_dir == want and s.state_dir.is_absolute() and s.config_errors == ()


def test_a_relative_xdg_cache_home_is_ignored_as_the_xdg_spec_requires(clean_env, tmp_path):
    """XDG Base Directory: a relative path in one of these variables is invalid and must
    be ignored. Control: an absolute one is honoured, so the variable is being read."""
    honoured = config.settings({"XDG_CACHE_HOME": str(tmp_path)})
    assert honoured.state_dir == tmp_path / "amicus" / "jobs"
    default = config.settings({}).state_dir
    # `~/cache` is relative as written; the spec tests the value itself, and nothing in it
    # asks for shell-style tilde expansion, so it is ignored rather than expanded.
    for raw in ("relative-cache", "~/cache", "~nosuchuser/cache", "", "   "):
        ignored = config.settings({"XDG_CACHE_HOME": raw})
        assert ignored.state_dir == default, raw
        assert ignored.state_dir.is_absolute() and ignored.config_errors == ()
