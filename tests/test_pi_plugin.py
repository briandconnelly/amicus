"""The pi plugin factory through the real registry path, the amicus-side declarations, and one
spend-free run end to end: MCP client → sync tool → worker → real pi plugin → the fake pi."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client
from tests.conftest import NEVER_SPAWN_PI

from amicus import backends as in_tree
from amicus import config, registry, server
from amicus.backends import pi as pi_pkg
from amicus.backends.pi import contract
from amicus.jobs import lifecycle
from amicus.sdk.testing import conformance

MODEL = "openrouter/moonshotai/kimi-k3"


def test_registry_loads_the_in_tree_pi_plugin(fake_pi, monkeypatch):
    monkeypatch.setenv("AMICUS_PI_BIN", str(fake_pi))
    monkeypatch.setenv("AMICUS_PI_MODEL", MODEL)
    reg = registry.BackendRegistry.load(("pi",), entry_points=())
    assert reg.ids == ("pi",) and reg.unavailable == {}
    plugin = reg.get("pi")
    assert plugin is not None and plugin.contract is contract.CONTRACT
    assert plugin.effects == in_tree.KNOWN_EFFECTS["pi"]
    assert plugin.contract.display_name == in_tree.KNOWN_DISPLAY_NAMES["pi"]
    assert plugin.env.prefix == contract.CONTRACT.env_prefix and plugin.local_codes == {}


def test_plugin_passes_the_conformance_kit(fake_pi):
    plugin = pi_pkg.plugin({"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": MODEL})
    assert conformance.check_contract(plugin.contract) == []
    assert conformance.check_backend(plugin.contract, plugin.backend) == []


def test_disclosures_and_vocabulary():
    plugin = pi_pkg.plugin({"AMICUS_PI_BIN": NEVER_SPAWN_PI})
    for phrase in contract.CONTRACT.forbidden_surface_phrases:
        assert phrase not in plugin.egress and phrase not in plugin.carriers
    assert plugin.egress == contract.EGRESS and plugin.carriers == contract.CARRIERS
    assert "stdin" in plugin.carriers and "--no-session" in plugin.carriers
    assert plugin.vocabulary.backend_id == "pi" and plugin.vocabulary.display_name == "Pi"
    assert "https://pi.dev" in plugin.vocabulary.install_hint
    assert plugin.vocabulary.login_hint == contract.LOGIN_HINT
    assert plugin.vocabulary.status_tool == "amicus_backends"


def test_options_carry_the_configured_defaults():
    plugin = pi_pkg.plugin(
        {
            "AMICUS_PI_BIN": NEVER_SPAWN_PI,
            "AMICUS_PI_MODEL": MODEL,
            "AMICUS_PI_REASONING_EFFORT": "high",
        }
    )
    by_name = {o.name: o for o in plugin.options}
    assert set(by_name) == {"model", "reasoning_effort"}
    assert by_name["model"].default == MODEL and by_name["reasoning_effort"].default == "high"


def test_plugin_factory_reads_the_process_env_by_default(fake_pi, monkeypatch):
    monkeypatch.setenv("AMICUS_PI_BIN", str(fake_pi))
    monkeypatch.setenv("AMICUS_PI_MODEL", MODEL)
    plugin = pi_pkg.plugin()
    assert {o.name: o.default for o in plugin.options}["model"] == MODEL
    assert plugin.help_probe.help_argv == (str(fake_pi), *contract.HELP_ARGS)
    assert plugin.help_probe.always_send_flags == contract.ALWAYS_SEND_FLAGS


def test_unusable_override_still_builds_a_plugin_that_probes_that_value():
    plugin = pi_pkg.plugin({"AMICUS_PI_BIN": "/nonexistent/pi"})
    assert plugin.binary.resolve() is None
    assert plugin.help_probe.help_argv[0] == "/nonexistent/pi"


def test_pi_loads_beside_the_other_in_tree_plugins():
    reg = registry.BackendRegistry.load(("codex", "kimi", "claude", "pi"), entry_points=())
    assert set(reg.ids) == {"codex", "kimi", "claude", "pi"} and reg.unavailable == {}


# --- end to end against the fake pi ----------------------------------------------------------


@pytest.fixture
def app(tmp_path, fake_pi, monkeypatch):
    monkeypatch.setenv("AMICUS_PI_BIN", str(fake_pi))
    monkeypatch.setenv("AMICUS_PI_MODEL", MODEL)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_PI_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_PI_STDIN_FILE", str(tmp_path / "stdin.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in ("FAKE_PI_AUTH", "FAKE_PI_EVENTS", "FAKE_PI_ANSWER", "FAKE_PI_EXIT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    return server.create_app(settings, registry.BackendRegistry.load(("pi",), entry_points=()))


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t.co"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)
    (r / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=r, check=True, capture_output=True)
    return r


async def test_consult_end_to_end_keeps_the_prompt_on_stdin(app, tmp_path, repo):
    question = "why does the lock canary 7f3e matter?"
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "pi", "question": question, "workspace_root": str(repo)},
            raise_on_error=False,
        )
    env = res.structured_content
    assert env is not None and env["ok"] is True, env
    assert env["summary"] == "Looks fine" and env["meta"]["backend"] == "pi"
    assert env["meta"]["usage"]["total_tokens"] == 160
    [argv] = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    assert argv[argv.index("--model") + 1] == MODEL
    assert argv[argv.index("--tools") + 1] == ",".join(contract.READ_ONLY_TOOLS)
    assert not any("7f3e" in token for token in argv)
    assert "7f3e" in (tmp_path / "stdin.txt").read_text()
