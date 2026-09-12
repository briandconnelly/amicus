"""Advertised outputSchema construction (ported from codex-in-claude schemas.py).

Every tool advertises its success branch(es) plus ONE fully opaque error branch. The
full Meta object is collapsed to an opaque pointer (it is published once at
amicus://result-meta), generated title/description/default noise is stripped, and
$defs orphaned by the opaquing are pruned. Descriptions registered in
KEPT_DESCRIPTIONS survive the strip; register a pointer/semantic description there
BEFORE the schema that carries it is built.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, TypeAdapter

from amicus.schemas.fingerprint import JSON_SCHEMA_DIALECT

# Pointer descriptions ride every tool's outputSchema (the error branch on all eighteen,
# meta on every success branch), so they are one clause plus the resource (issue #41).
ERROR_POINTER_DESC = "Error envelope; schema at amicus://error-envelope"
OPAQUE_ERROR_BRANCH: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "error", "meta"],
    "properties": {
        "ok": {"const": False},
        "error": {"type": "object", "description": ERROR_POINTER_DESC},
        "meta": {"type": "object"},
    },
}
RESULT_META_POINTER_DESC = "Result metadata; schema at amicus://result-meta"
OPAQUE_META: dict[str, Any] = {"type": "object", "description": RESULT_META_POINTER_DESC}
_META_REF = {"$ref": "#/$defs/Meta"}
OK_DESC = "true on success, false on error"

# Descriptions that survive _strip_schema_noise. Other modules add their pointer and
# semantic descriptions here at import time, before building their schemas.
KEPT_DESCRIPTIONS: set[str] = {
    ERROR_POINTER_DESC,
    RESULT_META_POINTER_DESC,
    OK_DESC,
}

_SUBSCHEMA_MAPS = frozenset(
    ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas")
)


def _strip_schema_noise(node: object) -> object:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("title", "default"):
                continue
            if k == "description" and v not in KEPT_DESCRIPTIONS:
                continue
            if k in _SUBSCHEMA_MAPS and isinstance(v, dict):
                out[k] = {name: _strip_schema_noise(sub) for name, sub in v.items()}
            else:
                out[k] = _strip_schema_noise(v)
        return out
    if isinstance(node, list):
        return [_strip_schema_noise(v) for v in node]
    return node


def _opaque_meta_refs(node: object) -> object:
    if isinstance(node, dict):
        if node == _META_REF:
            return dict(OPAQUE_META)
        return {k: _opaque_meta_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_opaque_meta_refs(v) for v in node]
    return node


def _local_def_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            names.add(ref.split("/")[-1])
        for v in node.values():
            names |= _local_def_names(v)
    elif isinstance(node, list):
        for v in node:
            names |= _local_def_names(v)
    return names


def _prune_defs(doc: dict[str, Any]) -> dict[str, Any]:
    defs = doc.get("$defs")
    if not defs:
        return doc
    body = {k: v for k, v in doc.items() if k != "$defs"}
    reachable: set[str] = set()
    frontier = _local_def_names(body)
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in defs:
            continue
        reachable.add(name)
        frontier |= _local_def_names(defs[name])
    doc["$defs"] = {k: v for k, v in defs.items() if k in reachable}
    return doc


def _dereference_top_branch(branch: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = branch.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/") and len(branch) == 1:
        name = ref.split("/")[-1]
        if name in defs:
            return dict(defs[name])
    return branch


def published_schema(
    *success_models: type[BaseModel],
    opaque_fields: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A tool's advertised outputSchema: success branch(es) plus one opaque error branch.

    ``opaque_fields`` maps a top-level success-branch property to a compact stub; the
    closure it referenced is pruned, the same shrink Meta gets."""
    if len(success_models) == 1:
        adapter: TypeAdapter[Any] = TypeAdapter(success_models[0])
    else:
        union: Any = success_models[0]
        for m in success_models[1:]:
            union = union | m
        adapter = TypeAdapter(union)
    raw = adapter.json_schema(ref_template="#/$defs/{model}")
    raw_defs: dict[str, Any] = raw.get("$defs", {})
    if "anyOf" in raw:
        # A union's branches are bare `$ref`s into $defs; a single model is inlined
        # directly (no self-ref). Dereference so every branch is inline, uniformly,
        # for downstream field access (opaque_fields) and orphaned-$defs pruning.
        branches = [_dereference_top_branch(b, raw_defs) for b in raw["anyOf"]]
    else:
        branches = [{k: v for k, v in raw.items() if k != "$defs"}]
    doc: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DIALECT,
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "description": OK_DESC},
        },
        "required": ["ok"],
        "anyOf": [*branches, OPAQUE_ERROR_BRANCH],
        "$defs": raw.get("$defs", {}),
    }
    if opaque_fields:
        for branch in branches:
            props = branch.get("properties")
            if not props:
                continue
            for field, stub in opaque_fields.items():
                if field in props:
                    props[field] = dict(stub)
    opaqued = _opaque_meta_refs(doc)
    assert isinstance(opaqued, dict)
    pruned = _prune_defs(opaqued)
    result = _strip_schema_noise(pruned)
    assert isinstance(result, dict)
    return result
