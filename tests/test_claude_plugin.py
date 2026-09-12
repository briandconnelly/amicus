"""The plugin factory through the real registry path, and the amicus-side declarations."""

from __future__ import annotations

from tests.support import claudefixtures as cf

from amicus import backends as in_tree
from amicus import registry
from amicus.backends import claude as claude_pkg
from amicus.backends.claude import adversarial, contract


def test_registry_loads_the_in_tree_claude_plugin(pinned_claude_bin):
    reg = registry.BackendRegistry.load(("claude",), entry_points=())
    assert reg.ids == ("claude",) and reg.unavailable == {}
    plugin = reg.get("claude")
    assert plugin is not None and plugin.contract is contract.CONTRACT
    assert plugin.effects == in_tree.KNOWN_EFFECTS["claude"]
    assert plugin.effects.paid_calls_destructive is True
    assert plugin.contract.display_name == in_tree.KNOWN_DISPLAY_NAMES["claude"]
    assert plugin.env.prefix == contract.CONTRACT.env_prefix
    assert set(plugin.local_codes) == {
        "budget_exceeded",
        "claude_permission_error",
        "api_key_invalid",
        "api_key_missing",
    }
    assert set(plugin.repair_overrides) == {"timeout"}
    assert plugin.repair_overrides["timeout"].temporary is False
    assert plugin.repair_overrides["timeout"].next_step == "start_new_job"
    assert isinstance(plugin.framing, adversarial.ClaudeFraming)
    for phrase in contract.FORBIDDEN_SURFACE_PHRASES:
        assert phrase not in plugin.egress and phrase not in plugin.carriers
    assert "Anthropic" in plugin.egress and "stdin" in plugin.carriers
    assert "instructions_append" in plugin.carriers and "--append-system-prompt" in plugin.carriers
    assert "constant" in plugin.carriers


def test_options_carry_defaults_and_applicability(pinned_claude_bin):
    plugin, _ = cf.make_backend(
        {
            "AMICUS_CLAUDE_CONFIG_MODE": "safe",
            "AMICUS_CLAUDE_MODEL": "opus",
            "AMICUS_CLAUDE_MAX_BUDGET_USD": "0.5",
        }
    )
    by_name = {o.name: o for o in plugin.options}
    assert set(by_name) == {"config_mode", "access", "max_budget_usd", "model", "reasoning_effort"}
    assert by_name["config_mode"].default == "safe" and by_name["access"].default == "toolless"
    assert by_name["max_budget_usd"].default == 0.5 and by_name["model"].default == "opus"
    assert by_name["reasoning_effort"].default == "xhigh"
    for spec in plugin.options:
        if spec.name == "config_mode":
            assert spec.applies_to in (
                frozenset({"consult", "review_changes"}),
                frozenset({"adversarial_review"}),
            )
        else:
            assert spec.applies_to == frozenset({"consult", "review_changes", "adversarial_review"})
        assert "delegate" not in spec.applies_to


def test_plugin_factory_reads_the_process_env_by_default(pinned_claude_bin, monkeypatch):
    monkeypatch.setenv("AMICUS_CLAUDE_BIN", "/CLAUDE")
    monkeypatch.setenv("AMICUS_CLAUDE_MODEL", "from-env")
    plugin = claude_pkg.plugin()
    assert {o.name: o.default for o in plugin.options}["model"] == "from-env"
    assert plugin.help_probe.help_argv == ("/CLAUDE", "--help")
    assert plugin.help_probe.always_send_flags == contract.ALWAYS_SEND_FLAGS


def test_all_three_in_tree_plugins_load_together_with_the_guards_in_place():
    reg = registry.BackendRegistry.load(("codex", "kimi", "claude"), entry_points=())
    assert set(reg.ids) == {"codex", "kimi", "claude"} and reg.unavailable == {}
    for backend_id in reg.ids:
        plugin = reg.get(backend_id)
        assert plugin is not None
        seen: dict[str, set[str]] = {}
        fields: dict[str, str] = {}
        for option in plugin.options:
            assert not seen.setdefault(option.name, set()) & option.applies_to
            seen[option.name].update(option.applies_to)
            assert fields.setdefault(option.name, option.maps_to) == option.maps_to
