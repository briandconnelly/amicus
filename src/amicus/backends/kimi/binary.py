"""Resolve the `kimi` executable. Precedence: AMICUS_KIMI_BIN (used exactly as given; an
unusable value is a loud BinaryNotFoundError, never a fallthrough) → shutil.which → the bare
literal "kimi" so a spawn fails as binary-missing rather than "no invocation possible"."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.backends.kimi import contract

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.kimi.config import KimiConfig

ENV_VAR = "AMICUS_KIMI_BIN"


class BinaryNotFoundError(RuntimeError):
    """AMICUS_KIMI_BIN names something that is not an executable file."""


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def kimi_bin(config: KimiConfig) -> str:
    """The token to spawn. Raises BinaryNotFoundError for an unusable override; the message
    names the env var and never its value (operator-controlled, unbounded)."""
    if config.bin_override:
        if not _is_executable_file(Path(config.bin_override)):
            raise BinaryNotFoundError(
                f"{ENV_VAR} is set, but it does not name an executable file on disk "
                "(missing path, a directory, or no execute bit)."
            )
        return config.bin_override
    return shutil.which(contract.KIMI_BIN) or contract.KIMI_BIN


class KimiBinary:
    """The plugin's BinaryResolver: None only when the override is unusable."""

    def __init__(self, config: KimiConfig) -> None:
        self._config = config

    def resolve(self) -> str | None:
        try:
            return kimi_bin(self._config)
        except BinaryNotFoundError:
            return None

    def override_error(self) -> str | None:
        try:
            kimi_bin(self._config)
        except BinaryNotFoundError as exc:
            return str(exc)
        return None
