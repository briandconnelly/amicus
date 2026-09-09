"""Success result models for every tool, and their advertised outputSchemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from amicus.schemas import publish
from amicus.schemas.codes import ErrorCode  # noqa: TC001 - pydantic needs this at runtime
from amicus.schemas.envelope import (
    BackendRef,
    ContextSummary,
    Repair,
    SuccessBase,
    Workspace,
    server_version_field,
)
from amicus.schemas.fingerprint import (
    FINGERPRINT,
    FINGERPRINT_COVERS,
    FINGERPRINT_COVERS_DESC,
    JSON_SCHEMA_DIALECT,
    PROTOCOL_REVISION,
    RESULT_FORMAT,
)

Severity = Literal["critical", "high", "medium", "low", "nit"]
Verdict = Literal["pass", "concerns", "fail", "unknown"]
Confidence = Literal["low", "medium", "high"]
ReviewScope = Literal["working_tree", "branch", "commit"]
Untracked = Literal["explicit_only", "include", "exclude"]
Detail = Literal["summary", "full"]
CapabilitiesDetail = Literal["summary", "full", "contracts"]
JobState = Literal["running", "done", "failed", "cancelled", "timeout"]
ToolStability = Literal["stable", "preview", "experimental"]
ReviewStatus = Literal["completed", "not_run"]
# Why a backend finding did not reach the caller intact, in this fixed order. A fixed
# vocabulary, never the omitted content: backend output can echo caller input (rule 18).
FindingReason = Literal[
    "severity_normalized",
    "extra_fields_omitted",
    "invalid_entry",
    "invalid_container",
    "missing_findings",
]

PAID_TOOLS: tuple[str, ...] = (
    "amicus_consult",
    "amicus_review_changes",
    "amicus_adversarial_review",
    "amicus_delegate",
)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    severity: Severity = "medium"
    file: str | None = None
    line: int | None = None
    evidence: str | None = None
    suggestion: str | None = None


_DROPPED_DESC = (
    "Whole findings entries that could not be represented. 0 does NOT mean nothing was "
    "lost: `extra_fields_omitted` reports content dropped from a finding that survived. "
    "null means the count is unknowable because the findings member could not be read at "
    "all. Read `reasons`, never this count alone."
)
_REASONS_DESC = (
    "Why findings did not reach you intact. severity_normalized: case/space only, finding "
    "intact. extra_fields_omitted: unrecognized keys and their content are gone, the rest "
    "of the finding survives. invalid_entry: an entry was dropped whole. "
    "invalid_container: the findings member was present but not a list. missing_findings: "
    "the required findings member was absent. The last three also stop a `pass` verdict "
    "from standing, which is delivered as unknown/low instead."
)
_DIAGNOSTICS_DESC = (
    "What the backend reported that amicus could not carry intact; null when nothing "
    "deviated. Read this before acting on an empty or short `findings` list."
)
publish.KEPT_DESCRIPTIONS.update({_DROPPED_DESC, _REASONS_DESC, _DIAGNOSTICS_DESC})


class FindingsDiagnostics(BaseModel):
    """What amicus could not carry from the backend's own findings list (issue #38).

    Present only when the backend's output deviated from the finding shape. `dropped`
    counts whole entries that could not be represented, so 0 does not mean nothing was
    lost: `extra_fields_omitted` reports content dropped from a finding that survived.
    It is null when the deviation makes the count unknowable (the findings member was not
    a list at all), which is why null and 0 differ - 0 says amicus assessed the list,
    null that it could not. Read `reasons`, never the count alone."""

    model_config = ConfigDict(extra="forbid")
    dropped: int | None = Field(default=None, description=_DROPPED_DESC)
    reasons: list[FindingReason] = Field(default_factory=list, description=_REASONS_DESC)


class RawResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    session_id: str | None = None
    model: str | None = None


class _ModelResult(SuccessBase):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    findings_diagnostics: FindingsDiagnostics | None = Field(
        default=None, description=_DIAGNOSTICS_DESC
    )
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    raw_response: RawResponse | None = None


class ConsultResult(_ModelResult):
    tool: Literal["amicus_consult"] = "amicus_consult"


class ReviewResult(_ModelResult):
    tool: Literal["amicus_review_changes"] = "amicus_review_changes"
    verdict: Verdict
    confidence: Confidence
    review_status: ReviewStatus = "completed"
    context_summary: ContextSummary | None = None


class AdversarialReviewResult(_ModelResult):
    tool: Literal["amicus_adversarial_review"] = "amicus_adversarial_review"
    verdict: Verdict
    confidence: Confidence
    review_status: ReviewStatus = "completed"
    context_summary: ContextSummary | None = None


class DelegateResult(_ModelResult):
    tool: Literal["amicus_delegate"] = "amicus_delegate"
    diff: str | None
    diffstat: str | None = None


# --- jobs -----------------------------------------------------------------------------


class JobStarted(SuccessBase):
    job_id: str
    backend: BackendRef
    kind: str
    status: JobState = "running"
    started_at: str
    deadline_seconds: int
    poll_after_ms: int
    expires_at: str | None
    task_id: str | None = None
    follow_up: Repair


class JobStatus(SuccessBase):
    job_id: str
    backend: BackendRef
    kind: str
    status: JobState
    elapsed_ms: int
    result_available: bool
    result_ok: bool | None
    poll_after_ms: int | None = None
    expires_at: str | None
    task_id: str | None = None
    workspace: Workspace
    cleanup_warnings: list[str] = Field(default_factory=list)


class JobSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    backend: BackendRef
    kind: str
    status: JobState
    started_at: str
    elapsed_ms: int
    result_available: bool
    result_ok: bool | None
    expires_at: str | None
    task_id: str | None = None


class JobListResult(SuccessBase):
    jobs: list[JobSummary]
    workspace: Workspace
    truncated: bool = False
    truncation_hint: str | None = None


# --- previews -------------------------------------------------------------------------


class DryRunResult(SuccessBase):
    tool: Literal["amicus_dry_run"] = "amicus_dry_run"
    backend: BackendRef
    would_call_model: bool
    scope: ReviewScope
    base: str | None = None
    commit: str | None = None
    paths: list[str] | None = None
    prompt_bytes: int
    context_summary: ContextSummary | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    backend_options: dict[str, Any] = Field(default_factory=dict)
    workspace: Workspace
    warnings: list[str] = Field(default_factory=list)


class WorktreePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_ref: str
    prefix: str


class DelegateDryRunResult(SuccessBase):
    tool: Literal["amicus_delegate_dry_run"] = "amicus_delegate_dry_run"
    backend: BackendRef
    task_bytes: int
    worktree: WorktreePlan
    model: str | None = None
    reasoning_effort: str | None = None
    backend_options: dict[str, Any] = Field(default_factory=dict)
    workspace: Workspace
    warnings: list[str] = Field(default_factory=list)


# --- discovery ------------------------------------------------------------------------


class BackendStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installed: bool
    version: str | None = None
    authenticated: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class EffectsInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paid_calls_destructive: bool
    job_reads_read_only: bool


class BackendOptionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    allowed_values: list[str] | None = None
    default: str | float | None = None


class BackendEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: BackendRef
    display_name: str
    enabled: bool
    available: bool
    status: BackendStatus | None = None
    features: list[str]
    effects: EffectsInfo
    options: list[BackendOptionInfo]
    egress: str | None = None
    carriers: str | None = None
    readonly_honesty: str | None = None
    implicit_context: str | None = None


class UnavailableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    reason: str
    detail: str


class BackendsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    backends: list[BackendEntry]
    unavailable: list[UnavailableEntry]
    env_warnings: list[str]
    config_errors: list[str]
    fingerprint: str = FINGERPRINT
    server_version: str | None = server_version_field()


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    display_name: str | None = None
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: list[str] | None = None


class ModelCatalogResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    backend: BackendRef
    available: bool
    models: list[ModelInfo]
    source: Literal["cache", "static", "live", "none"]
    fetched_at: str | None = None
    fingerprint: str = FINGERPRINT
    server_version: str | None = server_version_field()


class TaskSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    extension: str = "io.modelcontextprotocol/tasks"
    task_tools: list[str]
    fallback: str


_TOOL_STABILITY_DESC = (
    "Per-tool maturity override, advisory only. null inherits the top-level `stability`."
)
_TOOL_DETAILS_POINTER_DESC = (
    "Per-tool capability records; full schema via "
    "amicus_capabilities(include_schemas=['capabilities-result'])"
)
publish.KEPT_DESCRIPTIONS.update({_TOOL_STABILITY_DESC, _TOOL_DETAILS_POINTER_DESC})


class ToolCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    cost: Literal["free", "active"]
    stability: ToolStability | None = Field(default=None, description=_TOOL_STABILITY_DESC)
    backends: list[BackendRef] | None = None
    use_when: str | None = None
    required_params: list[str] = Field(default_factory=list)
    key_optional_params: list[str] = Field(default_factory=list)
    returns: str | None = None
    error_codes: list[ErrorCode] = Field(default_factory=list)


RESULT_FORMAT_DESC = (
    "The persisted job-result format this release reads and writes. A stored job record "
    "stamped with a different value is not delivered; amicus_job_result returns "
    "job_result_incompatible instead. It is versioned separately from `fingerprint`: a "
    "stored result's shape and the live tool surface move independently."
)


class CapabilitiesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    name: str
    version: str
    fingerprint: str = FINGERPRINT
    surface_digest: str
    server_version: str | None = server_version_field()
    fingerprint_covers: list[str] = Field(
        default_factory=lambda: list(FINGERPRINT_COVERS), description=FINGERPRINT_COVERS_DESC
    )
    protocol_revision: str = PROTOCOL_REVISION
    result_format: int = Field(default=RESULT_FORMAT, description=RESULT_FORMAT_DESC)
    transport: str
    stability: str
    enabled_backends: list[BackendRef]
    active_tools: list[str]
    free_tools: list[str]
    job_tools: list[str]
    tool_details: list[ToolCapability] = Field(default_factory=list)
    error_codes: list[str]
    scope: list[str]
    negative_scope: list[str]
    prerequisites: list[str]
    deprecation_policy: str
    tool_error_carrier: str
    resource_error_carrier: str
    annotations_reading: str
    tasks: TaskSupport
    meta_fields: list[str]
    error_envelope_resource: str = "amicus://error-envelope"
    result_meta_resource: str = "amicus://result-meta"
    params_resource: str = "amicus://params"
    schemas: dict[str, Any] | None = None


publish.KEPT_DESCRIPTIONS.add(FINGERPRINT_COVERS_DESC)
publish.KEPT_DESCRIPTIONS.add(RESULT_FORMAT_DESC)

CONSULT_RESULT_SCHEMA = publish.published_schema(ConsultResult)
REVIEW_RESULT_SCHEMA = publish.published_schema(ReviewResult)
ADVERSARIAL_RESULT_SCHEMA = publish.published_schema(AdversarialReviewResult)
DELEGATE_RESULT_SCHEMA = publish.published_schema(DelegateResult)
JOB_STARTED_SCHEMA = publish.published_schema(JobStarted)
JOB_STATUS_SCHEMA = publish.published_schema(JobStatus)
JOB_LIST_SCHEMA = publish.published_schema(JobListResult)
DRY_RUN_SCHEMA = publish.published_schema(DryRunResult)
DELEGATE_DRY_RUN_SCHEMA = publish.published_schema(DelegateDryRunResult)
BACKENDS_SCHEMA = publish.published_schema(BackendsResult)
MODEL_CATALOG_SCHEMA = publish.published_schema(ModelCatalogResult)
CAPABILITIES_SCHEMA = publish.published_schema(
    CapabilitiesResult,
    opaque_fields={"tool_details": {"type": "array", "description": _TOOL_DETAILS_POINTER_DESC}},
)

# amicus_job_result / amicus_job_consume_result return exactly the originating paid tool's
# envelope; the success branch is opaque and points at that tool's advertised schema.
_OPAQUE_JOB_SUCCESS_BRANCH: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "tool"],
    "properties": {
        "ok": {"const": True},
        "tool": {
            "enum": list(PAID_TOOLS),
            "description": (
                "Originating tool; the payload matches that tool's advertised outputSchema "
                "success branch — branch on this field."
            ),
        },
    },
}
JOB_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": JSON_SCHEMA_DIALECT,
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "description": "true = success result, false = error result"},
    },
    "required": ["ok"],
    "anyOf": [_OPAQUE_JOB_SUCCESS_BRANCH, publish.OPAQUE_ERROR_BRANCH],
    "$defs": {},
}

# Full capabilities shape, reachable via amicus_capabilities(include_schemas=[...]).
CAPABILITIES_RESULT_SCHEMA: dict[str, Any] = TypeAdapter(CapabilitiesResult).json_schema(
    ref_template="#/$defs/{model}"
)
CAPABILITIES_RESULT_SCHEMA["$schema"] = JSON_SCHEMA_DIALECT
