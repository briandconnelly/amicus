"""Guard: the manifest snapshot covers the full agent-visible surface, per profile."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastmcp import Client

from amicus import manifest
from amicus.schemas.fingerprint import FINGERPRINT_COVERS, FINGERPRINT_COVERS_DESC

FIXTURES = Path(__file__).parent / "fixtures"

# sha256 of each profile's canonical manifest JSON; regenerate per the failure message.
EXPECTED_MANIFEST_HASH: dict[str, str] = {
    "all": "113f92b33898a2589b855df254d3a8a7f5f14d38e3ede65d17d75b2798714d6b",
    "codex-kimi": "9b725485da71d95899a05bf0ba561ad43042ab7b1fa3fccdf970849db6acbd93",
    "claude": "e1dc34079dd07664eb33b27acd66dc564a59daa2d9b8f6aac5aff880146027c3",
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
    assert m["initialize"]["capabilities"] != m["discover"]["capabilities"]


async def test_modern_result_envelopes_are_pinned_at_the_sdk_default():
    """ttlMs/cacheScope are deliberately left at the SDK default (ADR 0006); the manifest
    pins the emitted values so a framework change is reviewed, not silent."""
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    env = m["modern_result_envelopes"]
    assert set(env) == set(_CACHING_SPEC_LIST_METHODS) | {"resources/read", "tools/call"}
    for method in _CACHING_SPEC_LIST_METHODS:
        assert env[method] == {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}, (
            method
        )
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
