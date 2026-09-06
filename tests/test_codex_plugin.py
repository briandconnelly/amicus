"""The plugin factory through the real registry path, and the amicus-side declarations."""

from __future__ import annotations

from tests.support import codexfixtures as cf

from amicus import backends as in_tree
from amicus import registry
from amicus.backends import codex as codex_pkg
from amicus.backends.codex import contract


def test_registry_loads_the_in_tree_codex_plugin(pinned_codex_bin):
    reg = registry.BackendRegistry.load(("codex",), entry_points=())
    assert reg.ids == ("codex",) and reg.unavailable == {}
    plugin = reg.get("codex")
    assert plugin is not None and plugin.contract is contract.CONTRACT
    assert plugin.effects == in_tree.KNOWN_EFFECTS["codex"]
    assert plugin.contract.display_name == in_tree.KNOWN_DISPLAY_NAMES["codex"]
    assert plugin.env.prefix == contract.CONTRACT.env_prefix
    assert "user_config_rejected" in plugin.local_codes
    assert "codex exec" not in plugin.egress and "codex exec" not in plugin.carriers
    assert "OpenAI" in plugin.egress and "developer_instructions" in plugin.carriers


def test_options_carry_defaults_and_applicability(pinned_codex_bin):
    plugin, _ = cf.make_backend(
        {"AMICUS_CODEX_ISOLATION": "ignore-rules", "AMICUS_CODEX_MODEL": "m"}
    )
    by_name = {o.name: o for o in plugin.options}
    assert by_name["isolation"].default == "ignore-rules"
    assert by_name["isolation"].applies_to == frozenset({"consult", "review_changes", "delegate"})
    assert by_name["model"].default == "m" and by_name["reasoning_effort"].default is None


def test_plugin_factory_reads_the_process_env_by_default(pinned_codex_bin, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", "/CODEX")
    monkeypatch.setenv("AMICUS_CODEX_MODEL", "from-env")
    plugin = codex_pkg.plugin()
    assert {o.name: o.default for o in plugin.options}["model"] == "from-env"
    assert plugin.help_probe.help_argv == ("/CODEX", "exec", "--help")
