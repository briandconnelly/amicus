"""The pi CLI contract: derivations from the constants, the failure signatures, and the
evidence rule (a flag the contract sends must appear in every capture under docs/pi-help/)."""

from __future__ import annotations

from pathlib import Path

import pytest

from amicus.backends.pi import contract
from amicus.sdk.backend.contract import IsolationPolicy
from amicus.sdk.testing import conformance

_DOCS_ROOT = Path(__file__).parent.parent / "docs" / "pi-help"
CAPTURES = sorted(p for p in _DOCS_ROOT.iterdir() if p.is_dir())


def _help(capture: Path) -> str:
    return (capture / "pi-help.txt").read_text()


def _version(capture: Path) -> str:
    return (capture / "pi-version.txt").read_text().strip()


def _missing_flags(help_text: str) -> list[str]:
    """Every flag a run sends that the help text does not mention."""
    return [f for f in (*contract.ALWAYS_SEND_FLAGS, contract.THINKING_FLAG) if f not in help_text]


def test_contract_is_derived_from_the_constants_and_self_consistent():
    c = contract.CONTRACT
    assert c.backend_id == "pi" and c.display_name == "Pi" and c.bin_name == "pi"
    assert c.env_prefix == "AMICUS_PI_" and c.always_send_flags == contract.ALWAYS_SEND_FLAGS
    assert c.isolation_policy is IsolationPolicy.WORKTREE_ALL_TIERS and c.needs_orphan_sweep
    assert c.effort_silently_ignored_upstream and c.effort_validation == "token_floor_plus_catalog"
    assert c.structured_output == "prompt_append"
    assert c.supported_features == {"delegate", "model_validation", "empty_response_detection"}
    assert c.model_catalog.strategy == "live_probe"
    assert c.model_catalog.model_identifier_authority == "authoritative"
    assert c.model_catalog.effort_metadata_authority == "advisory"
    assert c.readonly_honesty_statement == contract.READ_ONLY_HONESTY
    assert c.implicit_context_disclosure == contract.IMPLICIT_CONTEXT_DISCLOSURE
    assert conformance.check_contract(c) == []


def test_the_captures_are_the_ones_the_contract_claims():
    assert [p.name for p in CAPTURES] == ["1.5.0"]
    assert frozenset({(1, 5)}) == contract.SUPPORTED_VERSIONS


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_every_sent_flag_is_in_every_capture(capture):
    help_text = _help(capture)
    assert "--definitely-not-a-pi-flag" not in help_text  # the instrument can fail
    assert _missing_flags(help_text) == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_a_perturbed_capture_fails_the_flag_check(capture):
    perturbed = _help(capture).replace("--no-session", "")
    assert _missing_flags(perturbed) == ["--no-session"]


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_every_effort_is_in_the_captured_help(capture):
    thinking_line = next(
        line for line in _help(capture).splitlines() if contract.THINKING_FLAG in line
    )
    for effort in contract.EFFORTS:
        assert effort in thinking_line


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_captured_version_is_a_supported_version(capture):
    major, minor, _patch = _version(capture).split(".")
    assert _version(capture) == capture.name
    assert (int(major), int(minor)) in contract.SUPPORTED_VERSIONS


def test_run_flags_are_the_invocation():
    assert contract.RUN_FLAGS[:4] == ("-p", "--mode", "json", "--no-session")
    assert contract.RUN_FLAGS[4:] == contract.SUPPRESSION_FLAGS
    assert contract.SUPPRESSION_FLAGS == (
        "--no-context-files",
        "--no-skills",
        "--no-extensions",
        "--no-mcp",
        "--no-prompt-templates",
        "--no-themes",
        "--no-approve",
        "--offline",
    )
    assert set(contract.RUN_FLAGS) <= set(contract.ALWAYS_SEND_FLAGS) | {"-p", "json"}


def test_probes_carry_the_suppression_flags():
    assert set(contract.SUPPRESSION_FLAGS) <= set(contract.HELP_ARGS)
    assert contract.VERSION_ARGS == ("--version",)
    assert contract.LIST_MODELS_ARGS == ("--list-models",)
    assert contract.AUTH_CHECK_ARGS == ("auth", "check", "--json", "--no-refresh")


def test_system_prompt_can_never_name_a_path(tmp_path):
    raw = contract.PI_SYSTEM_PROMPT
    assert "/" not in raw and len(raw.encode()) > 255
    with pytest.raises(OSError):  # ENAMETOOLONG: no file by that name can be created
        (tmp_path / raw).write_text("x")


def test_read_only_tools_cannot_write_or_run():
    assert not {"bash", "edit", "write"} & set(contract.READ_ONLY_TOOLS)
    assert contract.READ_ONLY_TOOLS == ("read", "grep", "find", "ls")
    assert contract.WRITE_TOOLS == ("read", "bash", "edit", "write", "grep", "find", "ls")


def test_child_environment():
    assert contract.RUN_ENV_SET == {"PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1"}
    assert contract.RUN_ENV_DROP == ("PI_CODING_AGENT_SESSION_DIR",)
    assert (contract.SANDBOX_READ_ONLY, contract.SANDBOX_WORKSPACE_WRITE) == (
        "read-only",
        "workspace-write",
    )


def test_login_hint_names_no_auth_login():
    assert "auth login" not in contract.LOGIN_HINT and "/login" in contract.LOGIN_HINT


def test_disclosures_say_what_the_spec_says():
    assert "stdin" in contract.CARRIERS and "--no-session" in contract.CARRIERS
    assert "outside the workspace" in contract.EGRESS
    assert "no shell, edit or write tool" in contract.READ_ONLY_HONESTY
    assert "no OS sandbox" in contract.READ_ONLY_HONESTY
    assert "models.json" in contract.IMPLICIT_CONTEXT_DISCLOSURE
    assert "sessionDir" in contract.IMPLICIT_CONTEXT_DISCLOSURE


@pytest.mark.parametrize(
    "text, auth, drift, model, rate",
    [
        ("Connection error.", False, False, False, False),
        ("401 Unauthorized", True, False, False, False),
        ("429 Too Many Requests", False, False, False, True),
        ('Warning: Model "nope" not found for provider "fake". Using custom model id.',
         False, False, True, False),
        ("Error: Unknown option: --zap", False, True, False, False),
        ("all good", False, False, False, False),
    ],
)  # fmt: skip
def test_failure_signatures(text, auth, drift, model, rate):
    assert contract.is_auth_failure(text) is auth
    assert contract.is_contract_drift(text) is drift
    assert contract.is_invalid_model(text) is model
    assert contract.is_rate_limited(text) is rate


def test_retry_after_parsing():
    assert contract.parse_retry_after_ms("Retry-After: 5") == 5000
    assert contract.parse_retry_after_ms("retry_after=250ms") == 250
    assert contract.parse_retry_after_ms("try again in 2 minutes") == 120_000
    assert contract.parse_retry_after_ms("retry-after: 0") == 0
    assert contract.parse_retry_after_ms("nothing here") is None
    assert contract.parse_retry_after_ms(None, "") is None
