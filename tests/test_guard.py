"""The guard: an `ok: false` envelope is an MCP error result on every delivery path, with
the wire shape FastMCP's own dict conversion produces; an unexpected exception is an
internal_error envelope that names the exception type and never its text."""

from __future__ import annotations

from fastmcp import Client, FastMCP
from fastmcp.tools import ToolResult

from amicus import config
from amicus.errors import error_envelope
from amicus.schemas import envelope as e
from amicus.schemas.envelope import Meta
from amicus.tools._guard import GUARD_MARKER, as_tool_result, guard


def _envelope() -> dict:
    return error_envelope("internal_error", "boom", Meta(timeout_seconds=5))


def test_ok_false_becomes_an_error_tool_result_and_ok_true_passes_through():
    env = _envelope()
    out = as_tool_result(env)
    assert isinstance(out, ToolResult) and out.is_error is True
    assert out.structured_content == env
    assert as_tool_result({"ok": True, "x": 1}) == {"ok": True, "x": 1}
    assert as_tool_result({"x": 1}) == {"x": 1}


def test_ok_true_drops_null_meta_keys_on_every_tool_and_keeps_falsy_values():
    """The one wire chokepoint every tool passes through drops meta's null-valued keys, so
    a free or job-lifecycle envelope is as sparse as a delivered paid one (#47). Keyed on
    `is None`: 0, False and [] are populated values and survive."""
    meta = Meta(timeout_seconds=5, command_exit_code=0, truncated=False).model_dump(mode="json")
    assert meta["backend"] is None and meta["usage"] is None, "control: nulls went in"
    out = as_tool_result({"ok": True, "tool": "amicus_job_list", "meta": meta, "jobs": []})
    assert isinstance(out, dict)
    assert [k for k, v in out["meta"].items() if v is None] == []
    assert out["meta"]["command_exit_code"] == 0 and out["meta"]["truncated"] is False
    assert out["meta"]["compat_warnings"] == [] and out["meta"]["timeout_seconds"] == 5
    assert set(out["meta"]) >= set(e.META_ALWAYS_PRESENT)
    # The payload outside meta is untouched: a top-level null is that tool's own contract.
    assert (
        as_tool_result({"ok": True, "meta": meta, "truncation_hint": None})["truncation_hint"]
        is None
    )
    # An error envelope is not slimmed here; serialize_error already applied exclude_none.
    err = _envelope()
    assert as_tool_result(err).structured_content == err


async def test_guard_result_matches_fastmcp_dict_conversion_byte_for_byte():
    """Parity instrument: content and structured_content are exactly what FastMCP builds
    from the same dict returned under an explicit output schema."""
    app = FastMCP(name="scratch")

    @app.tool(name="probe", output_schema={"type": "object", "additionalProperties": True})
    async def probe() -> dict:
        return {}

    tool = await app.get_tool("probe")
    env = _envelope()
    theirs = tool.convert_result(env)
    ours = as_tool_result(env)
    assert isinstance(ours, ToolResult)
    assert ours.structured_content == theirs.structured_content
    assert [c.model_dump() for c in ours.content] == [c.model_dump() for c in theirs.content]
    assert theirs.is_error is False and ours.is_error is True


async def test_guarded_tool_delivers_is_error_without_any_middleware():
    settings = config.settings({})
    app = FastMCP(name="scratch")  # deliberately no SemanticErrorMiddleware

    @app.tool(name="failing", output_schema={"type": "object", "additionalProperties": True})
    @guard("failing", settings)
    async def failing(backend: str | None = None) -> dict:
        return _envelope()

    @app.tool(name="raising", output_schema={"type": "object", "additionalProperties": True})
    @guard("raising", settings)
    async def raising(backend: str | None = None) -> dict:
        raise RuntimeError("secret detail")

    @app.tool(name="fine", output_schema={"type": "object", "additionalProperties": True})
    @guard("fine", settings)
    async def fine(backend: str | None = None) -> dict:
        return {"ok": True, "answer": 42}

    assert getattr(failing, GUARD_MARKER) is True
    async with Client(app) as c:
        res = await c.call_tool("failing", {}, raise_on_error=False)
        exc = await c.call_tool("raising", {"backend": "codex"}, raise_on_error=False)
        ok = await c.call_tool("fine", {})
    assert res.is_error is True and res.structured_content["error"]["code"] == "internal_error"
    assert exc.is_error is True
    err = exc.structured_content["error"]
    assert err["code"] == "internal_error"
    # The guard puts the caller's backend on meta, not on error.backend (which only
    # error_envelope's own `backend=` kwarg sets, and the guard has never passed it).
    assert exc.structured_content["meta"]["backend"] == "codex"
    assert "RuntimeError" in err["message"] and "secret detail" not in err["message"]
    assert ok.is_error is False and ok.structured_content == {"ok": True, "answer": 42}
