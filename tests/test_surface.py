"""surface_digest: a sha256 over the server-side records, stable and profile-sensitive."""

from __future__ import annotations

from amicus import config, server, surface
from amicus.registry import BackendRegistry


async def test_digest_is_hex_deterministic_and_profile_sensitive():
    a = server.create_app(config.settings({}), BackendRegistry({}, {}))
    b = server.create_app(config.settings({}), BackendRegistry({}, {}))
    c = server.create_app(config.settings({"AMICUS_BACKENDS": "codex"}), BackendRegistry({}, {}))
    da, db, dc = (
        await surface.surface_digest(a),
        await surface.surface_digest(b),
        await surface.surface_digest(c),
    )
    assert len(da) == 64 and da == db and da != dc
    records = await surface.surface_records(a)
    assert [t["name"] for t in records["tools"]] == sorted(t["name"] for t in records["tools"])
    assert records["instructions"] == server.CAPABILITY_SUMMARY
    assert {r["uri"] for r in records["resources"]} >= {"amicus://capabilities"}
    assert {t["uriTemplate"] for t in records["resource_templates"]} == {
        "amicus://backends/{backend}",
        "amicus://models/{backend}",
    }


def test_clean_drops_a_meta_left_empty_after_stripping_the_fastmcp_key():
    record = surface._clean({"name": "x", "_meta": {"fastmcp": {"tags": []}}})
    assert "_meta" not in record
