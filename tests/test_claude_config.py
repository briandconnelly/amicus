"""AMICUS_CLAUDE_* resolution: defaults, retired names, degradations, the key check, hooks."""

from __future__ import annotations

from amicus.backends.claude import config as cc


def test_defaults_when_nothing_is_set():
    cfg = cc.load_config({})
    assert cfg.bin_override is None and cfg.model is None
    assert cfg.config_mode == "inherit" and cfg.access == "toolless"
    assert cfg.access_explicit is False
    assert cfg.reasoning_effort == "xhigh" and cfg.max_budget_usd == 1.0
    assert cfg.supported_majors == frozenset({2})
    assert cfg.warnings == () and cfg.errors == ()


def test_declared_variables_and_retired_twins():
    names = {v.name: v for v in cc.ENV.vars}
    assert set(names) == {
        "AMICUS_CLAUDE_BIN",
        "AMICUS_CLAUDE_CONFIG_MODE",
        "AMICUS_CLAUDE_ACCESS",
        "AMICUS_CLAUDE_MODEL",
        "AMICUS_CLAUDE_REASONING_EFFORT",
        "AMICUS_CLAUDE_MAX_BUDGET_USD",
        "AMICUS_CLAUDE_SUPPORTED_MAJORS",
    }
    assert all(v.legacy == () for v in names.values())
    assert names["AMICUS_CLAUDE_BIN"].removed == ()
    assert names["AMICUS_CLAUDE_CONFIG_MODE"].removed == ("CLAUDE_IN_CODEX_CLAUDE_CONFIG",)
    assert names["AMICUS_CLAUDE_REASONING_EFFORT"].removed == ("CLAUDE_IN_CODEX_EFFORT",)
    assert names["AMICUS_CLAUDE_MAX_BUDGET_USD"].removed == ("CLAUDE_IN_CODEX_MAX_BUDGET_USD",)
    assert "EXTRA_ARGS" not in " ".join(names)


def test_a_retired_name_is_reported_and_never_read():
    """#176: the CLAUDE_IN_CODEX_* names are tombstones since 0.4.0. The defaults apply,
    which for ACCESS and CONFIG_MODE means the sibling's stricter setting is NOT carried
    over silently: the warning is what tells the operator."""
    cfg = cc.load_config(
        {"CLAUDE_IN_CODEX_CLAUDE_CONFIG": "safe", "CLAUDE_IN_CODEX_ACCESS": "readonly"}
    )
    assert cfg.config_mode == "inherit" and cfg.access == "toolless" and cfg.errors == ()
    assert any(
        "CLAUDE_IN_CODEX_CLAUDE_CONFIG is set but not read" in w
        and "AMICUS_CLAUDE_CONFIG_MODE" in w
        for w in cfg.warnings
    )
    assert any("CLAUDE_IN_CODEX_ACCESS is set but not read" in w for w in cfg.warnings)
    pair = cc.load_config({"AMICUS_CLAUDE_MODEL": "opus", "CLAUDE_IN_CODEX_MODEL": "sonnet"})
    assert pair.model == "opus" and pair.errors == ()


def test_invalid_values_degrade_to_the_default_with_a_warning():
    cfg = cc.load_config(
        {
            "AMICUS_CLAUDE_CONFIG_MODE": "yolo",
            "AMICUS_CLAUDE_ACCESS": "full",
            "AMICUS_CLAUDE_REASONING_EFFORT": "ultra",
            "AMICUS_CLAUDE_MAX_BUDGET_USD": "50",
            "AMICUS_CLAUDE_SUPPORTED_MAJORS": "two",
        }
    )
    assert cfg.config_mode == "inherit" and cfg.access == "toolless"
    assert cfg.reasoning_effort == "xhigh" and cfg.max_budget_usd == 1.0
    assert cfg.supported_majors == frozenset({2})
    assert len(cfg.warnings) == 5 and all("using" in w for w in cfg.warnings)
    for w in cfg.warnings:
        assert "yolo" not in w and "full" not in w and "ultra" not in w  # value-free


def test_budget_and_majors_parse():
    cfg = cc.load_config(
        {"AMICUS_CLAUDE_MAX_BUDGET_USD": "0.25", "AMICUS_CLAUDE_SUPPORTED_MAJORS": "2,3"}
    )
    assert cfg.max_budget_usd == 0.25 and cfg.supported_majors == frozenset({2, 3})
    assert cc.load_config({"AMICUS_CLAUDE_MAX_BUDGET_USD": "abc"}).max_budget_usd == 1.0
    assert cc.load_config({"AMICUS_CLAUDE_MAX_BUDGET_USD": "0.001"}).max_budget_usd == 1.0


def test_placeholders_are_unset_and_reported():
    cfg = cc.load_config({"AMICUS_CLAUDE_MODEL": "${AMICUS_CLAUDE_MODEL}"})
    assert cfg.model is None
    assert "AMICUS_CLAUDE_MODEL" in cc.ENV.report({"AMICUS_CLAUDE_MODEL": "${X}"}).placeholders


def test_version_parsing_is_major_only_and_advisory():
    assert cc.parse_major("2.1.263 (Claude Code)") == 2
    assert cc.parse_major("v3.0.0") == 3
    assert cc.parse_major("nonsense") is None and cc.parse_major(None) is None
    cfg = cc.load_config({})
    assert cc.version_supported("2.1.263 (Claude Code)", cfg) is True
    assert cc.version_supported("3.0.0", cfg) is False
    assert cc.version_supported("garbage", cfg) is None


def test_api_key_presence_counts_placeholders_and_never_returns_the_value():
    assert cc.api_key_present({}) is False
    assert cc.api_key_present({"ANTHROPIC_API_KEY": ""}) is False
    assert cc.api_key_present({"ANTHROPIC_API_KEY": "sk-ant-x"}) is True
    assert cc.api_key_present({"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"}) is True


def test_hook_scan_is_advisory_and_mode_aware(tmp_path):
    assert cc.workspace_hook_settings(str(tmp_path)) == []
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"hooks": {"PreToolUse": []}}')
    (tmp_path / ".claude" / "settings.local.json").write_bytes(b"\xff\xfe not utf8")
    assert cc.workspace_hook_settings(str(tmp_path)) == [".claude/settings.json"]
    warnings = cc.hook_security_warnings(str(tmp_path), "inherit")
    assert len(warnings) == 1 and warnings[0].startswith(cc.HOOK_WARNING_PREFIX)
    assert ".claude/settings.json" in warnings[0] and str(tmp_path) not in warnings[0]
    assert cc.hook_security_warnings(str(tmp_path), "scoped") == warnings
    assert cc.hook_security_warnings(str(tmp_path), "safe") == []
    assert cc.hook_security_warnings(str(tmp_path), "bare") == []
    assert cc.hook_security_warnings(str(tmp_path / "missing"), "inherit") == []


def test_access_explicit_tracks_whether_the_operator_set_access_at_all():
    """#116: review_changes defaults to readonly only while access is unset. A set value binds
    every verb, and an invalid one binds as its toolless fallback, so a mistyped restriction
    never loosens into the review default."""
    unset = (
        {},
        {"AMICUS_CLAUDE_ACCESS": ""},
        {"AMICUS_CLAUDE_ACCESS": "${AMICUS_CLAUDE_ACCESS}"},
        # The retired name is a tombstone (#176): it neither sets ACCESS nor makes it explicit.
        {"CLAUDE_IN_CODEX_ACCESS": "toolless"},
        {"AMICUS_CLAUDE_ACCESS": "", "CLAUDE_IN_CODEX_ACCESS": "toolless"},
    )
    for environ in unset:
        assert cc.load_config(environ).access_explicit is False, environ
    explicit = (
        ({"AMICUS_CLAUDE_ACCESS": "toolless"}, "toolless"),
        ({"AMICUS_CLAUDE_ACCESS": "readonly"}, "readonly"),
        ({"AMICUS_CLAUDE_ACCESS": "tooless"}, "toolless"),
        ({"AMICUS_CLAUDE_ACCESS": "toolless", "CLAUDE_IN_CODEX_ACCESS": "readonly"}, "toolless"),
    )
    for environ, access in explicit:
        cfg = cc.load_config(environ)
        assert cfg.access_explicit is True and cfg.access == access, environ
