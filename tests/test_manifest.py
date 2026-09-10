"""Guard: the manifest snapshot covers the full agent-visible surface, per profile."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastmcp import Client

from amicus import manifest, server
from amicus.schemas.fingerprint import FINGERPRINT_COVERS, FINGERPRINT_COVERS_DESC
from amicus.schemas.params import WORKSPACE_PREREQUISITE, WORKSPACELESS_TOOLS

FIXTURES = Path(__file__).parent / "fixtures"

# sha256 of each profile's canonical manifest JSON; regenerate per the failure message.
EXPECTED_MANIFEST_HASH: dict[str, str] = {
    "all": "0f17561ec29e91451eec51f497edfbe411c91c8b868bae9c1f5ed78d3a142948",
    "codex-kimi": "9acdc599eaa46548ef2b87834640572170a36a86c4f257d434ca743e80be2dd0",
    "claude": "7bbdbc7a4c87082837e3a9860ec31aebda40d297d30f4c21a36588f7548672d2",
}

_CACHING_SPEC_LIST_METHODS = (
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
)


def test_canonicalize():
    assert manifest._canonicalize({"_meta": {"fastmcp": {"tags": []}, "app": {"k": 1}}}) == {
        "_meta": {"app": {"k": 1}}
    }
    assert manifest._canonicalize({"_meta": {"fastmcp": {"tags": []}}}) == {}
    canon = manifest._canonicalize(
        {"enum": ["c", "a"], "required": ["z", "a"], "type": ["string", "null"]}
    )
    assert canon == {"enum": ["a", "c"], "required": ["a", "z"], "type": ["null", "string"]}
    src = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert manifest._canonicalize(src)["anyOf"] == src["anyOf"]


async def test_build_manifest_covers_full_surface():
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    assert {t["name"] for t in m["tools"]} == set(m["capabilities"]["active_tools"]) | set(
        m["capabilities"]["free_tools"]
    ) | set(m["capabilities"]["job_tools"])
    assert len(m["tools"]) == 18
    for section in (
        "resources",
        "resource_templates",
        "initialize",
        "discover",
        "error_envelope",
        "result_meta",
        "params",
        "capabilities",
    ):
        assert m[section], section
    assert m["prompts"] == []


async def test_fingerprint_covers_accounts_for_every_section():
    section_tokens = {
        "tools": {
            "tool_names",
            "tool_input_schemas",
            "tool_output_schemas",
            "tool_descriptions",
            "tool_annotations",
            "tool_lifecycle_meta",
            "error_codes",
            "value_enums",
        },
        "resources": {"resource_metadata"},
        "resource_templates": {"resource_templates"},
        "prompts": {"prompts"},
        "initialize": {"initialize_response"},
        "discover": {"discover_response"},
        "modern_result_envelopes": {"modern_result_envelopes"},
        "error_envelope": {"error_envelope_schema"},
        "result_meta": {"result_meta_schema"},
        "params": {"parameter_contracts"},
        "capabilities": {
            "capabilities_payload",
            "capability_guarantees",
            "capabilities_result_schema",
        },
    }
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    assert set(section_tokens) == set(m)
    assert set().union(*section_tokens.values()) == set(FINGERPRINT_COVERS)


async def test_manifest_drops_exactly_the_declared_capability_fields():
    app = manifest.app_for_profile("all")
    m = await manifest.build_manifest(app)
    async with Client(app) as c:
        live = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
    dropped = set(live) - set(m["capabilities"])
    assert dropped == manifest.RELEASE_VARIABLE_EXCLUDE | manifest.SELF_REFERENTIAL_EXCLUDE
    assert set(live) >= manifest.RELEASE_VARIABLE_EXCLUDE | manifest.SELF_REFERENTIAL_EXCLUDE


def test_release_variable_exclusions_are_disclosed():
    clause = re.search(
        r"Release identity is excluded: (.+?) change every release", FINGERPRINT_COVERS_DESC
    )
    assert clause
    disclosed = {n.strip() for n in clause.group(1).split(",")}
    assert disclosed == manifest.RELEASE_VARIABLE_EXCLUDE | {"serverInfo.version"}
    assert "surface_digest" in FINGERPRINT_COVERS_DESC


async def test_static_resource_bodies_are_parsed():
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    for section in ("error_envelope", "result_meta", "params"):
        parsed = [b["text"] for b in m[section] if isinstance(b.get("text"), dict)]
        assert parsed, section
    assert any("backend" in b.get("properties", {}) for b in [x["text"] for x in m["result_meta"]])


async def test_initialize_and_discover_are_captured_without_versions():
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    assert m["initialize"]["serverInfo"]["name"] == "amicus"
    assert "version" not in m["initialize"]["serverInfo"]
    assert m["discover"]["supportedVersions"] == ["2026-07-28"]
    assert "version" not in m["discover"]["_meta"]["io.modelcontextprotocol/serverInfo"]
    # Equal since ADR 0018: the two eras derive `listChanged` from different inputs and
    # `_filter_capabilities` forces both to the honest `false`. Transport parity against the
    # real stdio wire is asserted in `tests/test_cache_hints.py`, which is where the
    # in-memory manifest could otherwise pin a value no client receives.
    assert m["initialize"]["capabilities"] == m["discover"]["capabilities"]


async def test_modern_result_envelopes_are_pinned_at_the_declared_cache_policy():
    """The list methods carry the catalog TTL and `resources/read` carries none (ADR 0018);
    the manifest pins the emitted values so a framework change is reviewed, not silent."""
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    env = m["modern_result_envelopes"]
    assert set(env) == set(_CACHING_SPEC_LIST_METHODS) | {"resources/read", "tools/call"}
    cached = {
        "resultType": "complete",
        "ttlMs": server.CATALOG_CACHE_TTL_MS,
        "cacheScope": server.CATALOG_CACHE_SCOPE,
    }
    for method in _CACHING_SPEC_LIST_METHODS:
        assert method in server.CACHED_CATALOG_METHODS, method
        assert env[method] == cached, method
    assert "resources/read" in server.UNCACHED_CACHEABLE_METHODS
    assert set(env["resources/read"]) == set(manifest.STATIC_RESOURCE_URIS)
    for uri, fields in env["resources/read"].items():
        assert fields == {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}, uri
    assert env["tools/call"]["resultType"] == "complete"
    listed = {r["uri"] for r in m["resources"]}
    assert listed == set(manifest.STATIC_RESOURCE_URIS) | set(manifest.DYNAMIC_RESOURCE_URIS)


async def test_list_items_are_era_neutral():
    app = manifest.app_for_profile("all")
    async with Client(app, mode="legacy") as legacy, Client(app) as modern:
        for lister in ("list_tools", "list_resources", "list_resource_templates"):
            a = [manifest._canonicalize(manifest._dump(x)) for x in await getattr(legacy, lister)()]
            b = [manifest._canonicalize(manifest._dump(x)) for x in await getattr(modern, lister)()]
            assert a == b, lister
        assert await modern.list_tools()


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
async def test_manifest_matches_golden(profile):
    app = manifest.app_for_profile(profile)
    current = manifest.manifest_json(await manifest.build_manifest(app))
    fixture = FIXTURES / f"manifest_snapshot.{profile}.json"
    assert fixture.exists(), (
        f"no snapshot for profile {profile!r}: `uv run python -m amicus.manifest --profile "
        f"{profile} > tests/fixtures/manifest_snapshot.{profile}.json` in its own commit"
    )
    assert current == fixture.read_text(encoding="utf-8"), (
        "agent-visible surface changed — review the snapshot diff, then in a DEDICATED "
        "commit: bump FINGERPRINT (schema-N) in schemas/fingerprint.py, regenerate every "
        "profile's fixture, and re-pin EXPECTED_MANIFEST_HASH and the surface digests."
    )
    assert await manifest.manifest_hash(app) == EXPECTED_MANIFEST_HASH[profile]


async def test_profiles_differ_where_annotations_differ():
    a = await manifest.build_manifest(manifest.app_for_profile("codex-kimi"))
    b = await manifest.build_manifest(manifest.app_for_profile("claude"))
    consult_a = next(t for t in a["tools"] if t["name"] == "amicus_consult")
    consult_b = next(t for t in b["tools"] if t["name"] == "amicus_consult")
    assert consult_a["annotations"]["destructiveHint"] is False
    assert consult_b["annotations"]["destructiveHint"] is True


def test_render_returns_canonical_json():
    out = manifest.render("all")
    assert out.startswith("{") and out.endswith("\n")


async def test_tools_list_bytes_is_positive():
    assert await manifest.tools_list_bytes(manifest.app_for_profile("all")) > 10_000


def _minimal_args(schema: dict) -> dict:
    """One accepted value for each required property, from the schema itself."""
    args = {}
    for field in schema.get("required", ()):
        prop = schema["properties"][field]
        enum = prop.get("enum")
        args[field] = enum[0] if enum else "x"
    return args


async def test_the_workspace_prerequisite_is_bound_to_the_schemas(tmp_path):
    """Issue #40: both published surfaces told a sessionless client to pass
    workspace_root on EVERY call, while three tools declare none and reject one
    (every inputSchema is additionalProperties: false), so the agent that followed
    the prerequisite failed its first call.

    What this pins is the tool set, not the prose: WORKSPACELESS_TOOLS must be
    exactly the tools whose schema omits the parameter, each must really reject
    one, and every surface stating the prerequisite must carry the single shared
    sentence rendered from that tuple. One sentence is then the only thing a
    reviewer has to read, and it cannot disagree with the schemas or with itself."""
    app = manifest.app_for_profile("all")
    m = await manifest.build_manifest(app)
    takes = {t["name"] for t in m["tools"] if "workspace_root" in t["inputSchema"]["properties"]}
    exempt = {t["name"] for t in m["tools"]} - takes
    assert exempt and takes, "schema probe found nothing to distinguish; the claims are vacuous"
    assert set(WORKSPACELESS_TOOLS) == exempt

    schemas = {t["name"]: t["inputSchema"] for t in m["tools"]}
    async with Client(app) as c:
        for name in sorted(exempt):
            # Every other required argument supplied, so the ONLY thing left to reject is
            # workspace_root: a bare call to amicus_models errors on its missing `backend`
            # and would pass this probe even if unknown arguments started being accepted.
            args = _minimal_args(schemas[name]) | {"workspace_root": str(tmp_path)}
            res = await c.call_tool(name, args, raise_on_error=False)
            err = (res.structured_content or {}).get("error", {})
            assert err.get("code") == "invalid_arguments", (name, err)
            assert err.get("details", {}).get("field") == "workspace_root", (name, err)
        # Positive control on the same instrument: a tool that DOES declare the parameter
        # accepts it, so the assertions above report the exemption, not a broken probe.
        control = await c.call_tool(
            "amicus_job_list", {"workspace_root": str(tmp_path)}, raise_on_error=False
        )
        assert not control.is_error, control.structured_content

    # Named by token, not substring: a future amicus_models_v2 that takes a workspace
    # must not satisfy the exemption by containing amicus_models.
    named = set(re.findall(r"amicus_[a-z_]+", WORKSPACE_PREREQUISITE))
    assert named == exempt

    surfaces = {
        "instructions": m["initialize"]["instructions"],
        "prerequisites": " ".join(m["capabilities"]["prerequisites"]),
    }
    stated = WORKSPACE_PREREQUISITE.rstrip(".")
    for where, text in surfaces.items():
        assert WORKSPACE_PREREQUISITE in text, where
        # and nowhere else on that surface, so no second sentence can contradict it.
        stray = [s.rstrip(".") for s in text.split(". ") if "workspace_root" in s]
        assert stray == [stated], (where, stray)
