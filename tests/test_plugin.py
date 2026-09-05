"""The plugin API: pure data plus runtime-checkable capability protocols."""

from __future__ import annotations

import dataclasses

from tests.support import fakeplugin

from amicus import plugin as p


def test_constants():
    assert p.PLUGIN_API_VERSION == 1
    assert p.ENTRY_POINT_GROUP == "amicus.backends"


def test_fake_plugin_is_a_complete_plugin():
    fp = fakeplugin.make_plugin()
    assert fp.backend_id == "fake"
    assert fp.api_version == 1
    assert isinstance(fp.status, p.StatusProbe)
    assert isinstance(fp.models, p.ModelCatalogReader)
    assert isinstance(fp.binary, p.BinaryResolver)
    assert fp.framing is None and fp.repair_overrides == {} and fp.local_codes == {}
    assert fp.egress == "" and fp.carriers == ""


def test_plugin_is_frozen():
    fp = fakeplugin.make_plugin()
    try:
        fp.api_version = 2  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("BackendPlugin must be frozen")


def test_option_spec_and_status_report_defaults():
    spec = p.OptionSpec("isolation", "isolation", frozenset({"consult"}))
    assert spec.default is None
    rep = p.StatusReport(installed=False)
    assert (rep.version, rep.authenticated, rep.warnings) == (None, None, ())
    listing = p.ModelListing(models=(), source="none")
    assert listing.fetched_at is None
