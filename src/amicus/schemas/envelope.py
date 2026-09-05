"""The §6 error envelope, result metadata, and the success-envelope base (ADR 0005)."""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from amicus import __version__
from amicus.schemas import publish
from amicus.schemas.codes import (  # noqa: TC001 - pydantic needs these at runtime
    ErrorCode,
    RepairStep,
)
from amicus.schemas.fingerprint import FINGERPRINT, JSON_SCHEMA_DIALECT

WorkspaceSource = Literal["param", "roots", "cwd"]
RootsSource = Literal["client", "not_negotiated", "probe_failed"]
# A backend id on the wire is an open lowercase identifier (the same shape pontonier's
# BackendContract enforces), so a third-party plugin's id fits; the `backend` PARAMETER is
# the v1 enum. Every result field named backend/id uses this alias.
BackendRef = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


def server_version_field() -> Any:
    """Release identity beside the contract identity (`fingerprint`). A default_factory
    keeps the literal out of the published schemas, so a release moves no snapshot."""
    return Field(
        default_factory=lambda: __version__,
        description=(
            "amicus package version attributed to this result. A replayed job result "
            "preserves the version of the run that produced it. Omitted when a stored "
            "payload predates this field — never backfilled, never sent as null."
        ),
    )


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


class ContextSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0


class Workspace(BaseModel):
    """Compact workspace context for job-lifecycle success responses."""

    model_config = ConfigDict(extra="forbid")
    cwd: str
    workspace_source: WorkspaceSource | None = None
    workspace_warning: str | None = None


class Meta(BaseModel):
    """Execution metadata on every envelope. Every field is optional except the
    identity trio at the end; `cwd` is None when no workspace was resolved (argument
    errors, unimplemented tools). Backend-specific facts ride `backend_details`."""

    model_config = ConfigDict(extra="forbid")
    backend: BackendRef | None = None
    cwd: str | None = None
    workspace_source: WorkspaceSource | None = None
    workspace_warning: str | None = None
    roots_source: RootsSource | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int | None = None
    elapsed_ms: int = 0
    command_exit_code: int | None = None
    session_id: str | None = None
    truncated: bool = False
    truncation_hint: str | None = None
    compat_warnings: list[str] = Field(default_factory=list)
    security_warnings: list[str] = Field(default_factory=list)
    redacted_paths: list[str] = Field(default_factory=list)
    usage: Usage | None = None
    context_summary: ContextSummary | None = None
    job_id: str | None = None
    job_kind: str | None = None
    task_id: str | None = None
    idempotency_replayed: Literal[True] | None = None
    backend_details: dict[str, Any] | None = None
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    fingerprint: str = FINGERPRINT
    server_version: str | None = server_version_field()


class SuccessBase(BaseModel):
    """Every success envelope: `ok: true`, a `tool` discriminator, and `meta`."""

    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    meta: Meta


def dump_success(result: SuccessBase) -> dict[str, Any]:
    """Success envelopes retain null optionals (unlike serialize_error's exclude_none);
    the asymmetry is part of the persisted result format (RESULT_FORMAT)."""
    return result.model_dump(mode="json")


class InvalidArgument(BaseModel):
    """One field-level argument failure. The rejected VALUE is never echoed."""

    model_config = ConfigDict(extra="forbid")
    field: str
    reason: str
    allowed_values: list[str] | None = None
    field_withheld: bool = False


class Repair(BaseModel):
    """Machine-actionable recovery: a symbolic `next_step`, the single callable
    `tool`/`arguments`, and an optional prose `alternative` ([6.repair-object])."""

    model_config = ConfigDict(extra="forbid")
    next_step: RepairStep
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    alternative: str | None = None


class ErrorDetail(BaseModel):
    """§6 details. `value` is omitted by policy (disclosed on amicus://error-envelope).
    Exactly one of `field`/`fields`, or neither."""

    model_config = ConfigDict(extra="forbid")
    field: str | None = None
    fields: (
        Annotated[list[str], Field(min_length=1, json_schema_extra={"uniqueItems": True})] | None
    ) = None
    reason: str | None = None
    allowed_values: list[str] | None = None
    field_withheld: bool = False

    @model_validator(mode="after")
    def _one_of_field_or_fields(self) -> ErrorDetail:
        if self.field is not None and self.fields is not None:
            raise ValueError("ErrorDetail: set at most one of field/fields, never both")
        if self.fields is not None and len(set(self.fields)) != len(self.fields):
            raise ValueError("ErrorDetail.fields must not contain duplicates")
        return self


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: ErrorCode
    message: str
    backend: BackendRef | None = Field(...)
    temporary: bool = Field(...)
    retry_after_ms: int | None = Field(..., ge=0)
    repair: Repair | None = None
    details: ErrorDetail | None = None
    invalid_arguments: list[InvalidArgument] | None = None
    limit_bytes: int | None = None
    actual_bytes: int | None = None
    candidate_roots: list[str] | None = None
    resource_uri: str | None = None
    request_id: str | None = None

    @model_validator(mode="after")
    def _retry_after_only_when_temporary(self) -> ErrorInfo:
        if not self.temporary and self.retry_after_ms is not None:
            raise ValueError("retry_after_ms must be None when temporary is False")
        return self


class ErrorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[False] = False
    error: ErrorInfo
    meta: Meta


_OFFENDING_VALUE_POLICY = (
    "details.value is omitted for every caller-supplied input: a string parameter can "
    "receive a mispasted secret and best-effort redaction cannot catch a plain one, so "
    "the caller — who already holds what it sent — repairs from field, reason and "
    "allowed_values. Machine identifiers this server minted (job_id) are refused, never "
    "echoed, when they carry a control character."
)


def _harden_error_envelope_schema(schema: dict[str, Any]) -> dict[str, Any]:
    s = copy.deepcopy(schema)
    s["$schema"] = JSON_SCHEMA_DIALECT
    s["description"] = (
        "The full error envelope every ok:false tool result carries in structuredContent; "
        "resource-read failures carry error (with code/message renamed machine_code/"
        f"human_message) in JSON-RPC error.data. {_OFFENDING_VALUE_POLICY}"
    )
    required = s.setdefault("required", [])
    if "ok" not in required:
        required.append("ok")
    info = s["$defs"]["ErrorInfo"]
    info["if"] = {"properties": {"temporary": {"const": False}}, "required": ["temporary"]}
    info["then"] = {"properties": {"retry_after_ms": {"const": None}}}
    return s


ERROR_ENVELOPE_SCHEMA = _harden_error_envelope_schema(
    TypeAdapter(ErrorResult).json_schema(ref_template="#/$defs/{model}")
)

RESULT_META_SCHEMA: dict[str, Any] = TypeAdapter(Meta).json_schema(ref_template="#/$defs/{model}")
RESULT_META_SCHEMA["$schema"] = JSON_SCHEMA_DIALECT
RESULT_META_SCHEMA["description"] = (
    "The full result-metadata contract. Every success envelope's `meta` is advertised "
    "as an opaque pointer to this schema. On the wire a delivered success envelope drops "
    "meta's null-valued keys; absence means exactly what null means (not applicable / not "
    "reported). Error envelopes strip absent optionals except retry_after_ms."
)

# The `ok` discriminator description survives noise stripping on every published schema.
publish.KEPT_DESCRIPTIONS.add("true = success result, false = error result")
