"""Single source of truth for the external `pi` (pi-mono coding agent) CLI contract, verified
against 1.5.0 by the captures under docs/pi-help/ and the zero-spend probe on issue #423.

`pi -p --mode json` differs from the other backends in three ways that drive the design:

1. There is no sandbox and there are no approvals. Read-only is the `--tools` allowlist, and a
   worktree changes pi's cwd, not its reach.
2. The prompt travels on stdin. argv carries only the fixed `PI_SYSTEM_PROMPT` literal.
3. `--no-session` leaves no session file, so there is no carrier to disclose beyond stdin.
"""

from __future__ import annotations

import re

from amicus.sdk.backend import contract as _pc

PI_BIN = "pi"

# `--system-prompt` replaces pi's default prompt. Pi reads a file when the value names an
# existing path, so this literal has no "/" and is longer than 255 bytes: it is then one path
# component longer than any filesystem allows, and cannot exist relative to any directory.
PI_SYSTEM_PROMPT = (
    "You are a careful software engineering assistant working for another AI agent that has "
    "asked for a second opinion. Follow the instructions in the user message exactly, "
    "including any requested output format. Use only the tools you have been given. Base "
    "every claim on what you read in the files you inspect, say plainly when you could not "
    "verify something, and never invent file contents, line numbers or command output. "
    "Keep your final answer complete and self-contained."
)

READ_ONLY_TOOLS: tuple[str, ...] = ("read", "grep", "find", "ls")
WRITE_TOOLS: tuple[str, ...] = ("read", "bash", "edit", "write", "grep", "find", "ls")

# Sent on every run and on every probe that can load resources (`--help`, `--list-models`):
# pi builds its runtime and loads resources before it handles either.
SUPPRESSION_FLAGS: tuple[str, ...] = (
    "--no-context-files",
    "--no-skills",
    "--no-extensions",
    "--no-mcp",
    "--no-prompt-templates",
    "--no-themes",
    "--no-approve",
    "--offline",
)
RUN_FLAGS: tuple[str, ...] = ("-p", "--mode", "json", "--no-session", *SUPPRESSION_FLAGS)

SYSTEM_PROMPT_FLAG = "--system-prompt"
APPEND_SYSTEM_PROMPT_FLAG = "--append-system-prompt"  # sent with "" so APPEND_SYSTEM.md is inert
TOOLS_FLAG = "--tools"
MODEL_FLAG = "--model"
THINKING_FLAG = "--thinking"
# Every long flag a run sends, for the help probe. `--thinking` is sent only with an effort.
ALWAYS_SEND_FLAGS: tuple[str, ...] = (
    "--mode",
    "--no-session",
    *SUPPRESSION_FLAGS,
    SYSTEM_PROMPT_FLAG,
    APPEND_SYSTEM_PROMPT_FLAG,
    TOOLS_FLAG,
    MODEL_FLAG,
)

# Reasoning effort: pi accepts these per `pi --help` and clamps one the model lacks.
EFFORTS: tuple[str, ...] = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

# Free probes (no model call).
VERSION_ARGS = ("--version",)
HELP_ARGS = ("--help", *SUPPRESSION_FLAGS)
LIST_MODELS_ARGS = ("--list-models",)  # callers append the id and SUPPRESSION_FLAGS
AUTH_CHECK_ARGS = ("auth", "check", "--json", "--no-refresh")  # callers add --model <model>

# Advisory: a mismatch warns on amicus_backends, never blocks.
SUPPORTED_VERSIONS = frozenset({(1, 5)})

# Posture labels (NOT pi flags).
SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"

# Child environment. Provider credentials and PI_CODING_AGENT_DIR are inherited: they are what
# authenticate the run. A session directory override is dropped so nothing is redirected.
RUN_ENV_SET: dict[str, str] = {"PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1"}
RUN_ENV_DROP: tuple[str, ...] = ("PI_CODING_AGENT_SESSION_DIR",)

# pi 1.5.0 has no `pi auth login`.
LOGIN_HINT = (
    "Start `pi` interactively and run `/login <provider>`, or set the provider's API-key "
    "environment variable (for OpenRouter, OPENROUTER_API_KEY)."
)

# --- Disclosures -------------------------------------------------------------------------
EGRESS = (
    "The prompt and, for reviews, the secret-redacted diff go to the provider the model's "
    "prefix names, through pi. Pi can read files outside the workspace, up to everything the "
    "OS user can read."
)
CARRIERS = (
    "The prompt rides stdin. argv carries only amicus's fixed system prompt, the model, the "
    "effort and flags. With --no-session pi wrote no session file on 1.5.0 after a success, a "
    "provider failure or a SIGTERM mid-request."
)
READ_ONLY_HONESTY = (
    "Read-only means pi has no shell, edit or write tool. It does not confine reads, so a "
    "prompt-injected repository could make pi read other files on this machine and send them "
    "to your configured provider, and it is no OS sandbox. It does not stop pi itself, at "
    "startup, renaming the workspace's .pi/commands/ to .pi/prompts/ when the latter does "
    "not exist."
)
IMPLICIT_CONTEXT_DISCLOSURE = (
    "Pi adds the working directory to its system prompt. User-level settings, `models.json` "
    "(whose `!command` key values pi runs) and credentials load. Context files, skills, "
    "extensions, MCP, prompt templates, themes and trust-gated project resources do not. A "
    "project `sessionDir` setting is read before trust is resolved, and under --no-session "
    "nothing was written there on 1.5.0. At startup pi renames the workspace's "
    ".pi/commands/ to .pi/prompts/ when the latter does not exist, so a consult or review in "
    "such a repository changes it; amicus cannot suppress this. amicus's own free probes run "
    "from a private directory of its own, or do not run, so they never do it."
)

# --- Failure signatures -------------------------------------------------------------------
_AUTH_PATTERNS = (
    re.compile(r"\b401\b|\bunauthorized\b", re.I),
    re.compile(r"\binvalid[_ -]?api[_ -]?key\b", re.I),
    re.compile(r"\bauthentication (failed|error|required)\b", re.I),
    re.compile(r"\bno api key\b|\bapi[_ -]?key (is )?(missing|not set)\b", re.I),
)
# pi rejecting a flag the plugin sent.
_DRIFT_PATTERNS = (re.compile(r"error: unknown option", re.I),)
# Anchored on the quoted id: the bare phrase is ordinary English the model's prose could hold.
_INVALID_MODEL_PATTERNS = (re.compile(r'\bModel ".*?" not found', re.I),)
_RATE_LIMIT_PATTERNS = (
    re.compile(r"\b429\b", re.I),
    re.compile(r"\brate[ _-]?limit(ed|_reached)?\b", re.I),
    re.compile(r"\btoo many requests\b", re.I),
    re.compile(r"\bquota (exceeded|exhausted)\b", re.I),
)
RATE_LIMIT_DEFAULT_BACKOFF_MS = 60_000
_RETRY_AFTER_PATTERNS = (
    re.compile(r"retry[- _]?after[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)\s*(ms|s|seconds?)?", re.I),
    re.compile(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s|seconds?|minutes?)", re.I),
)


def _any(patterns: tuple[re.Pattern[str], ...], texts: tuple[str | None, ...]) -> bool:
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return False
    return any(p.search(blob) for p in patterns)


def is_auth_failure(*texts: str | None) -> bool:
    return _any(_AUTH_PATTERNS, texts)


def is_contract_drift(*texts: str | None) -> bool:
    return _any(_DRIFT_PATTERNS, texts)


def is_invalid_model(*texts: str | None) -> bool:
    return _any(_INVALID_MODEL_PATTERNS, texts)


def is_rate_limited(*texts: str | None) -> bool:
    return _any(_RATE_LIMIT_PATTERNS, texts)


def parse_retry_after_ms(*texts: str | None) -> int | None:
    """A retry delay in ms, or None when the text carries none. Returns 0 faithfully."""
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return None
    for pattern in _RETRY_AFTER_PATTERNS:
        m = pattern.search(blob)
        if not m:
            continue
        value = float(m.group(1))
        unit = (m.group(2) or "s").lower()
        if unit == "ms":
            return int(value)
        if unit.startswith("minute"):
            return int(value * 60_000)
        return int(value * 1000)
    return None


# --- The SDK contract -----------------------------------------------------------------
CONTRACT = _pc.BackendContract(
    backend_id="pi",
    display_name="Pi",
    bin_name=PI_BIN,
    env_prefix="AMICUS_PI_",
    exec_argv_prefix=(),
    always_send_flags=ALWAYS_SEND_FLAGS,
    help_gated_flags=(),
    forbidden_surface_phrases=("pi auth login", "read-only sandbox"),
    supported_features=frozenset({"delegate", "model_validation", "empty_response_detection"}),
    readonly_honesty_statement=READ_ONLY_HONESTY,
    implicit_context_disclosure=IMPLICIT_CONTEXT_DISCLOSURE,
    structured_output="prompt_append",
    model_catalog=_pc.ModelCatalog(
        strategy="live_probe",
        # pi sends an unknown id anyway, so identifiers are checked pre-spend against the
        # catalog; effort metadata only advises (pi clamps an unsupported effort).
        model_identifier_authority="authoritative",
        effort_metadata_authority="advisory",
    ),
    isolation_policy=_pc.IsolationPolicy.WORKTREE_ALL_TIERS,
    needs_orphan_sweep=True,
    effort_silently_ignored_upstream=True,
    effort_validation="token_floor_plus_catalog",
    failure_signatures=_pc.FailureSignatures(
        auth=tuple(f"(?i){p.pattern}" for p in _AUTH_PATTERNS),
        contract_drift=tuple(f"(?i){p.pattern}" for p in _DRIFT_PATTERNS),
        invalid_model=tuple(f"(?i){p.pattern}" for p in _INVALID_MODEL_PATTERNS),
        rate_limited=tuple(f"(?i){p.pattern}" for p in _RATE_LIMIT_PATTERNS),
    ),
)
