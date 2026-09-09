"""Wire prose must not contradict what amicus does: a shared union of bans in M0, refined
per backend when each plugin's contract lands (its forbidden_surface_phrases join here)."""

from __future__ import annotations

import json

import pytest
from pontonier.testing import surface_honesty

from amicus import errors, manifest
from amicus.jobs import lifecycle

# Cross-backend vocabulary that would teach an agent a mechanism amicus lacks.
FORBIDDEN_SURFACE_PHRASES: tuple[str, ...] = (
    "applies the diff to your working tree",
    "--dangerously-bypass",
    "codex exec",
    "kimi exec",
    "codex_consult",
    "claude_consult",
    "kimi_consult",
    "codex-in-claude",
    "moonbridge",
    "claude-in-codex",
    "read-only sandbox",
)


@pytest.fixture(scope="module")
def wire() -> dict:
    import asyncio

    return asyncio.run(manifest.build_manifest(manifest.app_for_profile("all")))


@pytest.fixture(scope="module")
def wire_text(wire) -> str:
    return json.dumps(wire, ensure_ascii=False)


@pytest.mark.parametrize("phrase", FORBIDDEN_SURFACE_PHRASES)
def test_wire_prose_does_not_carry_sibling_vocabulary(wire_text, phrase):
    assert surface_honesty.find_forbidden_phrases(wire_text, (phrase,)) == []


def test_the_instrument_can_fail(wire_text):
    assert surface_honesty.find_forbidden_phrases(wire_text, ("amicus_consult",))


# Issue #35: three surfaces tell an agent how to wait for a background job. "Poll until
# result_available" never terminates for a cancelled, failed or timed-out job — the flag
# stays false and poll_after_ms is null on every terminal status (jobs/lookup.py) — so
# each surface must gate the wait on `status` and say what a terminal status yields.
_POLLING_PHRASES: tuple[str, ...] = ("while status is running", "terminal status")
_RESULT_PHRASES: tuple[str, ...] = ("cancelled", "failed", "timeout")

# The defective strings these replaced, frozen as the instrument's known positive:
# test_the_polling_instrument_can_fail proves every check below fails against them.
_SUPERSEDED: dict[str, str] = {
    "job_running repair": (
        "Poll amicus_job_status until result_available, honoring poll_after_ms."
    ),
    "async start follow_up": (
        "Poll amicus_job_status with these arguments, honoring poll_after_ms; read the "
        "result with amicus_job_result once result_available is true. Recover a lost "
        "job_id with amicus_job_list."
    ),
    "amicus_job_result description": (
        "Free — no model call. Return the originating paid tool's envelope once "
        "result_available; branch on `tool`. The record is retained, so a re-read is "
        "free. A still-running job is job_running with retry_after_ms. Records expire "
        "after AMICUS_JOB_TTL (default 24h) and a per-workspace cap evicts the oldest "
        "terminal records; read results promptly."
    ),
}


def _polling_surfaces(wire) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Each waiting instruction amicus puts on the wire, with the phrases it must carry."""
    description = next(t["description"] for t in wire["tools"] if t["name"] == "amicus_job_result")
    return {
        "job_running repair": (
            errors.repair_table()["job_running"].alternative,
            _POLLING_PHRASES,
        ),
        "async start follow_up": (lifecycle.POLL_FOLLOW_UP, _POLLING_PHRASES),
        "amicus_job_result description": (description, _RESULT_PHRASES),
    }


def test_polling_prose_gates_the_wait_on_status(wire):
    for name, (text, required) in _polling_surfaces(wire).items():
        assert "result_available" not in text, f"{name} still waits on a flag that may not flip"
        for phrase in required:
            assert phrase in text, f"{name} does not say {phrase!r}"


def test_the_polling_instrument_can_fail(wire):
    """Every assertion above fails against the string it replaced (issue #35)."""
    for name, (_, required) in _polling_surfaces(wire).items():
        old = _SUPERSEDED[name]
        assert "result_available" in old, name
        assert [p for p in required if p in old] == [], name
