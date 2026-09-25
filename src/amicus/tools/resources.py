"""Four static resources, two templates with completion, one lifecycle _meta each."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastmcp.resources import FunctionResource
from mcp_types import Resource as SDKResource
from mcp_types import ResourceTemplateReference

from amicus import middleware
from amicus.schemas.codes import BACKEND_IDS
from amicus.schemas.envelope import ERROR_ENVELOPE_SCHEMA, RESULT_META_SCHEMA
from amicus.schemas.fingerprint import TRIAGE_META_KEY
from amicus.schemas.params import PARAMS_RESOURCE_URI, params_resource_body
from amicus.tools import discovery
from amicus.tools._meta import server_lifecycle_meta

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
# Written descriptions for the two templates (#250): a docstring reaches the wire with its
# line breaks, and the old models text named internals and claimed a resource read carries
# no repair, which `error.data.repair` on resource_not_found disproves.
BACKEND_TEMPLATE_DESC = (
    "One backend's amicus_backends entry at detail=full, disclosures included; an unknown "
    "backend id is resource_not_found."
)
MODELS_TEMPLATE_DESC = (
    "One backend's amicus_models payload. Unlike the tool, a known but unavailable backend "
    "returns the informational available=false payload rather than a backend_unavailable "
    "error; only an unknown backend id is resource_not_found."
)


def _meta(*, volatile: bool = False) -> dict[str, Any]:
    """The `_meta` block of a resource or template record. Size is not here: it has a
    native home (`Resource.size`, see `SizedResource`), and it is omitted, never `0`,
    when the body is built per read. `volatile` has no native home, so it stays a
    convention extension and is the only triage key (#48)."""
    meta = server_lifecycle_meta()
    if volatile:
        meta[TRIAGE_META_KEY] = {"volatile": True}
    return meta


class SizedResource(FunctionResource):
    """A static resource whose record carries the native `Resource.size`. FastMCP's
    `Resource` has no size field and its `to_mcp_resource` forwards none, so the value
    rides this subclass and is set on the wire record here; `surface.py` and the manifest
    both go through `to_mcp_resource`, so the digest and the snapshot see the same record
    a client lists."""

    size: int | None = None

    def to_mcp_resource(self, **overrides: Any) -> SDKResource:
        return super().to_mcp_resource(**overrides).model_copy(update={"size": self.size})


def _static_body_size(payload: dict[str, Any]) -> int:
    """The byte length of exactly the text a read returns. FastMCP serialises a dict
    body with `json.dumps(value)` (no `indent`, no `separators`), so the same call here
    is the size of the served content, which is what `Resource.size` is defined as."""
    return len(json.dumps(payload).encode())


def _add_static(
    app: FastMCP, fn: Any, *, uri: str, name: str, title: str, mime_type: str, body: dict[str, Any]
) -> None:
    resource = SizedResource.from_function(
        fn, uri=uri, name=name, title=title, mime_type=mime_type, meta=_meta()
    )
    # `from_function` builds `cls`; its annotation says the base class, so narrow it.
    if not isinstance(resource, SizedResource):  # pragma: no cover
        raise TypeError("from_function did not build a SizedResource")
    resource.size = _static_body_size(body)
    app.add_resource(resource)


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

    def error_envelope_resource() -> dict[str, Any]:
        """The full ErrorResult schema; tool outputSchemas carry only an opaque error branch."""
        return ERROR_ENVELOPE_SCHEMA

    _add_static(
        app,
        error_envelope_resource,
        uri="amicus://error-envelope",
        name="amicus-error-envelope",
        title="amicus error envelope schema",
        mime_type="application/schema+json",
        body=ERROR_ENVELOPE_SCHEMA,
    )

    def result_meta_resource() -> dict[str, Any]:
        """The full Meta schema every success envelope's opaque `meta` points at."""
        return RESULT_META_SCHEMA

    _add_static(
        app,
        result_meta_resource,
        uri="amicus://result-meta",
        name="amicus-result-meta",
        title="amicus result metadata schema",
        mime_type="application/schema+json",
        body=RESULT_META_SCHEMA,
    )

    def params_resource() -> dict[str, Any]:
        """Full semantics for parameters whose inline description is a compressed summary."""
        return params_resource_body()

    _add_static(
        app,
        params_resource,
        uri=PARAMS_RESOURCE_URI,
        name="amicus-params",
        title="amicus parameter contracts",
        mime_type="application/json",
        body=params_resource_body(),
    )

    @app.resource(
        "amicus://backends/{backend}",
        name="amicus-backend",
        title="One backend's catalog entry",
        description=BACKEND_TEMPLATE_DESC,
        mime_type="application/json",
        meta=_meta(volatile=True),
    )
    def backend_resource(backend: str) -> dict[str, Any]:
        """See BACKEND_TEMPLATE_DESC; a single-backend read never takes the summary projection."""
        payload = discovery.backends_payload(
            settings, registry, state.config_errors, backend, detail="full"
        )
        if not payload["backends"]:
            raise _resource_not_found(f"amicus://backends/{backend}")
        return {**payload["backends"][0], "unavailable": payload["unavailable"]}

    @app.resource(
        "amicus://models/{backend}",
        name="amicus-models",
        title="One backend's model catalog",
        description=MODELS_TEMPLATE_DESC,
        mime_type="application/json",
        meta=_meta(volatile=True),
    )
    def models_resource(backend: str) -> dict[str, Any]:
        """See MODELS_TEMPLATE_DESC."""
        if backend not in BACKEND_IDS and registry.get(backend) is None:
            raise _resource_not_found(f"amicus://models/{backend}")
        return discovery.models_payload(registry, backend)

    app.completion(complete_backend)
