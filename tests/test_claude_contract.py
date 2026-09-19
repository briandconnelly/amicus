"""The Claude Code CLI contract: derivations from the constants, the failure signatures, and
the 2.1.263 evidence rule (a flag the contract sends must appear in the capture)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from amicus.backends.claude import contract
from amicus.sdk.backend.contract import IsolationPolicy
from amicus.sdk.testing import conformance

_DOCS_PATH = Path(__file__).parent.parent / "docs" / "claude-help" / "2.1.263"
HELP = (_DOCS_PATH / "claude-help.txt").read_text()
VERSION = (_DOCS_PATH / "claude-version.txt").read_text().strip()


def test_contract_is_derived_from_the_constants_and_self_consistent():
    c = contract.CONTRACT
    assert c.backend_id == "claude" and c.env_prefix == "AMICUS_CLAUDE_" and c.bin_name == "claude"
    assert c.exec_argv_prefix == contract.CORE_INVOCATION
    assert c.always_send_flags == contract.ALWAYS_SEND_FLAGS
    assert c.help_gated_flags == tuple(sorted(contract.HELP_GATED_FLAGS))
    assert c.isolation_policy is IsolationPolicy.TOOL_ALLOWLIST and not c.needs_orphan_sweep
    assert c.effort_silently_ignored_upstream and c.effort_validation == "enumerated"
    assert c.structured_output == "prompt_append" and c.model_catalog.strategy == "static"
    assert c.supported_features == {"adversarial_review", "usage_accounting"}
    assert "delegate" not in c.supported_features
    assert c.readonly_honesty_statement == contract.READ_ONLY_HONESTY
    assert c.implicit_context_disclosure == contract.IMPLICIT_CONTEXT_DISCLOSURE
    assert conformance.check_contract(c) == []


def test_flag_classes_do_not_overlap_and_are_all_long_flags():
    assert set(contract.ALWAYS_SEND_FLAGS).isdisjoint(contract.HELP_GATED_FLAGS)
    for flag in (*contract.ALWAYS_SEND_FLAGS, *contract.HELP_GATED_FLAGS):
        assert flag.startswith("--"), flag
    assert tuple(sorted(contract.ALWAYS_SEND_FLAGS)) == contract.ALWAYS_SEND_FLAGS
    assert contract.HELP_GATED_FLAGS == {
        "--effort": True,
        "--model": True,
        "--disallowed-tools": True,
    }


def test_vocabularies():
    assert contract.CONFIG_MODES == ("inherit", "scoped", "safe", "bare")
    assert {"inherit", "scoped", "safe"} == contract.LOGIN_MODES
    assert contract.ACCESS_MODES == ("toolless", "readonly")
    assert contract.VALID_EFFORTS == ("low", "medium", "high", "xhigh", "max")
    assert contract.DEFAULT_EFFORT == "xhigh" and contract.DEFAULT_CONFIG_MODE == "inherit"
    assert contract.DEFAULT_ACCESS == "toolless"
    assert (contract.MIN_BUDGET_USD, contract.MAX_BUDGET_USD) == (0.01, 5.0)
    assert contract.DEFAULT_MAX_BUDGET_USD == 1.0
    assert "Bash" not in contract.READONLY_TOOLS and "Write" not in contract.READONLY_TOOLS
    assert "Bash" in contract.READONLY_DISALLOWED_TOOLS
    assert contract.SUCCESS_SUBTYPES == (None, "success")
    assert "input_tokens" in contract.USAGE_KEYS


def test_forbidden_phrases_are_re_derived_for_a_multi_backend_server():
    assert "kimi" not in contract.FORBIDDEN_SURFACE_PHRASES
    assert "moonbridge" not in contract.FORBIDDEN_SURFACE_PHRASES
    assert {"codex exec", "kimi exec", "read-only sandbox"} <= set(
        contract.FORBIDDEN_SURFACE_PHRASES
    )


def test_evidence_the_instrument_can_fail():
    assert "--definitely-not-a-claude-flag" not in HELP


def test_captured_help_has_no_terminal_escape_bytes():
    assert "\x1b" not in HELP


@pytest.mark.parametrize(
    "flag",
    [*contract.ALWAYS_SEND_FLAGS, *contract.HELP_GATED_FLAGS, "--print", "--tools"],
)
def test_every_sent_flag_is_in_the_captured_help(flag):
    assert flag in HELP


def test_captured_help_documents_the_toolless_mechanism_and_the_effort_levels():
    assert 'Use "" to disable all tools' in HELP
    assert "(low, medium, high, xhigh, max)" in HELP


def test_captured_version_is_a_supported_major():
    major = int(VERSION.split(".")[0])
    assert major in contract.SUPPORTED_MAJORS
    assert frozenset({2}) == contract.SUPPORTED_MAJORS


@pytest.mark.parametrize(
    "text, logged_out, bad_key, authish, budget, permission, rate, drift",
    [
        ("Not logged in · Please run /login", True, False, True, False, False, False, False),
        ("please run /login to continue", True, False, True, False, False, False, False),
        ("Invalid API key.", False, True, False, False, False, False, False),
        ("api_key_invalid", False, True, False, False, False, False, False),
        ("Authentication required.", False, False, True, False, False, False, False),
        ("The author's approach is sound.", False, False, False, False, False, False, False),
        ("Budget stop threshold reached.", False, False, False, True, False, False, False),
        ("Permission denied for tool Read.", False, False, False, False, True, False, False),
        ("Access denied.", False, False, False, False, True, False, False),
        ("The reviewer denied the claim.", False, False, False, False, False, False, False),
        ("Rate limited; try later.", False, False, False, False, False, True, False),
        ("API is overloaded (529)", False, False, False, False, False, True, False),
        ("429 Too Many Requests", False, False, False, False, False, True, False),
        ("an accurate estimate", False, False, False, False, False, False, False),
        ("error: unknown option '--effort'", False, False, False, False, False, False, True),
        ("invalid value 'zap' for --effort", False, False, False, False, False, False, True),
        ("all good", False, False, False, False, False, False, False),
    ],
)
def test_failure_signatures(text, logged_out, bad_key, authish, budget, permission, rate, drift):
    assert contract.is_logged_out(text) is logged_out
    assert contract.is_invalid_api_key(text) is bad_key
    assert contract.mentions_auth(text) is authish
    assert contract.is_budget_stop(text) is budget
    assert contract.is_permission_denied(text) is permission
    assert contract.is_rate_limited(text) is rate
    assert contract.is_contract_drift(text) is drift


def test_predicates_tolerate_none_and_empty():
    for predicate in (
        contract.is_logged_out,
        contract.is_invalid_api_key,
        contract.mentions_auth,
        contract.is_budget_stop,
        contract.is_permission_denied,
        contract.is_rate_limited,
        contract.is_contract_drift,
    ):
        assert predicate(None, "") is False


def test_known_models_are_well_formed_aliases_first():
    slugs = [slug for slug, _name, _kind in contract.KNOWN_MODELS]
    assert slugs[:4] == ["opus", "sonnet", "haiku", "fable"]
    assert len(set(slugs)) == len(slugs)
    for slug, name, kind in contract.KNOWN_MODELS:
        assert contract.MODEL_SLUG_PATTERN.match(slug) and name and kind in ("alias", "full")


# --- every committed capture, not only the first (#188) -------------------------------------

_CAPTURE_ROOT = _DOCS_PATH.parent
# A capture directory may hold findings alone (2.1.274 records a budget-stop shape and no
# help text); only one with a help file is held to the flags.
HELP_CAPTURES = sorted(p for p in _CAPTURE_ROOT.iterdir() if (p / "claude-help.txt").is_file())
# An option ROW, by its shallow indent: claude's descriptions wrap at column 40 and can begin
# with a flag themselves, so a substring match would survive the option being dropped.
_OPTION_ROW = re.compile(r"^ {1,8}(-\S.*?)(?: {2,}|$)", re.MULTILINE)
_LONG_FLAG = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")


def _declared(help_text: str) -> set[str]:
    return {flag for row in _OPTION_ROW.findall(help_text) for flag in _LONG_FLAG.findall(row)}


def test_the_captures_under_test_include_the_newest_one():
    assert [p.name for p in HELP_CAPTURES] == ["2.1.263", "2.1.278"]


@pytest.mark.parametrize("capture", HELP_CAPTURES, ids=lambda p: p.name)
def test_every_sent_flag_is_declared_in_every_committed_capture(capture):
    text = (capture / "claude-help.txt").read_text()
    declared = _declared(text)
    # Controls: rows are found, and a flag named only in another option's description is
    # not counted as declared (2.1.278 names --mcp-config inside two descriptions).
    assert "--model" in declared and "--definitely-not-a-claude-flag" not in declared
    assert _declared(" " * 40 + "--mcp-config, mentioned in prose only\n") == set()
    sent = {*contract.ALWAYS_SEND_FLAGS, *contract.HELP_GATED_FLAGS, "--print", "--tools"}
    assert sorted(sent - declared) == [], capture.name
    assert "\x1b" not in text
    version = (capture / "claude-version.txt").read_text().strip()
    assert version.startswith(capture.name), (version, capture.name)
    assert int(capture.name.split(".")[0]) in contract.SUPPORTED_MAJORS
