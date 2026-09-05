"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import os

import fastmcp
import pytest
from pontonier.core.runtime import CommandRun

# Run the suite with fastmcp's camelCase compatibility bridge OFF so any camelCase read
# that sneaks in fails today as a hard AttributeError instead of on the next major.
fastmcp.settings.mcp_camelcase_compat = False

# The env prefixes this server reads: its own, and the three legacy prefixes the shim
# consults. Stripped so tests see built-in defaults.
ENV_PREFIXES = ("AMICUS_", "CODEX_IN_CLAUDE_", "MOONBRIDGE_", "CLAUDE_IN_CODEX_")


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every amicus and legacy env var so tests see built-in defaults."""
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
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
