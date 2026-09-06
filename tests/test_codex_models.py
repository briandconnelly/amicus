"""Advisory models catalog: live cache when usable, else the bundled static list."""

from __future__ import annotations

import json

from amicus.backends.codex import config as cc
from amicus.backends.codex import contract, models


def _reader(monkeypatch, home):
    monkeypatch.setenv("CODEX_HOME", str(home))
    return models.CodexModels(cc.load_config({}))


def test_cache_is_read_and_defensively_parsed(monkeypatch, tmp_path):
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-09-01T00:00:00Z",
                "client_version": "0.153.4",
                "models": [
                    {
                        "slug": "gpt-5.5",
                        "display_name": "GPT-5.5",
                        "default_reasoning_level": "medium",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "high"},
                            {"effort": "low"},
                        ],
                    },
                    {"slug": "-bad"},
                    "junk",
                    {"slug": "x", "display_name": "d\x1bx", "supported_reasoning_levels": "no"},
                ],
            }
        )
    )
    listing = _reader(monkeypatch, tmp_path).read()
    assert listing.source == "cache" and listing.fetched_at == "2026-09-01T00:00:00Z"
    assert [m.slug for m in listing.models] == ["gpt-5.5", "x"]
    first = listing.models[0]
    assert first.display_name == "GPT-5.5" and first.default_reasoning_effort == "medium"
    assert first.supported_reasoning_efforts == ("low", "high")
    assert listing.models[1].display_name == "dx"
    assert listing.models[1].supported_reasoning_efforts is None


def test_missing_or_malformed_cache_falls_back_to_static(monkeypatch, tmp_path):
    assert _reader(monkeypatch, tmp_path).read().source == "static"
    (tmp_path / "models_cache.json").write_text("{not json")
    listing = _reader(monkeypatch, tmp_path).read()
    assert listing.source == "static"
    assert tuple(m.slug for m in listing.models) == contract.KNOWN_MODEL_SLUGS
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [{"slug": "-bad"}]}))
    assert _reader(monkeypatch, tmp_path).read().source == "static"


def test_unexpandable_codex_home_falls_back(monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "~nonexistent_user_xyz/.codex")
    monkeypatch.setattr(
        models.Path, "expanduser", lambda self: (_ for _ in ()).throw(RuntimeError())
    )
    assert models.codex_home() is None
    assert models.CodexModels(cc.load_config({})).read().source == "static"


def test_no_static_fallback_reports_none(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(contract, "KNOWN_MODEL_SLUGS", ())
    listing = models.CodexModels(cc.load_config({})).read()
    assert listing.source == "none" and listing.models == ()
