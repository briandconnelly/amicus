"""The eight paid tools: schemas from the matrix, pre-spend validation, forced errors."""

from __future__ import annotations

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from tests.support import fakeplugin

from amicus import config, server, tools
from amicus.registry import BackendRegistry, UnavailableBackend
from amicus.schemas import params
from amicus.tools import _resolve

VALID = {
    "amicus_consult": {"backend": "codex", "question": "q"},
    "amicus_consult_async": {"backend": "codex", "question": "q"},
    "amicus_review_changes": {"backend": "codex"},
    "amicus_review_changes_async": {"backend": "codex"},
    "amicus_adversarial_review": {"backend": "claude", "target": "t"},
    "amicus_adversarial_review_async": {"backend": "claude", "target": "t"},
    "amicus_delegate": {"backend": "codex", "task": "t"},
    "amicus_delegate_async": {"backend": "codex", "task": "t"},
}


def _app(env: dict | None = None, registry: BackendRegistry | None = None):
    # None -> create_app's own BackendRegistry.load(settings.enabled_backends), which
    # tries to import the not-yet-shipped in-tree backend packages. The codex package exists
    # but its plugin factory lands in Task 6, so the registry records it as load_failed;
    # kimi loads since M3 and claude since M4. This is the realistic
    # intermediate state this milestone is in.
    return server.create_app(config.settings(env or {}), registry)


def _no_backends_registry() -> BackendRegistry:
    # codex shipped its plugin factory in M1 (Task 6), so the real load path now loads it
    # for real; an explicit no-plugins registry keeps this test proving the
    # backend_unavailable envelope rather than falling through to not_implemented.
    return BackendRegistry(
        {},
        {
            "codex": UnavailableBackend("codex", "import_failed", "x"),
            "claude": UnavailableBackend("claude", "import_failed", "x"),
        },
    )


def _fake_registry() -> BackendRegistry:
    return BackendRegistry(
        {
            "codex": fakeplugin.make_plugin("codex", features=frozenset({"delegate"})),
            "claude": fakeplugin.make_plugin("claude", features=frozenset({"adversarial_review"})),
        },
        {},
    )


async def _tools(app):
    async with Client(app) as c:
        return {t.name: t for t in await c.list_tools()}


async def test_eight_paid_tools_exist_with_matrix_params_and_closed_schemas():
    by_name = await _tools(_app())
    assert set(params.TOOL_VERB) <= set(by_name)
    for name in params.TOOL_VERB:
        schema = by_name[name].input_schema
        assert set(schema["properties"]) == params.expected_params(name), name
        assert set(schema.get("required", [])) == params.expected_required(name), name
        assert schema["additionalProperties"] is False
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert by_name[name].output_schema is not None
        desc = by_name[name].description or ""
        assert desc.startswith(_resolve.PAID_MARKER), name


async def test_backend_enum_is_the_v1_set():
    by_name = await _tools(_app())
    prop = by_name["amicus_consult"].input_schema["properties"]["backend"]
    assert prop["enum"] == ["codex", "kimi", "claude"]


@pytest.mark.parametrize("name", sorted(VALID))
async def test_without_a_loaded_backend_every_paid_tool_reports_backend_unavailable(name):
    app = _app(registry=_no_backends_registry())
    async with Client(app) as c:
        res = await c.call_tool(name, VALID[name], raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == name)
    assert res.is_error
    err = res.structured_content["error"]
    assert err["code"] == "backend_unavailable"
    assert err["backend"] == VALID[name]["backend"]
    assert err["repair"]["tool"] == "amicus_backends"
    assert "unavailable" in err["message"]
    assert res.structured_content["meta"]["backend"] == VALID[name]["backend"]
    Draft202012Validator(tool.output_schema).validate(res.structured_content)


async def test_live_tool_error_request_id_mirrors_meta_request_id():
    app = _app()
    async with Client(app) as c:
        res = await c.call_tool("amicus_consult", VALID["amicus_consult"], raise_on_error=False)
    assert res.is_error
    sc = res.structured_content
    assert sc["error"]["request_id"] == sc["meta"]["request_id"]


ASYNC_TOOLS = tuple(n for n in VALID if n.endswith("_async"))


@pytest.mark.parametrize("name", sorted(ASYNC_TOOLS))
async def test_async_twins_refuse_pre_spend_without_a_workspace(name):
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool(name, VALID[name], raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == name)
    err = res.structured_content["error"]
    assert err["code"] == "invalid_workspace_root", err
    Draft202012Validator(tool.output_schema).validate(res.structured_content)


async def test_sync_tools_need_a_workspace_from_a_sessionless_client():
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool("amicus_consult", VALID["amicus_consult"], raise_on_error=False)
    err = res.structured_content["error"]
    assert err["code"] == "invalid_workspace_root" and err["details"]["field"] == "workspace_root"
    assert res.structured_content["meta"]["roots_source"] == "not_negotiated"


async def test_feature_gating():
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate", {"backend": "claude", "task": "t"}, raise_on_error=False
        )
        adv = await c.call_tool(
            "amicus_adversarial_review", {"backend": "codex", "target": "t"}, raise_on_error=False
        )
    assert res.structured_content["error"]["code"] == "feature_unsupported"
    assert "delegate" in res.structured_content["error"]["message"]
    assert adv.structured_content["error"]["code"] == "feature_unsupported"


async def test_backend_options_are_validated_before_availability():
    app = _app()  # no backends loaded: options still fail first, zero spend, honest order
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q", "backend_options": {"config_mode": "safe"}},
            raise_on_error=False,
        )
        bad_value = await c.call_tool(
            "amicus_review_changes",
            {"backend": "kimi", "backend_options": {"isolation": "ignore-rules"}},
            raise_on_error=False,
        )
        unknown_key = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q", "backend_options": {"sandbox": "x"}},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "backend_options.config_mode"
    assert err["repair"]["tool"] == "amicus_consult"
    err = bad_value.structured_content["error"]
    assert err["details"]["allowed_values"] == ["inherit", "ignore-skills"]
    err = unknown_key.structured_content["error"]
    assert (
        err["code"] == "invalid_arguments" and err["details"]["field"] == "backend_options.sandbox"
    )


async def test_blank_inputs_are_refused_pre_spend():
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        q = await c.call_tool(
            "amicus_consult", {"backend": "codex", "question": "  "}, raise_on_error=False
        )
        t = await c.call_tool(
            "amicus_delegate_async", {"backend": "codex", "task": "\n"}, raise_on_error=False
        )
    assert q.structured_content["error"]["details"]["field"] == "question"
    assert q.structured_content["error"]["repair"]["tool"] == "amicus_consult"
    assert t.structured_content["error"]["details"]["field"] == "task"
    assert t.structured_content["error"]["repair"]["tool"] == "amicus_delegate_async"


async def test_blank_target_is_refused_pre_spend_for_adversarial_review():
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        sync = await c.call_tool(
            "amicus_adversarial_review",
            {"backend": "claude", "target": "  "},
            raise_on_error=False,
        )
        asy = await c.call_tool(
            "amicus_adversarial_review_async",
            {"backend": "claude", "target": "  "},
            raise_on_error=False,
        )
    sync_err = sync.structured_content["error"]
    assert sync_err["code"] == "invalid_arguments"
    assert sync_err["details"]["field"] == "target"
    assert sync_err["repair"]["tool"] == "amicus_adversarial_review"
    async_err = asy.structured_content["error"]
    assert async_err["code"] == "invalid_arguments"
    assert async_err["details"]["field"] == "target"
    assert async_err["repair"]["tool"] == "amicus_adversarial_review_async"


async def test_unknown_backend_is_a_boundary_invalid_arguments():
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "gemini", "question": "q"}, raise_on_error=False
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "backend"
    assert err["details"]["allowed_values"] == ["codex", "kimi", "claude"]


@pytest.mark.parametrize(
    ("env", "destructive"),
    [({}, True), ({"AMICUS_BACKENDS": "codex,kimi"}, False), ({"AMICUS_BACKENDS": "claude"}, True)],
)
async def test_paid_annotations_follow_the_worst_enabled_backend(env, destructive):
    by_name = await _tools(_app(env))
    for name in params.TOOL_VERB:
        ann = by_name[name].annotations
        assert ann is not None
        assert ann.read_only_hint is False and ann.open_world_hint is True
        assert ann.destructive_hint is destructive, name
        assert ann.idempotent_hint is False


async def test_pair_parity_sync_minus_sync_only_equals_async_minus_async_only():
    by_name = await _tools(_app())
    for sync_name, async_name in tools.PAIRS:
        s = by_name[sync_name].input_schema
        a = by_name[async_name].input_schema
        s_props = {k: v for k, v in s["properties"].items() if k not in params.SYNC_ONLY_PARAMS}
        a_props = {k: v for k, v in a["properties"].items() if k not in params.ASYNC_ONLY_PARAMS}
        assert s_props == a_props, (sync_name, async_name)
        assert set(s.get("required", [])) == set(a.get("required", []))


async def test_guard_turns_an_unexpected_exception_into_internal_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(_resolve, "resolve_paid_call", boom)
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False
        )
    err = res.structured_content["error"]
    assert err["code"] == "internal_error" and "kaboom" not in err["message"]
    assert "RuntimeError" in err["message"]
    assert res.structured_content["meta"]["backend"] == "codex"


async def test_lifecycle_meta_on_every_paid_tool():
    by_name = await _tools(_app())
    assert by_name["amicus_consult"].meta["dev.bconnelly.amicus/lifecycle"] == {
        "stability": "alpha"
    }
    assert by_name["amicus_consult_async"].meta["dev.bconnelly.amicus/lifecycle"] == {
        "stability": "experimental"
    }
