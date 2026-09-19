"""The codex live-gate predicate, exercised without a live run (#113)."""

from __future__ import annotations

import pytest
from tests.support.livegate import assert_codex_version_was_checked

from amicus.backends.codex import config as cc
from amicus.backends.codex import contract


def _status(version: str, warnings: list[str] | None = None) -> dict:
    return {
        "installed": True,
        "authenticated": True,
        "version": version,
        "warnings": warnings or [],
    }


def test_a_minor_in_the_built_in_contract_passes():
    major, minor = max(contract.SUPPORTED_VERSIONS)
    assert_codex_version_was_checked(_status(f"codex-cli {major}.{minor}.1"))


def test_an_ambient_override_cannot_vouch_for_an_unchecked_minor(clean_env):
    """The hole `warnings == []` leaves: the operator override makes 0.999 "supported", so
    no version warning is raised, and the evidence would record an unchecked minor."""
    assert (0, 999) not in contract.SUPPORTED_VERSIONS
    cfg = cc.load_config({"AMICUS_CODEX_SUPPORTED_VERSIONS": "0.999"})
    assert cc.version_supported("codex-cli 0.999.0", cfg) is True, "control: no warning here"
    with pytest.raises(AssertionError):
        assert_codex_version_was_checked(_status("codex-cli 0.999.0"))


def test_an_unparseable_version_is_not_a_checked_one(clean_env):
    """`version_supported` returns None for it, and status warns only on False."""
    assert cc.version_supported("codex-cli nightly", cc.load_config({})) is None
    with pytest.raises(AssertionError):
        assert_codex_version_was_checked(_status("codex-cli nightly"))


def test_any_status_warning_fails_the_gate():
    major, minor = max(contract.SUPPORTED_VERSIONS)
    with pytest.raises(AssertionError):
        assert_codex_version_was_checked(_status(f"codex-cli {major}.{minor}.0", ["drift"]))
