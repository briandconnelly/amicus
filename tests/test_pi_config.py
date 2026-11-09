"""AMICUS_PI_* resolution: namespace, defaults, model shape, versions, options."""

from __future__ import annotations

from amicus.backends.pi import config as pc
from amicus.backends.pi import contract
from amicus.backends.pi.options import options_for


def test_namespace_declares_four_settings_and_no_tombstones():
    names = pc.ENV.names()
    assert names == (
        "AMICUS_PI_BIN",
        "AMICUS_PI_MODEL",
        "AMICUS_PI_REASONING_EFFORT",
        "AMICUS_PI_SUPPORTED_VERSIONS",
    )
    assert all(pc.ENV.var(n).legacy == () and pc.ENV.var(n).removed == () for n in names)
    assert pc.ENV.prefix == contract.CONTRACT.env_prefix


def test_defaults_and_state_dir(tmp_path):
    cfg = pc.load_config({"AMICUS_STATE_DIR": str(tmp_path / "state")})
    assert cfg.bin_override is None and cfg.model is None and cfg.reasoning_effort is None
    assert cfg.supported_versions == contract.SUPPORTED_VERSIONS
    assert cfg.state_dir == tmp_path / "state" and cfg.warnings == () and cfg.errors == ()


def test_values_are_read():
    cfg = pc.load_config(
        {
            "AMICUS_PI_BIN": "/x/pi",
            "AMICUS_PI_MODEL": "anthropic/claude-x",
            "AMICUS_PI_REASONING_EFFORT": "high",
        }
    )
    assert cfg.bin_override == "/x/pi" and cfg.model == "anthropic/claude-x"
    assert cfg.reasoning_effort == "high" and cfg.warnings == ()


def test_model_without_a_slash_warns():
    cfg = pc.load_config({"AMICUS_PI_MODEL": "kimi-k3"})
    assert cfg.model == "kimi-k3"
    assert any("provider/id" in w for w in cfg.warnings)
    assert not any("kimi-k3" in w for w in cfg.warnings)


def test_supported_versions_and_version_parsing():
    cfg = pc.load_config({"AMICUS_PI_SUPPORTED_VERSIONS": "1.5, 2.0"})
    assert cfg.supported_versions == frozenset({(1, 5), (2, 0)})
    assert pc.load_config({"AMICUS_PI_SUPPORTED_VERSIONS": "x"}).supported_versions == (
        contract.SUPPORTED_VERSIONS
    )
    assert pc.parse_version("1.5.0") == (1, 5) and pc.parse_version("pi 1.5.2\n") == (1, 5)
    assert pc.parse_version("nope") is None and pc.parse_version(None) is None
    assert pc.version_supported("1.5.0", cfg) is True
    assert pc.version_supported("1.4.0", cfg) is False
    assert pc.version_supported(None, cfg) is None


def test_no_isolation_option():
    assert {o.name for o in options_for(pc.load_config({}))} == {"model", "reasoning_effort"}


def test_options_carry_defaults_and_verbs():
    cfg = pc.load_config({"AMICUS_PI_MODEL": "a/b", "AMICUS_PI_REASONING_EFFORT": "low"})
    opts = {o.name: o for o in options_for(cfg)}
    assert opts["model"].default == "a/b" and opts["reasoning_effort"].default == "low"
    for o in opts.values():
        assert set(o.applies_to) == {"consult", "review_changes", "delegate"}
