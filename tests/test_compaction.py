"""The published input schemas carry no `default: null` (issue #41).

Pydantic emits `"default": null` on every optional parameter; absence from `required`
already says the parameter is optional, so the annotation carried nothing and cost
~2 KB per tools/list. It is stripped at list time by a FastMCP transform, so the
server-held records (`surface.surface_records`, which skips middleware) and the wire
agree, and argument validation, which FastMCP runs from the function signature, is
untouched: an explicit null is still accepted wherever it was.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.utilities.json_schema import dereference_refs

from amicus import compaction, manifest, surface


def _null_defaults(node: object) -> int:
    if isinstance(node, dict):
        own = 1 if "default" in node and node["default"] is None else 0
        return own + sum(_null_defaults(v) for v in node.values())
    if isinstance(node, list):
        return sum(_null_defaults(v) for v in node)
    return 0


def test_strip_null_defaults_is_pure_and_keeps_non_null_defaults():
    src = {
        "properties": {
            "a": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "b": {"type": "string", "default": "summary"},
            "c": {
                "anyOf": [{"properties": {"d": {"default": None}}}, {"type": "null"}],
                "default": None,
            },
        },
        "required": ["b"],
    }
    before = json.dumps(src, sort_keys=True)
    out = compaction.strip_null_defaults(src)
    assert json.dumps(src, sort_keys=True) == before, "input must not be mutated"
    assert _null_defaults(out) == 0
    assert out["properties"]["b"]["default"] == "summary"
    assert out["properties"]["a"]["anyOf"] == src["properties"]["a"]["anyOf"]
    assert out["required"] == ["b"]


async def test_published_input_schemas_carry_no_null_default():
    app = manifest.app_for_profile("all")
    async with Client(app) as c:
        tools = await c.list_tools()
    assert len(tools) == 18
    assert sum(_null_defaults(t.input_schema) for t in tools) == 0
    # The server-held record (middleware not run) agrees with the wire.
    records = await surface.surface_records(app)
    assert sum(_null_defaults(t["inputSchema"]) for t in records["tools"]) == 0


async def test_non_null_defaults_survive_on_the_wire():
    app = manifest.app_for_profile("all")
    async with Client(app) as c:
        by_name = {t.name: t.input_schema["properties"] for t in await c.list_tools()}
    assert by_name["amicus_consult"]["detail"]["default"] == "summary"
    assert by_name["amicus_review_changes"]["scope"]["default"] == "working_tree"
    assert by_name["amicus_review_changes"]["untracked"]["default"] == "explicit_only"
    # The nullable shape itself is untouched: a client may still send an explicit null.
    assert by_name["amicus_consult"]["workspace_root"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]


def _differences(raw: object, out: object, path: tuple[object, ...] = ()) -> set[tuple]:
    """Every path at which `out` differs from `raw`: a key removed (tagged by whether its
    value was null), a key added at any depth, or a value changed. Written without
    `strip_null_defaults`, so the transform is judged by an instrument that does not
    share its code."""
    found: set[tuple] = set()
    if isinstance(raw, dict) and isinstance(out, dict):
        for k, v in raw.items():
            if k not in out:
                found.add((*path, k, "removed-null" if v is None else "removed"))
            else:
                found |= _differences(v, out[k], (*path, k))
        found |= {(*path, k, "<added>") for k in out if k not in raw}
        return found
    if isinstance(raw, list) and isinstance(out, list) and len(raw) == len(out):
        for i, (a, b) in enumerate(zip(raw, out, strict=True)):
            found |= _differences(a, b, (*path, i))
        return found
    return found if raw == out else {(*path, "<changed>")}


def test_differences_sees_every_kind_of_difference():
    """The instrument's own control: a removal, a changed scalar, a shortened list, and an
    addition at the top level and nested are each visible."""
    assert _differences({"a": {"default": None}}, {"a": {}}) == {("a", "default", "removed-null")}
    assert _differences({"a": {"default": 1}}, {"a": {}}) == {("a", "default", "removed")}
    assert _differences({"a": 1}, {"a": 2}) == {("a", "<changed>")}
    assert _differences({"a": [1, 2]}, {"a": [1]}) == {("a", "<changed>")}
    assert _differences({"a": 1}, {"a": 1, "b": 2}) == {("b", "<added>")}
    nested = _differences({"properties": {"a": {}}}, {"properties": {"a": {}, "b": {}}})
    assert nested == {("properties", "b", "<added>")}
    assert _differences({"a": [{"x": 1}]}, {"a": [{"x": 1, "y": 2}]}) == {("a", 0, "y", "<added>")}


async def test_the_strip_is_the_only_difference_from_the_raw_schema():
    """Mutation control: the transform removes `default: null` entries and nothing else.
    Judged by `_differences`, not by `strip_null_defaults`, so an over-broad helper
    cannot make the expected and actual schemas wrong in the same way."""
    app = manifest.app_for_profile("all")
    async with Client(app) as c:
        published = {t.name: t.input_schema for t in await c.list_tools()}
    signal = 0
    for name, schema in published.items():
        # A list-only transform leaves get_tool alone, so this is the raw schema FastMCP
        # built from the signature: the one argument validation is derived from.
        tool = await app.get_tool(name)
        assert tool is not None
        signal += _null_defaults(tool.parameters)
        # FastMCP inlines $ref on the way out; InputSchemaDialectMiddleware adds $schema.
        raw = dereference_refs(tool.parameters)
        differences = _differences(raw, schema)
        assert ("$schema", "<added>") in differences, name
        differences.discard(("$schema", "<added>"))
        assert all(p[-2:] == ("default", "removed-null") for p in differences), (name, differences)
        assert _null_defaults(schema) == 0, name
    assert signal > 100, "control lost its signal: the raw schemas carry no null defaults"


@pytest.mark.parametrize("value", [None, "codex"])
async def test_an_explicit_null_is_still_accepted_where_it_was(value):
    """`amicus_backends.backend` is `BackendId | None`; sending the null explicitly is
    as valid as omitting it, before and after the annotation strip."""
    app = manifest.app_for_profile("all")
    async with Client(app) as c:
        result = await c.call_tool("amicus_backends", {"backend": value}, raise_on_error=False)
    body = result.structured_content
    assert body is not None and body["ok"] is True, body


async def test_a_required_parameter_still_rejects_null():
    """Control for the test above: validation still runs from the signature, where
    `amicus_models.backend` is required and non-nullable."""
    app = manifest.app_for_profile("all")
    async with Client(app) as c:
        result = await c.call_tool("amicus_models", {"backend": None}, raise_on_error=False)
    body = result.structured_content
    assert body is not None and body["ok"] is False
    assert body["error"]["code"] == "invalid_arguments"
