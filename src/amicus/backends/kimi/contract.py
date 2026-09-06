"""Single source of truth for the external `kimi` (Kimi Code) CLI contract, ported from
moonbridge `cli_contract.py` (verified by the sibling against 0.35.0 and 0.39.1) and
re-verified against 0.41.0 by the captures in docs/kimi-help/0.41.0/.

`kimi -p` is NOT `codex exec`. Three differences drive the whole design:

1. There is no sandbox and there are no approvals. Prompt mode runs Bash and writes files
   with zero gating, and a worktree changes kimi's cwd, not its reach. The read-only
   control is READ_ONLY_AGENT_TOOLS, delivered per run via --agent-file.
2. The prompt is argv-only: stdin is ignored, and argv past ~950k chars crashes kimi with a
   Node RangeError. So the real prompt travels in a handshake file OUTSIDE the workspace
   and argv carries a short pointer to it.
3. There is no --output-last-message. The answer is recovered from the stream-json
   assistant lines or, when the tier has a Write tool, from an answer file the prompt asks
   kimi to produce.
"""

from __future__ import annotations

import re

from pontonier.backend import contract as _pc

KIMI_BIN = "kimi"

# kimi has no `exec` subcommand; headless runs ride the top-level `-p/--prompt` flag.
EXEC_SUBCOMMAND: tuple[str, ...] = ()
# Long forms only: the help probe parses long flags out of `kimi --help`.
PROMPT_FLAG = "--prompt"
OUTPUT_FORMAT_FLAG = "--output-format"
OUTPUT_FORMAT_JSON = "stream-json"
MODEL_FLAG = "--model"  # takes a config.toml ALIAS, not a raw provider model id
AGENT_FILE_FLAG = "--agent-file"  # the read-only guarantee; incompatible with --session
SKILLS_DIR_FLAG = "--skills-dir"  # replaces auto-discovered skill dirs (built-ins still load)
ADD_DIR_FLAG = "--add-dir"  # never sent: it would punch through worktree isolation
PROMPT_MODE_INCOMPATIBLE_FLAGS = (
    "-y",
    "--yolo",
    "--auto",
    "--plan",
    "-S",
    "--session",
    "-c",
    "--continue",
)

# Free probes (no model call).
VERSION_ARGS = ("--version",)
HELP_ARGS = ("--help",)
PROVIDER_LIST_ARGS = ("provider", "list", "--json")
HELP_CACHE_TTL_SECONDS = 300

# --- The read-only guarantee -------------------------------------------------------------
# Bash is deliberately absent: it can write. Verified on 0.35.0/0.39.1 that an agent file
# declaring exactly these three reports exactly these three.
READ_ONLY_AGENT_TOOLS = ("Read", "Glob", "Grep")
READ_ONLY_AGENT_NAME = "amicus-readonly"
READ_ONLY_CONFIDENTIALITY_LIMIT = (
    "Read-only means Kimi cannot MODIFY anything — it has no shell or write tool. It does "
    "NOT mean Kimi can only see the workspace: its Read tool accepts absolute paths, so a "
    "prompt-injected repository could make it read other files on this machine and send "
    "them to your configured Kimi provider. Do not point it at a workspace whose contents "
    "you would not hand to that provider."
)
# Wire prose that would teach a mechanism kimi lacks.
FORBIDDEN_SURFACE_PHRASES = ("kimi exec", "read-only sandbox")

# --- The file handshake -------------------------------------------------------------------
# Written OUTSIDE the workspace (a mkdtemp dir; symlink defense in cli.create_handshake_dir).
HANDSHAKE_DIR_PREFIX = "amicus-kimi-handshake-"
PROMPT_FILE_NAME = "prompt.md"
AGENT_FILE_NAME = "readonly-agent.md"
ANSWER_FILE_NAME = "answer.md"  # only a write-capable (delegate) run can produce it
MAX_ARGV_PROMPT_CHARS = 8_000  # far below the ~950k crash edge

# --- Reasoning effort ----------------------------------------------------------------------
# kimi has no effort FLAG; effort rides an env var and the accepted values are per model.
REASONING_EFFORT_ENV = "KIMI_MODEL_THINKING_EFFORT"
MODEL_OUTPUT_FORMAT_ENV = "KIMI_MODEL_OUTPUT_FORMAT"
# Shape of an effort token (our policy, not a kimi claim): anything that could be a level.
REASONING_EFFORT_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,31}")
# Used ONLY when the catalog is silent: kimi silently ignores an unrecognized effort, so
# refusing on a closed set is safer than spending on a guess.
REASONING_EFFORT_FALLBACK_VOCABULARY = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "max"}
)

# --- Flag classes ---------------------------------------------------------------------------
ALWAYS_SEND_FLAGS = (PROMPT_FLAG, OUTPUT_FORMAT_FLAG, AGENT_FILE_FLAG)
HELP_GATED_FLAGS: dict[str, bool] = {MODEL_FLAG: True, SKILLS_DIR_FLAG: True}

# --- Posture labels (NOT kimi flags) ------------------------------------------------------
SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"

# Advisory: a mismatch warns on amicus_backends, never blocks. (0, 41) is supported on the
# evidence in docs/kimi-help/0.41.0/.
SUPPORTED_VERSIONS = frozenset({(0, 35), (0, 39), (0, 41)})

# --- Models --------------------------------------------------------------------------------
MODEL_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
MODELS_CACHE_MAX_BYTES = 1_000_000
MODELS_CACHE_MAX_ENTRIES = 256
SUPPORTED_EFFORTS_MAX_ENTRIES = 16

# --- stream-json event surface --------------------------------------------------------------
# Verified line shapes on stdout (stderr carries raw tool output and warnings):
#   {"role":"meta","type":"system.version","version":"0.41.0"}          <- first
#   {"role":"assistant","content":"...","tool_calls":[...]}
#   {"role":"tool","tool_call_id":"...","content":"..."}
#   {"role":"meta","type":"session.resume_hint","session_id":"..."}     <- last
#   {"type":"goal.summary",...}                                        <- goal mode only
# `tool_call_id` is NOT unique within a run; `goal.summary` carries no "role".
ROLE_KEY = "role"
TYPE_KEY = "type"
ROLE_ASSISTANT = "assistant"
CONTENT_KEY = "content"
# kimi emits no per-turn token accounting outside goal mode; meta.usage stays null then.
USAGE_EVENT_MARKERS = ("tokensUsed", "turnsUsed")

# --- Disclosure -----------------------------------------------------------------------------
SKILLS_DISCOVERY_FACT = (
    "Kimi auto-loads the resolved workspace's AGENTS.md and discovers skills from its own "
    "config (including `extra_skill_dirs`, which may point outside the workspace)."
)
SKILLS_DISCOVERY_FACT_FULL = (
    SKILLS_DISCOVERY_FACT
    + " Skill names and descriptions are exposed to the model up front, so that content can "
    "be sent even if your prompt never mentions it. The isolation option does not suppress "
    "any of it: kimi's built-in skills always load, and AGENTS.md is read regardless."
)
REDACTION_LIMIT_FACT = (
    "Your inputs are sent raw and unredacted. Secret redaction is best-effort and covers "
    "the gathered diff and Kimi's returned output — not what you type, and not the files "
    "Kimi reads for itself."
)
SKILLS_ISOLATION_NOTE = (
    "backend_options.isolation='ignore-skills' replaces the auto-discovered user/project "
    "skill directories via --skills-dir, but kimi's BUILT-IN skills still load. It is a "
    "reduction in exposure, not an elimination."
)

# --- Failure signatures -----------------------------------------------------------------------
# Auth failures come from the user-configured provider, so these stay generic.
_AUTH_PATTERNS = (
    re.compile(r"\b401\b|\bunauthorized\b", re.I),
    re.compile(r"\binvalid[_ -]?api[_ -]?key\b", re.I),
    re.compile(r"\bauthentication (failed|error|required)\b", re.I),
    re.compile(r"\bno api key\b|\bapi[_ -]?key (is )?(missing|not set)\b", re.I),
    re.compile(r"\brun `?kimi login`?", re.I),
)
# kimi/commander rejecting a flag or value the plugin sent.
_DRIFT_PATTERNS = (
    re.compile(r"error: unknown option", re.I),
    re.compile(r"error: option .* argument missing", re.I),
    re.compile(r"\ballowed choices are\b|\binvalid argument\b", re.I),
    re.compile(r"Output format is only supported in prompt mode", re.I),
    re.compile(r"Cannot combine --prompt with", re.I),
    re.compile(r"Cannot use --session without an id", re.I),
    re.compile(r"unknown command", re.I),
)
# Two captured phrasings for an alias kimi cannot resolve. The second is anchored on the
# `failed to run prompt:` prefix because its tail is ordinary English that the MODEL's own
# prose (searched too) could contain; a false negative beats blaming a fine `model`.
_INVALID_MODEL_PATTERNS = (
    re.compile(r'Model ".*?" is not configured in config\.toml', re.I),
    re.compile(r"failed to run prompt: model \S+ does not resolve to a configured provider", re.I),
)
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


def is_unresolved_default_model(*texts: str | None) -> bool:
    """The unresolvable alias is config.toml's `default_model`, not the caller's `model`."""
    return _any((_INVALID_MODEL_PATTERNS[1],), texts)


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


# --- The pontonier contract -----------------------------------------------------------------
CONTRACT = _pc.BackendContract(
    backend_id="kimi",
    display_name="Kimi",
    bin_name=KIMI_BIN,
    env_prefix="AMICUS_KIMI_",
    exec_argv_prefix=EXEC_SUBCOMMAND,
    always_send_flags=ALWAYS_SEND_FLAGS,
    help_gated_flags=tuple(sorted(HELP_GATED_FLAGS)),
    forbidden_surface_phrases=FORBIDDEN_SURFACE_PHRASES,
    supported_features=frozenset({"delegate", "model_validation", "empty_response_detection"}),
    readonly_honesty_statement=READ_ONLY_CONFIDENTIALITY_LIMIT,
    implicit_context_disclosure=SKILLS_DISCOVERY_FACT_FULL,
    structured_output="prompt_append",
    model_catalog=_pc.ModelCatalog(
        strategy="live_probe",
        # kimi rejects an unknown alias outright, but only ADVISES on efforts.
        model_identifier_authority="authoritative",
        effort_metadata_authority="advisory",
    ),
    isolation_policy=_pc.IsolationPolicy.WORKTREE_ALL_TIERS,
    needs_orphan_sweep=True,
    # Verified: kimi SILENTLY IGNORES an unrecognized effort (exit 0, default effort), so
    # pre-spend validation is the only protection (adapter.validate_request).
    effort_silently_ignored_upstream=True,
    effort_validation="token_floor_plus_catalog",
    usage_event_markers=USAGE_EVENT_MARKERS,
    failure_signatures=_pc.FailureSignatures(
        auth=tuple(f"(?i){p.pattern}" for p in _AUTH_PATTERNS),
        contract_drift=tuple(f"(?i){p.pattern}" for p in _DRIFT_PATTERNS),
        invalid_model=tuple(f"(?i){p.pattern}" for p in _INVALID_MODEL_PATTERNS),
        rate_limited=tuple(f"(?i){p.pattern}" for p in _RATE_LIMIT_PATTERNS),
    ),
    limits=_pc.Limits(
        max_argv_prompt_chars=MAX_ARGV_PROMPT_CHARS,
        handshake_dir_name=HANDSHAKE_DIR_PREFIX,
        answer_file_name=ANSWER_FILE_NAME,
    ),
)
