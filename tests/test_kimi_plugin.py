"""The plugin factory through the real registry path, and the amicus-side declarations."""

from __future__ import annotations

from tests.support import kimifixtures as kf

from amicus import backends as in_tree
from amicus import registry
from amicus.backends import kimi as kimi_pkg
from amicus.backends.kimi import contract


def test_registry_loads_the_in_tree_kimi_plugin(pinned_kimi_bin):
    reg = registry.BackendRegistry.load(("kimi",), entry_points=())
    assert reg.ids == ("kimi",) and reg.unavailable == {}
    plugin = reg.get("kimi")
    assert plugin is not None and plugin.contract is contract.CONTRACT
    assert plugin.effects == in_tree.KNOWN_EFFECTS["kimi"]
    assert plugin.contract.display_name == in_tree.KNOWN_DISPLAY_NAMES["kimi"]
    assert plugin.env.prefix == contract.CONTRACT.env_prefix and plugin.local_codes == {}
    for phrase in contract.FORBIDDEN_SURFACE_PHRASES:
        assert phrase not in plugin.egress and phrase not in plugin.carriers
    assert "Kimi provider" in plugin.egress and "handshake" in plugin.carriers
    assert "instructions_append" in plugin.carriers and "stdin" in plugin.carriers


def test_options_carry_defaults_and_applicability(pinned_kimi_bin):
    plugin, _ = kf.make_backend(
        {"AMICUS_KIMI_ISOLATION": "ignore-skills", "AMICUS_KIMI_MODEL": "m"}
    )
    by_name = {o.name: o for o in plugin.options}
    assert by_name["isolation"].default == "ignore-skills"
    assert by_name["isolation"].applies_to == frozenset({"consult", "review_changes", "delegate"})
    assert by_name["model"].default == "m" and by_name["reasoning_effort"].default is None


def test_plugin_factory_reads_the_process_env_by_default(pinned_kimi_bin, monkeypatch):
    monkeypatch.setenv("AMICUS_KIMI_BIN", "/KIMI")
    monkeypatch.setenv("AMICUS_KIMI_MODEL", "from-env")
    plugin = kimi_pkg.plugin()
    assert {o.name: o.default for o in plugin.options}["model"] == "from-env"
    assert plugin.help_probe.help_argv == ("/KIMI", "--help")
    assert plugin.help_probe.always_send_flags == contract.ALWAYS_SEND_FLAGS


def test_kimi_loads_beside_the_other_in_tree_plugins():
    reg = registry.BackendRegistry.load(("codex", "kimi", "claude"), entry_points=())
    assert set(reg.ids) == {"codex", "kimi", "claude"} and reg.unavailable == {}
