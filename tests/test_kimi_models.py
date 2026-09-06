"""The live model catalog: allowlist-shaped parsing, shape-only effort tokens, the probe."""

from __future__ import annotations

import json

from pontonier.core.runtime import BINARY_NOT_FOUND, CommandRun

from amicus.backends.kimi import binary as kb
from amicus.backends.kimi import config as kc
from amicus.backends.kimi import models

PAYLOAD = {
    "providers": {"p1": {"apiKey": "sk-" + "s" * 40, "baseUrl": "https://private.example"}},
    "models": {
        "k3": {
            "displayName": "Kimi K3",
            "defaultEffort": "medium",
            "supportEfforts": ["low", "medium", "high", "xhigh", "not valid!"],
            "provider": "p1",
        },
        "bare": {},
        "bad alias!": {"supportEfforts": ["low"]},
        "empty": {"supportEfforts": []},
    },
}


def test_parse_catalog_reads_only_named_model_fields():
    entries = models.parse_catalog(PAYLOAD)
    assert entries is not None
    by_slug = {e.slug: e for e in entries}
    assert set(by_slug) == {"k3", "bare", "empty"}
    assert by_slug["k3"].display_name == "Kimi K3"
    assert by_slug["k3"].default_reasoning_effort == "medium"
    assert by_slug["k3"].supported_reasoning_efforts == ("low", "medium", "high", "xhigh")
    assert by_slug["bare"].supported_reasoning_efforts is None
    assert by_slug["empty"].supported_reasoning_efforts == ()
    assert "sk-" not in repr(entries) and "private.example" not in repr(entries)


def test_parse_catalog_returns_none_on_drift():
    assert models.parse_catalog([]) is None
    assert models.parse_catalog({"models": []}) is None
    assert models.parse_catalog({"models": {}}) is None
    parsed = models.parse_catalog({"models": {"k": {"supportEfforts": ["!!"]}}})
    assert parsed[0].supported_reasoning_efforts is None


def test_supported_efforts_for_none_means_cannot_tell():
    listing = models.ModelListing(models=tuple(models.parse_catalog(PAYLOAD) or ()), source="live")
    assert models.supported_efforts_for("k3", listing) == ("low", "medium", "high", "xhigh")
    assert models.supported_efforts_for("bare", listing) is None
    assert models.supported_efforts_for("unlisted", listing) is None
    assert models.supported_efforts_for(None, listing) is None
    assert models.supported_efforts_for("empty", listing) == ()


def _reader(monkeypatch, stdout, exit_code=0, binary_missing=False):
    calls = []

    def fake(cmd, timeout_seconds, **k):
        calls.append(cmd)
        if binary_missing:
            return CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
        return CommandRun(stdout, "", exit_code, 1, False)

    monkeypatch.setattr(models.runtime, "run_sync_capture", fake)
    cfg = kc.load_config({"AMICUS_KIMI_BIN": "/KIMI"})
    return models.KimiModels(cfg, kb.KimiBinary(cfg)), calls


def test_read_probes_live_and_caches(pinned_kimi_bin, monkeypatch):
    reader, calls = _reader(monkeypatch, json.dumps(PAYLOAD))
    listing = reader.read()
    assert listing.source == "live" and [m.slug for m in listing.models] == ["k3", "bare", "empty"]
    assert calls == [["/KIMI", "provider", "list", "--json"]]
    assert reader.read().source == "live" and len(calls) == 1
    assert reader.read(force=True).source == "live" and len(calls) == 2


def test_read_reports_none_when_the_probe_fails(pinned_kimi_bin, monkeypatch):
    assert _reader(monkeypatch, "", exit_code=1)[0].read().source == "none"
    assert _reader(monkeypatch, "not json")[0].read().source == "none"
    assert _reader(monkeypatch, "x" * 2_000_000)[0].read().source == "none"
    assert _reader(monkeypatch, "", binary_missing=True)[0].read().source == "none"
    unresolved = models.KimiModels(kc.load_config({}), kb.KimiBinary(kc.load_config({})))
    assert unresolved.read().source == "none"
