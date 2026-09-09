"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "5be3c626f4f8c05d2ded4ff0b47c02f50dfe812f5f3dde8753cd28b0bade18c9",
    "codex-kimi": "45263c2b457a2a94eec220d8e6eee565efda8c7721b41a0bc476cc902252add3",
    "claude": "5be3c626f4f8c05d2ded4ff0b47c02f50dfe812f5f3dde8753cd28b0bade18c9",
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
