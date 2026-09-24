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
# A backend id on the wire is an open lowercase identifier (the same shape the SDK's
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


class InstructionsFingerprint(BaseModel):
    """What a result discloses about `instructions_append`: a digest and a byte count,
    never the text (the parameter contract promises only a fingerprint is echoed)."""

    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1)


DiscardOutcome = Literal["removed", "missing", "state_changed", "delete_failed"]

_DISCARD_OUTCOME_DESC = (
    "What deleting the record did. removed: this call deleted it. missing: the store had "
    "already dropped it (consumed, expired or evicted); files a failed cleanup left may "
    "remain. After either, a repeat call returns job_not_found. state_changed: the record "
    "was not, or not verifiably, still as this call returned it (a failed job's result can "
    "still appear), so nothing was deleted. delete_failed: deletion failed or could not be "
    "verified, so the record may remain."
)
_CONSUME_DESC = (
    "Set only by amicus_job_consume_result, on the envelope it returns: what deleting "
    "the job record did. Never stored with the result."
)


class ConsumeFollowUpArguments(BaseModel):
    """The amicus_job_status call a consume follow-up names, closed to that call's shape so
    the published schema admits only a callable one. `workspace_root` is omitted, never
    null, when the caller did not supply one."""

    model_config = ConfigDict(extra="forbid")
    job_id: str
    workspace_root: str | None = None


class ConsumeFollowUp(BaseModel):
    """The one follow-up a consume hands back: inspect the record it may have left. The
    same shape as `Repair`, narrowed to that one action as `JobFollowUp` is, and its
    `arguments` narrowed to the call that action names (#44)."""

    model_config = ConfigDict(extra="forbid")
    next_step: Literal["inspect_and_retry"]
    tool: Literal["amicus_job_status"]
    arguments: ConsumeFollowUpArguments
    alternative: str | None = None


class ConsumeDisposition(BaseModel):
    """What amicus_job_consume_result did to the record after returning it (#44, #126)."""

    model_config = ConfigDict(extra="forbid")
    discard_outcome: DiscardOutcome = Field(description=_DISCARD_OUTCOME_DESC)
    follow_up: ConsumeFollowUp | None = None


class Meta(BaseModel):
    """Execution metadata on every envelope. Construction: every field has a default, so
    `Meta()` is valid. Wire: `META_ALWAYS_PRESENT` (the fields whose default is never None,
    minus `server_version`) is the success schema's `required` and is always delivered;
    every other key is delivered only when non-null (`slim_meta`, #47). `server_version`
    is not required because a stored payload can predate it. `cwd` is None when no
    workspace was resolved (argument errors, unimplemented tools). Backend-specific facts
    ride `backend_details`."""

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
    instructions_append: InstructionsFingerprint | None = None
    job_id: str | None = None
    job_kind: str | None = None
    task_id: str | None = None
    idempotency_replayed: Literal[True] | None = None
    backend_details: dict[str, Any] | None = None
    # Delivery-only: excluded from every dump, so a stored result.json keeps its shape and
    # RESULT_FORMAT does not move; jobs.delivery.attach_consume_disposition sets it on the
    # delivered dict instead (#44).
    consume: ConsumeDisposition | None = Field(
        default=None, exclude=True, description=_CONSUME_DESC
    )
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
    the asymmetry is part of the persisted result format (RESULT_FORMAT). This is the
    STORED shape; `slim_meta` is the wire shape."""
    return result.model_dump(mode="json")


def _always_present_meta() -> tuple[str, ...]:
    """The meta keys every wire envelope carries: fields whose default is never None,
    minus `server_version`, which a stored payload can predate and which is then omitted
    rather than backfilled. Derived, so a defaulted field cannot be added without being
    declared. `consume` is excluded from every dump and never listed."""
    return tuple(
        name
        for name, field in Meta.model_fields.items()
        if name != "server_version"
        and not field.exclude
        and (field.default is not None or field.default_factory is not None)
    )


META_ALWAYS_PRESENT: tuple[str, ...] = _always_present_meta()


def slim_meta(envelope: dict[str, Any]) -> dict[str, Any]:
    """Drop meta's null-valued keys from a success envelope on its way to the wire (#47).
    Every tool's success passes through this, paid or free, at the guard; a delivered
    stored result passes through it again at the delivery chokepoint. The persisted
    envelope keeps them (`dump_success`). Keyed on `is None`, never falsiness: 0, False
    and [] are populated values. Only `meta` is touched; a null outside it is that tool's
    own contract. Mutates."""
    if envelope.get("ok") is not True:
        return envelope
    meta = envelope.get("meta")
    if isinstance(meta, dict):
        envelope["meta"] = {k: v for k, v in meta.items() if v is not None}
    return envelope


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
_REPAIR_POLICY = (
    "repair.arguments, when present, is a complete call. A lookup or poll repair carries "
    "the failing call's backend when the lookup tool accepts it, a job_id this server "
    "minted, or the workspace_root of a call that already resolved it. An invalid_arguments "
    "repair whose every rejected argument is an unknown key carries the call as sent minus "
    "those keys, but only when every remaining value is null, a bool, a number, a member "
    "of the parameter's published enum, or an object built from those. Any other string "
    "could be a secret or a prompt input, so it suppresses the arguments. That call "
    "corrects the failures this envelope reports; a later check can still reject it with "
    "a repair of its own. A repair that names no tool is a symbolic next step, not a call. "
    "invalid_workspace_root and workspace_outside_roots carry no repair at all: only the "
    "caller holds the directory they need, details names the field, and details.reason is "
    "a fixed token naming the cause, listed in the workspace_root contract at amicus://params."
)


def _harden_error_envelope_schema(schema: dict[str, Any]) -> dict[str, Any]:
    s = copy.deepcopy(schema)
    s["$schema"] = JSON_SCHEMA_DIALECT
    s["description"] = (
        "The full error envelope every ok:false tool result carries in structuredContent; "
        "resource-read failures carry error (with code/message renamed machine_code/"
        f"human_message) in JSON-RPC error.data. {_OFFENDING_VALUE_POLICY} {_REPAIR_POLICY}"
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
# The always-present core is the schema's own `required`: a reader may index those keys
# without a presence check, and every other key is present only when it carries a value.
RESULT_META_SCHEMA["required"] = list(META_ALWAYS_PRESENT)
RESULT_META_SCHEMA["description"] = (
    "The full result-metadata contract. Every success envelope's `meta` is advertised "
    "as an opaque pointer to this schema. On the wire every success envelope, paid or "
    "free, drops meta's null-valued keys; absence means exactly what null means (not "
    "applicable / not reported). The keys in `required` are always present. An empty list "
    "there means this envelope reports none, not that a check ran: a job handle, status or "
    "list and a dry run report on the call that produced them, never on the run they name, "
    "whose warnings arrive on its own result. Error envelopes strip absent optionals except "
    "retry_after_ms."
)

# The `ok` discriminator description survives noise stripping on every published schema.
publish.KEPT_DESCRIPTIONS.add("true = success result, false = error result")
