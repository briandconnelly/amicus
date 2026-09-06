"""Codex-side configuration: the AMICUS_CODEX_* namespace (legacy CODEX_IN_CLAUDE_ shim),
the resolved CodexConfig, the operator extra-args allowlist, and the argv policy helpers
(sandbox by kind, isolation flags, effort shape). Ported from codex-in-claude `config.py`."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.core import redaction

from amicus.backends.codex import contract
from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder
from amicus.schemas.params import reasoning_effort_shape_error  # noqa: F401

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

PREFIX = "AMICUS_CODEX_"
_LEGACY = "CODEX_IN_CLAUDE_"

ENV = EnvNamespace(
    prefix=PREFIX,
    vars=(
        EnvVar(
            f"{PREFIX}BIN",
            "Explicit path to the codex executable; used exactly as given.",
            None,
            (f"{_LEGACY}CODEX_BIN",),
        ),
        EnvVar(
            f"{PREFIX}EXTRA_ARGS",
            "Operator-only extra global codex options (-c/--config, -p/--profile, "
            "--enable/--disable) added to every paid run; allowlisted, never echoed.",
            None,
            (f"{_LEGACY}EXTRA_ARGS",),
        ),
        EnvVar(
            f"{PREFIX}MODEL",
            "Default model slug when a call omits `model`.",
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
            "Default backend_options.isolation: inherit | ignore-config | ignore-rules.",
            "inherit",
            (f"{_LEGACY}ISOLATION",),
        ),
        EnvVar(
            f"{PREFIX}SUPPORTED_VERSIONS",
            "Comma-separated codex major.minor versions treated as supported (advisory).",
            None,
            (f"{_LEGACY}SUPPORTED_VERSIONS",),
        ),
    ),
)

VALID_ISOLATIONS = ("inherit", "ignore-config", "ignore-rules")
DEFAULT_ISOLATION = "inherit"

_KIND_SANDBOX = {
    "consult": contract.SANDBOX_READ_ONLY,
    "review_changes": contract.SANDBOX_READ_ONLY,
    "delegate": contract.SANDBOX_WORKSPACE_WRITE,
}


def sandbox_for_kind(kind: str) -> str:
    return _KIND_SANDBOX.get(kind, contract.SANDBOX_READ_ONLY)


def isolation_flags(isolation: str) -> list[str]:
    if isolation == "inherit":
        return []
    if isolation == "ignore-config":
        return ["--ignore-user-config"]
    if isolation == "ignore-rules":
        return ["--ignore-user-config", "--ignore-rules"]
    raise ValueError(f"unsupported isolation: {isolation}")


# --- Operator extra args (allowlist, never arbitrary argv) ------------------------------------
_EXTRA_CONFIG_FLAGS = ("-c", "--config")
_EXTRA_PROFILE_FLAGS = ("-p", "--profile")
_EXTRA_FEATURE_FLAGS = ("--enable", "--disable")
_PLUGIN_OWNED_FEATURES = frozenset(contract.MODEL_RUN_DISABLED_FEATURES)
_PLUGIN_OWNED_FEATURE_REASONS: dict[str, str] = {
    contract.REMOTE_PLUGIN_FEATURE: (
        "amicus disables the remote_plugin connectors as a security guarantee; "
        "an operator override cannot re-enable them"
    ),
    contract.SLEEP_TOOL_FEATURE: (
        "amicus disables the sleep_tool feature on every model-bearing run so a native "
        "sleep (up to 12h) cannot burn the run's budget into a timeout; an operator "
        "override cannot re-enable it"
    ),
}
_FEATURES_NAMESPACE = "features"
_DENIED_CONFIG_KEY_ROOTS = frozenset({"sandbox", "approval_policy", "shell_environment_policy"})
_DENIED_INSTRUCTION_CONFIG_KEYS = frozenset(
    {
        "developer_instructions",
        "model_instructions_file",
        "experimental_instructions_file",
        "instructions",
        "model_catalog_json",
    }
)
_RESERVED_META_CONFIG_KEYS: dict[str, tuple[str, str, str]] = {
    "model": ("meta.model", f"{PREFIX}MODEL", "model"),
    contract.MODEL_REASONING_EFFORT_CONFIG_KEY: (
        "meta.reasoning_effort",
        f"{PREFIX}REASONING_EFFORT",
        "reasoning_effort",
    ),
}


@dataclass(frozen=True)
class ExtraArgs:
    """Parsed AMICUS_CODEX_EXTRA_ARGS. `tokens` is the validated argv to inject (may carry
    secret `-c` VALUES — never echo it). `descriptors` are RAW identifiers (flag names, config
    KEYS, profile/feature NAMES) matched against a codex rejection; sanitize at emission."""

    tokens: tuple[str, ...] = ()
    descriptors: tuple[str, ...] = ()
    config_keys: tuple[str, ...] = ()
    profile_names: tuple[str, ...] = ()
    option_count: int = 0
    configured: bool = False
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None

    def owns_config_key(self, key: str) -> bool:
        if not (self.configured and self.valid):
            return False
        target = _normalize_config_key(key)
        for own in self.config_keys:
            own_n = _normalize_config_key(own)
            if target == own_n or target.startswith(own_n + "."):
                return True
        return False

    def owns_profile_file(self, path: str | None) -> bool:
        if not (self.configured and self.valid) or not path:
            return False
        base = Path(path.strip()).name
        return any(base == f"{name}.config.toml" for name in self.profile_names)


def _safe_token(token: str) -> str:
    return redaction.sanitize_echo(token)[:60]


def _normalize_config_key(key: str) -> str:
    return ".".join(seg.strip().strip("\"'").strip().lower() for seg in key.split("."))


def _flag_kind(flag: str) -> str | None:
    if flag in _EXTRA_CONFIG_FLAGS:
        return "config"
    if flag in _EXTRA_PROFILE_FLAGS:
        return "profile"
    if flag in _EXTRA_FEATURE_FLAGS:
        return "feature"
    return None


def _plugin_owned_feature_for_key(normalized: str) -> str | None:
    for feature in contract.MODEL_RUN_DISABLED_FEATURES:
        owned = f"{_FEATURES_NAMESPACE}.{feature}"
        if normalized == owned or normalized.startswith(f"{owned}."):
            return feature
    return None


def _config_key_denial(normalized: str, key: str) -> str | None:
    root = normalized.split(".", 1)[0]
    shown = _safe_token(key.strip())
    if any(root == d or root.startswith(f"{d}_") for d in _DENIED_CONFIG_KEY_ROOTS):
        return (
            f"config key '{shown}' is refused: it could weaken the sandbox / network / "
            "approval / host-env-isolation guarantees amicus advertises"
        )
    if normalized == _FEATURES_NAMESPACE:
        owned = ", ".join(contract.MODEL_RUN_DISABLED_FEATURES)
        return (
            f"config key '{shown}' is refused: the bare features table can reach the "
            f"plugin-owned features ({owned}) amicus forces off on every model-bearing "
            "run; set another feature by its own dotted key instead"
        )
    owned_feature = _plugin_owned_feature_for_key(normalized)
    if owned_feature is not None:
        return f"config key '{shown}' is refused: {_PLUGIN_OWNED_FEATURE_REASONS[owned_feature]}"
    if normalized == "developer_instructions":
        return (
            f"config key '{shown}' is refused: a raw override would place operator prose "
            "above the server's framing with no record in the result envelope; use the "
            "instructions_append parameter instead"
        )
    if normalized in _DENIED_INSTRUCTION_CONFIG_KEYS:
        return (
            f"config key '{shown}' is refused: it could replace or redefine model "
            "instructions wholesale (or is reserved for that)"
        )
    reserved = _RESERVED_META_CONFIG_KEYS.get(normalized)
    if reserved is not None:
        meta_field, env_var, param = reserved
        return (
            f"config key '{shown}' is reserved — it would contradict the provenance reported "
            f"in result envelopes ({meta_field}); set {env_var} or the per-call {param} "
            "parameter instead"
        )
    return None


def parse_extra_args(raw: str) -> ExtraArgs:
    """Tokenize + allowlist-validate a non-blank extra-args value. Never raises."""
    try:
        toks = shlex.split(raw)
    except ValueError:
        return ExtraArgs(configured=True, error="could not tokenize (unbalanced quotes?)")
    tokens: list[str] = []
    descriptors: list[str] = []
    config_keys: list[str] = []
    profile_names: list[str] = []
    count = 0
    i = 0
    while i < len(toks):
        tok = toks[i]
        attached = tok.startswith("--") and "=" in tok
        if attached:
            flag, value = tok.split("=", 1)
        else:
            flag = tok
        kind = _flag_kind(flag)
        if kind is None:
            return ExtraArgs(configured=True, error=f"unsupported argument: {_safe_token(tok)}")
        if not attached:
            if i + 1 >= len(toks):
                return ExtraArgs(configured=True, error=f"{flag} requires a value")
            value = toks[i + 1]
            i += 1
        if value.startswith("-"):
            return ExtraArgs(configured=True, error=f"{flag} value looks like a flag")
        if kind == "config":
            if "=" not in value:
                return ExtraArgs(configured=True, error=f"{flag} expects KEY=VALUE")
            key = value.split("=", 1)[0]
            if not key.strip():
                return ExtraArgs(configured=True, error=f"{flag} has an empty config key")
            denial = _config_key_denial(_normalize_config_key(key), key)
            if denial is not None:
                return ExtraArgs(configured=True, error=denial)
            tokens += [flag, value]
            descriptors += [flag, key]
            config_keys.append(key)
        else:
            if not value:
                return ExtraArgs(configured=True, error=f"{flag} requires a non-empty value")
            if kind == "feature" and value.strip().lower() in _PLUGIN_OWNED_FEATURES:
                reason = _PLUGIN_OWNED_FEATURE_REASONS[value.strip().lower()]
                return ExtraArgs(
                    configured=True,
                    error=(
                        f"feature '{_safe_token(value.strip())}' is managed by amicus and "
                        f"cannot be set via {PREFIX}EXTRA_ARGS (enable or disable): {reason}"
                    ),
                )
            tokens += [flag, value]
            descriptors += [flag, value]
            if kind == "profile":
                profile_names.append(value)
        count += 1
        i += 1
    return ExtraArgs(
        tokens=tuple(tokens),
        descriptors=tuple(dict.fromkeys(descriptors)),
        config_keys=tuple(dict.fromkeys(config_keys)),
        profile_names=tuple(dict.fromkeys(profile_names)),
        option_count=count,
        configured=True,
    )


# --- The resolved config ----------------------------------------------------------------------
@dataclass(frozen=True)
class CodexConfig:
    bin_override: str | None
    extra_args: ExtraArgs
    model: str | None
    reasoning_effort: str | None
    isolation: str
    supported_versions: frozenset[tuple[int, int]]
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


def load_config(environ: Mapping[str, str] | None = None) -> CodexConfig:
    """Resolve every AMICUS_CODEX_* setting once. Never raises: conflicts and bad values ride
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
    return CodexConfig(
        bin_override=get(f"{PREFIX}BIN") or None,
        extra_args=extra,
        model=get(f"{PREFIX}MODEL") or None,
        reasoning_effort=get(f"{PREFIX}REASONING_EFFORT") or None,
        isolation=isolation,
        supported_versions=_parse_supported_versions(get(f"{PREFIX}SUPPORTED_VERSIONS")),
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


def version_supported(version: str | None, config: CodexConfig) -> bool | None:
    parsed = parse_version(version)
    if parsed is None:
        return None
    return parsed in config.supported_versions
