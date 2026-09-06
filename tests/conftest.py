"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import fastmcp
import pytest
from pontonier.core.runtime import CommandRun

# Run the suite with fastmcp's camelCase compatibility bridge OFF so any camelCase read
# that sneaks in fails today as a hard AttributeError instead of on the next major.
fastmcp.settings.mcp_camelcase_compat = False

# The env prefixes this server reads: its own, and the three legacy prefixes the shim
# consults. Stripped so tests see built-in defaults.
ENV_PREFIXES = ("AMICUS_", "CODEX_IN_CLAUDE_", "MOONBRIDGE_", "CLAUDE_IN_CODEX_")

NEVER_SPAWN_CODEX = "/nonexistent/amicus-test-codex"

# git exports these into the environment of every hook it runs, and prek's pre-push hook
# runs this very suite (`entry = "uv run pytest"`, `stages = ["pre-push"]`). Without
# scrubbing them, a test that spawns `git` inside a tmp_path repo would inherit GIT_DIR
# (etc.) from the enclosing hook and silently operate on the real checkout instead of its
# fixture repo — which is exactly what corrupted the real worktree's index the first time
# `git push` ran this suite as a pre-push hook.
GIT_HOOK_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)


def _scrub_git_hook_env(monkeypatch) -> None:
    """Delete GIT_HOOK_ENV from the environment, so a test-spawned `git` in a tmp_path repo
    cannot be redirected at the real checkout by a hook's environment."""
    for key in GIT_HOOK_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _scrub_git_hook_env_fixture(monkeypatch):
    _scrub_git_hook_env(monkeypatch)


@pytest.fixture(autouse=True)
def _never_spawn_real_codex(monkeypatch):
    """No unit test may run the real codex CLI: an unusable AMICUS_CODEX_BIN makes every
    codex run short-circuit to backend_not_found. Tests that want a run point the override
    at the `fake_codex` fixture; the live suite (tests/test_codex_live.py) deletes it."""
    monkeypatch.setenv("AMICUS_CODEX_BIN", NEVER_SPAWN_CODEX)


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every amicus and legacy env var so tests see built-in defaults."""
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AMICUS_CODEX_BIN", NEVER_SPAWN_CODEX)
    return monkeypatch


def make_run(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    elapsed_ms: int = 5,
    timed_out: bool = False,
) -> CommandRun:
    return CommandRun(stdout, stderr, exit_code, elapsed_ms, timed_out)


@pytest.fixture
def pinned_codex_bin(monkeypatch):
    """Let AMICUS_CODEX_BIN=/CODEX resolve without a file on disk (argv tests only)."""
    from amicus.backends.codex import binary

    monkeypatch.setattr(
        binary, "_is_executable_file", lambda path: str(path) == "/CODEX" or path.is_file()
    )
    return monkeypatch


@pytest.fixture(scope="session")
def fake_codex(tmp_path_factory) -> Path:
    """An executable stand-in `codex` (tests/support/fake_codex.py) for spend-free runs."""
    src = Path(__file__).parent / "support" / "fake_codex.py"
    exe = tmp_path_factory.mktemp("fake-codex") / "codex"
    shutil.copy(src, exe)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return exe


@pytest.fixture
def live_codex(monkeypatch, tmp_path):
    """Opt back into the real codex CLI for `-m integration` tests. Skips when codex is
    absent or logged out, unless AMICUS_REQUIRE_LIVE=1 makes that a failure."""
    import shutil
    import subprocess

    monkeypatch.delenv("AMICUS_CODEX_BIN", raising=False)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    require = os.environ.get("AMICUS_REQUIRE_LIVE") == "1"
    codex = shutil.which("codex")
    if codex is None:
        (pytest.fail if require else pytest.skip)("codex CLI not installed")
    status = subprocess.run([codex, "login", "status"], capture_output=True, text=True, check=False)
    if status.returncode != 0:
        (pytest.fail if require else pytest.skip)("codex is not logged in")
    return codex
