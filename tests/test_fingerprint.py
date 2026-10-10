"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT, parse_fingerprint

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "27b14f47cd4897387637419d5df4fa1969ef79ff26bb9fb6190b2adc6c1003aa",
    "codex-kimi": "281d2b6378e28668ed962c2969978fb769bc67aa35aff1a6f997d3539dbbf20e",
    "claude": "27b14f47cd4897387637419d5df4fa1969ef79ff26bb9fb6190b2adc6c1003aa",
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


def test_fingerprint_has_the_documented_shape():
    # ADR 0006 and the design spec promise clients `amicus/0.1/schema-N`; FINGERPRINT is
    # bumped by hand, so this is what stops a typo'd bump from reaching the wire.
    name, major, _revision = parse_fingerprint(FINGERPRINT)
    assert (name, major) == ("amicus", "0.1")
