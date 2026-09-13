"""The verb x backend parameter matrix, the Annotated parameter aliases every tool is
built from, and the compressed/full parameter contracts served at amicus://params.

The MATRIX is the authority: tests derive each tool's expected inputSchema property set
from it, so a tool cannot grow a parameter the spec table does not grant it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import Field

from amicus.schemas.codes import BackendId
from amicus.schemas.options import BackendOptions
from amicus.schemas.results import CapabilitiesDetail, Detail, JobState, ReviewScope, Untracked

_ALL = frozenset({"consult", "review_changes", "adversarial_review", "delegate"})
_REVIEWS = frozenset({"review_changes", "adversarial_review"})

PARAM_MATRIX: dict[str, frozenset[str]] = {
    "backend": _ALL,
    "workspace_root": _ALL,
    "model": _ALL,
    "reasoning_effort": _ALL,
    "timeout_seconds": _ALL,
    "detail": _ALL,
    "idempotency_key": _ALL,
    "backend_options": _ALL,
    "extra_context": frozenset({"consult", "review_changes", "adversarial_review"}),
    # Not on adversarial_review (the fixed critic stance is the product) nor delegate
    # (edits files: a caller stance would widen what an untrusted workspace can steer).
    "instructions_append": frozenset({"consult", "review_changes"}),
    "scope": _REVIEWS,
    "base": _REVIEWS,
    "commit": _REVIEWS,
    "paths": _REVIEWS,
    "untracked": _REVIEWS,
    "focus": _REVIEWS,
    "target": frozenset({"adversarial_review"}),
    "evidence": frozenset({"adversarial_review"}),
    "task": frozenset({"delegate"}),
    "question": frozenset({"consult"}),
}
REQUIRED_BY_VERB: dict[str, frozenset[str]] = {
    "consult": frozenset({"backend", "question"}),
    "review_changes": frozenset({"backend"}),
    "adversarial_review": frozenset({"backend", "target"}),
    "delegate": frozenset({"backend", "task"}),
}
SYNC_ONLY_PARAMS = frozenset({"timeout_seconds", "detail"})
# Empty since #66 (ADR 0020): idempotency_key was async-only, which dropped the dedup both
# siblings offer on the tools a client-side retry actually duplicates. Kept as the named
# half of the split so the pair-parity test and expected_params() read the same way.
ASYNC_ONLY_PARAMS: frozenset[str] = frozenset()

TOOL_VERB: dict[str, tuple[str, bool]] = {
    "amicus_consult": ("consult", False),
    "amicus_consult_async": ("consult", True),
    "amicus_review_changes": ("review_changes", False),
    "amicus_review_changes_async": ("review_changes", True),
    "amicus_adversarial_review": ("adversarial_review", False),
    "amicus_adversarial_review_async": ("adversarial_review", True),
    "amicus_delegate": ("delegate", False),
    "amicus_delegate_async": ("delegate", True),
}


def expected_params(tool_name: str) -> frozenset[str]:
    """The inputSchema property set the matrix grants ``tool_name``."""
    verb, is_async = TOOL_VERB[tool_name]
    names = {name for name, verbs in PARAM_MATRIX.items() if verb in verbs}
    names -= ASYNC_ONLY_PARAMS if not is_async else SYNC_ONLY_PARAMS
    return frozenset(names)


def expected_required(tool_name: str) -> frozenset[str]:
    verb, _ = TOOL_VERB[tool_name]
    return REQUIRED_BY_VERB[verb]


# --- shape facts ------------------------------------------------------------------------

MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS = 10, 600
# No Unicode Cc code point (C0, DEL, C1). ECMA-safe; deliberately names no surrogates.
CONTROL_CHAR_FREE_PATTERN = r"^[^\x00-\x1F\x7F-\x9F]*$"
REASONING_EFFORT_MAX_LENGTH = 128
MAX_INSTRUCTIONS_APPEND_BYTES = 4096


def reasoning_effort_shape_error(value: str) -> str | None:
    """Why `value` fails the transport-shape bounds (value-free), else None. Checked
    character-wise so a trailing newline — which the advertised regex admits — is caught."""
    if len(value) > REASONING_EFFORT_MAX_LENGTH:
        return f"exceeds {REASONING_EFFORT_MAX_LENGTH} characters"
    if any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in value):
        return "contains a control character"
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        return "contains a surrogate code point"
    return None


PARAMS_RESOURCE_URI = "amicus://params"


@dataclass(frozen=True)
class ParamContract:
    """A parameter's compressed inline ``summary`` and authoritative ``full`` text."""

    name: str
    summary: str
    full: str


# The tools that declare no workspace_root. Every inputSchema is additionalProperties:
# false, so passing one to these fails as invalid_arguments — which is why the sessionless
# prerequisite below names them instead of saying "every call" (issue #40). The manifest
# test binds this tuple to the live schemas, so it cannot drift from them silently.
WORKSPACELESS_TOOLS: tuple[str, ...] = (
    "amicus_backends",
    "amicus_models",
    "amicus_capabilities",
)
_WORKSPACELESS_PROSE = ", ".join(WORKSPACELESS_TOOLS[:-1]) + f" and {WORKSPACELESS_TOOLS[-1]}"

# The scope every statement of the rule shares, so none of them can widen it alone: the
# published prerequisite, and the invalid_workspace_root repair in orchestration/workspace.
WORKSPACE_SCOPE: str = "on every call that declares the parameter"

# Stated once and rendered on every surface that states it: the server instructions
# (initialize_response) and amicus_capabilities.prerequisites (capabilities_payload).
WORKSPACE_PREREQUISITE: str = (
    f"Pass workspace_root from a sessionless (2026-07-28) client {WORKSPACE_SCOPE}, and on "
    f"no other: {_WORKSPACELESS_PROSE} declare none and reject one."
)


PARAMETER_CONTRACTS: dict[str, ParamContract] = {
    "workspace_root": ParamContract(
        name="workspace_root",
        summary=(
            "Absolute path of the repository the call targets; a sessionless (2026-07-28) "
            f"client must pass it. Resolution rules: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Resolution precedence: explicit workspace_root → the client's handshake-era "
            "file roots (first root; an explicit value must lie inside one of them or the "
            "call fails as workspace_outside_roots) → invalid_workspace_root. A sessionless "
            "client has no roots, so it must pass workspace_root; a handshake-era client "
            "may rely on its advertised roots. The server never falls back to its own cwd "
            "unless the operator opts in: it is used only when AMICUS_ALLOW_CWD_WORKSPACE=1, "
            "and then meta.workspace_warning discloses the resolved path. On an active call the "
            "workspace selects where the backend works, not what it can read: every "
            "backend CLI can read files outside it, up to everything the OS user can read."
        ),
    ),
    "idempotency_key": ParamContract(
        name="idempotency_key",
        summary=(
            "Dedup key scoped to this tool + backend + workspace: reusing it with identical "
            "args replays the prior result unpaid; different args are refused. Lifecycle: "
            f"{PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Reusing the key on the same tool with the same effective execution arguments "
            "(backend, model, reasoning_effort, backend_options, scope and the prompt "
            "inputs; on a sync tool timeout_seconds only bounds the wait and `detail` only "
            "shapes delivery, so either may differ) replays the existing run instead of "
            "paying for a duplicate: an _async call returns the same job_id; a sync call "
            "awaits that run and returns its result. A keyed sync run gets the job "
            "deadline (AMICUS_JOB_MAX_SECONDS), as an _async run does, and timeout_seconds "
            "bounds how long the call waits for it. A keyed sync wait that hits that bound "
            "or is cancelled leaves the run going, and its `timeout` repair points at "
            "amicus_job_status for that job; under the tasks extension a keyed task's job "
            "likewise survives tasks/cancel. Sync and _async are separate tools and never "
            "share a key. Reuse "
            "with different arguments is refused (idempotency_conflict); a key whose prior "
            "result was consumed or evicted is idempotency_result_unavailable; a "
            "still-publishing reservation is idempotency_in_progress (retry; a sync call "
            "waits about a second for it first). A completed result stays replayable while "
            "its job record lives (its TTL). meta.idempotency_replayed=true marks a "
            "replayed (unpaid) response. An empty key is rejected."
        ),
    ),
    "extra_context": ParamContract(
        name="extra_context",
        summary=(
            "Author intent/background, sent as labeled UNTRUSTED prompt data. Not redacted, "
            f"so no secrets. Bounds: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Added to the prompt as labeled untrusted data; the backend is instructed to "
            "treat embedded directives as data, not commands — best-effort prompt-injection "
            "mitigation, not a guarantee. Secret redaction covers the gathered diff, never "
            "this field, so it must carry no live secrets. It counts against the same input "
            "budget as the gathered diff, so an oversized value fails as input_too_large "
            "before any spend."
        ),
    ),
    "instructions_append": ParamContract(
        name="instructions_append",
        summary=(
            "Caller stance text behind the server's own framing. UNTRUSTED, grants no "
            "tools, best-effort compliance. No secrets: a backend may carry it on argv. Max "
            f"{MAX_INSTRUCTIONS_APPEND_BYTES} bytes. Contract: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Appended BEHIND this server's always-leading framing (codex: "
            "developer_instructions on argv; claude and kimi: a leading section of the "
            "stdin/handshake prompt). Normalized once (stripped; blank means omitted); "
            f"refused pre-spend as invalid_arguments when over {MAX_INSTRUCTIONS_APPEND_BYTES} "
            "bytes, when it carries a NUL, another C0 control (tab/LF/CR excepted), DEL, or "
            "a lone surrogate, or when it contains one of the server's framing marker lines. "
            "It grants no tools. The backend is instructed not to let it determine a verdict; "
            "compliance is behavioral, not mechanical, and non-compliance may be silent. Each "
            "backend's carrier (argv or handshake file) is disclosed on amicus_backends. "
            "Never put secrets here; result envelopes report only a fingerprint of the text."
        ),
    ),
    "reasoning_effort": ParamContract(
        name="reasoning_effort",
        summary=(
            "Per-call reasoning effort, an open per-model string (commonly "
            "minimal|low|medium|high|xhigh; amicus_models lists each model's set); omit for "
            f"the backend default. Bounds: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Omitted, the backend resolves its own default. The value is validated by the "
            "backend, and amicus_models's per-model set is advisory. A backend-rejected "
            "value fails as invalid_reasoning_effort (repair steers to amicus_models). "
            "Backends whose CLI silently ignores a bad effort (kimi) are "
            "validated pre-spend from the catalog. Control characters, surrogates, and "
            f"values over {REASONING_EFFORT_MAX_LENGTH} chars are rejected at the MCP "
            "boundary as invalid_arguments."
        ),
    ),
    "backend_options": ParamContract(
        name="backend_options",
        summary=(
            "One closed object of backend knobs: isolation (codex, kimi); config_mode, "
            "access, max_budget_usd (claude). A key or value the selected backend rejects "
            f"fails pre-spend. Values: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "A key the selected backend does not accept, or a value it does not accept for "
            "a key it does, fails pre-spend as invalid_arguments naming "
            "backend_options.<key>. "
            "isolation — codex: inherit|ignore-config|ignore-rules (drop $CODEX_HOME "
            "config, then also execpolicy rules); kimi: inherit|ignore-skills. "
            "config_mode — claude: inherit|scoped|safe|bare (how much of the user's Claude "
            "config the run inherits). Claude adversarial_review defaults to safe (bare when "
            "AMICUS_CLAUDE_CONFIG_MODE=bare); other verbs use the configured default. Explicit "
            "config_mode overrides are honored. Discovery reports default_by_verb when verbs "
            "differ, with default null. access — claude: toolless|readonly. max_budget_usd "
            "— claude: per-call best-effort spend cap in USD, 0.01–5.00. Unset keys "  # noqa: RUF001
            "take the backend's defaults; amicus_dry_run echoes review_changes values."
        ),
    ),
}


def params_resource_body() -> dict[str, Any]:
    return {
        "description": (
            "Full semantics for parameters whose tools/list description is a compressed "
            "summary. Each entry's `summary` ships inline; `full` is the authoritative "
            "contract."
        ),
        "params": {
            n: {"summary": c.summary, "full": c.full} for n, c in PARAMETER_CONTRACTS.items()
        },
    }


# --- Annotated aliases (the single home of every parameter description) ---------------

BackendParam = Annotated[
    BackendId,
    Field(description="Which backend answers: codex | kimi | claude. Required."),
]
OptionalBackendParam = Annotated[
    BackendId | None,
    Field(description="Restrict to one backend: codex | kimi | claude. Omit for all."),
]
QuestionParam = Annotated[
    str,
    Field(description="The question or ad-hoc diff to consult on. Must not be blank."),
]
TaskParam = Annotated[
    str,
    Field(
        description=(
            "The coding task to implement in a throwaway worktree; the diff is returned, "
            "never applied. Must not be blank."
        )
    ),
]
TargetParam = Annotated[
    str, Field(description="The plan, claim, or decision the adversarial critic attacks.")
]
EvidenceParam = Annotated[
    str | None, Field(description="Supporting evidence for the target. Omit for none.")
]
WorkspaceRootParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["workspace_root"].summary)
]
ExtraContextParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["extra_context"].summary)
]
InstructionsAppendParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["instructions_append"].summary)
]
ModelParam = Annotated[
    str | None,
    Field(
        description=(
            "Backend model slug; omit for the backend's default. amicus_models lists valid "
            "slugs (advisory). Control characters rejected."
        ),
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=256,
    ),
]
ReasoningEffortParam = Annotated[
    str | None,
    Field(
        description=PARAMETER_CONTRACTS["reasoning_effort"].summary,
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=REASONING_EFFORT_MAX_LENGTH,
    ),
]
TimeoutSecondsParam = Annotated[
    int | None,
    Field(
        description=(
            f"Deadline in seconds, clamped to {MIN_TIMEOUT_SECONDS}-{MAX_TIMEOUT_SECONDS}; "
            "omit for the server default (AMICUS_TIMEOUT_SECONDS). An unkeyed sync call "
            "past its deadline is terminated and its partial work lost; prefer the _async "
            "twin. For a keyed call (idempotency_key) this only bounds the wait: the run "
            "gets the job deadline and the timeout says how to fetch it."
        )
    ),
]
DetailParam = Annotated[
    Detail,
    Field(
        description=(
            "summary (default) omits raw_response.text; full includes it. Same shape either way."
        )
    ),
]
CapabilitiesDetailParam = Annotated[
    CapabilitiesDetail,
    Field(
        description=(
            "summary (default): name, cost, stability, backends, error_codes per tool; "
            "full adds use_when/returns/params; contracts omits tool_details."
        )
    ),
]
IdempotencyKeyParam = Annotated[
    str | None,
    Field(
        description=PARAMETER_CONTRACTS["idempotency_key"].summary,
        min_length=1,
        max_length=200,
    ),
]
BackendOptionsParam = Annotated[
    BackendOptions | None, Field(description=PARAMETER_CONTRACTS["backend_options"].summary)
]
ScopeParam = Annotated[
    ReviewScope,
    Field(
        description=(
            "working_tree (tracked changes vs HEAD), branch (vs `base`, default the "
            "upstream), or commit (one commit)."
        )
    ),
]
OptionalScopeParam = Annotated[
    ReviewScope | None,
    Field(
        description=(
            "Optionally attach a git diff to the critique: working_tree | branch | commit."
        )
    ),
]
BaseParam = Annotated[
    str | None,
    Field(
        description=(
            "Base ref for scope=branch; omit for the upstream. Control characters rejected."
        ),
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=256,
    ),
]
CommitParam = Annotated[
    str | None,
    Field(
        description="Commit ref for scope=commit. Control characters rejected.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=256,
    ),
]
PathsParam = Annotated[
    list[str] | None,
    Field(description="Restrict the diff to these repo-relative paths. Omit for all."),
]
UntrackedParam = Annotated[
    Untracked,
    Field(
        description=(
            "working_tree only: explicit_only (default; untracked files named in paths), "
            "include (every non-ignored untracked file — opt-in egress), exclude."
        )
    ),
]
FocusParam = Annotated[
    str | None,
    Field(
        description=(
            "Narrow the review to one concern (e.g. 'locking'). UNTRUSTED caller text; a "
            "focused pass is never a full review."
        ),
        max_length=500,
    ),
]
JobIdParam = Annotated[
    str,
    Field(
        description="Job id from an _async call or meta.job_id. Control characters rejected.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=64,
    ),
]
TaskIdParam = Annotated[
    str | None,
    Field(
        description="Filter to the job behind this tasks-extension task id.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=128,
    ),
]
JobLimitParam = Annotated[
    int | None,
    Field(
        description="Return at most this many newest jobs (1-1000); omit for all.",
        ge=1,
        le=1000,
    ),
]
JobStatusFilterParam = Annotated[
    JobState | None, Field(description="Only jobs in this state; omit for all.")
]
IncludeSchemasParam = Annotated[
    list[Literal["error-envelope", "result-meta", "capabilities-result", "parameter-contracts"]]
    | None,
    Field(
        description=(
            "Embed these documents in `schemas`: error-envelope, result-meta, "
            "capabilities-result, parameter-contracts. A resource-blind fallback."
        )
    ),
]
