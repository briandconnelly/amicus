"""Advisory models catalog: live cache when usable, else the bundled static list."""

from __future__ import annotations

import json

import pytest

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


def test_unresolvable_home_directory_falls_back(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(models.Path, "home", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert models.codex_home() is None
    assert models.CodexModels(cc.load_config({})).read().source == "static"


def test_empty_codex_home_is_unset(monkeypatch, tmp_path):
    # codex 0.156.1 treats CODEX_HOME="" as unset too (probed: it reads ~/.codex).
    monkeypatch.setenv("CODEX_HOME", "")
    monkeypatch.setattr(models.Path, "home", lambda: tmp_path)
    assert models.codex_home() == tmp_path / ".codex"
    assert cc.codex_home_error({"CODEX_HOME": ""}) is None


@pytest.mark.parametrize("value", ["codexhome", "./codexhome", "~/codexhome"])
def test_non_absolute_codex_home_is_never_read(monkeypatch, tmp_path, value):
    # Control first: the value names a real, readable cache from this cwd (and, for `~`,
    # from this $HOME), so the refusal below cannot pass by the file merely being missing.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "codexhome").mkdir()
    (tmp_path / "codexhome" / "models_cache.json").write_text(
        json.dumps({"models": [{"slug": "from-cache"}]})
    )
    assert _reader(monkeypatch, tmp_path / "codexhome").read().source == "cache"
    assert (tmp_path / value.replace("~", str(tmp_path))).resolve() == tmp_path / "codexhome"

    monkeypatch.setenv("CODEX_HOME", value)
    assert models.codex_home() is None
    assert models.CodexModels(cc.load_config({})).read().source == "static"
    error = cc.codex_home_error({"CODEX_HOME": value})
    assert error is not None and "CODEX_HOME" in error and value not in error


def test_no_static_fallback_reports_none(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(contract, "KNOWN_MODEL_SLUGS", ())
    listing = models.CodexModels(cc.load_config({})).read()
    assert listing.source == "none" and listing.models == ()
