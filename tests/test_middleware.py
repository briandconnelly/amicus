"""The four middlewares, driven through an in-memory client against a scratch app."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Literal

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client import extension_hooks
from fastmcp.exceptions import ResourceError
from mcp import MCPError

from amicus import config, middleware
from amicus.schemas.envelope import Meta


def _scratch_app() -> FastMCP:
    settings = config.settings({})
    app = FastMCP(name="scratch")
    app.add_middleware(middleware.ConnectionLogMiddleware())
    app.add_middleware(middleware.InputSchemaDialectMiddleware())
    app.add_middleware(middleware.SemanticErrorMiddleware())
    app.add_middleware(middleware.ValidationEnvelopeMiddleware(app, settings))
    app.add_middleware(middleware.ResourceErrorMiddleware())

    @app.tool(name="probe")
    async def probe(mode: Literal["ok", "fail"], paths: list[str] | None = None) -> dict:
        if mode == "fail":
            return {"ok": False, "error": {"code": "internal_error"}}
        return {"ok": True}

    @app.resource("scratch://boom")
    def boom() -> str:
        raise ResourceError("nope")

    return app


async def test_input_schema_dialect_is_stamped():
    async with Client(_scratch_app()) as c:
        [tool] = await c.list_tools()
    assert tool.input_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


async def test_input_schema_dialect_middleware_does_not_mutate_the_shared_tool():
    app = _scratch_app()
    async with Client(app) as c:
        [tool] = await c.list_tools()
    server_tool = await app.get_tool("probe")
    assert "$schema" not in (server_tool.parameters or {})
    assert tool.input_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


async def test_semantic_error_flips_is_error():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "fail"}, raise_on_error=False)
        ok = await c.call_tool("probe", {"mode": "ok"}, raise_on_error=False)
    assert res.is_error is True and res.structured_content["ok"] is False
    assert ok.is_error is False


async def test_validation_envelope_for_an_enum_failure():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "nope"}, raise_on_error=False)
    assert res.is_error
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "mode"
    assert err["details"]["allowed_values"] == ["ok", "fail"]
    assert err["repair"]["tool"] == "probe"
    assert "use one of the field's allowed_values" in err["repair"]["alternative"]
    assert res.structured_content["meta"]["timeout_seconds"] == 300
    assert "nope" not in err["message"]


async def test_validation_envelope_for_unknown_and_missing_arguments():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "ok", "extra": 1}, raise_on_error=False)
        missing = await c.call_tool("probe", {}, raise_on_error=False)
    assert res.structured_content["error"]["details"]["field"] == "extra"
    assert "remove the unknown argument" in res.structured_content["error"]["repair"]["alternative"]
    assert missing.structured_content["error"]["details"]["field"] == "mode"


async def test_validation_envelope_indexed_loc_and_withheld_name():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "ok", "paths": [1]}, raise_on_error=False)
        bad = await c.call_tool("probe", {"mode": "ok", "a\x07b": 1}, raise_on_error=False)
    assert res.structured_content["error"]["details"]["field"] == "paths[0]"
    detail = bad.structured_content["error"]["details"]
    assert detail["field"] == middleware.WITHHELD_FIELD and detail["field_withheld"] is True


def test_format_loc_bounds_and_withholds():
    assert middleware.format_loc(("paths", 0)) == "paths[0]"
    assert middleware.format_loc(()) == "<arguments>"
    assert middleware.format_loc(("x" * 200,)).endswith("…")
    assert middleware.format_loc(("a\x1bb",)) == middleware.WITHHELD_FIELD


def test_invalid_arguments_envelope_returns_none_for_non_argument_errors():
    out = middleware.invalid_arguments_envelope(
        "probe",
        param_names={"mode"},
        property_schemas={},
        errors=[{"loc": ("something_else",), "msg": "m", "type": "value_error"}],
        meta=Meta(),
    )
    assert out is None


async def test_resource_errors_carry_the_envelope_per_era():
    app = _scratch_app()
    async with Client(app, mode="legacy") as legacy:
        with pytest.raises(MCPError) as exc:
            await legacy.read_resource("scratch://missing")
    assert exc.value.error.code == -32002
    data = exc.value.error.data
    assert data["machine_code"] == "resource_not_found"
    assert data["human_message"] == "Resource not found."
    assert data["resource_uri"] == "scratch://missing"
    assert "code" not in data and "message" not in data
    async with Client(app) as modern:
        assert modern.protocol_version == "2026-07-28"
        with pytest.raises(MCPError) as exc:
            await modern.read_resource("scratch://missing")
        assert exc.value.error.code == -32602
        with pytest.raises(MCPError) as exc:
            await modern.read_resource("scratch://boom")
        assert exc.value.error.code == -32603
        assert exc.value.error.data["machine_code"] == "internal_error"


def test_resource_not_found_code_defaults_to_handshake_without_evidence():
    assert middleware.resource_not_found_code(object()) == -32002


async def test_connection_log_names_the_negotiated_facts_and_never_an_argument(caplog, monkeypatch):
    # Under the full suite, collecting tests/test_tasks_spike.py (pytest.importorskip
    # "fastmcp_tasks") registers a process-global internal client extension factory
    # (fastmcp.client.extension_hooks._internal_client_extension_factories) that makes
    # every later in-memory Client auto-declare the tasks extension, regardless of what
    # this scratch app itself registers. Clear it for this test so the measured default
    # (no client here opts into tasks) holds independent of collection order.
    monkeypatch.setattr(extension_hooks, "_internal_client_extension_factories", [])
    app = _scratch_app()
    with caplog.at_level(logging.DEBUG, logger="amicus.middleware"):
        async with Client(app) as c:
            await c.call_tool("probe", {"mode": "ok", "paths": ["SECRET-PATH"]})
        async with Client(
            app, mode="legacy", client_info={"name": "claude-code", "version": "2.1.263"}
        ) as c:
            await c.call_tool("probe", {"mode": "ok", "paths": ["SECRET-PATH"]})
    lines = [r.getMessage() for r in caplog.records if r.name == "amicus.middleware"]
    assert len(lines) == 2 and all(line.startswith("tools/call probe: ") for line in lines)
    modern, legacy = lines
    # Measured: an in-memory client declares mcp/0.1.0 by default, on BOTH eras; the
    # tasks extension is not negotiated because this scratch app registers none.
    assert "protocol=2026-07-28" in modern and "client=mcp/0.1.0" in modern
    assert "protocol=2025-11-25" in legacy and "client=claude-code/2.1.263" in legacy
    assert "tasks_negotiated=False" in modern and "tasks_negotiated=False" in legacy
    assert all("SECRET-PATH" not in line for line in lines)


def test_connection_facts_are_unknown_without_a_request():
    facts = middleware.connection_facts(SimpleNamespace())
    assert facts == {
        "protocol": "unknown",
        "client": "unknown",
        "client_version": "unknown",
        "tasks": False,
    }


def test_connection_facts_tolerate_a_context_whose_session_raises():
    class _Ctx:
        request_context = SimpleNamespace(protocol_version="2025-11-25")

        @property
        def session(self):
            raise RuntimeError("no active session")

        def client_extension_settings(self, identifier):
            raise RuntimeError("no active request")

    facts = middleware.connection_facts(SimpleNamespace(fastmcp_context=_Ctx()))
    assert facts["protocol"] == "2025-11-25" and facts["client"] == "unknown"
    assert facts["tasks"] is False
