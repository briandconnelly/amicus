"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "f673bed608d955bd5d4d1308b909039d46128e48b7fbc46a8de4c1e3d3aab5c1",
    "codex-kimi": "0f6015f3c02fa5290cde11fd7df37dbc99f779276d9a818daeb7b5f4c6b8b6f2",
    "claude": "f673bed608d955bd5d4d1308b909039d46128e48b7fbc46a8de4c1e3d3aab5c1",
}


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
async def test_surface_digest_is_pinned(profile):
    actual = await surface.surface_digest(manifest.app_for_profile(profile))
    assert actual == EXPECTED_SURFACE_DIGEST[profile], (
        f"surface_digest moved for {profile!r}: {actual}. If intentional, bump FINGERPRINT "
        f"(currently {FINGERPRINT}) and re-pin in a dedicated commit."
    )


async def test_digest_moves_when_a_description_changes():
    app = manifest.app_for_profile("all")
    before = await surface.surface_digest(app)
    tool = await app.get_tool("amicus_consult")
    original = tool.description
    tool.description = (original or "") + " probe"
    try:
        after = await surface.surface_digest(app)
    finally:
        tool.description = original
    assert after != before
    assert await surface.surface_digest(app) == before
