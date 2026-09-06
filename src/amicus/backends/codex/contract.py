"""Single source of truth for the external `codex` CLI contract (ported from
codex-in-claude `cli_contract.py`, verified against codex-cli 0.152.0/0.153.x).

Every assumption amicus makes about the `codex` CLI — subcommands, flags, sandbox values,
config keys it pins, the event/result extraction surface, and the stderr phrasings that
mean the contract drifted — lives here so an upstream change is centralized and testable.
The app-server surface (session transfer, quota reads) is deliberately not ported: amicus
defers Codex `transfer`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pontonier.backend import contract as _pc

CODEX_BIN = "codex"

# `exec` runs Codex headlessly; if it disappears upstream a run must fail loudly.
EXEC_SUBCOMMAND = ("exec",)
# Tells `codex exec` to read the prompt from stdin (keeps context/diffs off argv).
STDIN_PROMPT = "-"

# Free probes (no model call).
VERSION_ARGS = ("--version",)
LOGIN_STATUS_ARGS = ("login", "status")
EXEC_HELP_ARGS = ("exec", "--help")

# --- Sandbox modes (security boundary) ---------------------------------------------
# read-only is the consult/review posture; workspace-write is delegate's, confined to a
# throwaway worktree. amicus NEVER sends danger-full-access, --dangerously-bypass-*, or
# --approve-for-me (which would let a read-only run acquire write capability).
SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"
SANDBOX_DANGER_FULL = "danger-full-access"
VALID_SANDBOXES = (SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE, SANDBOX_DANGER_FULL)

# --- Features forced off on every model-bearing run --------------------------------
# remote_plugin (codex 0.143+ default-on third-party connectors: a network side-effect
# channel outside the sandbox) and sleep_tool (0.152+, a native sleep of up to 12h that can
# burn a run's budget into `timeout`). `--disable X` == `-c features.X=false`, wins over any
# `--enable` in either order, and an unknown feature name fails loud as
# `Error: Unknown feature flag` (classified cli_contract_changed). One `--disable` per
# entry, in this order, emitted before operator extra args; the config denylist derives
# from the same tuple.
DISABLE_FEATURE_FLAG = "--disable"
REMOTE_PLUGIN_FEATURE = "remote_plugin"
SLEEP_TOOL_FEATURE = "sleep_tool"
MODEL_RUN_DISABLED_FEATURES: tuple[str, ...] = (REMOTE_PLUGIN_FEATURE, SLEEP_TOOL_FEATURE)

# --- Implicit Codex context (disclosed on every egress carrier) ---------------------
SKILLS_DISCOVERY_FACT = (
    "Codex auto-loads the resolved workspace's AGENTS.md and, in a repository, ancestor "
    "AGENTS.md files through its root, plus a user-global $CODEX_HOME/AGENTS.override.md, "
    "else $CODEX_HOME/AGENTS.md; it discovers skills in the workspace's .agents/skills/ "
    "and user-global "
    "$CODEX_HOME/skills/ (default ~/.codex/skills/), reachable from outside the workspace."
)
SKILLS_ISOLATION_NOTE = "The isolation option does not suppress any of it."
SKILL_BODY_FACT = (
    "A skill's name and description arrive up front; selecting one makes the model read "
    "its body, which can reach OpenAI even if your inputs never mention it."
)
SKILLS_DISCOVERY_FACT_FULL = f"{SKILLS_DISCOVERY_FACT} {SKILLS_ISOLATION_NOTE}"
IMPLICIT_CONTEXT_DISCLOSURE = f"{SKILLS_DISCOVERY_FACT_FULL} {SKILL_BODY_FACT}"

# --- Read scope: the sandbox bounds writes, not reads ------------------------------
READ_SCOPE_FACT = (
    "Codex can read files outside the workspace — up to everything the OS user running it "
    "can read — and send them to OpenAI. The sandbox bounds writes, not reads, so no "
    "choice of workspace is a read boundary."
)

# --- workspace-write write scope ----------------------------------------------------
WORKSPACE_WRITE_SCOPE_FACT = (
    "The worktree does not bound Codex's writes: codex's workspace-write sandbox also "
    "lets commands write the OS temp roots (/tmp and $TMPDIR) by default."
)

# --- Strict config validation ----------------------------------------------------------
# `--strict-config` turns codex's silent tolerance of an unknown config KEY into a
# zero-spend startup failure. Emitted only on runs that carry a `-c` override (the plugin
# pins below, or an operator `-c`): at `inherit` isolation it also hard-fails on an
# unknown key anywhere in the user's own config.toml, so an override-free run must not
# carry it.
STRICT_CONFIG_FLAG = "--strict-config"

# --- Flag classes -----------------------------------------------------------------------
# ALWAYS_SEND: guarantee-bearing, never gated on `--help` parsing; codex rejecting one at
# arg-parse is zero-spend and classified cli_contract_changed.
ALWAYS_SEND_FLAGS = frozenset(
    {
        "--sandbox",
        "--cd",
        "--json",
        "--output-last-message",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--add-dir",
        "--output-schema",
        DISABLE_FEATURE_FLAG,
        STRICT_CONFIG_FLAG,
    }
)
# HELP_GATED: dropping one only reduces depth. Value: whether the flag takes an argument.
MODEL_FLAG = "--model"
HELP_GATED_FLAGS: dict[str, bool] = {MODEL_FLAG: True}

# --- Config keys the plugin pins through `-c` -------------------------------------------
# Effort has no dedicated exec flag; the key is sent as `-c model_reasoning_effort=<value>`
# (TOML-string-encoded). The two workspace-write pins close the config-file/--profile
# channels for network egress and writable roots. developer_instructions carries the
# caller's instructions_append as the FIRST developer-role message.
MODEL_REASONING_EFFORT_CONFIG_KEY = "model_reasoning_effort"
WORKSPACE_WRITE_NETWORK_ACCESS_CONFIG_KEY = "sandbox_workspace_write.network_access"
WORKSPACE_WRITE_WRITABLE_ROOTS_CONFIG_KEY = "sandbox_workspace_write.writable_roots"
DEVELOPER_INSTRUCTIONS_CONFIG_KEY = "developer_instructions"
PLUGIN_OWNED_CONFIG_KEYS = frozenset(
    {
        MODEL_REASONING_EFFORT_CONFIG_KEY,
        WORKSPACE_WRITE_NETWORK_ACCESS_CONFIG_KEY,
        WORKSPACE_WRITE_WRITABLE_ROOTS_CONFIG_KEY,
        DEVELOPER_INSTRUCTIONS_CONFIG_KEY,
    }
)

# --- Strict-config rejection grammar ------------------------------------------------------
# Two stderr shapes for an unknown key (verified live on 0.148.0): an OVERRIDE form naming a
# key from argv, and a FILE form naming a key in a user-owned config file. Anchored to whole
# lines and matched on stderr ALONE so model-produced text cannot impersonate it.
STRICT_CONFIG_ERROR_PREFIX = "Error loading config.toml"
STRICT_CONFIG_OVERRIDE_ORIGIN_PHRASE = "in -c/--config override"
STRICT_CONFIG_KEY_MAX_CHARS = 256
STRICT_CONFIG_PATH_MAX_CHARS = 4096
_STRICT_CONFIG_OVERRIDE_PATTERN = re.compile(
    rf"^{re.escape(STRICT_CONFIG_ERROR_PREFIX)}: unknown configuration field "
    rf"`(?P<key>[^`\n]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}})` "
    rf"{re.escape(STRICT_CONFIG_OVERRIDE_ORIGIN_PHRASE)}[ \t\r]*$",
    re.MULTILINE,
)
_STRICT_CONFIG_FILE_PATTERN = re.compile(
    rf"^(?P<path>[^\n]{{1,{STRICT_CONFIG_PATH_MAX_CHARS}}}?):(?P<line>\d{{1,9}}):\d{{1,9}}: "
    rf"unknown configuration field `(?P<key>[^`\n]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}})`"
    rf"[ \t\r]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class StrictConfigRejection:
    """A parsed `--strict-config` unknown-key rejection. `origin` is where codex read the
    key from: "override" (an argv `-c`, ours or the operator's) or "file" (a user-owned
    config file, located by `source_path`/`line`)."""

    origin: Literal["override", "file"]
    key: str
    source_path: str | None = None
    line: int | None = None


def parse_strict_config_rejection(text: str | None) -> StrictConfigRejection | None:
    """Parse the unknown-key rejection out of STDERR alone, else None."""
    if not text or STRICT_CONFIG_ERROR_PREFIX not in text:
        return None
    override = _STRICT_CONFIG_OVERRIDE_PATTERN.search(text)
    if override is not None:
        return StrictConfigRejection(origin="override", key=override.group("key"))
    in_file = _STRICT_CONFIG_FILE_PATTERN.search(text)
    if in_file is not None:
        return StrictConfigRejection(
            origin="file",
            key=in_file.group("key"),
            source_path=in_file.group("path"),
            line=int(in_file.group("line")),
        )
    return None


# --- Retired config SETTING rejection (codex 0.149) ---------------------------------------
# The key is recognized and only its VALUE is no longer accepted; the trailing imperative
# and the end anchor make the match exact rather than a prefix.
UNSUPPORTED_CONFIG_SETTING_PREFIX = "Error: "
UNSUPPORTED_CONFIG_SETTING_PHRASE = "is no longer supported"
UNSUPPORTED_CONFIG_SETTING_SUFFIX = "; remove this setting"
_UNSUPPORTED_CONFIG_SETTING_PATTERN = re.compile(
    rf"^{re.escape(UNSUPPORTED_CONFIG_SETTING_PREFIX)}"
    rf"(?P<key>[A-Za-z0-9_.]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}}) = "
    rf"(?P<value>[^\n]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}}?) "
    rf"{re.escape(UNSUPPORTED_CONFIG_SETTING_PHRASE)}"
    rf"{re.escape(UNSUPPORTED_CONFIG_SETTING_SUFFIX)}[ \t\r]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class UnsupportedConfigSetting:
    key: str
    value: str


def parse_unsupported_config_setting(text: str | None) -> UnsupportedConfigSetting | None:
    if not text or UNSUPPORTED_CONFIG_SETTING_PHRASE not in text:
        return None
    m = _UNSUPPORTED_CONFIG_SETTING_PATTERN.search(text)
    if m is None:
        return None
    return UnsupportedConfigSetting(key=m.group("key"), value=m.group("value"))


# --- Invalid config VALUE rejection (codex 0.149) -----------------------------------------
# A recognized key whose value fails serde validation: a two-line message that is the ENTIRE
# stderr. Anchored to the whole blob (\A..\Z). The offending value is consumed, never
# captured (it is free-form user text, plausibly a secret).
INVALID_CONFIG_VALUE_UNKNOWN_VARIANT_PHRASE = "unknown variant "
INVALID_CONFIG_VALUE_INVALID_TYPE_PHRASE = "invalid type: "
INVALID_CONFIG_VALUE_KEY_LINE_PREFIX = "in `"
INVALID_CONFIG_VALUE_MAX_VARIANTS = 64
_INVALID_CONFIG_VALUE_PATTERN = re.compile(
    rf"\A{re.escape(STRICT_CONFIG_ERROR_PREFIX)}: (?:"
    rf"{re.escape(INVALID_CONFIG_VALUE_UNKNOWN_VARIANT_PHRASE)}"
    rf"`[^\n]*?`, expected one of "
    rf"(?P<variants>`[^`\n]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}}`"
    rf"(?:, `[^`\n]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}}`)"
    rf"{{0,{INVALID_CONFIG_VALUE_MAX_VARIANTS - 1}}})"
    rf"|"
    rf"{re.escape(INVALID_CONFIG_VALUE_INVALID_TYPE_PHRASE)}"
    rf"[^\n]*?, expected "
    rf"(?P<expected_type>[^\n,]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}})"
    rf")[ \t\r]*\n"
    rf"{re.escape(INVALID_CONFIG_VALUE_KEY_LINE_PREFIX)}"
    rf"(?P<key>[A-Za-z0-9_.]{{1,{STRICT_CONFIG_KEY_MAX_CHARS}}})`[ \t\r\n]*\Z"
)


@dataclass(frozen=True)
class InvalidConfigValue:
    key: str
    kind: Literal["unknown_variant", "invalid_type"]
    expected: str


def parse_invalid_config_value(text: str | None) -> InvalidConfigValue | None:
    if not text or not text.startswith(STRICT_CONFIG_ERROR_PREFIX):
        return None
    m = _INVALID_CONFIG_VALUE_PATTERN.match(text)
    if m is None:
        return None
    if m.group("variants") is not None:
        return InvalidConfigValue(
            key=m.group("key"), kind="unknown_variant", expected=m.group("variants")
        )
    return InvalidConfigValue(
        key=m.group("key"), kind="invalid_type", expected=m.group("expected_type")
    )


# --- Reasoning effort ---------------------------------------------------------------------
# The backend's rejection of a bad effort VALUE reads "[ReasoningEffortParam] [reasoning.effort]
# [invalid_enum_value] ...", which also matches the generic drift patterns; both markers in
# their bracketed field form distinguish a caller error from contract drift.
REASONING_EFFORT_REJECTION_MARKERS = ("reasoning.effort", "reasoningeffortparam")
REASONING_EFFORT_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
SUPPORTED_EFFORTS_MAX_ENTRIES = 16

# --- Model catalog (advisory discovery) ---------------------------------------------------
MODELS_CACHE_FILENAME = "models_cache.json"
MODELS_CACHE_MAX_BYTES = 1_000_000
MODELS_CACHE_MAX_ENTRIES = 256
MODEL_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# Bundled fallback, copied from codex-cli 0.149.1's cache (re-verified unchanged at 0.152.0).
KNOWN_MODEL_SLUGS: tuple[str, ...] = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-reserve",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "codex-auto-review",
)

HELP_CACHE_TTL_SECONDS = 300

# Advisory: a mismatch warns on amicus_backends, never blocks.
SUPPORTED_VERSIONS = frozenset({(0, 152), (0, 153)})

# --- Result / event extraction surface -----------------------------------------------------
USAGE_EVENT_MARKERS = ("token_count", "usage")

# --- Login-status signatures ----------------------------------------------------------------
LOGIN_METHOD_CHATGPT = "ChatGPT"
LOGIN_METHOD_API_KEY = "API key"

# --- Contract-drift stderr signatures (clap) --------------------------------------------------
CONTRACT_DRIFT_STDERR_PATTERNS = (
    "unexpected argument",
    "unrecognized subcommand",
    "unrecognized option",
    "unknown option",
    "unknown flag",
    "invalid value",
    "invalid choice",
    "no such subcommand",
    "found argument",
    "unknown feature flag",
)

AUTH_FAILURE_PATTERNS = (
    "not logged in",
    "not authenticated",
    "please run `codex login`",
    "please run codex login",
    "run `codex login`",
    "401",
    "unauthorized",
)

RATE_LIMIT_PATTERNS = ("rate limit", "too many requests", "usage limit", "quota", "retry-after")
_HTTP_429_PATTERN = re.compile(r"\b429\b")
RATE_LIMIT_DEFAULT_BACKOFF_MS = 60_000
_SECOND_UNITS = frozenset({"", "s", "sec", "secs", "second", "seconds"})
_RETRY_AFTER_PATTERN = re.compile(
    r"(?:retry[-\s]?after|try\s+again\s+in)[\s:]*?(\d+)[ \t]*(-?[a-z]+)?",
    re.IGNORECASE,
)


def _blob(texts: tuple[str | None, ...]) -> str:
    return "\n".join(t for t in texts if t)


def is_contract_drift(*texts: str | None) -> bool:
    blob = _blob(texts).lower()
    return any(p in blob for p in CONTRACT_DRIFT_STDERR_PATTERNS)


def is_reasoning_effort_rejection(*texts: str | None) -> bool:
    blob = _blob(texts).lower()
    return all(f"[{m}]" in blob for m in REASONING_EFFORT_REJECTION_MARKERS)


def is_auth_failure(*texts: str | None) -> bool:
    blob = _blob(texts).lower()
    return any(p in blob for p in AUTH_FAILURE_PATTERNS)


def is_rate_limited(*texts: str | None) -> bool:
    blob = _blob(texts).lower()
    if any(p in blob for p in RATE_LIMIT_PATTERNS):
        return True
    return _HTTP_429_PATTERN.search(blob) is not None


def parse_retry_after_ms(*texts: str | None) -> int | None:
    """Backoff in ms from a seconds-valued Retry-After, else None (caller applies the
    default); minutes/hours and HTTP-date forms are rejected, not misread."""
    match = _RETRY_AFTER_PATTERN.search(_blob(texts))
    if match is None or (match.group(2) or "").lower() not in _SECOND_UNITS:
        return None
    return int(match.group(1)) * 1000


# --- The pontonier contract -------------------------------------------------------------------
# Wire prose that would contradict this contract. The sibling-name canaries live in amicus's
# own union (tests/test_surface_honesty.py); here only the mechanism claims.
FORBIDDEN_SURFACE_PHRASES = ("applies the diff to your working tree", "--dangerously-bypass")

CONTRACT = _pc.BackendContract(
    backend_id="codex",
    display_name="Codex",
    bin_name=CODEX_BIN,
    env_prefix="AMICUS_CODEX_",
    exec_argv_prefix=EXEC_SUBCOMMAND,
    always_send_flags=tuple(sorted(ALWAYS_SEND_FLAGS)),
    help_gated_flags=tuple(sorted(HELP_GATED_FLAGS)),
    forbidden_surface_phrases=FORBIDDEN_SURFACE_PHRASES,
    supported_features=frozenset({"delegate", "usage_accounting"}),
    readonly_honesty_statement=(
        "Read-only runs under codex's --sandbox read-only OS sandbox. Redaction of "
        "gathered diffs and returned output is best-effort defense-in-depth; it never "
        f"covers supplied inputs or files Codex reads itself. {READ_SCOPE_FACT}"
    ),
    implicit_context_disclosure=IMPLICIT_CONTEXT_DISCLOSURE,
    structured_output="argv_flag",
    model_catalog=_pc.ModelCatalog(
        strategy="cache_with_static_fallback",
        model_identifier_authority="advisory",
        effort_metadata_authority="advisory",
    ),
    isolation_policy=_pc.IsolationPolicy.SANDBOX_FLAG,
    needs_orphan_sweep=False,
    effort_silently_ignored_upstream=False,
    effort_validation="shape_only",
    usage_event_markers=USAGE_EVENT_MARKERS,
    failure_signatures=_pc.FailureSignatures(
        auth=tuple(f"(?i){re.escape(p)}" for p in AUTH_FAILURE_PATTERNS),
        contract_drift=tuple(f"(?i){re.escape(p)}" for p in CONTRACT_DRIFT_STDERR_PATTERNS),
        rate_limited=tuple(f"(?i){re.escape(p)}" for p in RATE_LIMIT_PATTERNS),
    ),
)
