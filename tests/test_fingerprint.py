"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT, parse_fingerprint

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "18f957727a54eff706b3f36ef9a3118e90bbe91c365c50b3b63f1e0948a08cdf",
    "codex-kimi": "ac81fb9acd35d5a39f6a518f5b4eb1333640a66f57603c6c8772e85a9a11bbee",
    "claude": "18f957727a54eff706b3f36ef9a3118e90bbe91c365c50b3b63f1e0948a08cdf",
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
