"""The static advisory catalog: no filesystem, no spawn, every KNOWN_MODELS entry."""

from __future__ import annotations

from amicus.backends.claude import config, contract, models


def test_static_catalog_lists_every_known_model_in_order():
    listing = models.ClaudeModels(config.load_config({})).read()
    assert listing.source == "static" and listing.fetched_at is None
    assert [m.slug for m in listing.models] == [s for s, _n, _k in contract.KNOWN_MODELS]
    assert listing.models[0].display_name == "Opus (alias → latest Opus)"
    assert all(m.supported_reasoning_efforts is None for m in listing.models)
    assert models.ClaudeModels(config.load_config({})).read(force=True) == listing
    assert "advisory" in models.ADVISORY.lower()
