"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT

EXPECTED_SURFACE_DIGEST: dict[str, str] = {
    "all": "454aabc5251fca2861682ee60a5d30982c215e76d5caaf2480a81071bc0c5661",
    "codex-kimi": "0668e8657647f80f38b1513f879ec346b452aadeab2d62c203bfdb5eb963b5b7",
    "claude": "454aabc5251fca2861682ee60a5d30982c215e76d5caaf2480a81071bc0c5661",
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
