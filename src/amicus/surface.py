"""The server-side surface records and their digest (ADR 0006)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pontonier.conventions.fingerprint import canonical_digest

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

_FASTMCP_META_KEY = "fastmcp"


def _clean(record: dict[str, Any]) -> dict[str, Any]:
    meta = record.get("_meta")
    if isinstance(meta, dict):
        meta = {k: v for k, v in meta.items() if k != _FASTMCP_META_KEY}
        if meta:
            record["_meta"] = meta
        else:
            record.pop("_meta", None)
    return record


def _dump(model: Any) -> dict[str, Any]:
    return _clean(model.model_dump(mode="json", by_alias=True, exclude_none=True))


async def surface_records(app: FastMCP) -> dict[str, Any]:
    """Tool, resource and template records as the server holds them, sorted by identity,
    plus the instructions text. Tools run WITH middleware (default): FastMCP's own client
    stamps the input-schema dialect onto the shared Tool.parameters dict in place the
    first time any `tools/list` (including an implicit one during a `call_tool` result's
    output-schema validation) runs with middleware, so a `run_middleware=False` read taken
    before that first stamp disagrees with one taken after it. Running middleware here
    applies (and stabilizes) that stamp instead of racing it. Resources/templates have no
    registered `on_list_*` middleware, so `run_middleware=False` is equivalent for them
    and kept for a minimal, deterministic dump."""
    tools = [_dump(t.to_mcp_tool()) for t in await app.list_tools()]
    resources = [_dump(r.to_mcp_resource()) for r in await app.list_resources(run_middleware=False)]
    templates = [
        _dump(t.to_mcp_template()) for t in await app.list_resource_templates(run_middleware=False)
    ]
    return {
        "tools": sorted(tools, key=lambda t: t["name"]),
        "resources": sorted(resources, key=lambda r: r["uri"]),
        "resource_templates": sorted(templates, key=lambda t: t["uriTemplate"]),
        "instructions": app.instructions,
    }


async def surface_digest(app: FastMCP) -> str:
    return canonical_digest(await surface_records(app))
