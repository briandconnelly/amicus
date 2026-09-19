"""What a live readiness test must establish before its run counts as rule-20 evidence.

Kept out of the live test files so the unit suite can exercise it: a live test never runs
in the gate, and an assertion nobody can see fail is not a check.
"""

from __future__ import annotations

from amicus.backends.codex import config as codex_config
from amicus.backends.codex import contract as codex_contract


def assert_codex_version_was_checked(status: dict) -> None:
    """The installed codex minor is one amicus's BUILT-IN contract names (#113).

    `status["warnings"]` alone cannot say so. It reads the effective configuration, so an
    ambient AMICUS_CODEX_SUPPORTED_VERSIONS naming an unchecked minor silences the version
    warning, and a version string that does not parse is never warned about at all.
    """
    installed = codex_config.parse_version(status["version"])
    assert installed in codex_contract.SUPPORTED_VERSIONS, status
    assert status["warnings"] == [], status
