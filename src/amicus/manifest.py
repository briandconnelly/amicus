"""Canonical manifest of the agent-visible surface, per profile (ADR 0006).

Ported from codex-in-claude: both protocol eras are captured (legacy `initialize`, modern
`server/discover` and the modern result envelopes), every static resource body is read
and parsed, and the capabilities payload is captured minus release-variable and
self-referential fields. A committed snapshot per profile plus a pinned hash guard
FINGERPRINT; regeneration is always its own commit.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import sys
from typing import Any

from fastmcp import Client, FastMCP

from amicus import config, server
from amicus.registry import BackendRegistry

PROFILES: dict[str, dict[str, str]] = {
    "all": {},
    "codex-kimi": {"AMICUS_BACKENDS": "codex,kimi"},
    "claude": {"AMICUS_BACKENDS": "claude"},
}
_FASTMCP_META_KEY = "fastmcp"
_SETLIKE_ARRAY_KEYS = frozenset({"enum", "required"})
RELEASE_VARIABLE_EXCLUDE = frozenset({"version", "server_version"})
SELF_REFERENTIAL_EXCLUDE = frozenset({"fingerprint", "surface_digest"})
_DISCOVER_SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
_MODERN_ERA = "2026-07-28"
RESULT_ENVELOPE_FIELDS = ("resultType", "ttlMs", "cacheScope")
STATIC_RESOURCE_URIS = ("amicus://error-envelope", "amicus://result-meta", "amicus://params")
# Content never read: it embeds surface_digest (self-referential) and the live env report.
DYNAMIC_RESOURCE_URIS = ("amicus://capabilities",)
_SECTION_BY_STATIC_URI = {
    "amicus://error-envelope": "error_envelope",
    "amicus://result-meta": "result_meta",
    "amicus://params": "params",
}
_ENVELOPE_PROBE_TOOL = "amicus_capabilities"
_ENVELOPE_PROBE_ARGS: dict[str, Any] = {"detail": "summary"}


def app_for_profile(profile: str) -> FastMCP:
    """An app for a profile with NO backend loaded: the manifest guards the schema-only
    surface, which must not depend on which CLIs this machine has installed."""
    return server.create_app(config.settings(PROFILES[profile]), BackendRegistry({}, {}))


def _sorted_by_json(items: list[Any]) -> list[Any]:
    return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, raw in obj.items():
            value = raw
            if key == "_meta" and isinstance(raw, dict):
                value = {k: v for k, v in raw.items() if k != _FASTMCP_META_KEY}
                if not value:
                    continue
            cval = _canonicalize(value)
            if isinstance(cval, list) and (key in _SETLIKE_ARRAY_KEYS or key == "type"):
                cval = _sorted_by_json(cval)
            out[key] = cval
        return out
    if isinstance(obj, list):
        return [_canonicalize(v) for v in obj]
    return obj


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def _envelope_fields(result: Any) -> dict[str, Any]:
    wire = _dump(result)
    return {k: wire[k] for k in RESULT_ENVELOPE_FIELDS if k in wire}


def _envelope_block(content: Any) -> dict[str, Any]:
    block = _canonicalize(_dump(content))
    text = block.get("text")
    if isinstance(text, str):
        with contextlib.suppress(json.JSONDecodeError):
            block["text"] = _canonicalize(json.loads(text))
    return block


async def build_manifest(app: FastMCP) -> dict[str, Any]:
    async with Client(app, mode="legacy") as client:
        tools = [_canonicalize(_dump(t)) for t in await client.list_tools()]
        resources = [_canonicalize(_dump(r)) for r in await client.list_resources()]
        templates = [_canonicalize(_dump(t)) for t in await client.list_resource_templates()]
        prompts = [_canonicalize(_dump(p)) for p in await client.list_prompts()]
        initialize = _canonicalize(_dump(client.initialize_result))
        server_info = initialize.get("serverInfo")
        if isinstance(server_info, dict):
            server_info.pop("version", None)
        static_sections = {
            _SECTION_BY_STATIC_URI[uri]: [
                _envelope_block(c) for c in await client.read_resource(uri)
            ]
            for uri in STATIC_RESOURCE_URIS
        }
        caps_result = await client.call_tool(_ENVELOPE_PROBE_TOOL, {"detail": "full"})
    caps = {
        k: v
        for k, v in caps_result.structured_content.items()
        if k not in RELEASE_VARIABLE_EXCLUDE | SELF_REFERENTIAL_EXCLUDE
    }
    async with Client(app) as modern:
        if modern.protocol_version != _MODERN_ERA:  # pragma: no cover - guard
            raise RuntimeError(f"default client negotiated {modern.protocol_version!r}")
        discover = _canonicalize(_dump(modern.session.discover_result))
        envelopes: dict[str, Any] = {
            "tools/list": _envelope_fields(await modern.list_tools_mcp()),
            "resources/list": _envelope_fields(await modern.list_resources_mcp()),
            "resources/templates/list": _envelope_fields(
                await modern.list_resource_templates_mcp()
            ),
            "prompts/list": _envelope_fields(await modern.list_prompts_mcp()),
            "resources/read": {
                uri: _envelope_fields(await modern.read_resource_mcp(uri))
                for uri in STATIC_RESOURCE_URIS
            },
            "tools/call": _envelope_fields(
                await modern.call_tool_mcp(_ENVELOPE_PROBE_TOOL, _ENVELOPE_PROBE_ARGS)
            ),
        }
    meta = discover.get("_meta")
    if isinstance(meta, dict) and isinstance(meta.get(_DISCOVER_SERVER_INFO_META), dict):
        meta[_DISCOVER_SERVER_INFO_META].pop("version", None)
    return {
        "tools": sorted(tools, key=lambda t: t["name"]),
        "resources": sorted(resources, key=lambda r: r["uri"]),
        "resource_templates": sorted(templates, key=lambda t: t["uriTemplate"]),
        "prompts": sorted(prompts, key=lambda p: p["name"]),
        "initialize": initialize,
        "discover": discover,
        "modern_result_envelopes": envelopes,
        **static_sections,
        "capabilities": _canonicalize(caps),
    }


def manifest_json(manifest: dict[str, Any]) -> str:
    return (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    )


async def manifest_hash(app: FastMCP) -> str:
    return hashlib.sha256(manifest_json(await build_manifest(app)).encode("utf-8")).hexdigest()


def render(profile: str) -> str:
    return manifest_json(asyncio.run(build_manifest(app_for_profile(profile))))


async def tools_list_bytes(app: FastMCP) -> int:
    """The serialized tools/list a client receives (the discovery-cost measurement)."""
    async with Client(app) as c:
        tools = await c.list_tools()
    payload = [t.model_dump(mode="json", exclude_none=True, by_alias=True) for t in tools]
    return len(json.dumps(payload, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description="Render the manifest or measure tools/list.")
    parser.add_argument("--profile", default="all", choices=sorted(PROFILES))
    parser.add_argument("--measure", action="store_true", help="print tools/list bytes per profile")
    args = parser.parse_args(argv)
    if args.measure:
        for profile in PROFILES:
            size = asyncio.run(tools_list_bytes(app_for_profile(profile)))
            sys.stdout.write(f"{profile}\t{size}\n")
        return 0
    sys.stdout.write(render(args.profile))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
