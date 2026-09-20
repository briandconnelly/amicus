"""Re-runnable probes for an agent-friendly-mcp review walk.

A walk whose surface has moved past the committed host captures has to re-run its
probes, and a review artifact that cites a probe it cannot reproduce is worth little.
Each probe here answers one of the review workflow's transcript probes and prints the
evidence the walk quotes, so a later reader can reproduce a finding rather than trust it.

    uv run python scripts/probe_review_surface.py --list
    uv run python scripts/probe_review_surface.py cold-start

None of these probes spends: every tool called is a free one, and the two that need a
backend registry only reach pre-spend validation. `manifest.app_for_profile` loads NO
backend, which silently turns a backend-dependent failure into `backend_unavailable`;
probes that need the real registry use `server.create_app(config.settings())` instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client

from amicus import config, server
from amicus.manifest import PROFILES, app_for_profile, tools_list_wire

REPO = Path(__file__).resolve().parents[1]
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _catalog() -> list[dict[str, Any]]:
    return list(json.loads(tools_list_wire("all"))["tools"])


def cold_start() -> None:
    """§1/§2 — what an agent sees before its first call, and how much of it a host shows."""
    wire = tools_list_wire("all")
    instructions = app_for_profile("all").instructions or ""
    rules_end = instructions.index("Reference:")
    print(f"tools/list wire body : {len(wire.encode())} bytes, {len(_catalog())} tools")
    print(f"instructions         : {len(instructions)} chars")
    print(f"rules block ends at  : char {rules_end} (Claude Code shows the first 2048)")
    print(f"every rule inside cap: {rules_end <= server.INSTRUCTIONS_HOST_CAP}")


async def _first_repair() -> None:
    workspace = str(REPO)
    # Each case carries its COMPLETE argument set. An earlier form injected
    # `workspace_root` into every case, which made the omitted-workspace case impossible
    # to express: it ran a real (free) dry run and returned no error at all.
    cases: list[tuple[str, dict[str, Any]]] = [
        (
            "amicus_adversarial_review",
            {"backend": "codex", "target": "x", "workspace_root": workspace},
        ),
        ("amicus_consult", {"backend": "gpt5", "question": "hi", "workspace_root": workspace}),
        ("amicus_consult", {"backend": "codex", "question": "   ", "workspace_root": workspace}),
        ("amicus_review_changes_dry_run", {"backend": "codex", "workspace_root": "/tmp"}),
        ("amicus_review_changes_dry_run", {"backend": "codex"}),
        ("amicus_job_status", {"job_id": "nope", "workspace_root": workspace}),
    ]
    async with Client(server.create_app(config.settings())) as client:
        for tool, call in cases:
            result = await client.call_tool(tool, call, raise_on_error=False)
            structured = result.structured_content or {}
            if not result.is_error:
                raise AssertionError(f"{tool} {call} returned ok; this probe needs a failure")
            error = structured.get("error", {})
            repair = error.get("repair")
            mirrored = [b.text for b in result.content if hasattr(b, "text")]
            mirrors = bool(mirrored) and json.loads(mirrored[0]) == result.structured_content
            print(
                f"{tool:30s} code={error.get('code')!s:22s} "
                f"repair.tool={(repair or {}).get('tool')!r:20s} "
                f"repair.arguments={'arguments' in (repair or {})} "
                f"details={json.dumps(error.get('details'))} "
                f"text_mirrors_structured={mirrors}"
            )


async def _advertised() -> None:
    for tool in _catalog():
        annotations = tool.get("annotations") or {}
        lifecycle = (tool.get("_meta") or {}).get("dev.bconnelly.amicus/lifecycle")
        print(
            f"{tool['name']:32s} outputSchema={bool(tool.get('outputSchema'))} "
            f"title={bool(tool.get('title'))} lifecycle={json.dumps(lifecycle)} "
            f"annotations={json.dumps(annotations, sort_keys=True)}"
        )


async def _tool_selection() -> None:
    for tool in _catalog():
        first = tool["description"].split(". ")[0]
        print(f"{tool['name']:32s} {first[:96]}")


def discovery_cost() -> None:
    """§2/§8 — the per-session token tax a preloading client pays."""
    for profile in PROFILES:
        wire = tools_list_wire(profile)
        print(f"{profile:11s} {len(wire.encode())} bytes")
    catalog = _catalog()
    inputs = sum(
        len(json.dumps(t.get("inputSchema", {}), separators=(",", ":")).encode()) for t in catalog
    )
    outputs = sum(
        len(json.dumps(t.get("outputSchema", {}), separators=(",", ":")).encode()) for t in catalog
    )
    print(f"inputSchema total {inputs} bytes; outputSchema total {outputs} bytes")


async def _cross_version() -> None:
    for profile in PROFILES:
        async with Client(app_for_profile(profile)) as client:
            result = await client.call_tool(
                "amicus_capabilities", {"detail": "summary", "include_tool_details": False}
            )
            payload = result.structured_content or {}
            tools = await client.list_tools()
            consult = next(t for t in tools if t.name == "amicus_consult")
            destructive = consult.annotations.destructive_hint if consult.annotations else None
            print(
                f"{profile:11s} fingerprint={payload['fingerprint']} "
                f"surface_digest={payload['surface_digest'][:16]} "
                f"enabled_backends={payload['enabled_backends']} "
                f"amicus_consult.destructiveHint={destructive}"
            )


async def _capability_gating() -> None:
    async with Client(app_for_profile("all")) as client:
        for template in ("amicus://backends/{backend}", "amicus://models/{backend}"):
            completion = await client.complete(
                ref={"type": "ref/resource", "uri": template},
                argument={"name": "backend", "value": ""},
            )
            print(f"completion {template:32s} -> {completion.values}")


async def _security_boundary() -> None:
    async with Client(server.create_app(config.settings())) as client:
        result = await client.call_tool("amicus_backends", {"detail": "full"})
        for backend in (result.structured_content or {}).get("backends", []):
            print(f"--- {backend['id']}")
            for field in ("egress", "carriers", "readonly_honesty", "implicit_context"):
                print(f"  {field}: {backend.get(field, '')[:160]}")


def resource_freshness() -> None:
    """§4/§8/§9 — cache hints, read off a real stdio subprocess.

    stdin stays OPEN between requests: closing it makes the server exit on EOF before
    answering the later ones, which reads as "the server stops responding" and is a
    defect of the probe, not of the server.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", "from amicus.server import main; main()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None:  # pragma: no cover - Popen contract
        raise RuntimeError("failed to open pipes to the amicus stdio server")
    requests: list[tuple[str, dict[str, Any]]] = [
        ("tools/list", {}),
        ("resources/list", {}),
        ("resources/templates/list", {}),
        ("prompts/list", {}),
        ("resources/read", {"uri": "amicus://params"}),
        ("resources/read", {"uri": "amicus://capabilities"}),
        ("resources/read", {"uri": "amicus://nope"}),
    ]
    try:
        for index, (method, params) in enumerate(requests, 1):
            payload = {
                "jsonrpc": "2.0",
                "id": index,
                "method": method,
                "params": {**params, "_meta": MODERN_META},
            }
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
            response = json.loads(proc.stdout.readline())
            label = f"{method} {params.get('uri', '')}".strip()
            if "error" in response:
                print(f"{label:42s} ERROR {json.dumps(response['error'])[:220]}")
            else:
                result = response["result"]
                print(
                    f"{label:42s} resultType={result.get('resultType')} "
                    f"ttlMs={result.get('ttlMs')} cacheScope={result.get('cacheScope')}"
                )
    finally:
        proc.stdin.close()
        proc.wait(timeout=20)


PROBES: dict[str, tuple[str, Any]] = {
    "cold-start": ("§1/§2 first read: catalog size, instructions, host cap", cold_start),
    "first-repair": ("§6 forced failures on both carriers", _first_repair),
    "tool-selection": ("§3 disambiguation across the catalog", _tool_selection),
    "advertised": ("§3 outputSchema, annotations, lifecycle per tool", _advertised),
    "discovery-cost": ("§2/§8 wire bytes per profile", discovery_cost),
    "cross-version": ("§9 fingerprint and digest per profile", _cross_version),
    "capability-gating": ("§2/§4 completion on the resource templates", _capability_gating),
    "resource-freshness": ("§4/§8 cache hints from a real stdio subprocess", resource_freshness),
    "security-boundary": ("§3 per-backend egress and carrier disclosure", _security_boundary),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("probe", nargs="?", choices=sorted(PROBES), help="which probe to run")
    parser.add_argument("--list", action="store_true", help="list the probes and exit")
    args = parser.parse_args()
    if args.list or not args.probe:
        for name, (summary, _) in sorted(PROBES.items()):
            print(f"{name:20s} {summary}")
        return 0
    _, run = PROBES[args.probe]
    if asyncio.iscoroutinefunction(run):
        asyncio.run(run())
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
