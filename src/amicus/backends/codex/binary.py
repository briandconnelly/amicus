"""Resolve the `codex` executable (ported from codex-in-claude `binpath.py`/`binresolve.py`).

Precedence: AMICUS_CODEX_BIN (used exactly as given; an unusable value is a loud
BinaryNotFoundError, never a fallthrough) → under WSL2 interop the native candidates
($HOME/.local/bin, /usr/local/bin, `npm prefix -g`/bin) → shutil.which → the bare literal
"codex" so a spawn fails as binary-missing rather than "no invocation possible"."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.core import runtime

from amicus.backends.codex import contract

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.codex.config import CodexConfig

USR_LOCAL_BIN = Path("/usr/local/bin")
PROC_VERSION_PATH = Path("/proc/version")
_NPM_BIN_TIMEOUT_SECONDS = 5
ENV_VAR = "AMICUS_CODEX_BIN"


class BinaryNotFoundError(RuntimeError):
    """AMICUS_CODEX_BIN names something that is not an executable file."""


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _home_local_bin_candidate() -> Path | None:
    home = os.environ.get("HOME")
    if not home:
        return None
    return Path(home) / ".local" / "bin" / contract.CODEX_BIN


def _running_under_wsl2_interop() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in PROC_VERSION_PATH.read_text().lower()
    except (OSError, UnicodeDecodeError):
        return False


def _npm_global_bin_candidate() -> Path | None:
    try:
        run = runtime.run_sync_capture(
            ["npm", "prefix", "-g"], timeout_seconds=_NPM_BIN_TIMEOUT_SECONDS
        )
    except Exception:
        return None
    if run.binary_missing or run.exit_code != 0:
        return None
    prefix = run.stdout.strip()
    if not prefix:
        return None
    return Path(prefix) / "bin" / contract.CODEX_BIN


def resolve_codex_bin() -> str | None:
    """The native `codex` path, or None. Never raises."""
    try:
        if _running_under_wsl2_interop():
            home_candidate = _home_local_bin_candidate()
            if home_candidate is not None and _is_executable_file(home_candidate):
                return str(home_candidate)
            usr_local = USR_LOCAL_BIN / contract.CODEX_BIN
            if _is_executable_file(usr_local):
                return str(usr_local)
            npm_candidate = _npm_global_bin_candidate()
            if npm_candidate is not None and _is_executable_file(npm_candidate):
                return str(npm_candidate)
        return shutil.which(contract.CODEX_BIN)
    except Exception:
        return None


def codex_bin(config: CodexConfig) -> str:
    """The token to spawn. Raises BinaryNotFoundError for an unusable override; the
    message names the env var and never its value (operator-controlled, unbounded)."""
    if config.bin_override:
        if not _is_executable_file(Path(config.bin_override)):
            raise BinaryNotFoundError(
                f"{ENV_VAR} is set, but it does not name an executable file on disk "
                "(missing path, a directory, or no execute bit)."
            )
        return config.bin_override
    resolved = resolve_codex_bin()
    return resolved if resolved is not None else contract.CODEX_BIN


class CodexBinary:
    """The plugin's BinaryResolver: None only when the override is unusable."""

    def __init__(self, config: CodexConfig) -> None:
        self._config = config

    def resolve(self) -> str | None:
        try:
            return codex_bin(self._config)
        except BinaryNotFoundError:
            return None

    def override_error(self) -> str | None:
        try:
            codex_bin(self._config)
        except BinaryNotFoundError as exc:
            return str(exc)
        return None
