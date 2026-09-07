"""Resolve the `claude` executable. Precedence: AMICUS_CLAUDE_BIN (used exactly as given; an
unusable value is a loud BinaryNotFoundError, never a fallthrough) -> shutil.which -> the bare
literal "claude" so a spawn fails as binary-missing rather than "no invocation possible"."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.backends.claude import contract

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.claude.config import ClaudeConfig

ENV_VAR = "AMICUS_CLAUDE_BIN"


class BinaryNotFoundError(RuntimeError):
    """AMICUS_CLAUDE_BIN names something that is not an executable file."""


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def claude_bin(config: ClaudeConfig) -> str:
    """The token to spawn. Raises BinaryNotFoundError for an unusable override; the message
    names the env var and never its value (operator-controlled, unbounded)."""
    if config.bin_override:
        if not _is_executable_file(Path(config.bin_override)):
            raise BinaryNotFoundError(
                f"{ENV_VAR} is set, but it does not name an executable file on disk "
                "(missing path, a directory, or no execute bit)."
            )
        return config.bin_override
    return shutil.which(contract.CLAUDE_BIN) or contract.CLAUDE_BIN


class ClaudeBinary:
    """The plugin's BinaryResolver: None only when the override is unusable."""

    def __init__(self, config: ClaudeConfig) -> None:
        self._config = config

    def resolve(self) -> str | None:
        try:
            return claude_bin(self._config)
        except BinaryNotFoundError:
            return None

    def override_error(self) -> str | None:
        try:
            claude_bin(self._config)
        except BinaryNotFoundError as exc:
            return str(exc)
        return None
