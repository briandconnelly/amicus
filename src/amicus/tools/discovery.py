"""amicus_backends, amicus_models, amicus_capabilities (free discovery)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pontonier.core.redaction import exc_summary

from amicus import SERVER_NAME, __version__, surface
from amicus.backends import KNOWN_DISPLAY_NAMES, KNOWN_EFFECTS
from amicus.errors import error_envelope
from amicus.schemas.codes import BACKEND_IDS, ERROR_CODES
from amicus.schemas.envelope import ERROR_ENVELOPE_SCHEMA, RESULT_META_SCHEMA, Meta
from amicus.schemas.options import OPTION_ALLOWED_VALUES
from amicus.schemas.params import (
    BackendParam,
    CapabilitiesDetailParam,
    IncludeSchemasParam,
    OptionalBackendParam,
    expected_params,
    expected_required,
    params_resource_body,
)
from amicus.schemas.results import (
    BACKENDS_SCHEMA,
    CAPABILITIES_RESULT_SCHEMA,
    CAPABILITIES_SCHEMA,
    MODEL_CATALOG_SCHEMA,
    PAID_TOOLS,
    BackendEntry,
    BackendOptionInfo,
    BackendsResult,
    BackendStatus,
    CapabilitiesResult,
    EffectsInfo,
    ModelCatalogResult,
    ModelInfo,
    TaskSupport,
    ToolCapability,
    UnavailableEntry,
)
from amicus.tools import ACTIVE_TOOLS, FREE_TOOLS, JOB_TOOLS, TOOL_ORDER
from amicus.tools._guard import guard
from amicus.tools._meta import (
    SERVER_STABILITY,
    TOOL_STABILITY,
    annotations_for,
    base_meta,
    effects_for,
    lifecycle_meta,
)
from amicus.tools._resolve import FREE_MARKER

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from fastmcp import FastMCP

    from amicus.appstate import AppState
    from amicus.config import Settings
    from amicus.plugin import BackendPlugin
    from amicus.registry import BackendRegistry

_SUMMARY_FIELDS = ("name", "cost", "stability", "backends", "error_codes")

# Per-tool inventory facts tools/list does not carry. required/key params are derived
# from the matrix for the paid tools so this table cannot disagree with the schemas.
_COMMON_PAID_CODES = [
    "backend_unavailable",
    "feature_unsupported",
    "invalid_arguments",
    "invalid_workspace_root",
    "workspace_outside_roots",
    "unexpanded_env_placeholder",
    "input_too_large",
    "invalid_reasoning_effort",
    "timeout",
    "nonzero_exit",
    "backend_not_found",
    "backend_auth_required",
    "backend_rate_limited",
    "cli_contract_changed",
    "extra_args_rejected",
    "user_config_rejected",
    "budget_exceeded",
    "claude_permission_error",
    "api_key_invalid",
    "api_key_missing",
    "internal_error",
]
_REVIEW_CODES = [
    "invalid_scope",
    "invalid_base",
    "invalid_commit",
    "invalid_paths",
    "not_a_git_repo",
    "git_unavailable",
    "invalid_json",
    "schema_violation",
    "context_too_large",
]
# Lifecycle codes a sync tool's amicus_job_result-shaped envelope can carry once
# lifecycle.run_sync reaches jobs/delivery.py's STATE_TO_ERROR.
_SYNC_LIFECYCLE_CODES = [
    "job_failed",
    "job_cancelled",
    "job_timeout",
    "job_result_incompatible",
]
_REVIEW_CODES_EMITTED = [c for c in _REVIEW_CODES if c != "context_too_large"]
_IDEMPOTENCY_CODES = [
    "idempotency_conflict",
    "idempotency_in_progress",
    "idempotency_result_unavailable",
]
TOOL_DETAILS: dict[str, dict[str, Any]] = {
    "amicus_consult": {
        "cost": "active",
        "backends": list(BACKEND_IDS),
        "use_when": (
            "A read-only second opinion or Q&A from another model, including on a diff "
            "pasted inline."
        ),
        "returns": "summary, findings, questions, next_steps, raw_response (detail=full) and meta.",
        "error_codes": _COMMON_PAID_CODES + _SYNC_LIFECYCLE_CODES,
    },
    "amicus_consult_async": {
        "cost": "active",
        "backends": list(BACKEND_IDS),
        "use_when": "The same consult when it may exceed the sync deadline; returns a job handle.",
        "returns": "job_id, poll_after_ms, expires_at, follow_up; result via amicus_job_result.",
        "error_codes": _COMMON_PAID_CODES + _IDEMPOTENCY_CODES,
    },
    "amicus_review_changes": {
        "cost": "active",
        "backends": list(BACKEND_IDS),
        "use_when": "A structured review of changes that live in git.",
        "returns": "verdict, confidence, findings, review_status, context_summary and meta.",
        "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES_EMITTED + _SYNC_LIFECYCLE_CODES,
    },
    "amicus_review_changes_async": {
        "cost": "active",
        "backends": list(BACKEND_IDS),
        "use_when": "A multi-file or whole-branch review that may exceed the sync deadline.",
        "returns": "a job handle; result via amicus_job_result.",
        "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES + _IDEMPOTENCY_CODES,
    },
    "amicus_delegate": {
        "cost": "active",
        "backends": ["codex", "kimi"],
        "use_when": (
            "A coding task implemented in a throwaway worktree, returned as a diff you "
            "apply yourself."
        ),
        "returns": "diff, diffstat, summary and meta.",
        "error_codes": [
            *_COMMON_PAID_CODES,
            "not_a_git_repo",
            "git_unavailable",
            "worktree_error",
            *_SYNC_LIFECYCLE_CODES,
        ],
    },
    "amicus_delegate_async": {
        "cost": "active",
        "backends": ["codex", "kimi"],
        "use_when": "A substantial delegate that may exceed the sync deadline.",
        "returns": "a job handle; result via amicus_job_result.",
        "error_codes": [
            *_COMMON_PAID_CODES,
            "not_a_git_repo",
            "git_unavailable",
            "worktree_error",
            *_IDEMPOTENCY_CODES,
        ],
    },
    "amicus_adversarial_review": {
        "cost": "active",
        "backends": ["claude"],
        "use_when": "A fixed critic attacking a plan, claim or decision before you commit to it.",
        "returns": "verdict, confidence, findings and meta.",
        "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES,
    },
    "amicus_adversarial_review_async": {
        "cost": "active",
        "backends": ["claude"],
        "use_when": "The same critique when it may exceed the sync deadline.",
        "returns": "a job handle; result via amicus_job_result.",
        "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES + _IDEMPOTENCY_CODES,
    },
    "amicus_dry_run": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Preview a review's scope, size and resolved options before spending.",
        "returns": (
            "would_call_model, scope, prompt_bytes, context_summary, resolved backend_options."
        ),
        "error_codes": [
            "backend_unavailable",
            "invalid_arguments",
            "invalid_workspace_root",
            "workspace_outside_roots",
            "unexpanded_env_placeholder",
            "input_too_large",
            "invalid_reasoning_effort",
            *_REVIEW_CODES[:6],
        ],
    },
    "amicus_delegate_dry_run": {
        "cost": "free",
        "backends": ["codex", "kimi"],
        "use_when": "Preview a delegate's worktree baseline before spending.",
        "returns": "worktree plan, task_bytes, resolved backend_options.",
        "error_codes": [
            "backend_unavailable",
            "feature_unsupported",
            "invalid_arguments",
            "invalid_workspace_root",
            "workspace_outside_roots",
            "unexpanded_env_placeholder",
            "input_too_large",
            "invalid_reasoning_effort",
            "not_a_git_repo",
            "git_unavailable",
            "worktree_error",
        ],
    },
    "amicus_backends": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": (
            "Before the first paid call: which backends are enabled, installed, "
            "authenticated, and what each supports."
        ),
        "returns": "per-backend entries, unavailable reasons, env warnings, config errors.",
        "error_codes": ["invalid_arguments"],
    },
    "amicus_models": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Before overriding model or reasoning_effort.",
        "returns": "advisory model slugs with effort sets and the catalog source.",
        "error_codes": ["invalid_arguments", "backend_unavailable"],
    },
    "amicus_capabilities": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "The full inventory, fingerprint, surface_digest and error catalog.",
        "returns": "this payload.",
        "error_codes": ["invalid_arguments"],
    },
    "amicus_job_status": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Poll a job without fetching its result.",
        "returns": "status, result_available, result_ok, poll_after_ms.",
        "error_codes": [
            "job_not_found",
            "invalid_workspace_root",
            "workspace_outside_roots",
        ],
    },
    "amicus_job_result": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Fetch a finished job's envelope.",
        "returns": "the originating tool's envelope.",
        "error_codes": [
            "job_not_found",
            "job_running",
            "job_failed",
            "job_cancelled",
            "job_timeout",
            "job_result_incompatible",
            "invalid_workspace_root",
            "workspace_outside_roots",
        ],
    },
    "amicus_job_consume_result": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Fetch a finished job's envelope and delete the record.",
        "returns": "the originating tool's envelope.",
        "error_codes": [
            "job_not_found",
            "job_running",
            "job_failed",
            "job_cancelled",
            "job_timeout",
            "job_result_incompatible",
            "invalid_workspace_root",
            "workspace_outside_roots",
        ],
    },
    "amicus_job_cancel": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Stop a running job.",
        "returns": "the job's status after cancellation.",
        "error_codes": [
            "job_not_found",
            "invalid_workspace_root",
            "workspace_outside_roots",
        ],
    },
    "amicus_job_list": {
        "cost": "free",
        "backends": list(BACKEND_IDS),
        "use_when": "Recover job_ids, including the job behind a task_id.",
        "returns": "job summaries, truncated flag.",
        "error_codes": ["invalid_workspace_root", "workspace_outside_roots"],
    },
}
_JOB_PARAMS: dict[str, tuple[list[str], list[str]]] = {
    "amicus_dry_run": (
        ["backend"],
        ["scope", "base", "commit", "paths", "workspace_root", "backend_options"],
    ),
    "amicus_delegate_dry_run": (["backend", "task"], ["workspace_root", "backend_options"]),
    "amicus_backends": ([], ["backend"]),
    "amicus_models": (["backend"], []),
    "amicus_capabilities": ([], ["detail", "include_schemas"]),
    "amicus_job_status": (["job_id"], ["workspace_root"]),
    "amicus_job_result": (["job_id"], ["workspace_root", "detail"]),
    "amicus_job_consume_result": (["job_id"], ["workspace_root", "detail"]),
    "amicus_job_cancel": (["job_id"], ["workspace_root"]),
    "amicus_job_list": ([], ["workspace_root", "limit", "status", "backend", "task_id"]),
}


def _params_for(name: str) -> tuple[list[str], list[str]]:
    if name in _JOB_PARAMS:
        return _JOB_PARAMS[name]
    required = sorted(expected_required(name))
    optional = sorted(expected_params(name) - set(required))
    return required, optional


def _status_of(plugin: BackendPlugin) -> BackendStatus:
    try:
        rep = plugin.status.probe()
    except Exception as exc:
        return BackendStatus(installed=False, warnings=[f"status probe failed: {exc_summary(exc)}"])
    return BackendStatus(
        installed=rep.installed,
        version=rep.version,
        authenticated=rep.authenticated,
        warnings=list(rep.warnings),
    )


def _options_for(backend_id: str, plugin: BackendPlugin | None) -> list[BackendOptionInfo]:
    defaults = {o.name: o.default for o in plugin.options} if plugin else {}
    out: list[BackendOptionInfo] = []
    for name, per_backend in OPTION_ALLOWED_VALUES.items():
        if backend_id in per_backend:
            allowed = per_backend[backend_id]
            out.append(
                BackendOptionInfo(
                    name=name,
                    allowed_values=list(allowed) if allowed else None,
                    default=defaults.get(name),
                )
            )
    return out


def backends_payload(
    settings: Settings,
    registry: BackendRegistry,
    config_errors: list[str],
    backend: str | None = None,
) -> dict[str, Any]:
    ids = list(dict.fromkeys([*BACKEND_IDS, *settings.enabled_backends]))
    entries: list[BackendEntry] = []
    for backend_id in ids:
        if backend is not None and backend_id != backend:
            continue
        plugin = registry.get(backend_id)
        contract = plugin.contract if plugin else None
        effects = plugin.effects if plugin else KNOWN_EFFECTS.get(backend_id)
        entries.append(
            BackendEntry(
                id=backend_id,
                display_name=contract.display_name
                if contract
                else KNOWN_DISPLAY_NAMES.get(backend_id, backend_id),
                enabled=backend_id in settings.enabled_backends,
                available=plugin is not None,
                status=_status_of(plugin) if plugin else None,
                features=sorted(contract.supported_features) if contract else [],
                effects=EffectsInfo(
                    paid_calls_destructive=effects.paid_calls_destructive if effects else True,
                    job_reads_read_only=True,
                ),
                options=_options_for(backend_id, plugin),
                egress=(plugin.egress or None) if plugin else None,
                carriers=(plugin.carriers or None) if plugin else None,
                readonly_honesty=contract.readonly_honesty_statement if contract else None,
                implicit_context=contract.implicit_context_disclosure if contract else None,
            )
        )
    unavailable = [
        UnavailableEntry(id=u.backend_id, reason=u.reason, detail=u.detail)
        for u in registry.unavailable.values()
        if backend is None or u.backend_id == backend
    ]
    return BackendsResult(
        backends=entries,
        unavailable=unavailable,
        env_warnings=[
            *settings.env_warnings,
            *(f"{p} is an unexpanded ${{...}} placeholder" for p in settings.placeholders),
        ],
        config_errors=list(config_errors),
    ).model_dump(mode="json")


def models_payload(registry: BackendRegistry, backend: str) -> dict[str, Any]:
    plugin = registry.get(backend)
    if plugin is None:
        return ModelCatalogResult(
            backend=backend, available=False, models=[], source="none"
        ).model_dump(mode="json")
    listing = plugin.models.read()
    return ModelCatalogResult(
        backend=backend,
        available=True,
        models=[
            ModelInfo(
                slug=m.slug,
                display_name=m.display_name,
                default_reasoning_effort=m.default_reasoning_effort,
                supported_reasoning_efforts=list(m.supported_reasoning_efforts)
                if m.supported_reasoning_efforts is not None
                else None,
            )
            for m in listing.models
        ],
        source=listing.source,
        fetched_at=listing.fetched_at,
    ).model_dump(mode="json")


async def capabilities_payload(
    app: FastMCP,
    settings: Settings,
    registry: BackendRegistry,  # noqa: ARG001 - accepted for a future per-backend capabilities pass
    config_errors: list[str],  # noqa: ARG001 - accepted; not yet surfaced in CapabilitiesResult
    tasks_active: bool,
    detail: str = "summary",
    include_schemas: Sequence[str] | None = None,
) -> dict[str, Any]:
    effects = effects_for(settings)
    details = [
        ToolCapability(
            name=name,
            cost=TOOL_DETAILS[name]["cost"],
            stability=TOOL_STABILITY.get(name),  # ty: ignore[invalid-argument-type]
            backends=TOOL_DETAILS[name]["backends"],
            use_when=TOOL_DETAILS[name]["use_when"],
            required_params=_params_for(name)[0],
            key_optional_params=_params_for(name)[1],
            returns=TOOL_DETAILS[name]["returns"],
            error_codes=TOOL_DETAILS[name]["error_codes"],
        )
        for name in TOOL_ORDER
    ]
    schemas: dict[str, Any] | None = None
    if include_schemas:
        bodies = {
            "error-envelope": ERROR_ENVELOPE_SCHEMA,
            "result-meta": RESULT_META_SCHEMA,
            "capabilities-result": CAPABILITIES_RESULT_SCHEMA,
            "parameter-contracts": params_resource_body(),
        }
        schemas = {k: bodies[k] for k in include_schemas}
    caps = CapabilitiesResult(
        name=SERVER_NAME,
        version=__version__,
        surface_digest=await surface.surface_digest(app),
        transport="stdio",
        stability=SERVER_STABILITY,
        enabled_backends=list(settings.enabled_backends),
        active_tools=list(ACTIVE_TOOLS),
        free_tools=list(FREE_TOOLS),
        job_tools=list(JOB_TOOLS),
        tool_details=details,
        error_codes=list(ERROR_CODES),
        scope=[
            "Second opinions, git-change reviews, adversarial critiques and delegated diffs "
            "from Codex, Kimi or Claude Code, selected per call.",
            "Durable background jobs for every paid verb, plus the tasks extension when enabled.",
        ],
        negative_scope=[
            "Never applies a diff to your working tree.",
            "Never bypasses a backend's sandbox or approvals.",
            "Does not bound what a backend CLI reads: the workspace selects where it works, "
            "not what it can read.",
            "No session transfer in v1.",
        ],
        prerequisites=[
            "At least one backend CLI installed and authenticated (amicus_backends reports which).",
            "workspace_root on every call from a sessionless (2026-07-28) client.",
        ],
        deprecation_policy=(
            "A deprecated tool, parameter or code stays discoverable for two minor releases "
            "with a deprecation marker in its lifecycle _meta naming the replacement."
        ),
        tool_error_carrier=(
            "tool result with isError: true; the error envelope is in structuredContent, and "
            "content[0].text mirrors it as JSON. error.request_id carries the same value as "
            "meta.request_id (mirrored)."
        ),
        resource_error_carrier=(
            "JSON-RPC error; the envelope (machine_code/human_message/backend/temporary/"
            "retry_after_ms/repair/resource_uri/request_id) is in error.data. Classify by "
            "error.data.machine_code: the numeric is era-bound (-32002 on a 2025-11-25 "
            "connection, -32602 on 2026-07-28; -32603 for a read failure on both)."
        ),
        annotations_reading=(
            "Annotations describe the worst ENABLED backend, not the backend selected per "
            f"call: paid tools are destructiveHint {str(effects.paid_calls_destructive).lower()} "
            "for this profile because "
            + (
                "Claude Code is enabled and its config modes may run workspace hooks. "
                if effects.paid_calls_destructive
                else "every enabled backend confines writes to a throwaway worktree. "
            )
            + "readOnlyHint tracks whether a call changes observable state that outlives the "
            "response (a job record, committed spend), so paid tools are readOnlyHint false "
            "even when the run writes nothing, and job reads stay readOnlyHint true under the "
            "observable-scope reading. Per-backend effects are published on amicus_backends."
        ),
        tasks=TaskSupport(
            enabled=tasks_active,
            task_tools=list(PAID_TOOLS) if tasks_active else [],
            fallback=(
                "A `completed` task is a delivery statement, not a success statement: inspect "
                "the delivered result's ok field (isError is set on it too). Only a modern-era "
                "client that declares the extension gets a task; a handshake-era client gets "
                "the plain result. A task result is readable through tasks/get for 15 minutes "
                "after completion; the job behind it is retained separately for AMICUS_JOB_TTL "
                "(default 24h, operator-configurable down to 60s, so it can expire before or "
                "after the task result), amicus_job_list(task_id=...) recovers it while "
                "retained, cancelling the task cancels the job, and every host can use the "
                "amicus_job_* tools instead."
            ),
        ),
        meta_fields=list(Meta.model_fields),
        schemas=schemas,
    ).model_dump(mode="json", exclude_none=True)
    if detail == "contracts":
        caps["tool_details"] = []
    elif detail == "summary":
        caps["tool_details"] = [
            {k: d.get(k) for k in _SUMMARY_FIELDS} for d in caps["tool_details"]
        ]
    else:
        for entry in caps["tool_details"]:
            entry.setdefault("stability", None)
    return caps


def register(
    app: FastMCP, settings: Settings, registry: BackendRegistry, state: AppState
) -> tuple[str, ...]:
    @app.tool(
        name="amicus_backends",
        annotations=annotations_for("free", settings),
        output_schema=BACKENDS_SCHEMA,
        title="List backends and their readiness (free)",
        meta=lifecycle_meta("amicus_backends"),
        description=(
            f"{FREE_MARKER} Every known backend with enabled/available state, an installed/"
            "authenticated probe for the available ones, declared features, the backend_options "
            "each accepts with allowed values, annotation effects, egress and prompt carriers; "
            "plus why an enabled backend is unavailable, legacy-env warnings and config errors. "
            "Run it before the first paid call."
        ),
    )
    @guard("amicus_backends", settings)
    async def amicus_backends(backend: OptionalBackendParam = None) -> dict[str, Any]:
        """List backends."""
        return backends_payload(settings, registry, state.config_errors, backend)

    @app.tool(
        name="amicus_models",
        annotations=annotations_for("free", settings),
        output_schema=MODEL_CATALOG_SCHEMA,
        title="List a backend's models (free)",
        meta=lifecycle_meta("amicus_models"),
        description=(
            f"{FREE_MARKER} Advisory model slugs for `backend` (pass as `model`) with each "
            "model's advertised reasoning-effort set; the backend validates the real values. "
            "Not fingerprint-stable; same payload as amicus://models/{backend}."
        ),
    )
    @guard("amicus_models", settings)
    async def amicus_models(backend: BackendParam) -> dict[str, Any]:
        """List a backend's models. Reports `backend_unavailable`, like every paid tool,
        when the backend has no loaded plugin (see `resolve_paid_call`'s same shape)."""
        plugin = registry.get(backend)
        if plugin is None:
            why = registry.unavailable_for(backend)
            detail = f"{why.reason}: {why.detail}" if why else "not enabled in AMICUS_BACKENDS"
            return error_envelope(
                "backend_unavailable",
                f"backend {backend!r} is unavailable ({detail})",
                base_meta(settings, backend=backend),
                backend=backend,
            )
        return models_payload(registry, backend)

    @app.tool(
        name="amicus_capabilities",
        annotations=annotations_for("free", settings),
        output_schema=CAPABILITIES_SCHEMA,
        title="List server capabilities (free)",
        meta=lifecycle_meta("amicus_capabilities"),
        description=(
            f"{FREE_MARKER} The tool inventory, fingerprint and surface_digest (cache by them), "
            "the full error-code catalog, the annotation policy, the tasks/jobs contract, and "
            "meta's field list. detail=summary (default) | full | contracts; include_schemas "
            "embeds error-envelope, result-meta, capabilities-result and/or "
            "parameter-contracts for resource-blind clients."
        ),
    )
    @guard("amicus_capabilities", settings)
    async def amicus_capabilities(
        detail: CapabilitiesDetailParam = "summary", include_schemas: IncludeSchemasParam = None
    ) -> dict[str, Any]:
        """List capabilities. An unknown `include_schemas` name is rejected at the call
        boundary (ValidationEnvelopeMiddleware) since the parameter is a Literal list."""
        return await capabilities_payload(
            app,
            settings,
            registry,
            state.config_errors,
            state.tasks_active,
            detail,
            include_schemas,
        )

    return ("amicus_backends", "amicus_models", "amicus_capabilities")
