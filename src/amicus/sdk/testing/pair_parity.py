"""Sync/async tool-pair parity: the async twin must accept what the sync tool
accepts.

Given the built manifest's tool entries (name -> input schema), verify each
declared pair differs only by the async-only additions (``idempotency_key``)
and never by parameter types or requiredness. Silent drift between a pair is
how a client's working sync call fails when it switches to the async form.
"""

from __future__ import annotations

from typing import Any

ASYNC_ONLY_PARAMS = frozenset({"idempotency_key"})


def check_pair(
    sync_name: str,
    sync_schema: dict[str, Any],
    async_name: str,
    async_schema: dict[str, Any],
) -> list[str]:
    """Violations for one sync/async pair. Schemas are JSON Schema objects with
    ``properties`` and optional ``required``."""
    out: list[str] = []
    sync_props: dict[str, Any] = sync_schema.get("properties", {})
    async_props: dict[str, Any] = async_schema.get("properties", {})

    missing = set(sync_props) - set(async_props)
    if missing:
        out.append(f"{async_name} lacks {sorted(missing)} that {sync_name} accepts")
    extra = set(async_props) - set(sync_props) - ASYNC_ONLY_PARAMS
    if extra:
        out.append(f"{async_name} adds unexpected params {sorted(extra)} over {sync_name}")

    for name in set(sync_props) & set(async_props):
        if sync_props[name] != async_props[name]:
            out.append(f"param {name!r} differs between {sync_name} and {async_name}")

    sync_required = set(sync_schema.get("required", []))
    async_required = set(async_schema.get("required", [])) - ASYNC_ONLY_PARAMS
    if sync_required != async_required:
        out.append(
            f"required sets differ: {sync_name}={sorted(sync_required)} "
            f"{async_name}={sorted(async_required)}"
        )
    return out


def check_pairs(tools: dict[str, dict[str, Any]], pairs: tuple[tuple[str, str], ...]) -> list[str]:
    """Violations across all declared (sync_name, async_name) pairs; a named
    tool missing from the manifest is itself a violation."""
    out: list[str] = []
    for sync_name, async_name in pairs:
        if sync_name not in tools:
            out.append(f"declared pair references unknown tool {sync_name!r}")
            continue
        if async_name not in tools:
            out.append(f"declared pair references unknown tool {async_name!r}")
            continue
        out.extend(check_pair(sync_name, tools[sync_name], async_name, tools[async_name]))
    return out
