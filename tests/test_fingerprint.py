"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "8b83822aa6e73219924d979d5ff30ba11f93cac40171c9c22fdfbb1d31cecb63",
    "codex-kimi": "767feb4ac2bab65a8a464cb7ff775353633ded7515eb90b131b39bf6ce1fd91d",
    "claude": "8b83822aa6e73219924d979d5ff30ba11f93cac40171c9c22fdfbb1d31cecb63",
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
