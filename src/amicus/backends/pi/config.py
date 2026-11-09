"""Pi-side configuration: the AMICUS_PI_* namespace, the resolved PiConfig and version
parsing. There is no extra-args passthrough, no isolation option and no retired names: pi is
new, and its resource isolation is fixed by the suppression flags in `contract`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from amicus.backends.pi import contract
from amicus.config import settings as global_settings
from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping
    from pathlib import Path

PREFIX = "AMICUS_PI_"

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
            import os  # noqa: PLC0415

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
    )


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
