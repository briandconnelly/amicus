"""Single source of truth for the external `claude` (Claude Code) CLI contract, ported from
claude-in-codex `cli_contract.py`/`config.py` (0.9.0, built against the 2.x majors) and
re-verified against 2.1.263 by the captures in docs/claude-help/2.1.263/.

`claude -p` differs from the other two CLIs in the ways that shape this package:

1. Errors ride a ZERO-EXIT JSON envelope (`is_error`, `subtype`): the adapter is an
   OutcomeInspector and every completed process is inspected before it counts as a result.
2. Read-only is a tool allowlist (`--tools ""` / `--tools Read,Grep,Glob`), not a sandbox,
   and hooks in the workspace's .claude/settings*.json run outside it under inherit/scoped.
3. The prompt rides stdin; argv carries only constant text (the guardrails) and flags.
"""

from __future__ import annotations

import re

from pontonier.backend import contract as _pc

CLAUDE_BIN = "claude"

# Core invocation that cannot be dropped: print mode + one JSON result on stdout.
CORE_INVOCATION = ("-p", "--output-format", "json")
NO_CHROME_FLAG = "--no-chrome"  # no Chrome-integration picker hanging an unattended run
APPEND_SYSTEM_PROMPT_FLAG = "--append-system-prompt"  # the independent-critic guardrails
MAX_BUDGET_FLAG = "--max-budget-usd"  # best-effort spend stop threshold
EFFORT_FLAG = "--effort"
MODEL_FLAG = "--model"
TOOLS_FLAG = "--tools"  # the read-only / no-tool guarantee
DISALLOWED_TOOLS_FLAG = "--disallowed-tools"  # defense in depth behind --tools
NO_SESSION_PERSISTENCE_FLAG = "--no-session-persistence"  # never store prompts on disk
STRICT_MCP_FLAG = "--strict-mcp-config"
MCP_CONFIG_FLAG = "--mcp-config"  # with EMPTY_MCP: strip the user's MCP fleet
SETTING_SOURCES_FLAG = "--setting-sources"  # scoped mode
SAFE_MODE_FLAG = "--safe-mode"
BARE_FLAG = "--bare"
EMPTY_MCP = '{"mcpServers":{}}'

# Free probes (no model call).
VERSION_ARGS = ("--version",)
HELP_ARGS = ("--help",)
AUTH_STATUS_ARGS = ("auth", "status", "--text")  # exit code only; the text names the account
HELP_CACHE_TTL_SECONDS = 300

# --- Flag classes ---------------------------------------------------------------------------
# ALWAYS_SEND: guarantee-bearing, never gated on `--help` parsing. If upstream drops one,
# claude rejects it at arg-parse BEFORE any model call and the classifier says
# cli_contract_changed. HELP_GATED: dropping one only reduces depth or relies on a still-
# present primary guard; the value is whether the flag takes an argument.
ALWAYS_SEND_FLAGS = tuple(
    sorted(
        {
            "--output-format",
            NO_CHROME_FLAG,
            APPEND_SYSTEM_PROMPT_FLAG,
            MAX_BUDGET_FLAG,
            NO_SESSION_PERSISTENCE_FLAG,
            TOOLS_FLAG,
            STRICT_MCP_FLAG,
            MCP_CONFIG_FLAG,
            SETTING_SOURCES_FLAG,
            BARE_FLAG,
            SAFE_MODE_FLAG,
        }
    )
)
HELP_GATED_FLAGS: dict[str, bool] = {
    EFFORT_FLAG: True,
    MODEL_FLAG: True,
    DISALLOWED_TOOLS_FLAG: True,
}

# --- config_mode / access -------------------------------------------------------------------
CONFIG_MODES = ("inherit", "scoped", "safe", "bare")
DEFAULT_CONFIG_MODE = "inherit"
# Login-backed modes use Claude Code's OAuth/session path; a stale direct-credential env
# var must not override it, so these are stripped from the child env. bare NEEDS the key.
LOGIN_MODES = frozenset({"inherit", "scoped", "safe"})
LOGIN_CREDENTIAL_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
API_KEY_ENV = "ANTHROPIC_API_KEY"

ACCESS_MODES = ("toolless", "readonly")
DEFAULT_ACCESS = "toolless"
# --tools is the PRIMARY allowlist; --disallowed-tools is defense in depth. Never widen
# READONLY_TOOLS to a write or shell tool.
READONLY_TOOLS = "Read,Grep,Glob"
READONLY_DISALLOWED_TOOLS = "Edit,Write,NotebookEdit,Bash"
HOOK_SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")

# --- Reasoning effort, budget, versions -----------------------------------------------------
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "xhigh"
DEFAULT_MAX_BUDGET_USD = 1.00
MIN_BUDGET_USD, MAX_BUDGET_USD = 0.01, 5.00
# Advisory: a mismatch warns on amicus_backends, never blocks.
SUPPORTED_MAJORS = frozenset({2})

# --- The JSON envelope `claude -p --output-format json` prints -------------------------------
SUCCESS_SUBTYPES: tuple[str | None, ...] = (None, "success")
USAGE_KEYS = frozenset(
    {"input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"}
)

# --- Models (static, advisory) -------------------------------------------------------------
MODEL_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# (slug, display_name, kind). Aliases first: they track the latest model and are the
# recommended value; full IDs go stale per release.
KNOWN_MODELS: tuple[tuple[str, str, str], ...] = (
    ("opus", "Opus (alias → latest Opus)", "alias"),
    ("sonnet", "Sonnet (alias → latest Sonnet)", "alias"),
    ("haiku", "Haiku (alias → latest Haiku)", "alias"),
    ("fable", "Fable (alias → latest Fable)", "alias"),
    ("claude-opus-4-8", "Opus 4.8", "full"),
    ("claude-sonnet-4-6", "Sonnet 4.6", "full"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5", "full"),
    ("claude-fable-5", "Fable 5", "full"),
)

# --- Disclosure -----------------------------------------------------------------------------
READ_ONLY_HONESTY = (
    "access=toolless grants Claude no tools at all; access=readonly grants Read/Grep/Glob, "
    "which lets Claude read files itself — bypassing diff redaction — and Read accepts "
    "absolute paths outside the workspace. Neither is an OS sandbox."
)
IMPLICIT_CONTEXT_DISCLOSURE = (
    "What the claude CLI auto-loads depends on backend_options.config_mode: inherit/scoped "
    "read the workspace's CLAUDE.md and .claude/settings*.json — including hooks, which run "
    "OUTSIDE the tool allowlist (reported on meta.security_warnings); safe disables "
    "customizations and hooks while preserving the login; bare loads nothing but requires "
    "ANTHROPIC_API_KEY. Every mode strips the user's MCP servers."
)
# Wire prose that would teach a mechanism claude lacks or a sibling's vocabulary. The
# sibling's "kimi"/"moonbridge" canaries are NOT carried: this server hosts Kimi.
FORBIDDEN_SURFACE_PHRASES = ("codex exec", "kimi exec", "read-only sandbox", "applies the diff")

# --- Failure signatures ----------------------------------------------------------------------
# Narrow on purpose: a bare "/login" can appear in reviewed content or URLs.
_LOGGED_OUT_PATTERNS = (
    re.compile(r"\bnot logged in\b", re.I),
    re.compile(r"please run /login", re.I),
)
_INVALID_KEY_PATTERNS = (
    re.compile(r"\bapi_key_invalid\b", re.I),
    re.compile(r"\binvalid api key\b", re.I),
    re.compile(r"anthropic_api_key is invalid", re.I),
)
# The sibling matched the substrings "auth"/"login" on the STRUCTURED blob only; word-bounded
# here so "author" and "plugin" cannot read as authentication.
_AUTHISH_PATTERNS = (
    re.compile(r"\b(auth|authentication|authorization|unauthorized|unauthenticated)\b", re.I),
    re.compile(r"\blogin\b", re.I),
)
_BUDGET_PATTERNS = (re.compile(r"\bbudget\b", re.I),)
_PERMISSION_PATTERNS = (
    re.compile(r"\bpermission\b", re.I),
    re.compile(r"\baccess denied\b", re.I),
)
_RATE_LIMIT_PATTERNS = (
    re.compile(r"\b429\b"),
    re.compile(r"\b529\b"),
    re.compile(r"\brate[ _-]?limit(ed|_reached)?\b", re.I),
    re.compile(r"\btoo many requests\b", re.I),
    re.compile(r"\boverloaded\b", re.I),
)
# Phrasings claude (commander) prints when it rejects a flag or value amicus sent.
_DRIFT_PATTERNS = tuple(
    re.compile(re.escape(p), re.I)
    for p in (
        "unknown option",
        "unknown flag",
        "unknown argument",
        "unrecognized option",
        "unrecognized argument",
        "no such option",
        "invalid choice",
        "invalid value",
        "unexpected argument",
    )
)


def _any(patterns: tuple[re.Pattern[str], ...], texts: tuple[str | None, ...]) -> bool:
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return False
    return any(p.search(blob) for p in patterns)


def is_logged_out(*texts: str | None) -> bool:
    return _any(_LOGGED_OUT_PATTERNS, texts)


def is_invalid_api_key(*texts: str | None) -> bool:
    return _any(_INVALID_KEY_PATTERNS, texts)


def mentions_auth(*texts: str | None) -> bool:
    return _any(_AUTHISH_PATTERNS, texts)


def is_budget_stop(*texts: str | None) -> bool:
    return _any(_BUDGET_PATTERNS, texts)


def is_permission_denied(*texts: str | None) -> bool:
    return _any(_PERMISSION_PATTERNS, texts)


def is_rate_limited(*texts: str | None) -> bool:
    return _any(_RATE_LIMIT_PATTERNS, texts)


def is_contract_drift(*texts: str | None) -> bool:
    return _any(_DRIFT_PATTERNS, texts)


# --- The pontonier contract -----------------------------------------------------------------
CONTRACT = _pc.BackendContract(
    backend_id="claude",
    display_name="Claude Code",
    bin_name=CLAUDE_BIN,
    env_prefix="AMICUS_CLAUDE_",
    exec_argv_prefix=CORE_INVOCATION,
    always_send_flags=ALWAYS_SEND_FLAGS,
    help_gated_flags=tuple(sorted(HELP_GATED_FLAGS)),
    forbidden_surface_phrases=FORBIDDEN_SURFACE_PHRASES,
    # Review-only by design: no delegate (--no-session-persistence is ALWAYS sent and the
    # tool allowlist never includes a write tool). adversarial_review is the Claude-only
    # verb in v1. Usage comes from the envelope, so its keys are the markers.
    supported_features=frozenset({"adversarial_review", "usage_accounting"}),
    readonly_honesty_statement=READ_ONLY_HONESTY,
    implicit_context_disclosure=IMPLICIT_CONTEXT_DISCLOSURE,
    structured_output="prompt_append",
    model_catalog=_pc.ModelCatalog(
        strategy="static",
        model_identifier_authority="advisory",
        effort_metadata_authority="advisory",
    ),
    extra_args=_pc.ExtraArgsPolicy(reserved_keys=frozenset({"model", "effort"})),
    isolation_policy=_pc.IsolationPolicy.TOOL_ALLOWLIST,
    needs_orphan_sweep=False,
    # claude rejects a bad --effort at arg-parse (loud), and the adapter enforces
    # VALID_EFFORTS pre-spend anyway.
    effort_silently_ignored_upstream=False,
    effort_validation="enumerated",
    usage_event_markers=tuple(sorted(USAGE_KEYS)),
    failure_signatures=_pc.FailureSignatures(
        auth=tuple(f"(?i){p.pattern}" for p in _LOGGED_OUT_PATTERNS),
        contract_drift=tuple(f"(?i){p.pattern}" for p in _DRIFT_PATTERNS),
        rate_limited=tuple(f"(?i){p.pattern}" for p in _RATE_LIMIT_PATTERNS),
    ),
)
