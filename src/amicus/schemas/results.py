"""Success result models for every tool, and their advertised outputSchemas."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

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
Confidence = Literal["low", "medium", "high", "unknown"]
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
CoverageStatus = Literal["complete", "partial"]
# Why a review was not complete, in this fixed order (review.build_coverage). Not every
# reason withholds input: `focused` narrows the ask, `tree_changed_during_gather` is a
# consistency caveat (ADR 0019).
CoverageReason = Literal[
    "untracked_omitted",
    "tree_changed_during_gather",
    "truncated",
    "redacted",
    "focused",
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
_CONFIDENCE_DESC = (
    "How sure this review is. Usually the backend's own low|medium|high. amicus substitutes "
    "`low` exactly where it also withholds the verdict as `unknown`: partial coverage, "
    "findings it could not carry, or `review_status: not_run`, where no backend was called "
    "at all. So beside any OTHER verdict this is the backend's word - a `fail` or `concerns` "
    "keeps its rating whatever was lost, and a high one is no evidence that coverage was "
    "complete. `unknown` is the ABSENCE of a rating - no readable value, and no such "
    "substitution - never a low one."
)
publish.KEPT_DESCRIPTIONS.update(
    {_DROPPED_DESC, _REASONS_DESC, _DIAGNOSTICS_DESC, _CONFIDENCE_DESC}
)


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


# Inlined into three tools' output schemas each, so every byte here is paid three times in
# tools/list (tests/test_discovery_cost.py). Each sentence guards a misreading; add none
# that does not.
_COVERAGE_DESC = (
    "How complete this review was. `partial` when any omission_reasons entry applies. "
    "`complete` means amicus detected no omission; it is not proof that nothing was missed, "
    "that every line was examined, or on a not_run result that anything was. A `pass` over "
    "partial coverage is delivered as unknown/low; a `fail` or `concerns` is not, so check "
    "this on those too."
)
_OMISSION_REASONS_DESC = (
    "Why it was not complete, in fixed order. untracked_omitted: untracked files in scope "
    "were not sent. tree_changed_during_gather: the tree changed while amicus read it "
    "(best-effort; its absence proves nothing). truncated: the diff was cut at the byte cap. "
    "redacted: secrets were withheld or masked (see redaction). focused: `focus` narrowed "
    "the review; nothing was withheld."
)
_UNTRACKED_DESC = (
    "Untracked files in the review's paths: detected = included (sent) + omitted. All three "
    "are null outside scope=working_tree."
)
_REDACTION_DESC = (
    "The `redacted` reason by file. Can be null beside it when the redaction fell only in "
    "content the byte cap cut; meta.redacted_paths lists every redacted file."
)
_WITHHELD_DESC = "Changes withheld whole (secret-looking path); the backend did not see them."
_MASKED_DESC = "Sent with secret-looking values masked."
publish.KEPT_DESCRIPTIONS.update(
    {
        _COVERAGE_DESC,
        _OMISSION_REASONS_DESC,
        _UNTRACKED_DESC,
        _REDACTION_DESC,
        _WITHHELD_DESC,
        _MASKED_DESC,
    }
)


class RedactionSummary(BaseModel):
    """The `redacted` reason broken down (codex-in-claude #433): a withheld file's changes
    never reached the backend, a masked file's did with values replaced."""

    model_config = ConfigDict(extra="forbid")
    withheld_paths: list[str] = Field(default_factory=list, description=_WITHHELD_DESC)
    masked_paths: list[str] = Field(default_factory=list, description=_MASKED_DESC)
    inline_masks: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_invariants(self) -> RedactionSummary:
        if not (self.withheld_paths or self.masked_paths):
            raise ValueError("redaction must name at least one withheld or masked path")
        if set(self.withheld_paths) & set(self.masked_paths):
            raise ValueError("withheld_paths and masked_paths must be disjoint")
        if self.masked_paths and self.inline_masks < len(self.masked_paths):
            raise ValueError("inline_masks must be >= len(masked_paths)")
        if not self.masked_paths and self.inline_masks:
            raise ValueError("inline_masks must be 0 when masked_paths is empty")
        return self


class Coverage(BaseModel):
    """How complete a review was (issue #65; codex-in-claude's `Coverage` plus amicus's
    `focused`). Not only "what the backend was shown": `focused` withholds nothing, and
    `tree_changed_during_gather` is a consistency caveat. The invariants below make every
    field agree with every other, because a client branches on them without reading
    `summary`, and delivery trusts whatever validates."""

    model_config = ConfigDict(extra="forbid")
    status: CoverageStatus
    untracked_files_detected: int | None = Field(default=None, ge=0, description=_UNTRACKED_DESC)
    untracked_files_included: int | None = Field(default=None, ge=0)
    untracked_files_omitted: int | None = Field(default=None, ge=0)
    omission_reasons: list[CoverageReason] = Field(
        default_factory=list, description=_OMISSION_REASONS_DESC
    )
    redaction: RedactionSummary | None = Field(default=None, description=_REDACTION_DESC)

    @model_validator(mode="after")
    def _check_invariants(self) -> Coverage:
        reasons = self.omission_reasons
        if (self.status == "partial") != bool(reasons):
            raise ValueError("coverage.status must be 'partial' iff omission_reasons is non-empty")
        if reasons != [r for r in get_args(CoverageReason) if r in reasons]:
            raise ValueError("omission_reasons must be unique and in their fixed order")
        detected = self.untracked_files_detected
        included = self.untracked_files_included
        omitted = self.untracked_files_omitted
        if detected is None or included is None or omitted is None:
            if (detected, included, omitted) != (None, None, None):
                raise ValueError("the untracked counts must be all set or all null")
            if "tree_changed_during_gather" in reasons:
                raise ValueError("tree_changed_during_gather needs the working_tree counts")
        elif detected != included + omitted:
            raise ValueError("untracked_files_detected must equal included + omitted")
        if ("untracked_omitted" in reasons) != bool(omitted):
            raise ValueError("untracked_omitted is listed exactly when files were omitted")
        if self.redaction is not None and "redacted" not in reasons:
            raise ValueError("coverage.redaction requires 'redacted' in omission_reasons")
        return self


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
    confidence: Confidence = Field(description=_CONFIDENCE_DESC)
    review_status: ReviewStatus = "completed"
    context_summary: ContextSummary | None = None
    coverage: Coverage = Field(description=_COVERAGE_DESC)


class AdversarialReviewResult(_ModelResult):
    tool: Literal["amicus_adversarial_review"] = "amicus_adversarial_review"
    verdict: Verdict
    confidence: Confidence = Field(description=_CONFIDENCE_DESC)
    review_status: ReviewStatus = "completed"
    context_summary: ContextSummary | None = None
    coverage: Coverage = Field(description=_COVERAGE_DESC)


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

_DRY_RUN_COVERAGE_DESC = (
    "The coverage the paid review would report for these arguments; the tree can still "
    "change before you spend."
)
_MAX_INPUT_BYTES_DESC = (
    "The paid call's byte cap: the diff is cut beyond it (`truncated`), caller text rejected."
)
publish.KEPT_DESCRIPTIONS.update({_DRY_RUN_COVERAGE_DESC, _MAX_INPUT_BYTES_DESC})


class DryRunResult(SuccessBase):
    tool: Literal["amicus_dry_run"] = "amicus_dry_run"
    backend: BackendRef
    would_call_model: bool
    scope: ReviewScope
    base: str | None = None
    commit: str | None = None
    paths: list[str] | None = None
    prompt_bytes: int
    coverage: Coverage = Field(description=_DRY_RUN_COVERAGE_DESC)
    max_input_bytes: int = Field(description=_MAX_INPUT_BYTES_DESC)
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
    default: str | float | None = Field(
        default=None,
        description="Common default across verbs; null if absent or defaults vary by verb.",
    )
    default_by_verb: dict[str, str | float | None] | None = Field(
        default=None,
        description="Resolved defaults keyed by verb when they differ; null for a common default.",
    )


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
    stability: ToolStability
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
