"""Kimi-side configuration: the AMICUS_KIMI_* namespace (legacy MOONBRIDGE_ shim), the
resolved KimiConfig, the refuse-all extra-args parser, isolation → skills dir, and version
parsing. Ported from moonbridge `config.py`; tiers, sandbox defaults and WORKTREE_BASE are
not ported (amicus has kinds, not tiers, and one worktree policy)."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.core import redaction

from amicus.backends.kimi import contract
from amicus.config import settings as global_settings
from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

PREFIX = "AMICUS_KIMI_"
_LEGACY = "MOONBRIDGE_"

ENV = EnvNamespace(
    prefix=PREFIX,
    vars=(
        EnvVar(
            f"{PREFIX}BIN",
            "Explicit path to the kimi executable; used exactly as given.",
            None,
            (),
        ),
        EnvVar(
            f"{PREFIX}EXTRA_ARGS",
            "Operator passthrough of extra kimi options. kimi exposes no option amicus can "
            "pass safely, so any value is refused and reported by amicus_backends.",
            None,
            (f"{_LEGACY}EXTRA_ARGS",),
        ),
        EnvVar(
            f"{PREFIX}MODEL",
            "Default model ALIAS (from kimi's config.toml) when a call omits `model`.",
            None,
            (f"{_LEGACY}MODEL",),
        ),
        EnvVar(
            f"{PREFIX}REASONING_EFFORT",
            "Default reasoning effort when a call omits `reasoning_effort`.",
            None,
            (f"{_LEGACY}REASONING_EFFORT",),
        ),
        EnvVar(
            f"{PREFIX}ISOLATION",
            "Default backend_options.isolation: inherit | ignore-skills.",
            "inherit",
            (f"{_LEGACY}ISOLATION",),
        ),
        EnvVar(
            f"{PREFIX}SUPPORTED_VERSIONS",
            "Comma-separated kimi major.minor versions treated as supported (advisory).",
            None,
            (f"{_LEGACY}SUPPORTED_VERSIONS",),
        ),
    ),
)

VALID_ISOLATIONS = ("inherit", "ignore-skills")
DEFAULT_ISOLATION = "inherit"

# There is no safe passthrough: kimi reuses the short flags a Codex-style allowlist would
# accept for different things (`-p` is the PROMPT flag, `-c` is --continue), and
# `--add-dir` would punch through worktree isolation.
NO_PASSTHROUGH_REASON = (
    "kimi exposes no option amicus can pass through safely (-p is its prompt flag, -c is "
    "--continue, --add-dir defeats isolation); unset this variable"
)


@dataclass(frozen=True)
class ExtraArgs:
    """Parsed AMICUS_KIMI_EXTRA_ARGS. `tokens` is always empty: the allowlist is empty and
    a configured value only yields a value-free `error` naming the first token."""

    tokens: tuple[str, ...] = ()
    option_count: int = 0
    configured: bool = False
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None


def _safe_token(token: str) -> str:
    return redaction.sanitize_echo(token)[:60]


def parse_extra_args(raw: str) -> ExtraArgs:
    """Tokenize a non-blank value; every token is refused with the reason. Never raises."""
    try:
        toks = shlex.split(raw)
    except ValueError:
        return ExtraArgs(configured=True, error="could not tokenize (unbalanced quotes?)")
    if not toks:
        return ExtraArgs(configured=True, error="no options found")
    return ExtraArgs(
        configured=True,
        option_count=len(toks),
        error=f"unsupported argument: {_safe_token(toks[0])} — {NO_PASSTHROUGH_REASON}",
    )


@dataclass(frozen=True)
class KimiConfig:
    bin_override: str | None
    extra_args: ExtraArgs
    model: str | None
    reasoning_effort: str | None
    isolation: str
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


def load_config(environ: Mapping[str, str] | None = None) -> KimiConfig:
    """Resolve every AMICUS_KIMI_* setting once. Never raises: conflicts and bad values ride
    `warnings`/`errors` so amicus_backends can report them."""
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

    isolation = get(f"{PREFIX}ISOLATION") or DEFAULT_ISOLATION
    if isolation not in VALID_ISOLATIONS:
        warnings.append(
            f"{PREFIX}ISOLATION={isolation!r} is not one of {', '.join(VALID_ISOLATIONS)}; "
            f"using {DEFAULT_ISOLATION}"
        )
        isolation = DEFAULT_ISOLATION
    raw_extra = get(f"{PREFIX}EXTRA_ARGS")
    extra = parse_extra_args(raw_extra) if raw_extra and raw_extra.strip() else ExtraArgs()
    return KimiConfig(
        bin_override=get(f"{PREFIX}BIN") or None,
        extra_args=extra,
        model=get(f"{PREFIX}MODEL") or None,
        reasoning_effort=get(f"{PREFIX}REASONING_EFFORT") or None,
        isolation=isolation,
        supported_versions=_parse_supported_versions(get(f"{PREFIX}SUPPORTED_VERSIONS")),
        state_dir=global_settings(environ).state_dir,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def skills_dir_for(isolation: str, state_dir: Path) -> str | None:
    """Directory for --skills-dir under `isolation`, or None to leave discovery alone.
    'ignore-skills' points kimi at a stable empty directory; built-in skills still load."""
    if isolation != "ignore-skills":
        return None
    path = Path(state_dir) / "empty-skills"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def parse_version(version: str | None) -> tuple[int, int] | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.(\d+)\.\d+", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def version_supported(version: str | None, config: KimiConfig) -> bool | None:
    parsed = parse_version(version)
    if parsed is None:
        return None
    return parsed in config.supported_versions
