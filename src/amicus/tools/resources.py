"""Four static resources, two templates with completion, one lifecycle _meta each."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from mcp_types import ResourceTemplateReference

from amicus import middleware
from amicus.schemas.codes import BACKEND_IDS
from amicus.schemas.envelope import ERROR_ENVELOPE_SCHEMA, RESULT_META_SCHEMA
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY, TRIAGE_META_KEY
from amicus.schemas.params import PARAMS_RESOURCE_URI, params_resource_body
from amicus.tools import discovery
from amicus.tools._meta import SERVER_STABILITY

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP
    from mcp import MCPError

    from amicus.appstate import AppState
    from amicus.config import Settings
    from amicus.registry import BackendRegistry

STATIC_RESOURCE_URIS: tuple[str, ...] = (
    "amicus://capabilities",
    "amicus://error-envelope",
    "amicus://result-meta",
    PARAMS_RESOURCE_URI,
)
TEMPLATE_URIS: tuple[str, ...] = ("amicus://backends/{backend}", "amicus://models/{backend}")


def _meta(payload: dict[str, Any] | None = None, *, volatile: bool = False) -> dict[str, Any]:
    # `size_bytes` is always present (0 for a volatile resource with no static payload to
    # size) so a caller can check it unconditionally before falling back to `volatile`.
    triage: dict[str, Any] = {
        "size_bytes": len(json.dumps(payload).encode()) if payload is not None else 0
    }
    if volatile:
        triage["volatile"] = True
    return {LIFECYCLE_META_KEY: {"stability": SERVER_STABILITY}, TRIAGE_META_KEY: triage}


def complete_backend(ref: Any, argument: Any, context: Any) -> list[str] | None:  # noqa: ARG001
    if not isinstance(ref, ResourceTemplateReference) or ref.uri not in TEMPLATE_URIS:
        return None
    if getattr(argument, "name", None) != "backend":
        return []
    prefix = getattr(argument, "value", "") or ""
    return [b for b in BACKEND_IDS if b.startswith(prefix)]


def _resource_not_found(uri: str) -> MCPError:
    """A ready `resource_not_found` MCPError, raised directly rather than via
    `fastmcp.exceptions.NotFoundError`: that type does not subclass FastMCPError, so
    FastMCP's own read_resource masks a handler-raised instance into a generic
    ResourceError before ResourceErrorMiddleware ever sees it. An MCPError we build
    ourselves (via the same `middleware.resource_error` builder the middleware itself
    uses) is passed through unmodified by both FastMCP and that middleware."""
    try:
        from fastmcp.server.dependencies import get_context  # noqa: PLC0415

        code = middleware.resource_not_found_code(SimpleNamespace(fastmcp_context=get_context()))
    except RuntimeError:
        code = middleware.RESOURCE_NOT_FOUND_HANDSHAKE
    return middleware.resource_error("resource_not_found", code, "Resource not found.", uri)


def register_resources(
    app: FastMCP, settings: Settings, registry: BackendRegistry, state: AppState
) -> None:
    @app.resource(
        "amicus://capabilities",
        name="amicus-capabilities",
        title="amicus capability summary",
        mime_type="application/json",
        meta=_meta(volatile=True),
    )
    async def capabilities_resource() -> dict[str, Any]:
        """The amicus_capabilities payload (detail=summary) as a resource."""
        return await discovery.capabilities_payload(
            app, settings, registry, state.config_errors, state.tasks_active
        )

    @app.resource(
        "amicus://error-envelope",
        name="amicus-error-envelope",
        title="amicus error envelope schema",
        mime_type="application/schema+json",
        meta=_meta(ERROR_ENVELOPE_SCHEMA),
    )
    def error_envelope_resource() -> dict[str, Any]:
        """The full ErrorResult schema; tool outputSchemas carry only an opaque error branch."""
        return ERROR_ENVELOPE_SCHEMA

    @app.resource(
        "amicus://result-meta",
        name="amicus-result-meta",
        title="amicus result metadata schema",
        mime_type="application/schema+json",
        meta=_meta(RESULT_META_SCHEMA),
    )
    def result_meta_resource() -> dict[str, Any]:
        """The full Meta schema every success envelope's opaque `meta` points at."""
        return RESULT_META_SCHEMA

    @app.resource(
        PARAMS_RESOURCE_URI,
        name="amicus-params",
        title="amicus parameter contracts",
        mime_type="application/json",
        meta=_meta(params_resource_body()),
    )
    def params_resource() -> dict[str, Any]:
        """Full semantics for parameters whose inline description is a compressed summary."""
        return params_resource_body()

    @app.resource(
        "amicus://backends/{backend}",
        name="amicus-backend",
        title="One backend's catalog entry",
        mime_type="application/json",
        meta=_meta(volatile=True),
    )
    def backend_resource(backend: str) -> dict[str, Any]:
        """The amicus_backends entry for one backend."""
        payload = discovery.backends_payload(settings, registry, state.config_errors, backend)
        if not payload["backends"]:
            raise _resource_not_found(f"amicus://backends/{backend}")
        return {**payload["backends"][0], "unavailable": payload["unavailable"]}

    @app.resource(
        "amicus://models/{backend}",
        name="amicus-models",
        title="One backend's model catalog",
        mime_type="application/json",
        meta=_meta(volatile=True),
    )
    def models_resource(backend: str) -> dict[str, Any]:
        """The amicus_models payload for one backend, unlike the `amicus_models` TOOL:
        for an unavailable (but known) backend id this returns the informational
        `available: false` payload rather than a `backend_unavailable` error envelope,
        because a resource read has no repair carrier to put one in. Only an unknown
        backend id (not in BACKEND_IDS and not a loaded plugin) is resource_not_found."""
        if backend not in BACKEND_IDS and registry.get(backend) is None:
            raise _resource_not_found(f"amicus://models/{backend}")
        return discovery.models_payload(registry, backend)

    app.completion(complete_backend)
