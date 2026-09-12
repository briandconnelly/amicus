"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import fastmcp
import pytest
from pontonier.core.runtime import CommandRun

from amicus import config

# Run the suite with fastmcp's camelCase compatibility bridge OFF so any camelCase read
# that sneaks in fails today as a hard AttributeError instead of on the next major.
fastmcp.settings.mcp_camelcase_compat = False

# The env prefixes this server reads: its own, and the three legacy prefixes the shim
# consults. Stripped so tests see built-in defaults. One definition, the server's own, so
# a namespace added there is stripped here without anyone remembering to.
ENV_PREFIXES = config.ENV_PREFIXES

NEVER_SPAWN_CODEX = "/nonexistent/amicus-test-codex"
NEVER_SPAWN_KIMI = "/nonexistent/amicus-test-kimi"
NEVER_SPAWN_CLAUDE = "/nonexistent/amicus-test-claude"

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


@pytest.fixture(autouse=True)
def _never_spawn_real_kimi(monkeypatch):
    """No unit test may run the real kimi CLI: an unusable AMICUS_KIMI_BIN makes every kimi
    run, probe and catalog read short-circuit. Tests that want a run point the override at
    the `fake_kimi` fixture; the live suite (tests/test_kimi_live.py) deletes it."""
    monkeypatch.setenv("AMICUS_KIMI_BIN", NEVER_SPAWN_KIMI)


@pytest.fixture(autouse=True)
def _never_spawn_real_claude(monkeypatch):
    """No unit test may run the real claude CLI: an unusable AMICUS_CLAUDE_BIN makes every
    claude run and probe short-circuit. Tests that want a run point the override at the
    `fake_claude` fixture; the live suite (tests/test_claude_live.py) deletes it."""
    monkeypatch.setenv("AMICUS_CLAUDE_BIN", NEVER_SPAWN_CLAUDE)


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every amicus and legacy env var so tests see built-in defaults."""
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AMICUS_CODEX_BIN", NEVER_SPAWN_CODEX)
    monkeypatch.setenv("AMICUS_KIMI_BIN", NEVER_SPAWN_KIMI)
    monkeypatch.setenv("AMICUS_CLAUDE_BIN", NEVER_SPAWN_CLAUDE)
    return monkeypatch


def spawned_server_env() -> dict[str, str]:
    """A minimal environment for a spawned `amicus.server` subprocess, matching what
    `clean_env` gives an in-process test: every prefix in `ENV_PREFIXES` stripped, then the
    guard's unusable backend binaries restored (the autouse fixtures monkeypatch THIS
    process, not a child).

    `AMICUS_` alone is not enough. `CODEX_IN_CLAUDE_LOG_FILE` and `MOONBRIDGE_LOG_FILE` are
    accepted legacy aliases for `AMICUS_LOG_FILE` (`config/__init__.py`), and `obs.configure`
    opens that path — so a developer with one exported had these tests writing to their own
    log file. Measured before the fix: the subprocess created it.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(ENV_PREFIXES)}
    return env | {
        "AMICUS_CODEX_BIN": NEVER_SPAWN_CODEX,
        "AMICUS_KIMI_BIN": NEVER_SPAWN_KIMI,
        "AMICUS_CLAUDE_BIN": NEVER_SPAWN_CLAUDE,
    }


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


@pytest.fixture
def pinned_kimi_bin(monkeypatch):
    """Let AMICUS_KIMI_BIN=/KIMI resolve without a file on disk (argv tests only)."""
    from amicus.backends.kimi import binary

    monkeypatch.setattr(
        binary, "_is_executable_file", lambda path: str(path) == "/KIMI" or path.is_file()
    )
    return monkeypatch


@pytest.fixture
def pinned_claude_bin(monkeypatch):
    """Let AMICUS_CLAUDE_BIN=/CLAUDE resolve without a file on disk (argv tests only)."""
    from amicus.backends.claude import binary

    monkeypatch.setattr(
        binary, "_is_executable_file", lambda path: str(path) == "/CLAUDE" or path.is_file()
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


@pytest.fixture(scope="session")
def fake_kimi(tmp_path_factory) -> Path:
    """An executable stand-in `kimi` (tests/support/fake_kimi.py) for spend-free runs."""
    src = Path(__file__).parent / "support" / "fake_kimi.py"
    exe = tmp_path_factory.mktemp("fake-kimi") / "kimi"
    shutil.copy(src, exe)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return exe


@pytest.fixture(scope="session")
def fake_claude(tmp_path_factory) -> Path:
    """An executable stand-in `claude` (tests/support/fake_claude.py) for spend-free runs."""
    src = Path(__file__).parent / "support" / "fake_claude.py"
    exe = tmp_path_factory.mktemp("fake-claude") / "claude"
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


@pytest.fixture
def live_kimi(monkeypatch, tmp_path):
    """Opt back into the real kimi CLI for `-m integration` tests. Skips when kimi is absent
    or has no provider, unless AMICUS_REQUIRE_LIVE=1 makes that a failure."""
    import json
    import shutil
    import subprocess

    monkeypatch.delenv("AMICUS_KIMI_BIN", raising=False)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    require = os.environ.get("AMICUS_REQUIRE_LIVE") == "1"
    kimi = shutil.which("kimi")
    if kimi is None:
        (pytest.fail if require else pytest.skip)("kimi CLI not installed")
    probe = subprocess.run(
        [kimi, "provider", "list", "--json"], capture_output=True, text=True, check=False
    )
    try:
        providers = json.loads(probe.stdout).get("providers") or {}
    except (json.JSONDecodeError, AttributeError):
        providers = {}
    if probe.returncode != 0 or not providers:
        (pytest.fail if require else pytest.skip)("kimi has no configured provider")
    return kimi


@pytest.fixture
def live_claude(monkeypatch, tmp_path):
    """Opt back into the real claude CLI for `-m integration` tests. Skips when claude is
    absent or logged out, unless AMICUS_REQUIRE_LIVE=1 makes that a failure. The auth probe
    is exit-code only: `claude auth status` prints the account, which must not reach a log."""
    import shutil
    import subprocess

    monkeypatch.delenv("AMICUS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    require = os.environ.get("AMICUS_REQUIRE_LIVE") == "1"
    claude = shutil.which("claude")
    if claude is None:
        (pytest.fail if require else pytest.skip)("claude CLI not installed")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    status = subprocess.run(
        [claude, "auth", "status", "--text"], capture_output=True, text=True, check=False, env=env
    )
    if status.returncode != 0:
        (pytest.fail if require else pytest.skip)(
            "claude is not logged in (config_mode=inherit needs a login)"
        )
    return claude
