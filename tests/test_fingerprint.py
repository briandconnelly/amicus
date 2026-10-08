"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT, parse_fingerprint

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "eb2544d47268fb6748b0d5ed9c4bbcec07e0ff394baac2d117bc92da81f42495",
    "codex-kimi": "6bcc350ca1fa0b7bce470ecd98d795f50d28241f047ca5aecbc4f101385b86c9",
    "claude": "eb2544d47268fb6748b0d5ed9c4bbcec07e0ff394baac2d117bc92da81f42495",
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
