"""Claude-side configuration: the AMICUS_CLAUDE_* namespace (the CLAUDE_IN_CODEX_ names are
retired since 0.4.0), the resolved ClaudeConfig, version parsing, the API-key presence check
and the workspace hook scan. Ported from claude-in-codex `config.py`; the timeout/input/git/job
knobs are not ported (the global AMICUS_* settings cover them) and there is no extra-args
channel."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.backends.claude import contract
from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

PREFIX = "AMICUS_CLAUDE_"
_RETIRED = "CLAUDE_IN_CODEX_"  # not read; tombstones only (#176)

ENV = EnvNamespace(
    prefix=PREFIX,
    vars=(
        EnvVar(
            f"{PREFIX}BIN",
            "Explicit path to the claude executable; used exactly as given.",
            None,
        ),
        EnvVar(
            f"{PREFIX}CONFIG_MODE",
            "Default backend_options.config_mode: inherit | scoped | safe | bare. "
            "Adversarial reviews default to safe even when inherit/scoped is configured, "
            "or bare when bare is configured. Explicit per-call config_mode overrides apply.",
            contract.DEFAULT_CONFIG_MODE,
            removed=(f"{_RETIRED}CLAUDE_CONFIG",),
        ),
        EnvVar(
            f"{PREFIX}ACCESS",
            "Default backend_options.access: toolless | readonly. Unset, reviews default to "
            "readonly and other verbs to toolless; set, it applies to every verb.",
            contract.DEFAULT_ACCESS,
            removed=(f"{_RETIRED}ACCESS",),
        ),
        EnvVar(
            f"{PREFIX}MODEL",
            "Default model slug when a call omits `model`.",
            None,
            removed=(f"{_RETIRED}MODEL",),
        ),
        EnvVar(
            f"{PREFIX}REASONING_EFFORT",
            "Default reasoning effort when a call omits `reasoning_effort`: "
            "low | medium | high | xhigh | max.",
            contract.DEFAULT_EFFORT,
            removed=(f"{_RETIRED}EFFORT",),
        ),
        EnvVar(
            f"{PREFIX}MAX_BUDGET_USD",
            "Default backend_options.max_budget_usd (0.01-5.00), a best-effort stop threshold "
            "checked between model calls.",
            f"{contract.DEFAULT_MAX_BUDGET_USD}",
            removed=(f"{_RETIRED}MAX_BUDGET_USD",),
        ),
        EnvVar(
            f"{PREFIX}SUPPORTED_MAJORS",
            "Comma-separated claude major versions treated as supported (advisory).",
            None,
            removed=(f"{_RETIRED}SUPPORTED_MAJORS",),
        ),
    ),
)

HOOK_WARNING_PREFIX = "Workspace Claude settings define hooks"


@dataclass(frozen=True)
class ClaudeConfig:
    bin_override: str | None
    config_mode: str
    access: str
    model: str | None
    reasoning_effort: str
    max_budget_usd: float
    supported_majors: frozenset[int]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    # Whether the operator set AMICUS_CLAUDE_ACCESS at all. An invalid
    # value counts: _choice falls back to toolless with a warning, and that fallback binds
    # every verb, so a mistyped restriction never loosens into the review default.
    access_explicit: bool = False


def _choice(
    name: str, value: str | None, allowed: tuple[str, ...], default: str, warnings: list[str]
) -> str:
    if value is None or value == "":
        return default
    if value in allowed:
        return value
    # Value-free: an env value is operator-controlled and unbounded.
    warnings.append(f"{name} is not one of {', '.join(allowed)}; using {default}")
    return default


def _budget(name: str, value: str | None, warnings: list[str]) -> float:
    if value is None or value == "":
        return contract.DEFAULT_MAX_BUDGET_USD
    try:
        parsed = float(value)
    except ValueError:
        warnings.append(f"{name} is not a number; using {contract.DEFAULT_MAX_BUDGET_USD}")
        return contract.DEFAULT_MAX_BUDGET_USD
    if not (contract.MIN_BUDGET_USD <= parsed <= contract.MAX_BUDGET_USD):
        warnings.append(
            f"{name} is outside {contract.MIN_BUDGET_USD}-{contract.MAX_BUDGET_USD}; "
            f"using {contract.DEFAULT_MAX_BUDGET_USD}"
        )
        return contract.DEFAULT_MAX_BUDGET_USD
    return parsed


def _majors(name: str, value: str | None, warnings: list[str]) -> frozenset[int]:
    if not value:
        return contract.SUPPORTED_MAJORS
    try:
        parsed = frozenset(int(part) for part in value.split(",") if part.strip())
    except ValueError:
        warnings.append(f"{name} is not a comma-separated list of integers; using the built-in set")
        return contract.SUPPORTED_MAJORS
    return parsed or contract.SUPPORTED_MAJORS


def load_config(environ: Mapping[str, str] | None = None) -> ClaudeConfig:
    """Resolve every AMICUS_CLAUDE_* setting once. Never raises: conflicts and bad values
    ride `warnings`/`errors` so amicus_backends can report them."""
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

    def is_set(name: str) -> bool:
        try:
            resolved = ENV.resolve(name, environ)
            # An empty value is unset to _choice, so it is unset here too.
            return resolved.source in ("env", "legacy") and bool(resolved.value)
        except EnvConflictError:
            # Both names are set and disagree: get() keeps the current name's value, so this
            # is explicit exactly when that value is, and an empty one stays unset.
            return bool(get(name))

    return ClaudeConfig(
        bin_override=get(f"{PREFIX}BIN") or None,
        config_mode=_choice(
            f"{PREFIX}CONFIG_MODE",
            get(f"{PREFIX}CONFIG_MODE"),
            contract.CONFIG_MODES,
            contract.DEFAULT_CONFIG_MODE,
            warnings,
        ),
        access=_choice(
            f"{PREFIX}ACCESS",
            get(f"{PREFIX}ACCESS"),
            contract.ACCESS_MODES,
            contract.DEFAULT_ACCESS,
            warnings,
        ),
        access_explicit=is_set(f"{PREFIX}ACCESS"),
        model=get(f"{PREFIX}MODEL") or None,
        reasoning_effort=_choice(
            f"{PREFIX}REASONING_EFFORT",
            get(f"{PREFIX}REASONING_EFFORT"),
            contract.VALID_EFFORTS,
            contract.DEFAULT_EFFORT,
            warnings,
        ),
        max_budget_usd=_budget(f"{PREFIX}MAX_BUDGET_USD", get(f"{PREFIX}MAX_BUDGET_USD"), warnings),
        supported_majors=_majors(
            f"{PREFIX}SUPPORTED_MAJORS", get(f"{PREFIX}SUPPORTED_MAJORS"), warnings
        ),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def parse_major(version: str | None) -> int | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.\d+\.\d+", version)
    return int(match.group(1)) if match else None


def version_supported(version: str | None, config: ClaudeConfig) -> bool | None:
    major = parse_major(version)
    if major is None:
        return None
    return major in config.supported_majors


def api_key_present(environ: Mapping[str, str] | None = None) -> bool:
    """Whether a non-empty ANTHROPIC_API_KEY is set (a `${...}` placeholder counts as present:
    the placeholder check reports it separately). The value is never returned."""
    import os  # noqa: PLC0415

    env = os.environ if environ is None else environ
    return bool(env.get(contract.API_KEY_ENV))


def workspace_hook_settings(cwd: str) -> list[str]:
    """Workspace Claude settings files that define hooks (advisory: print mode silently
    ignores invalid settings files, and amicus is not a settings validator)."""
    found: list[str] = []
    root = Path(cwd)
    for rel in contract.HOOK_SETTINGS_FILES:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r'"hooks"\s*:', text):
            found.append(rel)
    return found


def hook_security_warnings(cwd: str, mode: str) -> list[str]:
    """The one warning a run under inherit/scoped carries when the workspace defines hooks;
    safe and bare disable hooks, so nothing is reported for them."""
    if mode in ("safe", "bare"):
        return []
    hook_files = workspace_hook_settings(cwd)
    if not hook_files:
        return []
    return [
        f"{HOOK_WARNING_PREFIX} ({', '.join(hook_files)}). Claude Code hooks run outside the "
        "tool allowlist and may run shell under config_mode=inherit/scoped; use "
        "backend_options.config_mode='safe' or 'bare' for an untrusted workspace."
    ]
