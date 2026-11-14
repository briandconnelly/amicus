"""The 18-tool surface, the free discovery tools, and job tools (schema-only)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import get_args

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from tests.support import fakeplugin

from amicus import config, server, tools
from amicus.plugin import ModelEntry, ModelListing, StatusReport
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
    # Consume deletes a retained result and cancel discards in-flight work, so
    # neither is additive (#213).
    assert consume.destructive_hint is True and cancel.destructive_hint is True


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
    # 43 = 24 lifecycle records + capabilities.stability + 18 tool_details rows: every row
    # now carries its effective tier rather than a null override (#250).
    assert len(tiers) == 43, sorted(tiers)
    assert {v for v in tiers.values() if v not in set(get_args(results.ToolStability))} == set()


async def test_an_illegal_server_tier_would_reach_every_lifecycle_record(monkeypatch):
    """Mutation control for the collector above: one bad server-wide tier has to surface on
    all 24 records, because every record now inherits it; a deprecated tool would too, since
    deprecation never replaces a tier (#98), though none exists since the alias was removed
    (#204). That all-inherit invariant is what this pins, not the historical state: `alpha`
    reached 15 of the 24 records there were then
    (nine tools, four resources, two templates) plus `amicus_capabilities.stability`,
    because the other nine tools carried an explicit `experimental` override (#43). It also
    pins the single-sourcing -- a module that had bound its own copy of the constant would
    stay behind here."""
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
            "amicus_review_changes_dry_run": {"backend": "codex"},
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
            "amicus_review_changes_dry_run",
            {"backend": "codex", "backend_options": {"access": "readonly"}},
            raise_on_error=False,
        )
        # No workspace_root from a sessionless client: zero-spend invalid_workspace_root,
        # reached only once options and backend availability already checked out.
        ok = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "codex"}, raise_on_error=False
        )
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
        res = await c.call_tool("amicus_backends", {"detail": "full"})
        tool = next(t for t in await c.list_tools() if t.name == "amicus_backends")
        only = await c.call_tool("amicus_backends", {"backend": "kimi"})
    payload = res.structured_content
    Draft202012Validator(tool.output_schema).validate(payload)
    assert payload["omitted_fields"] == []
    by_id = {b["id"]: b for b in payload["backends"]}
    assert set(by_id) == {"codex", "kimi", "claude", "pi"}
    assert by_id["codex"]["enabled"] and by_id["codex"]["available"]
    assert by_id["codex"]["status"] == {
        "installed": True,
        "version": "fake 1.0",
        "authenticated": True,
        "warnings": [],
    }
    assert by_id["codex"]["features"] == ["delegate"]
    assert by_id["codex"]["egress"] == "sends to OpenAI" and by_id["codex"]["carriers"] == "argv"
    # full keeps a null where no loaded plugin declares one (kimi's plugin did not load).
    assert by_id["kimi"]["egress"] is None and "egress" in by_id["kimi"]
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
    # A retired sibling name (#176) is reported in the top-level env_warnings, never read.
    assert any(
        "MOONBRIDGE_TIMEOUT_SECONDS is set but not read" in w for w in payload["env_warnings"]
    )
    assert [b["id"] for b in only.structured_content["backends"]] == ["kimi"]


async def test_backends_status_probe_does_not_stall_the_event_loop():
    """#307: a status probe spawns up to three CLI subprocesses, each bounded at 10 s; run
    inline it froze every concurrent call, poll and ping for that long."""

    class SlowStatus:
        def probe(self) -> StatusReport:
            time.sleep(0.3)
            return StatusReport(installed=True, version="slow 1.0", authenticated=True)

    registry = BackendRegistry(
        {
            "codex": fakeplugin.make_plugin(
                "codex", status=SlowStatus(), egress="x", carriers="argv"
            )
        },
        {},
    )
    app = _app(env={"AMICUS_BACKENDS": "codex"}, registry=registry)

    async def ticker() -> float:
        worst = 0.0
        for _ in range(10):
            t0 = time.perf_counter()
            await asyncio.sleep(0.03)
            worst = max(worst, time.perf_counter() - t0 - 0.03)
        return worst

    async with Client(app) as c:
        tick = asyncio.create_task(ticker())
        res = await c.call_tool("amicus_backends", {})
        worst = await tick
    [entry] = [b for b in res.structured_content["backends"] if b["id"] == "codex"]
    assert entry["status"]["installed"] is True
    assert worst < 0.15, f"the loop stalled {worst:.3f}s while a status probe ran"


async def test_a_backend_tombstone_is_reported_only_through_that_backend_s_status():
    """A retired BACKEND name reaches `status.warnings` of the backend that owns it, so it is
    reported only while that backend is enabled and loaded; a stale name for a backend that
    is not enabled affects nothing, and the payload says nothing about it. docs/MIGRATION.md
    states exactly this, so a future top-level scan must change that sentence too."""
    from amicus.backends import codex

    environ = {
        "AMICUS_BACKENDS": "codex",
        "CODEX_IN_CLAUDE_ISOLATION": "ignore-rules",
        "MOONBRIDGE_MODEL": "k3",
        "AMICUS_CODEX_BIN": "/nonexistent/amicus-test-codex",
    }
    settings = config.settings(environ)
    # The real codex plugin, from the same environ (its status probe is what carries the
    # backend's config warnings); kimi is not enabled, so no kimi plugin exists at all.
    registry = BackendRegistry({"codex": codex.plugin(environ)}, {})
    async with Client(server.create_app(settings, registry)) as c:
        res = await c.call_tool("amicus_backends", {})
    payload = res.structured_content
    by_id = {b["id"]: b for b in payload["backends"]}
    codex_warnings = "\n".join(by_id["codex"]["status"]["warnings"])
    assert "CODEX_IN_CLAUDE_ISOLATION is set but not read" in codex_warnings
    assert "AMICUS_CODEX_ISOLATION" in codex_warnings
    assert not any("CODEX_IN_CLAUDE_ISOLATION" in w for w in payload["env_warnings"])
    assert by_id["kimi"]["status"] is None and not by_id["kimi"]["enabled"]
    assert "MOONBRIDGE_MODEL" not in json.dumps(payload)


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


async def test_models_reports_a_truncated_catalog():
    """#414: a catalog cut at the backend's entry bound says so, rather than reading as whole."""

    class _Cut:
        def read(self):
            return ModelListing(models=(ModelEntry(slug="m0"),), source="live", truncated=True)

    reg = BackendRegistry({"kimi": fakeplugin.make_plugin("kimi", models=_Cut())}, {})
    async with Client(_app(registry=reg)) as c:
        res = await c.call_tool("amicus_models", {"backend": "kimi"})
        tool = next(t for t in await c.list_tools() if t.name == "amicus_models")
    Draft202012Validator(tool.output_schema).validate(res.structured_content)
    assert res.structured_content["truncated"] is True
    hint = res.structured_content["truncation_hint"]
    assert "these 1 models" in hint and "`model`" in hint and "reasoning_effort" in hint


class _CutListing:
    def read(self):
        return ModelListing(models=(ModelEntry(slug="m0"),), source="live", truncated=True)


async def _models_both_ways(backend):
    """(tool payload, amicus://models/{backend} payload) for a cut listing on `backend`."""
    reg = BackendRegistry({backend: fakeplugin.make_plugin(backend, models=_CutListing())}, {})
    async with Client(_app(registry=reg)) as c:
        tool = (await c.call_tool("amicus_models", {"backend": backend})).structured_content
        [content] = await c.read_resource(f"amicus://models/{backend}")
    return tool, json.loads(content.text)


async def test_a_truncated_pi_listing_says_the_exact_model_is_still_checked():
    """#443: pi looks the exact model up on its own, past amicus's listing bound, and checks
    its effort pre-spend; the hint says so, without promising the model is accepted."""
    tool, resource = await _models_both_ways("pi")
    assert tool["truncation_hint"] == resource["truncation_hint"]
    hint = tool["truncation_hint"]
    assert "these 1 models" in hint
    assert "provider/id" in hint and "reasoning_effort" in hint
    assert "checks" in hint and "before any spend" in hint
    assert "refus" in hint  # a model pi cannot resolve is refused, not promised
    assert "cannot check" not in hint and "is still valid" not in hint


async def test_a_truncated_kimi_listing_does_not_vouch_for_a_slug_past_the_cut():
    tool, resource = await _models_both_ways("kimi")
    assert tool["truncation_hint"] == resource["truncation_hint"]
    hint = tool["truncation_hint"]
    assert "these 1 models" in hint and "may still be valid" in hint
    assert "is still valid" not in hint
    assert "cannot check a reasoning_effort" in hint


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
    assert codex.structured_content["truncated"] is False
    assert codex.structured_content["truncation_hint"] is None
    # amicus_models on an unavailable backend now reports the same backend_unavailable
    # envelope every paid tool reports, rather than the resource's informational
    # available:false payload (that stays on amicus://models/{backend}).
    assert kimi.is_error
    Draft202012Validator(tool.output_schema).validate(kimi.structured_content)
    err = kimi.structured_content["error"]
    assert err["code"] == "backend_unavailable"
    assert err["repair"]["tool"] == "amicus_backends"
    assert "unavailable" in err["message"]


async def test_backends_summary_omits_the_disclosures_and_says_so():
    """The default projection drops the four disclosure KEYS (not nulls them, which would
    read as "no loaded plugin declares one") and names them in omitted_fields; the
    resource never does."""
    app = _app(env={"AMICUS_BACKENDS": "codex,kimi"}, registry=_mixed_registry())
    async with Client(app) as c:
        tool = next(t for t in await c.list_tools() if t.name == "amicus_backends")
        summary = (await c.call_tool("amicus_backends", {})).structured_content
        full = (await c.call_tool("amicus_backends", {"detail": "full"})).structured_content
        [entry] = await c.read_resource("amicus://backends/codex")
    Draft202012Validator(tool.output_schema).validate(summary)
    assert tool.input_schema["properties"]["detail"]["default"] == "summary"
    omitted = {"egress", "carriers", "readonly_honesty", "implicit_context"}
    assert summary["omitted_fields"] == sorted(
        omitted, key=list(results.BACKEND_DISCLOSURE_FIELDS).index
    )
    assert set(results.BACKEND_DISCLOSURE_FIELDS) == omitted
    assert [b["id"] for b in summary["backends"]] == [b["id"] for b in full["backends"]]
    for thin, fat in zip(summary["backends"], full["backends"], strict=True):
        assert not (omitted & set(thin)), thin["id"]
        assert omitted <= set(fat), fat["id"]
        assert {k: v for k, v in fat.items() if k not in omitted} == thin
    assert summary["unavailable"] == full["unavailable"]
    resource_entry = json.loads(entry.text)
    assert resource_entry["carriers"] == "argv" and resource_entry["egress"] == "sends to OpenAI"
    assert "omitted_fields" not in resource_entry
    # The wire cost the projection buys, per entry: the disclosures are most of it.
    thin_codex = json.dumps(summary["backends"][0], separators=(",", ":"))
    fat_codex = json.dumps(full["backends"][0], separators=(",", ":"))
    assert len(thin_codex) < len(fat_codex)


async def test_capabilities_summary_full_row_selection_and_include_schemas():
    app = _app()
    async with Client(app) as c:
        tool = next(t for t in await c.list_tools() if t.name == "amicus_capabilities")
        summary = (await c.call_tool("amicus_capabilities", {})).structured_content
        full = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
        no_rows = (
            await c.call_tool("amicus_capabilities", {"include_tool_details": False})
        ).structured_content
        no_rows_full = (
            await c.call_tool(
                "amicus_capabilities", {"include_tool_details": False, "detail": "full"}
            )
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
    assert summary["enabled_backends"] == ["codex", "kimi", "claude", "pi"]
    assert {d["name"] for d in summary["tool_details"]} == set(tools.TOOL_ORDER)
    # detail changes field density only: same rows, same order, at both levels.
    assert [d["name"] for d in summary["tool_details"]] == [d["name"] for d in full["tool_details"]]
    entry = next(d for d in summary["tool_details"] if d["name"] == "amicus_consult")
    assert set(entry) == {"name", "cost", "stability", "deprecation", "backends"}
    assert entry["stability"] == "experimental"
    entry_full = next(d for d in full["tool_details"] if d["name"] == "amicus_consult")
    assert set(entry_full) == set(entry) | set(results.TOOL_DETAIL_FULL_FIELDS)
    assert entry_full["required_params"] == ["backend", "question"]
    assert "use_when" in entry_full and entry_full["returns"]
    assert "backend_unavailable" in entry_full["error_codes"]
    # A summary row never carries error_codes at all: an empty list there would claim the
    # tool raises nothing, and the key's absence is what says "not requested".
    assert all("error_codes" not in d for d in summary["tool_details"])
    # Row selection rides include_tool_details, never detail.
    assert no_rows["tool_details"] == [] and no_rows_full["tool_details"] == []
    assert {k: v for k, v in no_rows.items() if k != "tool_details"} == {
        k: v for k, v in summary.items() if k != "tool_details"
    }
    assert set(with_schemas["schemas"]) == {"error-envelope", "parameter-contracts"}
    assert with_schemas["schemas"]["error-envelope"]["$schema"]
    assert "surface_digest" in summary and summary["fingerprint"] == FINGERPRINT
    assert "delivery statement" in summary["tasks"]["fallback"]
    assert set(get_args(CapabilitiesDetail)) == {"summary", "full"}
    assert tool.input_schema["properties"]["include_tool_details"]["default"] is True


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
    assert set(props) == {"workspace_root", "limit", "cursor", "status", "backend", "task_id"}
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


def test_empty_response_is_listed_exactly_where_kimi_can_run_the_tool():
    """Kimi's inspector emits empty_response on every paid verb it runs; a tool no kimi call
    can reach (claude-only adversarial review, the free tools) must not promise it."""
    from amicus.tools.discovery import TOOL_DETAILS

    paid = {n: r for n, r in TOOL_DETAILS.items() if r["cost"] == "active"}
    assert paid, "no paid tools found: the instrument is broken"
    for name, row in paid.items():
        assert ("empty_response" in row["error_codes"]) == ("kimi" in row["backends"]), name
    # The job-read tools deliver a paid tool's stored envelope, so they inherit it (#440).
    free = [
        r
        for n, r in TOOL_DETAILS.items()
        if r["cost"] != "active" and n not in discovery.JOB_READ_TOOLS
    ]
    assert all("empty_response" not in r["error_codes"] for r in free)
    for name in discovery.JOB_READ_TOOLS:
        assert "empty_response" in TOOL_DETAILS[name]["error_codes"], name


# --- #440: every code a tool returns is on its row, and every other code says why -------------


def test_every_catalog_code_is_on_a_row_or_classified_and_never_both():
    assert discovery.unaccounted_codes(ERROR_CODES) == []
    on_rows = {c for row in discovery.TOOL_DETAILS.values() for c in row["error_codes"]}
    classified = set(discovery.RESOURCE_ONLY_CODES) | set(discovery.RESERVED_CODES)
    assert on_rows & classified == set()
    assert set(discovery.RESOURCE_ONLY_CODES) & set(discovery.RESERVED_CODES) == set()
    assert classified <= set(ERROR_CODES)
    assert all(reason.strip() for reason in [*discovery.RESERVED_CODES.values()])
    # The control: the same function reports a catalog code nothing accounts for.
    assert discovery.unaccounted_codes((*ERROR_CODES, "invented_code")) == ["invented_code"]


async def test_every_tool_row_lists_the_boundary_and_guard_codes():
    """Derived from the registered tools, not from the table: a tool with parameters is
    behind the call-boundary validation (invalid_arguments), and a guarded one returns
    internal_error on an unexpected exception."""
    from amicus.tools._guard import GUARD_MARKER

    app = _app()
    listed = await _tools(app)
    assert len(listed) == len(discovery.TOOL_DETAILS)
    guarded = 0
    for tool in listed:
        codes = discovery.TOOL_DETAILS[tool.name]["error_codes"]
        if tool.input_schema.get("properties"):
            assert "invalid_arguments" in codes, tool.name
        registered = await app.get_tool(tool.name)
        if getattr(registered.fn, GUARD_MARKER, False):
            guarded += 1
            assert "internal_error" in codes, tool.name
    assert guarded == len(listed)


def test_invalid_model_is_listed_by_tool_role():
    """On a paid tool whose verb accepts a backend declaring model_validation, on a dry run
    that accepts pi (the one backend that refuses a model before spending), and on the job
    reads that deliver those paid tools' errors; nowhere else."""
    import importlib

    from amicus.backends import IN_TREE
    from amicus.schemas.codes import VERB_BACKENDS
    from amicus.schemas.params import TOOL_VERB

    validating = set()
    for backend_id in IN_TREE:
        contract = importlib.import_module(f"amicus.backends.{backend_id}.contract").CONTRACT
        if "model_validation" in contract.supported_features:
            validating.add(backend_id)
    assert validating == {"kimi", "pi"}
    expected = {
        name
        for name, (verb, _is_async) in TOOL_VERB.items()
        if set(VERB_BACKENDS[verb]) & validating
    }
    expected |= {
        name
        for name in ("amicus_review_changes_dry_run", "amicus_delegate_dry_run")
        if "pi" in discovery.TOOL_DETAILS[name]["backends"]
    }
    expected |= set(discovery.JOB_READ_TOOLS)
    actual = {n for n, r in discovery.TOOL_DETAILS.items() if "invalid_model" in r["error_codes"]}
    assert actual == expected
    assert "amicus_adversarial_review" not in actual and "amicus_models" not in actual


def test_the_job_reads_list_every_code_a_paid_tool_can_store():
    for name in discovery.JOB_READ_TOOLS:
        codes = set(discovery.TOOL_DETAILS[name]["error_codes"])
        for paid in discovery.PAID_ROWS:
            missing = set(discovery.TOOL_DETAILS[paid]["error_codes"]) - codes
            assert not missing, (name, paid, missing)
        assert {"job_not_found", "job_running", "job_result_incompatible"} <= codes, name


def test_the_catalog_description_names_the_reserved_class():
    [success] = [b for b in results.CAPABILITIES_SCHEMA["anyOf"] if "name" in b["properties"]]
    field = success["properties"]["error_codes"]
    assert field["description"] == results._CATALOG_DESC
    assert "reserved" in field["description"] and "resource_not_found" in field["description"]


async def test_hand_listed_params_match_each_tools_input_schema():
    # The tools _JOB_PARAMS covers are not derived from expected_params, so a parameter added
    # to one (wait_seconds, #266) would otherwise be missing from amicus_capabilities'
    # key_optional_params while tools/list and the handler accept it.
    # The two dry-run rows are a curated subset of their schemas, so they are checked only
    # for naming parameters that exist; every other row lists its tool's whole schema.
    schemas = {t.name: t.input_schema for t in await _tools(_app())}
    for name, (required, optional) in discovery._JOB_PARAMS.items():
        props = set(schemas[name].get("properties", {}))
        listed = set(required) | set(optional)
        assert set(required) == set(schemas[name].get("required", [])), name
        if name.endswith("_dry_run"):
            assert listed <= props, f"{name}: lists {sorted(listed - props)}, not in its schema"
        else:
            assert listed == props, (
                f"{name}: discovery lists {sorted(listed)}, the schema declares {sorted(props)}"
            )


async def test_capabilities_names_where_a_defect_is_reported():
    """`issues_url` is the one place on the tool surface that names the issue tracker. It is
    pinned to the `Issues` URL `pyproject.toml` publishes so the two cannot drift, it rides
    both detail levels (a summary reader is the one most likely to be mid-failure), and its
    description survives schema publication, because it carries the obligations - offer, do
    not file; no prompt input in a report - that make the pointer safe to act on."""
    import tomllib
    from pathlib import Path

    import amicus

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["urls"]["Issues"] == amicus.ISSUES_URL
    app = _app()
    async with Client(app) as c:
        summary = (await c.call_tool("amicus_capabilities", {})).structured_content
        full = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
    assert summary["issues_url"] == amicus.ISSUES_URL
    assert full["issues_url"] == amicus.ISSUES_URL
    desc = results.CAPABILITIES_SCHEMA["anyOf"][0]["properties"]["issues_url"]["description"]
    assert desc == results.ISSUES_URL_DESC
    for phrase in (
        "rather than opening one unasked",
        "no prompt input",
        "a resource-read failure's error.data.machine_code",
        "a tool failure's meta.job_id, else its error.request_id",
        "a resource-read failure's error.data.request_id",
        "A backend's wrong or poor answer, or a backend CLI failure amicus reports "
        "correctly, is not one.",
    ):
        assert phrase in desc, phrase


async def _annotations_reading(settings, registry=None):
    """annotations_reading and the paid tools' destructiveHint, read from one app."""
    app = server.create_app(settings, registry or BackendRegistry({}, {}))
    async with Client(app) as c:
        body = (await c.call_tool("amicus_capabilities", {})).structured_content
        by_name = {t.name: t for t in await c.list_tools()}
    paid = {by_name[n].annotations.destructive_hint for n in results.PAID_TOOLS}
    assert len(paid) == 1, paid
    return body["annotations_reading"], paid.pop()


def _destructive_sentence(reading: str) -> str:
    [sentence] = [s for s in reading.split(". ") if "destructiveHint" in s and "paid tools" in s]
    return sentence


_CLAUDE_REASON = "Claude Code is enabled and its config modes may run workspace hooks"
_PI_REASON = "Pi is enabled and its delegate runs unsandboxed shell commands"
_KIMI_REASON = (
    "Kimi is enabled and its delegate runs shell commands and writes files with no sandbox"
)
_CONFINED = "every enabled backend confines writes to a throwaway worktree"


@pytest.mark.parametrize(
    ("profile", "named", "unnamed"),
    [
        ("pi", [_PI_REASON], [_CLAUDE_REASON, "Claude Code"]),
        ("claude", [_CLAUDE_REASON], [_PI_REASON, "Pi "]),
        (None, [_KIMI_REASON, _CLAUDE_REASON, _PI_REASON], []),
        ("pi,claude", [_CLAUDE_REASON, _PI_REASON], []),
        ("kimi", [_KIMI_REASON], [_CLAUDE_REASON, _PI_REASON, "Codex"]),
        ("codex,kimi", [_KIMI_REASON], [_CLAUDE_REASON, _PI_REASON, "Codex"]),
    ],
)
async def test_annotations_reading_names_each_enabled_destructive_backend(profile, named, unnamed):
    """#442: a pi-only profile was told paid tools are destructive "because Claude Code is
    enabled". The sentence now names each enabled backend that makes them so, with its own
    reason, and agrees with the destructiveHint the paid tools actually carry. The profile
    is enabled, not loaded: the registry here is empty, so no plugin is loaded at all."""
    env = {"AMICUS_BACKENDS": profile} if profile else {}
    reading, destructive = await _annotations_reading(config.settings(env))
    sentence = _destructive_sentence(reading)
    assert destructive is True
    assert "destructiveHint true for this profile because" in sentence
    for reason in named:
        assert reason in sentence, (reason, sentence)
    for absent in unnamed:
        assert absent not in sentence, (absent, sentence)
    assert _CONFINED not in sentence
    if _CLAUDE_REASON in named and _PI_REASON in named:
        # Deterministic: the declaration order, whatever order AMICUS_BACKENDS lists them in.
        assert sentence.index(_CLAUDE_REASON) < sentence.index(_PI_REASON)


async def test_annotations_reading_keeps_the_confined_sentence_without_a_destructive_backend():
    """codex alone is the one profile left whose paid tools are not destructive: kimi has
    no sandbox, so enabling it makes them destructive (#426)."""
    reading, destructive = await _annotations_reading(config.settings({"AMICUS_BACKENDS": "codex"}))
    sentence = _destructive_sentence(reading)
    assert destructive is False
    assert f"destructiveHint false for this profile because {_CONFINED}" in sentence
    for absent in ("Claude Code", "Pi ", "Kimi"):
        assert absent not in sentence, absent


async def test_annotations_reading_never_invents_a_cause_for_an_undeclared_backend():
    """An enabled id amicus has no effects declaration for is annotated for the worst case
    (`_meta._UNKNOWN_EFFECTS`); the sentence says exactly that rather than borrowing a
    known backend's reason. config rejects an unknown AMICUS_BACKENDS token, so the
    settings are built with the id set directly."""
    import dataclasses

    settings = dataclasses.replace(
        config.settings({"AMICUS_BACKENDS": "codex"}), enabled_backends=("codex", "zeta")
    )
    reading, destructive = await _annotations_reading(settings)
    sentence = _destructive_sentence(reading)
    assert destructive is True
    assert (
        "zeta is enabled and annotated for the worst case because amicus has no declaration for it"
    ) in sentence
    for absent in (_CLAUDE_REASON, _PI_REASON, "Codex", _CONFINED):
        assert absent not in sentence, absent


def test_every_destructive_backend_declares_its_reason():
    """A backend whose KNOWN_EFFECTS says paid calls are destructive must carry the reason
    annotations_reading gives for it, and a reason may not outlive its declaration."""
    from amicus.backends import DESTRUCTIVE_REASONS, KNOWN_EFFECTS

    destructive = {b for b, e in KNOWN_EFFECTS.items() if e.paid_calls_destructive}
    assert destructive == {"claude", "kimi", "pi"}
    assert set(DESTRUCTIVE_REASONS) == destructive
    assert all(r.strip() and not r.endswith(".") for r in DESTRUCTIVE_REASONS.values())


async def test_annotations_reading_says_which_job_read_records_a_delivery():
    """#446: job reads stay readOnlyHint true (decision D5), and the reading says the one
    thing a read changes: amicus_job_result records the delivery, which is what lets the
    per-workspace cap evict the result."""
    reading, _ = await _annotations_reading(config.settings({}))
    [sentence] = [s for s in reading.split(". ") if "job reads stay readOnlyHint true" in s]
    assert "amicus_job_result records each result it returns" in sentence
    assert "evictable by the cap" in sentence


def _sentences(text: str | None) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join((text or "").split())) if s]


async def _loaded_backends():
    """amicus_backends at both details and each backend's template read, with every in-tree
    plugin loaded through the real registry path (the autouse guards in conftest make each
    binary unreachable, so no backend CLI runs). The manifest snapshots are built with an
    empty registry and never see a plugin's disclosures, so this is the instrument for them."""
    ids = ("codex", "kimi", "claude", "pi")
    registry = BackendRegistry.load(ids, entry_points=())
    assert registry.unavailable == {}
    app = _app(registry=registry)
    async with Client(app) as c:
        summary = (await c.call_tool("amicus_backends", {})).structured_content
        full = (await c.call_tool("amicus_backends", {"detail": "full"})).structured_content
        resources = {}
        for b in ids:
            [entry] = await c.read_resource(f"amicus://backends/{b}")
            resources[b] = json.loads(entry.text)
    return summary, {e["id"]: e for e in full["backends"]}, resources


# What leaves and to whom: each backend's egress names its recipient and the inputs it sends.
_EGRESS_NAMES: dict[str, tuple[str, ...]] = {
    "codex": ("OpenAI", "question/task", "extra_context", "instructions_append", "diff"),
    "kimi": ("Kimi provider", "question/task", "extra_context", "instructions_append", "diff"),
    "claude": ("Anthropic", "question/target/evidence", "extra_context", "diff"),
    "pi": ("provider",),
}


async def test_backend_egress_says_only_what_leaves_and_never_repeats_its_neighbours():
    """#445: egress repeated, verbatim, sentences the same entry publishes as
    readonly_honesty or implicit_context, which made the mandatory first read about 14%
    longer. Each sentence now has one home in the entry; pi's entry was already the control."""
    summary, full, resources = await _loaded_backends()
    assert set(full) == set(_EGRESS_NAMES)
    for backend, entry in full.items():
        for name in _EGRESS_NAMES[backend]:
            assert name in entry["egress"], (backend, name)
        neighbours = " ".join(
            " ".join((entry[f] or "").split()) for f in ("readonly_honesty", "implicit_context")
        )
        repeated = [s for s in _sentences(entry["egress"]) if s in neighbours]
        assert repeated == [], (backend, repeated)
    # The summary still names all four disclosures as omitted.
    assert summary["omitted_fields"] == list(results.BACKEND_DISCLOSURE_FIELDS)
    # The template returns one flattened entry; its disclosures equal the full tool entry's.
    for backend, entry in full.items():
        for field in results.BACKEND_DISCLOSURE_FIELDS:
            assert resources[backend][field] == entry[field], (backend, field)


@pytest.mark.parametrize("answer", ['["not", "an", "object"]', '{"summary": 3}', "plain prose"])
async def test_no_paid_verb_turns_a_schema_violating_answer_into_schema_violation(
    tmp_path, fake_codex, monkeypatch, answer
):
    """The behaviour behind classifying schema_violation as reserved (#440): an answer the
    structured parser rejects reaches a consult as prose, a review as review_status
    unstructured, and a delegate as its diff; none of them is an error envelope."""
    import subprocess

    from amicus.jobs import lifecycle

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@t.co"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True, capture_output=True)
    (repo / "a.py").write_text("x = 2\n")
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ANSWER", answer)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    app = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    ws = {"backend": "codex", "workspace_root": str(repo)}
    async with Client(app) as c:
        consult = await c.call_tool("amicus_consult", {**ws, "question": "why?"})
        review = await c.call_tool("amicus_review_changes", ws)
        delegate = await c.call_tool("amicus_delegate", {**ws, "task": "edit a.py"})
    assert consult.structured_content["ok"] is True
    assert review.structured_content["ok"] is True
    if not answer.startswith("{"):
        assert review.structured_content["review_status"] == "unstructured"
    assert delegate.structured_content["ok"] is True


async def test_an_unsupported_detail_or_isolation_is_invalid_arguments(tmp_path):
    """The behaviour behind classifying unsupported_detail and unsupported_isolation as
    reserved (#440): both values are closed enums the call boundary or the option check
    refuses as invalid_arguments, before any SDK classification could apply."""
    async with Client(_app()) as c:
        detail = await c.call_tool("amicus_backends", {"detail": "bogus"}, raise_on_error=False)
        isolation = await c.call_tool(
            "amicus_review_changes_dry_run",
            {
                "backend": "codex",
                "workspace_root": str(tmp_path),
                "backend_options": {"isolation": "bogus"},
            },
            raise_on_error=False,
        )
    assert detail.structured_content["error"]["code"] == "invalid_arguments"
    assert isolation.structured_content["error"]["code"] == "invalid_arguments"
