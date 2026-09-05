"""Six resources: four static bodies, two templates with completion."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp import MCPError
from mcp_types import ResourceTemplateReference
from tests.support import fakeplugin

from amicus import config, server
from amicus.registry import BackendRegistry
from amicus.tools import resources


def _app(registry=None):
    return server.create_app(config.settings({}), registry or BackendRegistry({}, {}))


async def test_static_resources_list_and_read_as_json_with_triage_and_lifecycle_meta():
    async with Client(_app()) as c:
        listed = {str(r.uri): r for r in await c.list_resources()}
        assert (
            set(listed)
            == set(resources.STATIC_RESOURCE_URIS)
            == {
                "amicus://capabilities",
                "amicus://error-envelope",
                "amicus://result-meta",
                "amicus://params",
            }
        )
        for uri, rec in listed.items():
            meta = rec.meta or {}
            assert "dev.bconnelly.amicus/lifecycle" in meta, uri
            assert meta["dev.bconnelly.amicus/triage"]["size_bytes"] > 0 or meta[
                "dev.bconnelly.amicus/triage"
            ].get("volatile")
            [block] = await c.read_resource(uri)
            body = json.loads(block.text)
            assert isinstance(body, dict)
        assert listed["amicus://error-envelope"].mime_type == "application/schema+json"
        assert listed["amicus://params"].mime_type == "application/json"


async def test_templates_are_listed_and_readable():
    reg = BackendRegistry({"codex": fakeplugin.make_plugin("codex")}, {})
    async with Client(_app(reg)) as c:
        templates = {t.uri_template for t in await c.list_resource_templates()}
        assert templates == set(resources.TEMPLATE_URIS)
        [entry] = await c.read_resource("amicus://backends/codex")
        assert json.loads(entry.text)["available"] is True
        [models] = await c.read_resource("amicus://models/codex")
        assert json.loads(models.text)["models"][0]["slug"] == "fake-1"
        [kimi] = await c.read_resource("amicus://backends/kimi")
        assert json.loads(kimi.text)["available"] is False
        # Unlike the amicus_models TOOL (backend_unavailable envelope), the resource
        # keeps the informational available:false payload for a known-but-unloaded
        # backend: no repair carrier exists on a resource read.
        [kimi_models] = await c.read_resource("amicus://models/kimi")
        kimi_models_body = json.loads(kimi_models.text)
        assert kimi_models_body["ok"] is True
        assert kimi_models_body["available"] is False
        assert kimi_models_body["models"] == []
        assert kimi_models_body["source"] == "none"
        with pytest.raises(MCPError) as exc:
            await c.read_resource("amicus://backends/gemini")
        assert exc.value.error.data["machine_code"] == "resource_not_found"
        with pytest.raises(MCPError) as exc:
            await c.read_resource("amicus://models/gemini")
        assert exc.value.error.data["machine_code"] == "resource_not_found"


def test_resource_not_found_falls_back_to_the_handshake_code_outside_a_request():
    err = resources._resource_not_found("amicus://backends/gemini")
    assert err.error.code == -32002
    assert err.error.data["machine_code"] == "resource_not_found"
    assert err.error.data["resource_uri"] == "amicus://backends/gemini"


async def test_completion_for_the_backend_template_variable():
    async with Client(_app()) as c:
        ref = ResourceTemplateReference(uri="amicus://backends/{backend}")
        assert (await c.complete(ref, {"name": "backend", "value": "c"})).values == [
            "codex",
            "claude",
        ]
        ref = ResourceTemplateReference(uri="amicus://models/{backend}")
        assert (await c.complete(ref, {"name": "backend", "value": ""})).values == [
            "codex",
            "kimi",
            "claude",
        ]
        assert (await c.complete(ref, {"name": "other", "value": ""})).values == []
    assert resources.complete_backend(object(), None, None) is None


async def test_capabilities_resource_matches_the_tool():
    async with Client(_app()) as c:
        via_tool = (await c.call_tool("amicus_capabilities", {})).structured_content
        [block] = await c.read_resource("amicus://capabilities")
    via_resource = json.loads(block.text)
    assert via_resource["surface_digest"] == via_tool["surface_digest"]
    assert via_resource["error_codes"] == via_tool["error_codes"]
