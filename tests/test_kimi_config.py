"""AMICUS_KIMI_* resolution: legacy shim, isolation default, refused extra args, versions."""

from __future__ import annotations

from pathlib import Path

from amicus.backends.kimi import config as kc
from amicus.backends.kimi import contract


def test_namespace_declares_the_six_settings_with_legacy_twins():
    names = kc.ENV.names()
    assert names == (
        "AMICUS_KIMI_BIN",
        "AMICUS_KIMI_EXTRA_ARGS",
        "AMICUS_KIMI_MODEL",
        "AMICUS_KIMI_REASONING_EFFORT",
        "AMICUS_KIMI_ISOLATION",
        "AMICUS_KIMI_SUPPORTED_VERSIONS",
    )
    assert kc.ENV.var("AMICUS_KIMI_BIN").legacy == ()
    assert kc.ENV.var("AMICUS_KIMI_MODEL").legacy == ("MOONBRIDGE_MODEL",)
    assert kc.ENV.prefix == contract.CONTRACT.env_prefix


def test_defaults_and_state_dir(tmp_path):
    cfg = kc.load_config({"AMICUS_STATE_DIR": str(tmp_path / "state")})
    assert cfg.bin_override is None and cfg.model is None and cfg.reasoning_effort is None
    assert cfg.isolation == "inherit" and cfg.supported_versions == contract.SUPPORTED_VERSIONS
    assert cfg.state_dir == tmp_path / "state" and cfg.warnings == () and cfg.errors == ()
    assert not cfg.extra_args.configured and cfg.extra_args.valid


def test_legacy_names_are_read_with_a_warning_and_conflicts_are_errors():
    cfg = kc.load_config({"MOONBRIDGE_MODEL": "k3", "MOONBRIDGE_ISOLATION": "ignore-skills"})
    assert cfg.model == "k3" and cfg.isolation == "ignore-skills"
    assert any("read from legacy MOONBRIDGE_MODEL" in w for w in cfg.warnings)
    conflict = kc.load_config({"AMICUS_KIMI_MODEL": "a", "MOONBRIDGE_MODEL": "b"})
    assert conflict.model == "a" and any("different values" in e for e in conflict.errors)


def test_bad_isolation_warns_and_falls_back():
    cfg = kc.load_config({"AMICUS_KIMI_ISOLATION": "ignore-config"})
    assert cfg.isolation == "inherit"
    assert any("AMICUS_KIMI_ISOLATION" in w and "ignore-skills" in w for w in cfg.warnings)


def test_extra_args_are_always_refused_with_the_reason():
    refused = kc.parse_extra_args("-p secret-prompt")
    assert refused.configured and not refused.valid and refused.tokens == ()
    assert refused.error is not None
    assert "unsupported argument: -p" in refused.error and "prompt flag" in refused.error
    assert "secret-prompt" not in refused.error
    assert kc.parse_extra_args("'unbalanced").error == "could not tokenize (unbalanced quotes?)"
    assert kc.parse_extra_args("   ").error == "no options found"
    assert kc.load_config({"AMICUS_KIMI_EXTRA_ARGS": "--model x"}).extra_args.valid is False
    assert kc.load_config({"AMICUS_KIMI_EXTRA_ARGS": ""}).extra_args.configured is False


def test_supported_versions_and_version_parsing():
    cfg = kc.load_config({"AMICUS_KIMI_SUPPORTED_VERSIONS": "0.41, 1.0"})
    assert cfg.supported_versions == frozenset({(0, 41), (1, 0)})
    assert kc.load_config({"AMICUS_KIMI_SUPPORTED_VERSIONS": "x"}).supported_versions == (
        contract.SUPPORTED_VERSIONS
    )
    assert kc.parse_version("0.41.0") == (0, 41) and kc.parse_version("kimi 1.2.3\n") == (1, 2)
    assert kc.parse_version("nope") is None and kc.parse_version(None) is None
    assert kc.version_supported("0.41.0", cfg) is True
    assert kc.version_supported("0.30.0", cfg) is False
    assert kc.version_supported(None, cfg) is None


def test_skills_dir_for_creates_an_empty_dir_only_for_ignore_skills(tmp_path):
    assert kc.skills_dir_for("inherit", tmp_path) is None
    path = kc.skills_dir_for("ignore-skills", tmp_path)
    assert path == str(tmp_path / "empty-skills") and Path(path).is_dir()
    assert list(Path(path).iterdir()) == []
