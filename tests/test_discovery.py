"""The 18-tool surface, the free discovery tools, and job tools (schema-only)."""

from __future__ import annotations

import json
from typing import get_args

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from tests.support import fakeplugin

from amicus import config, server, tools
from amicus.registry import BackendRegistry, UnavailableBackend
from amicus.schemas import field_policy, results
from amicus.schemas.codes import ERROR_CODES
from amicus.schemas.envelope import Meta
from amicus.schemas.fingerprint import FINGERPRINT, LIFECYCLE_META_KEY
from amicus.schemas.results import CapabilitiesDetail
from amicus.tools import _meta, _resolve, discovery


def _app(env=None, registry=None):
    return server.create_app(config.settings(env or {}), registry or BackendRegistry({}, {}))


def _mixed_registry():
    return BackendRegistry(
        {"codex": fakeplugin.make_plugin("codex", egress="sends to OpenAI", carriers="argv")},
        {"kimi": UnavailableBackend("kimi", "import_failed", "no module amicus.backends.kimi")},
    )


async def _tools(app):
    async with Client(app) as c:
        return await c.list_tools()


async def test_exactly_eighteen_tools_in_the_fixed_order():
    listed = [t.name for t in await _tools(_app())]
    assert len(listed) == 18
    assert listed == list(tools.TOOL_ORDER)


async def test_free_and_job_tool_markers_and_annotations():
    by_name = {t.name: t for t in await _tools(_app())}
    for name in tools.FREE_TOOLS:
        assert (by_name[name].description or "").startswith(_resolve.FREE_MARKER), name
        ann = by_name[name].annotations
        assert ann.read_only_hint is True and ann.open_world_hint is False
        assert ann.destructive_hint is None and ann.idempotent_hint is None
    for name in ("amicus_job_status", "amicus_job_result", "amicus_job_list"):
        assert by_name[name].annotations.read_only_hint is True
    consume = by_name["amicus_job_consume_result"].annotations
    cancel = by_name["amicus_job_cancel"].annotations
    assert consume.read_only_hint is False and consume.idempotent_hint is False
    assert cancel.read_only_hint is False and cancel.idempotent_hint is True


async def _lifecycle_stability_tiers(app) -> dict[str, str]:
    """Every stability value the discovery records carry in `_meta`, keyed by where it
    appears: 18 tools, 4 static resources, 2 templates. One collector covers all three
    surfaces, so none of them can drift on its own. These blocks are plain dicts with no
    model behind them, so nothing rejects an illegal tier at runtime -- the declared type
    of `SERVER_STABILITY` and this collector are what hold them."""
    tiers: dict[str, str] = {}
    async with Client(app) as c:
        for tool in await c.list_tools():
            assert LIFECYCLE_META_KEY in (tool.meta or {}), tool.name
            tiers[f"tools/list:{tool.name}"] = tool.meta[LIFECYCLE_META_KEY]["stability"]
        for res in await c.list_resources():
            assert LIFECYCLE_META_KEY in (res.meta or {}), res.uri
            tiers[f"resources/list:{res.uri}"] = res.meta[LIFECYCLE_META_KEY]["stability"]
        for tpl in await c.list_resource_templates():
            assert LIFECYCLE_META_KEY in (tpl.meta or {}), tpl.uri_template
            tiers[f"templates/list:{tpl.uri_template}"] = tpl.meta[LIFECYCLE_META_KEY]["stability"]
    return tiers


async def test_every_published_stability_tier_is_in_the_closed_set():
    """[9.stability-tiers] closes the set so an agent can filter on the tier directly;
    the server published `alpha`, outside it and outside its own literal, until #43."""
    tiers = await _lifecycle_stability_tiers(_app())
    assert len(tiers) == 24, sorted(tiers)
    async with Client(_app()) as c:
        caps = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
    tiers["capabilities:stability"] = caps["stability"]
    for entry in caps["tool_details"]:
        if entry["stability"] is not None:
            tiers[f"capabilities:tool_details:{entry['name']}"] = entry["stability"]
    # 25, not 26+: every tool_details override is null today, because the per-tool table
    # is empty and each tool inherits the server-wide tier.
    assert len(tiers) == 25, sorted(tiers)
    assert {v for v in tiers.values() if v not in set(get_args(results.ToolStability))} == set()


async def test_an_illegal_server_tier_would_reach_every_lifecycle_record(monkeypatch):
    """Mutation control for the collector above: one bad server-wide tier has to surface on
    all 24 records, because every record now inherits it. That all-inherit invariant is what
    this pins, not the historical state: `alpha` reached 15 of these 24 (nine tools, four
    resources, two templates) plus `amicus_capabilities.stability`, because the other nine
    tools carried an explicit `experimental` override (#43). It also pins the single-sourcing
    -- a module that had bound its own copy of the constant would stay behind here."""
    monkeypatch.setattr(_meta, "SERVER_STABILITY", "alpha")
    tiers = await _lifecycle_stability_tiers(_app())
    assert len(tiers) == 24 and set(tiers.values()) == {"alpha"}


async def test_capabilities_refuses_to_publish_a_tier_outside_the_closed_set(monkeypatch):
    """The other half: `CapabilitiesResult.stability` is typed to the closed set, so an
    illegal tier fails assembly instead of reaching a caller as an uninterpretable value.
    The passing call in the closed-set test above is this probe's positive control."""
    monkeypatch.setattr(_meta, "SERVER_STABILITY", "alpha")
    async with Client(_app()) as c:
        res = await c.call_tool("amicus_capabilities", {}, raise_on_error=False)
    assert res.structured_content["error"]["code"] == "internal_error"


async def test_advertised_control_char_patterns_are_complete():
    app = _app()
    patterns = await field_policy.advertised_patterns(app)
    for name in field_policy.REJECT_PARAMS:
        assert patterns.get(name) == field_policy.CONTROL_CHAR_FREE_PATTERN, name


async def test_every_tool_output_schema_is_valid_and_every_error_envelope_validates():
    app = _app()
    async with Client(app) as c:
        listed = await c.list_tools()
        args = {
            "amicus_dry_run": {"backend": "codex"},
            "amicus_delegate_dry_run": {"backend": "codex", "task": "t"},
            "amicus_models": {"backend": "codex"},
            "amicus_job_status": {"job_id": "a" * 32},
            "amicus_job_result": {"job_id": "a" * 32},
            "amicus_job_consume_result": {"job_id": "a" * 32},
            "amicus_job_cancel": {"job_id": "a" * 32},
            "amicus_job_list": {},
        }
        for tool in listed:
            Draft202012Validator.check_schema(tool.output_schema)
            if tool.name in args:
                res = await c.call_tool(tool.name, args[tool.name], raise_on_error=False)
                Draft202012Validator(tool.output_schema).validate(res.structured_content)
                assert res.structured_content["error"]["code"] in {
                    "backend_unavailable",
                    "invalid_workspace_root",
                }


async def test_dry_runs_validate_options_then_report_backend_state():
    async with Client(_app(registry=_mixed_registry())) as c:
        bad = await c.call_tool(
            "amicus_dry_run",
            {"backend": "codex", "backend_options": {"access": "readonly"}},
            raise_on_error=False,
        )
        # No workspace_root from a sessionless client: zero-spend invalid_workspace_root,
        # reached only once options and backend availability already checked out.
        ok = await c.call_tool("amicus_dry_run", {"backend": "codex"}, raise_on_error=False)
        kimi = await c.call_tool(
            "amicus_delegate_dry_run", {"backend": "kimi", "task": "t"}, raise_on_error=False
        )
    assert bad.structured_content["error"]["details"]["field"] == "backend_options.access"
    assert ok.structured_content["error"]["code"] == "invalid_workspace_root"
    assert kimi.structured_content["error"]["code"] == "backend_unavailable"


async def test_delegate_dry_run_needs_a_workspace_once_the_backend_resolves():
    async with Client(_app(registry=_mixed_registry())) as c:
        res = await c.call_tool(
            "amicus_delegate_dry_run", {"backend": "codex", "task": "t"}, raise_on_error=False
        )
    assert res.structured_content["error"]["code"] == "invalid_workspace_root"


async def test_delegate_dry_run_rejects_a_blank_task():
    async with Client(_app(registry=_mixed_registry())) as c:
        res = await c.call_tool(
            "amicus_delegate_dry_run", {"backend": "codex", "task": "   "}, raise_on_error=False
        )
    assert res.structured_content["error"]["details"]["field"] == "task"


async def test_backends_catalog_reports_enabled_available_and_unavailable():
    app = _app(
        env={"AMICUS_BACKENDS": "codex,kimi", "MOONBRIDGE_TIMEOUT_SECONDS": "60"},
        registry=_mixed_registry(),
    )
    async with Client(app) as c:
        res = await c.call_tool("amicus_backends", {})
        tool = next(t for t in await c.list_tools() if t.name == "amicus_backends")
        only = await c.call_tool("amicus_backends", {"backend": "kimi"})
    payload = res.structured_content
    Draft202012Validator(tool.output_schema).validate(payload)
    by_id = {b["id"]: b for b in payload["backends"]}
    assert set(by_id) == {"codex", "kimi", "claude"}
    assert by_id["codex"]["enabled"] and by_id["codex"]["available"]
    assert by_id["codex"]["status"] == {
        "installed": True,
        "version": "fake 1.0",
        "authenticated": True,
        "warnings": [],
    }
    assert by_id["codex"]["features"] == ["delegate"]
    assert by_id["codex"]["egress"] == "sends to OpenAI" and by_id["codex"]["carriers"] == "argv"
    assert {o["name"] for o in by_id["codex"]["options"]} == {"isolation"}
    assert by_id["codex"]["options"][0]["allowed_values"] == [
        "inherit",
        "ignore-config",
        "ignore-rules",
    ]
    assert by_id["codex"]["effects"] == {
        "paid_calls_destructive": False,
        "job_reads_read_only": True,
    }
    assert by_id["kimi"]["enabled"] and not by_id["kimi"]["available"]
    assert not by_id["claude"]["enabled"]
    assert by_id["claude"]["effects"]["paid_calls_destructive"] is True
    assert payload["unavailable"] == [
        {"id": "kimi", "reason": "import_failed", "detail": "no module amicus.backends.kimi"}
    ]
    assert any("MOONBRIDGE_TIMEOUT_SECONDS" in w for w in payload["env_warnings"])
    assert [b["id"] for b in only.structured_content["backends"]] == ["kimi"]


async def test_backends_status_probe_failure_is_a_warning_not_a_crash():
    class Boom:
        def probe(self):
            raise RuntimeError("probe died")

    reg = BackendRegistry({"codex": fakeplugin.make_plugin("codex", status=Boom())}, {})
    async with Client(_app(registry=reg)) as c:
        res = await c.call_tool("amicus_backends", {"backend": "codex"})
    [entry] = res.structured_content["backends"]
    assert entry["status"]["installed"] is False
    assert any("RuntimeError" in w for w in entry["status"]["warnings"])


async def test_models_for_available_and_unavailable_backends():
    async with Client(_app(registry=_mixed_registry())) as c:
        codex = await c.call_tool("amicus_models", {"backend": "codex"})
        kimi = await c.call_tool("amicus_models", {"backend": "kimi"}, raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == "amicus_models")
    Draft202012Validator(tool.output_schema).validate(codex.structured_content)
    assert codex.structured_content["models"] == [
        {
            "slug": "fake-1",
            "display_name": None,
            "default_reasoning_effort": None,
            "supported_reasoning_efforts": None,
        }
    ]
    assert codex.structured_content["source"] == "static"
    # amicus_models on an unavailable backend now reports the same backend_unavailable
    # envelope every paid tool reports, rather than the resource's informational
    # available:false payload (that stays on amicus://models/{backend}).
    assert kimi.is_error
    Draft202012Validator(tool.output_schema).validate(kimi.structured_content)
    err = kimi.structured_content["error"]
    assert err["code"] == "backend_unavailable"
    assert err["repair"]["tool"] == "amicus_backends"
    assert "unavailable" in err["message"]


async def test_capabilities_summary_full_contracts_and_include_schemas():
    app = _app()
    async with Client(app) as c:
        tool = next(t for t in await c.list_tools() if t.name == "amicus_capabilities")
        summary = (await c.call_tool("amicus_capabilities", {})).structured_content
        full = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
        contracts = (
            await c.call_tool("amicus_capabilities", {"detail": "contracts"})
        ).structured_content
        with_schemas = (
            await c.call_tool(
                "amicus_capabilities",
                {"include_schemas": ["error-envelope", "parameter-contracts"]},
            )
        ).structured_content
    Draft202012Validator(tool.output_schema).validate(summary)
    assert set(summary["active_tools"]) == set(tools.ACTIVE_TOOLS)
    assert set(summary["free_tools"]) == set(tools.FREE_TOOLS)
    assert set(summary["job_tools"]) == set(tools.JOB_TOOLS)
    assert set(summary["error_codes"]) == set(ERROR_CODES)
    assert summary["meta_fields"] == list(Meta.model_fields)
    assert len(summary["surface_digest"]) == 64
    assert summary["tasks"]["enabled"] is False and summary["tasks"]["task_tools"] == []
    assert summary["enabled_backends"] == ["codex", "kimi", "claude"]
    assert {d["name"] for d in summary["tool_details"]} == set(tools.TOOL_ORDER)
    entry = next(d for d in summary["tool_details"] if d["name"] == "amicus_consult")
    assert set(entry) == {"name", "cost", "stability", "backends", "error_codes"}
    assert entry["stability"] is None
    entry_full = next(d for d in full["tool_details"] if d["name"] == "amicus_consult")
    assert entry_full["required_params"] == ["backend", "question"]
    assert "use_when" in entry_full and entry_full["returns"]
    assert contracts["tool_details"] == []
    assert set(with_schemas["schemas"]) == {"error-envelope", "parameter-contracts"}
    assert with_schemas["schemas"]["error-envelope"]["$schema"]
    assert "surface_digest" in summary and summary["fingerprint"] == FINGERPRINT
    assert "delivery statement" in summary["tasks"]["fallback"]
    assert set(get_args(CapabilitiesDetail)) == {"summary", "full", "contracts"}


async def test_capabilities_reports_unknown_include_schemas_as_invalid_arguments():
    # include_schemas is now a Literal list, so this is rejected at the call boundary
    # (ValidationEnvelopeMiddleware) rather than by hand-rolled validation in the tool
    # body; field, allowed_values and repair.tool are unchanged, only the pydantic
    # literal_error message text differs from the old hand-written "unknown schema name".
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_capabilities", {"include_schemas": ["nope"]}, raise_on_error=False
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments" and err["details"]["field"] == "include_schemas[0]"
    assert err["repair"]["tool"] == "amicus_capabilities"
    assert err["details"]["allowed_values"] == [
        "error-envelope",
        "result-meta",
        "capabilities-result",
        "parameter-contracts",
    ]


async def test_job_list_filters_are_advertised():
    by_name = {t.name: t for t in await _tools(_app())}
    props = by_name["amicus_job_list"].input_schema["properties"]
    assert set(props) == {"workspace_root", "limit", "status", "backend", "task_id"}
    assert set(by_name["amicus_job_result"].input_schema["properties"]) == {
        "job_id",
        "workspace_root",
        "detail",
    }
    assert set(by_name["amicus_job_cancel"].input_schema["properties"]) == {
        "job_id",
        "workspace_root",
    }


@pytest.mark.parametrize("name", ["amicus_backends", "amicus_capabilities"])
async def test_free_tool_payloads_are_json_serializable(name):
    async with Client(_app()) as c:
        res = await c.call_tool(name, {})
    json.dumps(res.structured_content)


async def test_the_confidence_enum_and_its_meaning_reach_an_mcp_client():
    """Issue #53. `unknown` has to be ON the published enum or a closed-schema caller
    rejects a valid result, and its MEANING has to be published too: an MCP-only caller
    has no docstring and no skill file, so a `confidence` field that is sometimes the
    backend's report and sometimes amicus's own assessment is misread by default. A
    description not registered in publish.KEPT_DESCRIPTIONS is stripped before it ships,
    which is exactly how the semantic would go missing (issue #38's lesson)."""
    async with Client(_app()) as c:
        listed = {t.name: t for t in await c.list_tools()}
    for name in ("amicus_review_changes", "amicus_adversarial_review"):
        branches = listed[name].output_schema["anyOf"]
        success = next(b for b in branches if "confidence" in b.get("properties", {}))
        field = success["properties"]["confidence"]
        assert set(field["enum"]) == {"low", "medium", "high", "unknown"}, name
        assert field["description"] == results._CONFIDENCE_DESC, name
        assert "unknown" in field["description"], name


def test_sync_paid_tools_advertise_the_idempotency_codes():
    """Issue #66: a keyed sync call can end in any of the three dedup codes, so each sync
    tool's catalog names them, exactly as its _async twin's does."""
    for sync_name, async_name in tools.PAIRS:
        sync_codes = set(discovery.TOOL_DETAILS[sync_name]["error_codes"])
        async_codes = set(discovery.TOOL_DETAILS[async_name]["error_codes"])
        assert set(discovery._IDEMPOTENCY_CODES) <= sync_codes, sync_name
        assert set(discovery._IDEMPOTENCY_CODES) <= async_codes, async_name
