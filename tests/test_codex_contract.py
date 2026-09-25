"""The Codex CLI contract: grammars, signatures and the pontonier contract object.

Ported from codex-in-claude `tests/test_cli_contract.py` behaviour; every stderr sample
below is the sibling's captured phrasing."""

from __future__ import annotations

import pytest

from amicus.backends.codex import contract as c
from amicus.sdk.testing import conformance


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
    assert c.MODEL_RUN_DISABLED_FEATURES == ("remote_plugin", "sleep_tool", "goals")
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


# Issue #160: the digits 401 inside a token count or an id must not read as "not
# authenticated"; only an HTTP-status 401 or codex's own auth phrasings may.
_USAGE_LIMIT_MESSAGE = (
    "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at "
    "Sep 19th, 2026 8:37 AM."
)


@pytest.mark.parametrize(
    "text",
    [
        '{"usage":{"input_tokens":14012}}',
        "request_id=a401bc",
        "You have hit your usage limit (14010 tokens)",
        "trace 7f-401-9c",
        "src/app.py:401: warning",
        '{"input_tokens":401}',
        '{"status":4012}',
        "status401; usage limit",
        "http401",
        "run codex loginhelper; usage limit",
        _USAGE_LIMIT_MESSAGE,
    ],
)
def test_auth_failure_ignores_401_digits_outside_an_http_status(text):
    assert not c.is_auth_failure(text)


@pytest.mark.parametrize(
    "text",
    [
        "HTTP 401 Unauthorized",
        "unexpected status 401: {}",
        "unexpected status 401 Unauthorized: token expired",
        "http/1.1 401",
        "status code: 401",
        '{"type":"error","message":"401 unauthorized"}',
        '{"status":401}',
        '{"error": {"status_code": 401}}',
        "Not logged in",
        "HTTP/1.1 401",
        "run codex login.",
        "not authenticated; please run `codex login`",
        "Your access token could not be refreshed. Please log out and sign in again.",
        "Your authentication session could not be refreshed automatically. Please log out "
        "and sign in again.",
    ],
)
def test_auth_failure_matches_http_401_and_codex_auth_phrasings(text):
    assert c.is_auth_failure(text)


def test_declared_auth_signatures_agree_with_the_predicate():
    compiled = c.CONTRACT.failure_signatures.compiled()["auth"]
    for text in ("unexpected status 401: {}", "Not logged in", "request_id=a401bc"):
        assert any(p.search(text) for p in compiled) is c.is_auth_failure(text)


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
    # Pinned exactly (the catalog codex-cli 0.156.1 fetched on 2026-09-23, priority order) so a
    # removal or reorder fails.
    assert c.KNOWN_MODEL_SLUGS == (
        "gpt-6-astra",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-reserve",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "codex-auto-review",
    )
    assert all(c.MODEL_SLUG_PATTERN.match(s) for s in c.KNOWN_MODEL_SLUGS)
    assert c.MODEL_SLUG_PATTERN.match("gpt-5.4-mini")
    assert not c.MODEL_SLUG_PATTERN.match("-bad")
    assert {(0, 153), (0, 154), (0, 155), (0, 156), (0, 157)} <= c.SUPPORTED_VERSIONS
    assert c.RATE_LIMIT_DEFAULT_BACKOFF_MS == 60_000


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # codex-cli 0.154.0's two observed shapes (2026-09-17): date+time and time only.
        (
            "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
            "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try "
            "again at Sep 19th, 2026 8:37 AM.",
            "Sep 19th, 2026 8:37 AM",
        ),
        ("usage limit ... or try again at 12:39 PM.", "12:39 PM"),
        ("usage limit; try again at 12:39 PM", "12:39 PM"),
        ("usage limit; try again at 12:39 PM\nmore", "12:39 PM"),
        # Diagnostics carry the raw JSON event line, so the phrase ends in `."}}`.
        ('{"type":"error","message":"usage limit or try again at 12:39 PM."}', "12:39 PM"),
        (
            '{"error":{"message":"usage limit; try again at Sep 19th, 2026 8:37 AM."}}',
            "Sep 19th, 2026 8:37 AM",
        ),
        # A zone, when codex ever prints one, is kept with the phrase.
        ("usage limit; try again at 12:39 PM UTC.", "12:39 PM UTC"),
        ("usage limit; try again at Sep 19th, 2026 8:37 AM PDT.", "Sep 19th, 2026 8:37 AM PDT"),
        ("usage limit; try again at 08:37 +02:00.", "08:37 +02:00"),
        # Relative delays, plain limits and non-clock wording carry no reset phrase.
        ("usage limit; try again in 5 seconds", None),
        ("usage limit reached", None),
        ("usage limit; try again at noon.", None),
        ("usage limit; try again at tomorrow morning.", None),
        ("usage limit; try again at " + "x" * 500 + ".", None),
        ("rate limit; retry-after 9", None),
        (None, None),
    ],
)
def test_parse_usage_limit_reset(text, expected):
    reset = c.parse_usage_limit_reset(text)
    assert (reset.when if reset else None) == expected
    if reset is not None:
        assert len(reset.when) <= c.USAGE_LIMIT_RESET_MAX_CHARS


@pytest.mark.parametrize(
    ("text", "zone_stated"),
    [
        ("try again at 12:39 PM.", False),
        ("try again at Sep 19th, 2026 8:37 AM.", False),
        ("try again at 12:39 PM UTC.", True),
        ("try again at 12:39 PM GMT", True),
        ("try again at 08:37 +02:00.", True),
    ],
)
def test_parse_usage_limit_reset_reports_whether_a_zone_was_stated(text, zone_stated):
    reset = c.parse_usage_limit_reset(text)
    assert reset is not None and reset.zone_stated is zone_stated


def test_parse_usage_limit_reset_is_sanitized():
    reset = c.parse_usage_limit_reset("try again at 1:00\x1b[31m PM.")
    assert reset is not None and "\x1b" not in reset.when


def _codex_captures():
    from pathlib import Path

    root = Path(__file__).parent.parent / "docs" / "codex-help"
    return sorted(p for p in root.iterdir() if p.is_dir())


def test_every_flag_the_contract_always_sends_is_declared_in_every_committed_capture():
    """The evidence rule kimi and claude already had (#188): a flag amicus sends without
    asking `--help` first must appear in each capture taken of `codex exec --help`. It is
    checked as a declared option, since a flag named only in another option's prose would
    keep a substring match passing after codex dropped it."""
    import re

    captures = _codex_captures()
    assert captures, "no codex help capture is committed; scripts/check_backend_compat.py --write"
    declared_row = re.compile(r"^\s+(?:-\w, )?(--[a-z][\w-]*)", re.MULTILINE)
    for capture in captures:
        text = (capture / "codex-help.txt").read_text()
        declared = set(declared_row.findall(text))
        # Control: the parse finds options at all, and rejects a flag codex never had.
        assert "--sandbox" in declared and "--amicus-no-such-flag" not in declared
        missing = sorted(c.ALWAYS_SEND_FLAGS - declared)
        assert missing == [], f"{capture.name}: {missing}"
        version = (capture / "codex-version.txt").read_text().strip()
        assert version == capture.name
        major, minor, _patch = version.split(".")
        assert (int(major), int(minor)) in c.SUPPORTED_VERSIONS, (
            f"a capture exists for {version}, which the contract does not support"
        )


def test_server_down_fallback_recipe_disables_every_model_run_feature():
    """The skill's direct-CLI fallback says its flags come from MODEL_RUN_DISABLED_FEATURES;
    keep the two from drifting (#222 added goals to one and not, until now, the other)."""
    from pathlib import Path

    recipe = (
        Path(__file__).parent.parent
        / "skills/collaborating-with-amicus/references/server-down-fallback.md"
    ).read_text()
    command = recipe.split("```sh", 1)[1].split("```", 1)[0]
    disabled = [
        line.split()[1] for line in command.splitlines() if line.strip().startswith("--disable ")
    ]
    assert "remote_plugin" in disabled, "control: the parse finds the recipe's disables"
    assert disabled == list(c.MODEL_RUN_DISABLED_FEATURES)
