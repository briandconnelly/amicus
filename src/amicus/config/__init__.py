"""Operator settings resolved from the AMICUS_* namespace (with the legacy shim)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder
from amicus.schemas.codes import BACKEND_IDS
from amicus.schemas.params import MAX_TIMEOUT_SECONDS, MIN_TIMEOUT_SECONDS

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

PROFILE_DEFAULT: tuple[str, ...] = BACKEND_IDS
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_INPUT_BYTES = 200_000
DEFAULT_JOB_TTL_SECONDS = 86_400
DEFAULT_JOB_MAX_SECONDS = 1_800
DEFAULT_JOB_MAX_COUNT = 50
DEFAULT_MAX_OUTPUT_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_DELEGATE_DIFF_BYTES = 200_000
DEFAULT_GIT_TIMEOUT_SECONDS = 60
DEFAULT_LOG_LEVEL = "WARNING"
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_TRUE = frozenset({"1", "true", "yes", "on"})

_ALL_LEGACY = ("CODEX_IN_CLAUDE_", "MOONBRIDGE_", "CLAUDE_IN_CODEX_")


def _legacy(suffix: str, *prefixes: str) -> tuple[str, ...]:
    return tuple(f"{p}{suffix}" for p in (prefixes or _ALL_LEGACY))


GLOBAL_ENV = EnvNamespace(
    prefix="AMICUS_",
    vars=(
        EnvVar(
            "AMICUS_BACKENDS", "Comma-separated enabled backends; default: every in-tree backend."
        ),
        EnvVar(
            "AMICUS_TIMEOUT_SECONDS",
            "Default sync deadline (10-600).",
            str(DEFAULT_TIMEOUT_SECONDS),
            _legacy("TIMEOUT_SECONDS"),
        ),
        EnvVar(
            "AMICUS_MAX_INPUT_BYTES",
            "Byte budget for caller inputs plus the gathered diff.",
            str(DEFAULT_MAX_INPUT_BYTES),
            _legacy("MAX_INPUT_BYTES"),
        ),
        EnvVar(
            "AMICUS_JOB_TTL",
            "Seconds a terminal job record is retained.",
            str(DEFAULT_JOB_TTL_SECONDS),
            _legacy("JOB_TTL"),
        ),
        EnvVar(
            "AMICUS_JOB_MAX_SECONDS",
            "Background job wall-clock cap (60-7200).",
            str(DEFAULT_JOB_MAX_SECONDS),
            _legacy("JOB_MAX_SECONDS"),
        ),
        EnvVar(
            "AMICUS_JOB_MAX_COUNT",
            "Retained job records per workspace (1-1000).",
            str(DEFAULT_JOB_MAX_COUNT),
            _legacy("JOB_MAX_COUNT"),
        ),
        EnvVar(
            "AMICUS_MAX_OUTPUT_BYTES",
            "Byte ceiling for a backend process's captured stdout+stderr (head+tail kept).",
            str(DEFAULT_MAX_OUTPUT_BYTES),
            _legacy("MAX_OUTPUT_BYTES"),
        ),
        EnvVar(
            "AMICUS_MAX_DELEGATE_DIFF_BYTES",
            "Byte cap for the diff a delegate returns inline (diffstat stays whole).",
            str(DEFAULT_MAX_DELEGATE_DIFF_BYTES),
            _legacy("MAX_DELEGATE_DIFF_BYTES"),
        ),
        EnvVar(
            "AMICUS_GIT_TIMEOUT_SECONDS",
            "Per-git-command timeout for diff gathering and worktrees (1-3600).",
            str(DEFAULT_GIT_TIMEOUT_SECONDS),
            _legacy("GIT_TIMEOUT_SECONDS"),
        ),
        EnvVar(
            "AMICUS_STATE_DIR", "Directory for job records; default $XDG_CACHE_HOME/amicus/jobs."
        ),
        EnvVar(
            "AMICUS_LOG_LEVEL",
            "Diagnostic log level (stderr).",
            DEFAULT_LOG_LEVEL,
            _legacy("LOG_LEVEL", "CODEX_IN_CLAUDE_", "MOONBRIDGE_"),
        ),
        EnvVar(
            "AMICUS_LOG_FILE",
            "Optional file mirroring the stderr log.",
            None,
            _legacy("LOG_FILE", "CODEX_IN_CLAUDE_", "MOONBRIDGE_"),
        ),
        EnvVar("AMICUS_TASKS", "1 to register the paid sync tools with the tasks extension.", "0"),
        EnvVar(
            "AMICUS_TASKS_BACKEND_URL",
            "Docket backend for the tasks extension (memory:// or redis://).",
            "memory://",
        ),
        EnvVar("AMICUS_HOST_NAME", "Override the host name used in prompt framing."),
        EnvVar(
            "AMICUS_ALLOW_CWD_WORKSPACE",
            "1 to allow falling back to the server cwd (disclosed).",
            "0",
        ),
    ),
)


@dataclass(frozen=True)
class Settings:
    enabled_backends: tuple[str, ...]
    timeout_seconds: int
    max_input_bytes: int
    job_ttl_seconds: int
    job_max_seconds: int
    job_max_count: int
    max_output_bytes: int
    max_delegate_diff_bytes: int
    git_timeout_seconds: int
    state_dir: Path
    log_level: str
    log_file: str | None
    tasks_enabled: bool
    tasks_backend_url: str
    host_name: str | None
    allow_cwd_workspace: bool
    env_warnings: tuple[str, ...]
    config_errors: tuple[str, ...]
    placeholders: tuple[str, ...]


def _bounded_int(
    name: str, value: str | None, default: int, lo: int, hi: int, warnings: list[str]
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        warnings.append(f"{name}={value!r} is not an integer; using {default}")
        return default
    return max(lo, min(hi, parsed))


def _profile(raw: str | None, errors: list[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return PROFILE_DEFAULT
    out: list[str] = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if token not in BACKEND_IDS:
            errors.append(f"AMICUS_BACKENDS entry {token!r} is not an in-tree backend")
            continue
        if token not in out:
            out.append(token)
    return tuple(out) or PROFILE_DEFAULT


def settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Resolve every setting once. Never raises: problems ride `env_warnings`,
    `config_errors` and `placeholders` so `amicus_backends` can report them."""
    report = GLOBAL_ENV.report(environ)
    warnings = list(report.warnings)
    errors = list(report.errors)
    env = os.environ if environ is None else environ

    def get(name: str) -> str | None:
        try:
            return GLOBAL_ENV.resolve(name, environ).value
        except EnvConflictError:
            # Already recorded by report(); fall back to the amicus name (unless it's an
            # unexpanded placeholder, already recorded in report.placeholders) or the default.
            own = env.get(name)
            if is_env_placeholder(own):
                own = None
            return own if own is not None else GLOBAL_ENV.var(name).default

    state_raw = get("AMICUS_STATE_DIR")
    if state_raw:
        state_dir = Path(state_raw).expanduser()
    else:
        base = env.get("XDG_CACHE_HOME")
        state_dir = (
            (Path(base).expanduser() if base else Path.home() / ".cache") / "amicus" / "jobs"
        )
    level = (get("AMICUS_LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
    return Settings(
        enabled_backends=_profile(get("AMICUS_BACKENDS"), errors),
        timeout_seconds=_bounded_int(
            "AMICUS_TIMEOUT_SECONDS",
            get("AMICUS_TIMEOUT_SECONDS"),
            DEFAULT_TIMEOUT_SECONDS,
            MIN_TIMEOUT_SECONDS,
            MAX_TIMEOUT_SECONDS,
            warnings,
        ),
        max_input_bytes=_bounded_int(
            "AMICUS_MAX_INPUT_BYTES",
            get("AMICUS_MAX_INPUT_BYTES"),
            DEFAULT_MAX_INPUT_BYTES,
            1_000,
            10**9,
            warnings,
        ),
        job_ttl_seconds=_bounded_int(
            "AMICUS_JOB_TTL", get("AMICUS_JOB_TTL"), DEFAULT_JOB_TTL_SECONDS, 60, 10**9, warnings
        ),
        job_max_seconds=_bounded_int(
            "AMICUS_JOB_MAX_SECONDS",
            get("AMICUS_JOB_MAX_SECONDS"),
            DEFAULT_JOB_MAX_SECONDS,
            60,
            7_200,
            warnings,
        ),
        job_max_count=_bounded_int(
            "AMICUS_JOB_MAX_COUNT",
            get("AMICUS_JOB_MAX_COUNT"),
            DEFAULT_JOB_MAX_COUNT,
            1,
            1_000,
            warnings,
        ),
        max_output_bytes=_bounded_int(
            "AMICUS_MAX_OUTPUT_BYTES",
            get("AMICUS_MAX_OUTPUT_BYTES"),
            DEFAULT_MAX_OUTPUT_BYTES,
            65_536,
            10**10,
            warnings,
        ),
        max_delegate_diff_bytes=_bounded_int(
            "AMICUS_MAX_DELEGATE_DIFF_BYTES",
            get("AMICUS_MAX_DELEGATE_DIFF_BYTES"),
            DEFAULT_MAX_DELEGATE_DIFF_BYTES,
            1_000,
            10**9,
            warnings,
        ),
        git_timeout_seconds=_bounded_int(
            "AMICUS_GIT_TIMEOUT_SECONDS",
            get("AMICUS_GIT_TIMEOUT_SECONDS"),
            DEFAULT_GIT_TIMEOUT_SECONDS,
            1,
            3_600,
            warnings,
        ),
        state_dir=state_dir,
        log_level=level if level in VALID_LOG_LEVELS else DEFAULT_LOG_LEVEL,
        log_file=get("AMICUS_LOG_FILE") or None,
        tasks_enabled=(get("AMICUS_TASKS") or "0").strip().lower() in _TRUE,
        tasks_backend_url=get("AMICUS_TASKS_BACKEND_URL") or "memory://",
        host_name=get("AMICUS_HOST_NAME") or None,
        allow_cwd_workspace=(get("AMICUS_ALLOW_CWD_WORKSPACE") or "0").strip().lower() in _TRUE,
        env_warnings=tuple(warnings),
        config_errors=tuple(errors),
        placeholders=tuple(report.placeholders),
    )
