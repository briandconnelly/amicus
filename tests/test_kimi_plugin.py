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


def test_carriers_disclose_kimis_own_session_store(pinned_kimi_bin):
    """Rule 18 exempts a native carrier only where CARRIERS discloses it (#179). The kimi
    CLI keeps the prompt and answer in its own session store, which nothing amicus owns
    reaches, so every retention control a caller might assume covers it is named as not
    covering it."""
    plugin, _ = kf.make_backend({})
    carriers = " ".join(plugin.carriers.split())
    assert "its own session files" in carriers and "outside amicus's job store" in carriers
    assert "does not delete them" in carriers
    for control in ("AMICUS_JOB_TTL", "AMICUS_JOB_MAX_COUNT", "amicus_job_consume_result"):
        assert control in carriers, f"{control} must be named as not removing them"


def test_read_only_is_scoped_to_the_agents_tools_not_the_cli(pinned_kimi_bin):
    """The read-only profile removes the agent's shell and write tools; the kimi CLI still
    writes its own session files, so "cannot MODIFY anything" overclaimed (#179)."""
    statement = contract.READ_ONLY_CONFIDENTIALITY_LIMIT
    assert "cannot MODIFY anything" not in statement
    assert "no shell or write tool" in statement
    assert "session files" in statement and "`carriers`" in statement
    assert "absolute paths" in statement, "the read-boundary warning must survive"


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
