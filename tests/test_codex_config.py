"""AMICUS_CODEX_* namespace, extra-args allowlist, and the codex argv policy helpers."""

from __future__ import annotations

import pytest

from amicus.backends.codex import config as cc


def test_load_config_defaults(clean_env):
    cfg = cc.load_config({})
    assert cfg.bin_override is None
    assert cfg.model is None and cfg.reasoning_effort is None
    assert cfg.isolation == "inherit"
    assert cfg.extra_args.configured is False and cfg.extra_args.valid
    assert (0, 153) in cfg.supported_versions
    assert cfg.warnings == () and cfg.errors == ()


def test_load_config_reads_amicus_then_legacy_with_a_warning(clean_env):
    cfg = cc.load_config(
        {"CODEX_IN_CLAUDE_MODEL": "gpt-5.5", "AMICUS_CODEX_ISOLATION": "ignore-rules"}
    )
    assert cfg.model == "gpt-5.5" and cfg.isolation == "ignore-rules"
    assert any(
        "AMICUS_CODEX_MODEL read from legacy CODEX_IN_CLAUDE_MODEL" in w for w in cfg.warnings
    )
    conflict = cc.load_config({"AMICUS_CODEX_MODEL": "a", "CODEX_IN_CLAUDE_MODEL": "b"})
    assert conflict.model == "a" and any("different values" in e for e in conflict.errors)


def test_invalid_isolation_default_falls_back_with_a_warning(clean_env):
    cfg = cc.load_config({"AMICUS_CODEX_ISOLATION": "nope"})
    assert cfg.isolation == "inherit"
    assert any("AMICUS_CODEX_ISOLATION" in w for w in cfg.warnings)


def test_supported_versions_override_and_fallback(clean_env):
    assert cc.load_config({"AMICUS_CODEX_SUPPORTED_VERSIONS": "0.150, 1.2"}).supported_versions == {
        (0, 150),
        (1, 2),
    }
    assert (
        cc.load_config({"AMICUS_CODEX_SUPPORTED_VERSIONS": "x.y"}).supported_versions
        == cc.contract.SUPPORTED_VERSIONS
    )


def test_version_parsing_and_support():
    cfg = cc.load_config({})
    assert cc.parse_version("codex-cli 0.153.4") == (0, 153)
    assert cc.parse_version(None) is None and cc.parse_version("garbage") is None
    assert cc.version_supported("codex-cli 0.153.4", cfg) is True
    assert cc.version_supported("codex-cli 0.100.0", cfg) is False
    assert cc.version_supported("?", cfg) is None


def test_sandbox_for_kind_and_isolation_flags():
    assert cc.sandbox_for_kind("consult") == "read-only"
    assert cc.sandbox_for_kind("review_changes") == "read-only"
    assert cc.sandbox_for_kind("delegate") == "workspace-write"
    assert cc.isolation_flags("inherit") == []
    assert cc.isolation_flags("ignore-config") == ["--ignore-user-config"]
    assert cc.isolation_flags("ignore-rules") == ["--ignore-user-config", "--ignore-rules"]
    with pytest.raises(ValueError):
        cc.isolation_flags("bogus")


@pytest.mark.parametrize("value", ["high", "", "xhigh", "medium-ish", "h" * 128])
def test_reasoning_effort_shape_accepts(value):
    assert cc.reasoning_effort_shape_error(value) is None


@pytest.mark.parametrize(
    ("value", "fragment"),
    [("h" * 129, "exceeds"), ("hi\x00", "control"), ("hi\n", "control"), ("\ud800", "surrogate")],
)
def test_reasoning_effort_shape_rejects(value, fragment):
    reason = cc.reasoning_effort_shape_error(value)
    assert reason is not None and fragment in reason


def test_extra_args_allowlist_and_descriptors():
    ea = cc.parse_extra_args('-c model_provider=azure --profile work --enable "feature_x"')
    assert ea.valid and ea.configured and ea.option_count == 3
    assert ea.tokens == ("-c", "model_provider=azure", "--profile", "work", "--enable", "feature_x")
    assert ea.config_keys == ("model_provider",) and ea.profile_names == ("work",)
    assert ea.owns_config_key("model_provider") and ea.owns_config_key("Model_Provider.child")
    assert not ea.owns_config_key("model_providerx")
    assert ea.owns_profile_file("/home/u/.codex/work.config.toml")
    assert not ea.owns_profile_file("/home/u/.codex/config.toml")
    attached = cc.parse_extra_args("--config=model_provider=x")
    assert attached.tokens == ("--config", "model_provider=x")


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("--bogus 1", "unsupported argument"),
        ("model_provider=x", "unsupported argument"),
        ("-c", "requires a value"),
        ("-c model_provider", "expects KEY=VALUE"),
        ("-c --sneaky", "looks like a flag"),
        ("-cmodel_provider=x", "unsupported argument"),
        ("-c sandbox_mode=x", "refused"),
        ("-c 'approval_policy'=x", "refused"),
        ("-c shell_environment_policy.inherit=all", "refused"),
        ("-c features.remote_plugin=true", "remote_plugin"),
        ("-c features={remote_plugin=true}", "features table"),
        ("--enable sleep_tool", "sleep_tool"),
        ("--disable remote_plugin", "remote_plugin"),
        ("-c model=gpt-5.5", "reserved"),
        ("-c model_reasoning_effort=high", "reserved"),
        ("-c developer_instructions=x", "instructions_append"),
        ("-c model_instructions_file=/x", "replace or redefine"),
        ('-c "unbalanced', "tokenize"),
    ],
)
def test_extra_args_refusals(raw, fragment):
    ea = cc.parse_extra_args(raw)
    assert not ea.valid and ea.configured
    assert fragment in (ea.error or "")


def test_extra_args_refusal_never_echoes_a_secret_value():
    secret = "sk-" + "z" * 40
    ea = cc.parse_extra_args(f"-c sandbox_mode={secret}")
    assert secret not in (ea.error or "")


@pytest.mark.parametrize(
    "raw", ["-c features.sleep_toolbox.mode=x", "-c features.other=true", "-c model_verbosity=high"]
)
def test_extra_args_allows_near_misses(raw):
    assert cc.parse_extra_args(raw).valid


def test_ownership_is_false_when_unconfigured_or_invalid():
    assert not cc.ExtraArgs().owns_config_key("anything")
    bad = cc.parse_extra_args("--bogus 1")
    assert not bad.owns_config_key("model_provider") and not bad.owns_profile_file(
        "/x/work.config.toml"
    )
