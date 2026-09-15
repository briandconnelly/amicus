"""The Kimi CLI contract: derivations from the constants, the failure signatures, and the
evidence rule (a flag the contract sends or refuses must be declared by an option row in
every capture under docs/kimi-help/)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from amicus.backends.kimi import contract
from amicus.sdk.backend.contract import IsolationPolicy
from amicus.sdk.testing import conformance

_DOCS_ROOT = Path(__file__).parent.parent / "docs" / "kimi-help"
CAPTURES = sorted(p for p in _DOCS_ROOT.iterdir() if p.is_dir())
# An option row: two spaces, then the declaration column up to the gap before its description.
_OPTION_ROW = re.compile(r"^  (-\S.*?)(?: {2,}|$)")
_FLAG = re.compile(r"(?<![\w-])-{1,2}[A-Za-z][\w-]*")


def _help(capture: Path) -> str:
    return (capture / "kimi-help.txt").read_text()


def _declared(help_text: str) -> frozenset[str]:
    """Flags an option row declares. A flag that appears only in prose (`--agent-file` in the
    `--agent` description, `-c` inside `kimi-code`) is not declared, so a substring match
    would keep passing after kimi dropped the option."""
    return frozenset(
        flag
        for line in help_text.splitlines()
        if (row := _OPTION_ROW.match(line))
        for flag in _FLAG.findall(row.group(1))
    )


def _version(capture: Path) -> str:
    return (capture / "kimi-version.txt").read_text().strip()


def _minor(capture: Path) -> tuple[int, int]:
    major, minor, _patch = _version(capture).split(".")
    return int(major), int(minor)


def test_contract_is_derived_from_the_constants_and_self_consistent():
    c = contract.CONTRACT
    assert c.backend_id == "kimi" and c.env_prefix == "AMICUS_KIMI_" and c.bin_name == "kimi"
    assert c.exec_argv_prefix == () and c.always_send_flags == contract.ALWAYS_SEND_FLAGS
    assert c.help_gated_flags == tuple(sorted(contract.HELP_GATED_FLAGS))
    assert c.isolation_policy is IsolationPolicy.WORKTREE_ALL_TIERS and c.needs_orphan_sweep
    assert c.effort_silently_ignored_upstream and c.effort_validation == "token_floor_plus_catalog"
    assert c.structured_output == "prompt_append" and c.model_catalog.strategy == "live_probe"
    assert c.supported_features == {"delegate", "model_validation", "empty_response_detection"}
    assert c.limits.max_argv_prompt_chars == contract.MAX_ARGV_PROMPT_CHARS
    assert c.limits.answer_file_name == contract.ANSWER_FILE_NAME
    assert c.readonly_honesty_statement == contract.READ_ONLY_CONFIDENTIALITY_LIMIT
    assert conformance.check_contract(c) == []


def test_read_only_tools_carry_no_shell_or_write():
    assert "Bash" not in contract.READ_ONLY_AGENT_TOOLS
    assert "Write" not in contract.READ_ONLY_AGENT_TOOLS
    assert contract.READ_ONLY_AGENT_NAME == "amicus-readonly"


def test_the_captures_are_the_ones_the_contract_claims():
    # An empty parameter set skips rather than fails, so pin the directories the tests below
    # run over.
    assert [p.name for p in CAPTURES] == ["0.41.0", "0.42.0", "0.43.1"]
    assert frozenset({(0, 35), (0, 39), (0, 41), (0, 42), (0, 43)}) == contract.SUPPORTED_VERSIONS
    # The newest supported minor is the one the live gate pins, so it must carry a capture.
    assert max(_minor(p) for p in CAPTURES) == max(contract.SUPPORTED_VERSIONS)


def test_the_flag_matcher_reads_declarations_not_prose():
    row = "  --agent <name>   loaded via --agent-file; see kimi-code (-c, --continue)\n"
    assert _declared(f"Options:\n{row}") == {"--agent"}
    assert _declared("  -S, --session [id]   Resume.\n  export [options]   Export.\n") == {
        "-S",
        "--session",
    }


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_evidence_the_instrument_can_fail(capture):
    assert "--definitely-not-a-kimi-flag" not in _declared(_help(capture))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
@pytest.mark.parametrize(
    "flag",
    [
        *contract.ALWAYS_SEND_FLAGS,
        *contract.HELP_GATED_FLAGS,
        contract.ADD_DIR_FLAG,
        *contract.PROMPT_MODE_INCOMPATIBLE_FLAGS,
    ],
)
def test_every_sent_or_refused_flag_is_in_the_captured_help(capture, flag):
    assert flag in _declared(_help(capture))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_captured_version_is_a_supported_version(capture):
    assert _version(capture) == capture.name
    assert _minor(capture) in contract.SUPPORTED_VERSIONS


@pytest.mark.parametrize(
    "text, auth, drift, model, unresolved, rate",
    [
        ("Error: 401 Unauthorized", True, False, False, False, False),
        ("invalid api key", True, False, False, False, False),
        ("error: unknown option '--zap'", False, True, False, False, False),
        ("Cannot combine --prompt with --yolo.", False, True, False, False, False),
        (
            'error: failed to run prompt: Model "x" is not configured in config.toml.',
            False,
            False,
            True,
            False,
            False,
        ),
        (
            "error: failed to run prompt: model foo does not resolve to a configured provider",
            False,
            False,
            True,
            True,
            False,
        ),
        (
            "this alias does not resolve to a configured provider, said the docs",
            False,
            False,
            False,
            False,
            False,
        ),
        ("429 Too Many Requests", False, False, False, False, True),
        ("quota exhausted", False, False, False, False, True),
        ("all good", False, False, False, False, False),
    ],
)
def test_failure_signatures(text, auth, drift, model, unresolved, rate):
    assert contract.is_auth_failure(text) is auth
    assert contract.is_contract_drift(text) is drift
    assert contract.is_invalid_model(text) is model
    assert contract.is_unresolved_default_model(text) is unresolved
    assert contract.is_rate_limited(text) is rate


def test_retry_after_parsing():
    assert contract.parse_retry_after_ms("Retry-After: 5") == 5000
    assert contract.parse_retry_after_ms("retry_after=250ms") == 250
    assert contract.parse_retry_after_ms("try again in 2 minutes") == 120_000
    assert contract.parse_retry_after_ms("retry-after: 0") == 0
    assert contract.parse_retry_after_ms("nothing here") is None
    assert contract.parse_retry_after_ms(None, "") is None


def test_effort_token_pattern_is_shape_only():
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch("xhigh")
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch("future-level.2")
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch("") is None
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch(" high ") is None
    assert "xhigh" in contract.REASONING_EFFORT_FALLBACK_VOCABULARY
