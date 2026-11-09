"""Pi-side configuration: the AMICUS_PI_* namespace, the resolved PiConfig and version
parsing. There is no extra-args passthrough, no isolation option and no retired names: pi is
new, and its resource isolation is fixed by the suppression flags in `contract`."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.backends.pi import contract
from amicus.config import settings as global_settings
from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

PREFIX = "AMICUS_PI_"
# The directory every free probe spawns pi from; see probe_cwd.
PROBE_CWD_DIRNAME = "pi-probe-cwd"

AGENT_DIR_VAR = "PI_CODING_AGENT_DIR"
AGENT_DIR_NOT_ABSOLUTE = (
    f"{AGENT_DIR_VAR} is set, but it is not an absolute path as written. pi resolves a "
    "relative value against its working directory, and amicus runs pi's free probes from its "
    "own probe directory but a paid run from the workspace (or a delegate's throwaway "
    "worktree), so the two would read different pi configuration (auth.json, models.json). "
    "Set it to an absolute path (pi also expands a leading `~/`), or unset it."
)

ENV = EnvNamespace(
    prefix=PREFIX,
    vars=(
        EnvVar(
            f"{PREFIX}BIN",
            "Absolute path to the pi executable; used exactly as given.",
            None,
        ),
        EnvVar(
            f"{PREFIX}MODEL",
            "Default model (`provider/id`, as `pi --list-models` prints it) when a call "
            "omits `model`.",
            None,
        ),
        EnvVar(
            f"{PREFIX}REASONING_EFFORT",
            "Default reasoning effort when a call omits `reasoning_effort`.",
            None,
        ),
        EnvVar(
            f"{PREFIX}SUPPORTED_VERSIONS",
            "Comma-separated pi major.minor versions treated as supported (advisory).",
            None,
        ),
    ),
)


@dataclass(frozen=True)
class PiConfig:
    bin_override: str | None
    model: str | None
    reasoning_effort: str | None
    supported_versions: frozenset[tuple[int, int]]
    state_dir: Path
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    agent_dir_error: str | None = None


def agent_dir_error(environ: Mapping[str, str] | None = None) -> str | None:
    """Why $PI_CODING_AGENT_DIR is unusable, or None. pi's own variable: pi 1.5.0 expands a
    leading `~` or `~/` against the home directory and resolves anything else that is not
    absolute against its cwd, which differs between a probe and a paid run, so such a value is
    refused rather than resolved (as CODEX_HOME is, #193). An empty value is unset, as it is to
    pi. The message never echoes the value."""
    raw = (os.environ if environ is None else environ).get(AGENT_DIR_VAR)
    if not raw or raw == "~" or raw.startswith("~/") or Path(raw).is_absolute():
        return None
    return AGENT_DIR_NOT_ABSOLUTE


def _parse_supported_versions(raw: str | None) -> frozenset[tuple[int, int]]:
    if not raw:
        return contract.SUPPORTED_VERSIONS
    parsed: set[tuple[int, int]] = set()
    for part in raw.split(","):
        bits = part.strip().split(".")
        if len(bits) < 2:
            continue
        try:
            parsed.add((int(bits[0]), int(bits[1])))
        except ValueError:
            return contract.SUPPORTED_VERSIONS
    return frozenset(parsed) or contract.SUPPORTED_VERSIONS


def load_config(environ: Mapping[str, str] | None = None) -> PiConfig:
    """Resolve every AMICUS_PI_* setting once. Never raises: conflicts and bad values ride
    `warnings`/`errors` so amicus_backends can report them; messages never carry a value."""
    report = ENV.report(environ)
    warnings = list(report.warnings)
    errors = list(report.errors)

    def get(name: str) -> str | None:
        try:
            return ENV.resolve(name, environ).value
        except EnvConflictError:
            env = os.environ if environ is None else environ
            own = env.get(name)
            if is_env_placeholder(own):
                own = None
            return own if own is not None else ENV.var(name).default

    model = get(f"{PREFIX}MODEL") or None
    if model is not None and "/" not in model:
        warnings.append(
            f"{PREFIX}MODEL is not in provider/id form (see `pi --list-models`); "
            "a call that uses it will be refused before any spend"
        )
    return PiConfig(
        bin_override=get(f"{PREFIX}BIN") or None,
        model=model,
        reasoning_effort=get(f"{PREFIX}REASONING_EFFORT") or None,
        supported_versions=_parse_supported_versions(get(f"{PREFIX}SUPPORTED_VERSIONS")),
        state_dir=global_settings(environ).state_dir,
        warnings=tuple(warnings),
        errors=tuple(errors),
        agent_dir_error=agent_dir_error(environ),
    )


_FALLBACK_PROBE_DIRS: list[str] = []


def _private_fallback_dir() -> str | None:
    """A private directory of our own under the system temporary root, reused for the process.
    Never the root itself (a shared `<tmp>/.pi/commands` would be migrated) and never inside
    the server's cwd, which `tempfile.gettempdir()` falls back to when no temp root works."""
    if _FALLBACK_PROBE_DIRS and Path(_FALLBACK_PROBE_DIRS[0]).is_dir():
        return _FALLBACK_PROBE_DIRS[0]
    try:
        if Path(tempfile.gettempdir()).resolve() == Path.cwd().resolve():
            return None
        made = tempfile.mkdtemp(prefix="amicus-pi-probe-")
    except OSError:
        return None
    _FALLBACK_PROBE_DIRS[:] = [made]
    return made


def _is_private_dir(path: Path) -> bool:
    """`path` exists (created 0o700 if absent) as a real directory, not a symlink to one,
    owned by this user and writable by no one else. A symlink could point the probes at a
    workspace, and a directory others can write could have `.pi/commands/` planted in it."""
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(st.st_mode)
        and st.st_uid == os.getuid()
        and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def probe_cwd(config: PiConfig) -> str | None:
    """The directory every free probe spawns pi from, created on each call so a removed one
    is not reported as a missing pi. pi runs its project migrations against its cwd before it
    handles `--help` or `--list-models` (renaming `.pi/commands/` to `.pi/prompts/`), so a
    probe must never run in whatever directory the server was started in. When the state
    directory cannot hold it as a private real directory (see _is_private_dir), a private
    `amicus-pi-probe-*` directory stands in. When that fails too, or PI_CODING_AGENT_DIR is
    refused (a probe would read a different pi configuration than a run), the result is None
    and the caller treats the probe as failed: pi is not spawned."""
    if config.agent_dir_error is not None:
        return None
    path = Path(config.state_dir) / PROBE_CWD_DIRNAME
    if not _is_private_dir(path):
        return _private_fallback_dir()
    return str(path)


def parse_version(version: str | None) -> tuple[int, int] | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.(\d+)\.\d+", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def version_supported(version: str | None, config: PiConfig) -> bool | None:
    parsed = parse_version(version)
    if parsed is None:
        return None
    return parsed in config.supported_versions
