"""FastMCP middlewares: connection log, schema dialect, semantic isError, the invalid_arguments
envelope at the call boundary, and the JSON-RPC error.data envelope for resource reads."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastmcp.exceptions import DisabledError, NotFoundError, ResourceError
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from pontonier.core import redaction
from pydantic import ValidationError

from amicus import obs
from amicus.errors import make_error, serialize_error, serialize_error_info
from amicus.schemas.envelope import ErrorResult, InvalidArgument, Meta
from amicus.schemas.fingerprint import JSON_SCHEMA_DIALECT

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings

MAX_INVALID_ARGS = 25
MAX_ARG_REASON_LEN = 300
MAX_ARG_FIELD_LEN = 128
WITHHELD_FIELD = "<withheld>"
_MISSING_TYPES = frozenset({"missing", "missing_argument"})
RESOURCE_NOT_FOUND_HANDSHAKE = -32002
RESOURCE_NOT_FOUND_MODERN = INVALID_PARAMS
TASKS_EXTENSION_ID = "io.modelcontextprotocol/tasks"


def _has_control_char(text: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in text)


def _loc_is_withheld(loc: tuple[object, ...]) -> bool:
    return any(isinstance(c, str) and _has_control_char(c) for c in loc)


def format_loc(loc: tuple[object, ...]) -> str:
    """A stable accessor path for a pydantic loc; withheld when it carries a control char."""
    if _loc_is_withheld(loc):
        return WITHHELD_FIELD
    out = ""
    for component in loc:
        if isinstance(component, int):
            out += f"[{component}]"
        elif out:
            out += f".{component}"
        else:
            out = str(component)
    if len(out) > MAX_ARG_FIELD_LEN:
        out = out[:MAX_ARG_FIELD_LEN] + "…"
    return out or "<arguments>"


def _enum_for_property(prop: Any, *, element: bool = False) -> list[str] | None:
    if not isinstance(prop, dict):
        return None
    branches = [prop, *(b for b in prop.get("anyOf", []) if isinstance(b, dict))]
    for branch in branches:
        node = branch.get("items") if element else branch
        if not isinstance(node, dict):
            continue
        enum = node.get("enum")
        if isinstance(enum, list):
            return [str(v) for v in enum]
    return None


def invalid_arguments_envelope(
    tool_name: str,
    *,
    param_names: set[str],
    property_schemas: dict[str, Any],
    errors: list[Any],
    meta: Meta,
) -> dict[str, Any] | None:
    """The `invalid_arguments` envelope for a pydantic argument ValidationError, or None
    when the errors are not request-argument failures (re-raise those untouched)."""
    for err in errors:
        loc = err.get("loc") or ()
        is_extra = err.get("type") in ("unexpected_keyword_argument", "extra_forbidden")
        if not is_extra and not (loc and str(loc[0]) in param_names):
            return None
    total = len(errors)
    items: list[InvalidArgument] = []
    for err in errors[:MAX_INVALID_ARGS]:
        loc = tuple(err.get("loc") or ())
        indexed = len(loc) > 1 and isinstance(loc[1], int)
        allowed = (
            _enum_for_property(property_schemas.get(str(loc[0])), element=indexed) if loc else None
        )
        items.append(
            InvalidArgument(
                field=format_loc(loc),
                reason=str(err.get("msg", ""))[:MAX_ARG_REASON_LEN],
                allowed_values=allowed,
                field_withheld=_loc_is_withheld(loc),
            )
        )
    first = items[0]
    shown = f" (showing {len(items)} of {total})" if total > len(items) else ""
    safe_field = redaction.sanitize_echo(first.field)
    message = f"{tool_name}: {total} invalid argument(s){shown}: {safe_field} — {first.reason}"
    types = {err.get("type") for err in errors}
    hints: list[str] = []
    if types & {"unexpected_keyword_argument", "extra_forbidden"}:
        hints.append("remove the unknown argument(s)")
    if types & _MISSING_TYPES:
        hints.append("provide the required argument(s)")
    if "literal_error" in types:
        hints.append("use one of the field's allowed_values")
    detail = f" — {'; '.join(hints)}" if hints else ""
    alternative = (
        f"Correct the argument(s) first{detail}. Consult each tool's inputSchema "
        "(tools/list) or call amicus_capabilities for the parameters and accepted values, "
        "then retry."
    )
    return serialize_error(
        ErrorResult(
            error=make_error(
                "invalid_arguments",
                message[:300],
                repair_tool=tool_name,
                repair_alternative=alternative,
                invalid_arguments=items,
            ),
            meta=meta,
        )
    )


def connection_facts(context: object) -> dict[str, Any]:
    """What a tool call's connection negotiated: the protocol version, the handshake-era
    clientInfo (modern connections carry none) and whether the client declared the tasks
    extension for this request. Every read is defensive: an in-memory client, a legacy
    session and a sessionless request each lack some of these."""
    fastmcp_context = getattr(context, "fastmcp_context", None)
    request_context = getattr(fastmcp_context, "request_context", None)
    version = getattr(request_context, "protocol_version", None)
    session = None
    if fastmcp_context is not None:
        try:
            session = fastmcp_context.session
        except RuntimeError:
            session = None
    params = getattr(session, "client_params", None)
    # `client_info` on the MCP SDK v2; `clientInfo` is the pre-v2 alias (see Task 2's fix).
    info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
    name = getattr(info, "name", None)
    client_version = getattr(info, "version", None)
    tasks = False
    if fastmcp_context is not None:
        try:
            tasks = fastmcp_context.client_extension_settings(TASKS_EXTENSION_ID) is not None
        except Exception:
            tasks = False
    return {
        "protocol": str(version) if version else "unknown",
        "client": name if isinstance(name, str) and name else "unknown",
        "client_version": (
            client_version if isinstance(client_version, str) and client_version else "unknown"
        ),
        "tasks": tasks,
    }


class ConnectionLogMiddleware(Middleware):
    """One DEBUG line per tool call naming what the connection negotiated. The line carries
    the tool NAME and connection facts only, never an argument (AGENTS.md rule 18); it is
    the instrument behind the host captures under docs/host-captures/ (M5)."""

    async def on_call_tool(self, context, call_next):  # type: ignore[no-untyped-def]
        facts = connection_facts(context)
        obs.get_logger(__name__).debug(
            "tools/call %s: protocol=%s client=%s/%s tasks_negotiated=%s",
            getattr(getattr(context, "message", None), "name", "?"),
            facts["protocol"],
            facts["client"],
            facts["client_version"],
            facts["tasks"],
        )
        return await call_next(context)


class InputSchemaDialectMiddleware(Middleware):
    """Stamp the JSON Schema dialect onto every tool's input schema ([3.dialect]).

    Returns COPIES, never mutating the registry's own `Tool.parameters` dict in place:
    an in-place stamp would leak into every other reader of that shared object (e.g.
    `surface.surface_records`'s `run_middleware=False` dump), making the visible schema
    depend on whether a middleware-driven `tools/list` happened to run first."""

    async def on_list_tools(self, context, call_next):  # type: ignore[no-untyped-def]
        tools = await call_next(context)
        return [
            tool.model_copy(
                update={"parameters": {**tool.parameters, "$schema": JSON_SCHEMA_DIALECT}}
            )
            if tool.parameters is not None
            else tool
            for tool in tools
        ]


class SemanticErrorMiddleware(Middleware):
    """An `ok: false` envelope is an MCP `isError: true` result ([6.tool-errors]).

    Safety net for the foreground path only. A task-augmented call (`fastmcp[tasks]`,
    ADR 0004) intercepts `tools/call` before this middleware's `call_next` reaches the
    tool body and returns a `CreateTaskResult` instead of a `ToolResult`, and the eventual
    task result never re-enters this middleware (the worker invokes the tool directly), so
    the flip an agent relies on is produced by the tool itself: `tools._guard.as_tool_result`
    returns an `is_error` `ToolResult` for every `ok: false` envelope on both paths (M5).
    """

    async def on_call_tool(self, context, call_next):  # type: ignore[no-untyped-def]
        result = await call_next(context)
        if not isinstance(result, ToolResult):
            return result
        sc = result.structured_content
        if isinstance(sc, dict) and sc.get("ok") is False:
            result.is_error = True
        return result


class ValidationEnvelopeMiddleware(Middleware):
    """Re-emit a call-boundary argument ValidationError as the documented envelope."""

    def __init__(self, app: FastMCP, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def on_call_tool(self, context, call_next):  # type: ignore[no-untyped-def]
        try:
            return await call_next(context)
        except (ValidationError, FastMCPValidationError) as exc:
            cause = exc if isinstance(exc, ValidationError) else exc.__cause__
            if not isinstance(cause, ValidationError):
                raise
            name = context.message.name
            try:
                tool = await self._app.get_tool(name)
                params = tool.parameters if tool is not None else None
                props = params.get("properties", {}) if params else {}
            except Exception:
                raise exc from None
            envelope = invalid_arguments_envelope(
                name,
                param_names=set(props),
                property_schemas=props,
                errors=cause.errors(),
                meta=Meta(timeout_seconds=self._settings.timeout_seconds),
            )
            if envelope is None:
                raise
            return ToolResult(structured_content=envelope, is_error=True)


def resource_not_found_code(context: object) -> int:
    """-32002 on a handshake-era connection, -32602 on a modern one (SEP-2164); the
    handshake value without positive evidence of a modern connection."""
    fastmcp_context = getattr(context, "fastmcp_context", None)
    request_context = getattr(fastmcp_context, "request_context", None)
    version = getattr(request_context, "protocol_version", None)
    if version in MODERN_PROTOCOL_VERSIONS:
        return RESOURCE_NOT_FOUND_MODERN
    return RESOURCE_NOT_FOUND_HANDSHAKE


def resource_error(code: str, mcp_code: int, message: str, resource_uri: str | None) -> MCPError:
    """Build the §6 JSON-RPC envelope for a resource-read failure, with code/message
    renamed machine_code/human_message ([6.rename]). Shared by ResourceErrorMiddleware
    (a read failure it observes) and any resource/template handler that needs to raise
    the same envelope itself — a handler-raised `MCPError` passes through both FastMCP's
    own read_resource and this middleware unmodified, unlike `NotFoundError` (which does
    not subclass FastMCPError and gets masked into a generic ResourceError first)."""
    info = make_error(code, message)
    info.resource_uri = resource_uri
    info.request_id = uuid4().hex
    data = serialize_error_info(info)
    data["machine_code"] = data.pop("code")
    data["human_message"] = data.pop("message")
    return MCPError(code=mcp_code, message=message, data=data)


class ResourceErrorMiddleware(Middleware):
    """Carry the §6 envelope in a resource-read failure's JSON-RPC error.data, with
    code/message renamed machine_code/human_message ([6.rename])."""

    async def on_read_resource(self, context, call_next):  # type: ignore[no-untyped-def]
        message = getattr(context, "message", None)
        uri = str(getattr(message, "uri", "") or "") or None
        try:
            return await call_next(context)
        except (NotFoundError, DisabledError) as exc:
            raise resource_error(
                "resource_not_found", resource_not_found_code(context), "Resource not found.", uri
            ) from exc
        except ResourceError as exc:
            raise resource_error(
                "internal_error", INTERNAL_ERROR, "Resource read failed.", uri
            ) from exc
