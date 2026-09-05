"""The Codex CLI contract: grammars, signatures and the pontonier contract object.

Ported from codex-in-claude `tests/test_cli_contract.py` behaviour; every stderr sample
below is the sibling's captured phrasing."""

from __future__ import annotations

import pytest
from pontonier.testing import conformance

from amicus.backends.codex import contract as c


def test_contract_passes_pontonier_checks_and_names_the_amicus_namespace():
    assert conformance.check_contract(c.CONTRACT) == []
    assert c.CONTRACT.backend_id == "codex"
    assert c.CONTRACT.env_prefix == "AMICUS_CODEX_"
    assert c.CONTRACT.supported_features == frozenset({"delegate", "usage_accounting"})
    assert c.CONTRACT.effort_validation == "shape_only"
    assert c.CONTRACT.exec_argv_prefix == ("exec",)
    assert "--sandbox" in c.CONTRACT.always_send_flags
    assert c.CONTRACT.help_gated_flags == ("--model",)


def test_forbidden_phrases_exclude_sibling_names_but_ban_the_mechanisms_amicus_lacks():
    assert "applies the diff to your working tree" in c.FORBIDDEN_SURFACE_PHRASES
    assert "--dangerously-bypass" in c.FORBIDDEN_SURFACE_PHRASES
    for text in (c.CONTRACT.readonly_honesty_statement, c.CONTRACT.implicit_context_disclosure):
        assert "codex exec" not in text  # amicus's own union ban (tests/test_surface_honesty.py)


def test_disabled_features_are_ordered_and_always_send():
    assert c.MODEL_RUN_DISABLED_FEATURES == ("remote_plugin", "sleep_tool")
    assert c.DISABLE_FEATURE_FLAG in c.ALWAYS_SEND_FLAGS
    assert c.STRICT_CONFIG_FLAG in c.ALWAYS_SEND_FLAGS
    assert not set(c.ALWAYS_SEND_FLAGS) & set(c.HELP_GATED_FLAGS)


def test_plugin_owned_config_keys_are_the_four_pins():
    assert (
        frozenset(
            {
                "model_reasoning_effort",
                "sandbox_workspace_write.network_access",
                "sandbox_workspace_write.writable_roots",
                "developer_instructions",
            }
        )
        == c.PLUGIN_OWNED_CONFIG_KEYS
    )


def test_strict_config_override_grammar():
    text = (
        "Error loading config.toml: unknown configuration field `model_reasoning_effort` "
        "in -c/--config override\n"
    )
    got = c.parse_strict_config_rejection(text)
    assert got == c.StrictConfigRejection(origin="override", key="model_reasoning_effort")


def test_strict_config_file_grammar():
    text = (
        "Error loading config.toml:\n"
        "/home/u/.codex/config.toml:12:3: unknown configuration field `sandbox_mode_x`\n"
    )
    got = c.parse_strict_config_rejection(text)
    assert got is not None
    assert (got.origin, got.key, got.source_path, got.line) == (
        "file",
        "sandbox_mode_x",
        "/home/u/.codex/config.toml",
        12,
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Error: something else",
        (
            "quoted: 'Error loading config.toml: unknown configuration field `k` "
            "in -c/--config override' trailing"
        ),
    ],
)
def test_strict_config_grammar_rejects_non_matches(text):
    assert c.parse_strict_config_rejection(text) is None


def test_retired_setting_grammar_is_exact():
    text = "Error: approval_policy = untrusted is no longer supported; remove this setting\n"
    assert c.parse_unsupported_config_setting(text) == c.UnsupportedConfigSetting(
        key="approval_policy", value="untrusted"
    )
    # A prefix match must not steal the classification.
    assert (
        c.parse_unsupported_config_setting(
            'Error: token = "401 unauthorized is no longer supported" please login\n'
        )
        is None
    )


def test_invalid_value_grammar_both_forms():
    variant = (
        "Error loading config.toml: unknown variant `yolo`, expected one of `a`, `b`\n"
        "in `approval_policy`\n\n"
    )
    got = c.parse_invalid_config_value(variant)
    assert got == c.InvalidConfigValue(
        key="approval_policy", kind="unknown_variant", expected="`a`, `b`"
    )
    typed = (
        'Error loading config.toml: invalid type: string "yes", expected a boolean\n'
        "in `sandbox_workspace_write.network_access`\n\n"
    )
    got = c.parse_invalid_config_value(typed)
    assert got == c.InvalidConfigValue(
        key="sandbox_workspace_write.network_access", kind="invalid_type", expected="a boolean"
    )
    assert c.parse_invalid_config_value("prefix " + typed) is None


def test_signature_predicates():
    assert c.is_contract_drift("error: unexpected argument '--zap' found")
    assert c.is_contract_drift("Error: Unknown feature flag: remote_plugin")
    assert not c.is_contract_drift("all good")
    assert c.is_auth_failure("HTTP 401 Unauthorized")
    assert c.is_rate_limited("Too Many Requests") and c.is_rate_limited("status 429")
    assert not c.is_rate_limited("file429.py")
    assert c.is_reasoning_effort_rejection("[reasoning.effort] [ReasoningEffortParam] bad")
    assert not c.is_reasoning_effort_rejection("reasoning.effort ReasoningEffortParam")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Retry-After: 5", 5000),
        ("try again in 12 seconds", 12000),
        ("retry after 0s", 0),
        ("retry after 5 minutes", None),
        ("Retry-After: Wed, 21 Oct 2026 07:28:00 GMT", None),
        ("nothing", None),
    ],
)
def test_parse_retry_after_ms(text, expected):
    assert c.parse_retry_after_ms(text) == expected


def test_static_catalog_and_version_pins():
    assert "gpt-5.5" in c.KNOWN_MODEL_SLUGS
    assert c.MODEL_SLUG_PATTERN.match("gpt-5.4-mini")
    assert not c.MODEL_SLUG_PATTERN.match("-bad")
    assert (0, 153) in c.SUPPORTED_VERSIONS
    assert c.RATE_LIMIT_DEFAULT_BACKOFF_MS == 60_000
