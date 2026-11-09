"""Resolve the `pi` executable. Precedence: AMICUS_PI_BIN (used exactly as given; an
unusable value is a loud BinaryNotFoundError, never a fallthrough) → shutil.which → the bare
literal "pi" so a spawn fails as binary-missing rather than "no invocation possible"."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.backends.pi import contract

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.pi.config import PiConfig

ENV_VAR = "AMICUS_PI_BIN"


class BinaryNotFoundError(RuntimeError):
    """AMICUS_PI_BIN names something that is not an executable file."""


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def pi_bin(config: PiConfig) -> str:
    """The token to spawn. Raises BinaryNotFoundError for an unusable override; the message
    names the env var and never its value (operator-controlled, unbounded)."""
    if config.bin_override:
        # A relative override names one file to the server and another to a job worker,
        # which runs with cwd=<job_dir>; refuse it rather than resolve it twice (#173).
        if not Path(config.bin_override).is_absolute():
            raise BinaryNotFoundError(
                f"{ENV_VAR} is set, but it is not an absolute path. A relative value, or a "
                "bare command name, would resolve against whichever directory the process "
                "happens to be in."
            )
        if not _is_executable_file(Path(config.bin_override)):
            raise BinaryNotFoundError(
                f"{ENV_VAR} is set, but it does not name an executable file on disk "
                "(missing path, a directory, or no execute bit)."
            )
        return config.bin_override
    return shutil.which(contract.PI_BIN) or contract.PI_BIN


class PiBinary:
    """The plugin's BinaryResolver: None only when the override is unusable."""

    def __init__(self, config: PiConfig) -> None:
        self._config = config

    def resolve(self) -> str | None:
        try:
            return pi_bin(self._config)
        except BinaryNotFoundError:
            return None

    def override_error(self) -> str | None:
        try:
            pi_bin(self._config)
        except BinaryNotFoundError as exc:
            return str(exc)
        return None
