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
import importlib
import json
import os
import subprocess
import sys
import threading
from typing import IO, TYPE_CHECKING, Any

from fastmcp import Client, FastMCP

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

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


# The era both captured hosts negotiate (docs/host-captures/: Claude Code 2.1.263 and
# Codex CLI 0.153.4 both initialize at 2025-11-25), so this is the body they receive. The
# 2026-07-28 body differs by its cache envelope and serverInfo `_meta` (~150 bytes) and by
# key order; it is not measured here.
HANDSHAKE_ERA = "2025-11-25"
_INITIALIZE_ID = 1
_TOOLS_LIST_ID = 2
_SERVER_ARGV = (sys.executable, "-m", "amicus.server")


def _result_body(line: str, request_id: int) -> str:
    """The `result` object's exact text out of one JSON-RPC response line.

    Exactness is the point: the line is never parsed and re-serialized, so key order,
    separators and escaping are the transport's own, and a tokenizer count over the
    returned text is a count of what the client read. Any other line shape is an error,
    never a guess."""
    prefix = f'{{"jsonrpc":"2.0","id":{request_id},"result":'
    if not line.startswith(prefix) or not line.endswith("}\n"):
        raise ValueError(f"unexpected JSON-RPC response shape for id {request_id}: {line[:80]!r}")
    return line[len(prefix) : -2]


def measurement_env() -> dict[str, str]:
    """This process's environment minus every namespace the server reads (`AMICUS_` and
    the legacy aliases `config.ENV_PREFIXES` names), so the profile alone decides the
    configuration and a developer's exported `*_LOG_FILE` is not opened by the
    measurement subprocess."""
    return {k: v for k, v in os.environ.items() if not k.startswith(config.ENV_PREFIXES)}


def _read_line(stream: IO[str], timeout: float, phase: str) -> str:
    """One response line from the child, or TimeoutError naming the `phase` that stalled.
    A blocking `readline` has no deadline of its own, and a child that starts but never
    answers would otherwise hang the measurement CLI and the pytest gate alike."""
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.append(stream.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        raise TimeoutError(f"amicus.server gave no {phase} response within {timeout}s")
    return lines[0]


def tools_list_wire(
    profile: str, *, env: Mapping[str, str] | None = None, timeout: float = 30.0
) -> str:
    """The `tools/list` result body as a real `amicus.server` stdio subprocess writes it
    for a handshake-era client, byte for byte (the discovery-cost measurement, issue #41).

    `env` is the subprocess environment (default: `measurement_env()`); the profile's own
    variables are laid over it. Tests pass an environment whose backend binaries are
    unusable. Each of the two responses must arrive within `timeout` seconds, or the
    child is terminated (killed if it ignores that) and TimeoutError says which stalled."""
    base = dict(env) if env is not None else measurement_env()
    proc = subprocess.Popen(
        _SERVER_ARGV,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=base | PROFILES[profile],
        text=True,
        encoding="utf-8",
    )
    stdin, stdout = proc.stdin, proc.stdout
    assert stdin is not None
    assert stdout is not None
    try:

        def send(message: dict[str, Any]) -> None:
            stdin.write(json.dumps(message) + "\n")
            stdin.flush()

        send(
            {
                "jsonrpc": "2.0",
                "id": _INITIALIZE_ID,
                "method": "initialize",
                "params": {
                    "protocolVersion": HANDSHAKE_ERA,
                    "capabilities": {},
                    "clientInfo": {"name": "amicus-manifest", "version": "0"},
                },
            }
        )
        init_line = _read_line(stdout, timeout, "initialize")
        negotiated = json.loads(_result_body(init_line, _INITIALIZE_ID))
        if negotiated.get("protocolVersion") != HANDSHAKE_ERA:
            raise ValueError(f"server negotiated {negotiated.get('protocolVersion')!r}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": _TOOLS_LIST_ID, "method": "tools/list", "params": {}})
        line = _read_line(stdout, timeout, "tools/list")
    finally:
        stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return _result_body(line, _TOOLS_LIST_ID)


def tools_list_bytes(profile: str, *, env: Mapping[str, str] | None = None) -> int:
    """UTF-8 bytes of `tools_list_wire`."""
    return len(tools_list_wire(profile, env=env).encode("utf-8"))


# Reference encodings for `--tokens`. Neither is the tokenizer of any backend amicus
# serves or of any host that preloads the catalog; they are stable, public encodings
# that turn a byte count into a token count with a known method, which is what the
# byte/4 proxy could not do (issue #41). Record the encoding beside any count you cite.
TOKEN_ENCODINGS: tuple[str, ...] = ("o200k_base", "cl100k_base")


def token_counts(text: str, encodings: tuple[str, ...] = TOKEN_ENCODINGS) -> dict[str, int]:
    """Token counts of `text` under each reference encoding, or SystemExit with the
    remedy when they cannot be produced. Never a partial or silent result: a count that
    is missing looks like one that was never asked for, so it is refused instead."""
    try:
        # Optional (`measure` group). Loaded by name so the type check is the same with
        # the package installed (a developer measuring) and without it (the gate).
        tiktoken = importlib.import_module("tiktoken")
    except ImportError as exc:
        raise SystemExit(
            "tiktoken is not installed; it is in the `measure` group: `uv sync --group measure`"
        ) from exc
    counts: dict[str, int] = {}
    for name in encodings:
        try:
            # First use fetches the encoding's data over the network into tiktoken's
            # cache (TIKTOKEN_CACHE_DIR); offline and uncached, this raises.
            encoding = tiktoken.get_encoding(name)
        except Exception as exc:
            raise SystemExit(
                f"could not load tiktoken encoding {name!r} ({type(exc).__name__}); it is "
                "fetched over the network on first use and cached under TIKTOKEN_CACHE_DIR"
            ) from exc
        counts[name] = len(encoding.encode(text))
    return counts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description="Render the manifest or measure tools/list.")
    parser.add_argument("--profile", default="all", choices=sorted(PROFILES))
    parser.add_argument("--measure", action="store_true", help="print tools/list bytes per profile")
    parser.add_argument(
        "--tokens",
        action="store_true",
        help="with --measure: also count tokens under the reference encodings (needs tiktoken)",
    )
    args = parser.parse_args(argv)
    if args.tokens and not args.measure:
        parser.error("--tokens counts the measurement; pass it with --measure")
    if args.measure:
        for profile in PROFILES:
            wire = tools_list_wire(profile)
            row = f"{profile}\t{len(wire.encode('utf-8'))}"
            if args.tokens:
                row += "".join(f"\t{k}={v}" for k, v in token_counts(wire).items())
            sys.stdout.write(row + "\n")
        return 0
    sys.stdout.write(render(args.profile))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
