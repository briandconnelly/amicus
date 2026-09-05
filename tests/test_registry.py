"""BackendRegistry never raises on a bad backend; every failure is recorded."""

from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest
from tests.support import fakeplugin

from amicus import backends, registry
from amicus.plugin import ENTRY_POINT_GROUP


def _ep(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)


def test_in_tree_declarations():
    assert set(backends.IN_TREE) == {"codex", "kimi", "claude"}
    assert backends.IN_TREE["codex"] == "amicus.backends.codex:plugin"
    assert backends.KNOWN_EFFECTS["claude"].paid_calls_destructive is True
    assert backends.KNOWN_EFFECTS["codex"].paid_calls_destructive is False
    assert all(e.job_reads_read_only for e in backends.KNOWN_EFFECTS.values())
    assert backends.KNOWN_DISPLAY_NAMES["claude"] == "Claude Code"


def test_default_load_records_the_unported_in_tree_backends_as_unavailable():
    reg = registry.BackendRegistry.load(("codex", "kimi", "claude"), entry_points=())
    assert reg.available == {}
    assert set(reg.unavailable) == {"codex", "kimi", "claude"}
    assert reg.unavailable["codex"].reason == "import_failed"
    assert "amicus.backends.codex" in reg.unavailable["codex"].detail
    assert reg.get("codex") is None
    assert reg.ids == ()


def test_entry_point_plugin_loads_through_the_real_path():
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={}, entry_points=(_ep("fake", "tests.support.fakeplugin:plugin"),)
    )
    assert reg.ids == ("fake",)
    assert reg.get("fake") is fakeplugin.plugin
    assert reg.unavailable == {}


def test_factory_callables_are_called():
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:make_plugin"}, entry_points=()
    )
    assert reg.get("fake") is not None


def test_not_enabled_entry_points_are_ignored():
    reg = registry.BackendRegistry.load(
        ("codex",), in_tree={}, entry_points=(_ep("fake", "tests.support.fakeplugin:plugin"),)
    )
    assert reg.ids == () and reg.unavailable["codex"].reason == "not_installed"


def test_in_tree_ids_are_reserved_against_entry_points():
    reg = registry.BackendRegistry.load(
        ("codex",), in_tree={}, entry_points=(_ep("codex", "tests.support.fakeplugin:plugin"),)
    )
    assert reg.get("codex") is None
    assert reg.unavailable["codex"].reason == "reserved_id"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"api_version": 2}, "api_version"),
        ({"contract": fakeplugin.make_contract("other")}, "id_mismatch"),
    ],
)
def test_bad_plugins_are_recorded_not_raised(monkeypatch, override, reason):
    bad = fakeplugin.make_plugin(**override)
    monkeypatch.setattr(fakeplugin, "bad", bad, raising=False)
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:bad"}, entry_points=()
    )
    assert reg.get("fake") is None
    assert reg.unavailable["fake"].reason == reason


def test_contract_and_backend_conformance_failures_are_recorded(monkeypatch):
    # A contract whose own prose contains a phrase it bans fails check_contract.
    import dataclasses

    contract = dataclasses.replace(
        fakeplugin.make_contract(),
        readonly_honesty_statement="applies the diff to your working tree",
    )
    monkeypatch.setattr(
        fakeplugin, "bad_contract", fakeplugin.make_plugin(contract=contract), raising=False
    )
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:bad_contract"}, entry_points=()
    )
    assert reg.unavailable["fake"].reason == "contract_violation"
    assert "forbidden phrase" in reg.unavailable["fake"].detail

    # A backend that is not structurally an AgentBackend fails check_backend.
    monkeypatch.setattr(
        fakeplugin, "bad_backend", fakeplugin.make_plugin(backend=object()), raising=False
    )
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:bad_backend"}, entry_points=()
    )
    assert reg.unavailable["fake"].reason == "backend_violation"


def test_a_factory_that_raises_is_recorded():
    def boom():
        raise RuntimeError("no config")

    import tests.support.fakeplugin as fp

    fp.boom = boom  # type: ignore[attr-defined]
    try:
        reg = registry.BackendRegistry.load(
            ("fake",), in_tree={"fake": "tests.support.fakeplugin:boom"}, entry_points=()
        )
    finally:
        del fp.boom  # type: ignore[attr-defined]
    assert reg.unavailable["fake"].reason == "load_failed"
    assert "RuntimeError" in reg.unavailable["fake"].detail


def test_wrong_type_is_recorded():
    import tests.support.fakeplugin as fp

    fp.not_a_plugin = 42  # type: ignore[attr-defined]
    try:
        reg = registry.BackendRegistry.load(
            ("fake",), in_tree={"fake": "tests.support.fakeplugin:not_a_plugin"}, entry_points=()
        )
    finally:
        del fp.not_a_plugin  # type: ignore[attr-defined]
    assert reg.unavailable["fake"].reason == "load_failed"


def test_load_reads_installed_entry_points_by_default(monkeypatch):
    monkeypatch.setattr(
        registry, "_entry_points", lambda: (_ep("fake", "tests.support.fakeplugin:plugin"),)
    )
    reg = registry.BackendRegistry.load(("fake",), in_tree={})
    assert reg.ids == ("fake",)
