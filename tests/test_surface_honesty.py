"""Wire prose must not contradict what amicus does: a shared union of bans in M0, refined
per backend when each plugin's contract lands (its forbidden_surface_phrases join here)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import get_args

import pytest
from pontonier.testing import surface_honesty

from amicus import errors, manifest
from amicus.jobs import delivery, lifecycle
from amicus.schemas.envelope import DiscardOutcome
from amicus.tools import discovery

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


# Issue #101: a repeated keyed start replays the existing job's handle, which can already be
# terminal, so each async tool's description gates its polling on `status` as well.
_ASYNC_POLL_PHRASE = "poll amicus_job_status while status is running"
_ASYNC_SUPERSEDED = "poll amicus_job_status, read amicus_job_result"
_ASYNC_TOOLS: tuple[str, ...] = (
    "amicus_consult_async",
    "amicus_review_changes_async",
    "amicus_adversarial_review_async",
    "amicus_delegate_async",
)


def test_async_descriptions_gate_polling_on_status(wire):
    descriptions = {t["name"]: t["description"] for t in wire["tools"]}
    for name in _ASYNC_TOOLS:
        assert _ASYNC_POLL_PHRASE in descriptions[name], f"{name} polls without a status gate"
        assert _ASYNC_SUPERSEDED not in descriptions[name], name


def test_the_timeout_repair_gates_polling_on_status():
    # The sync timeout repair sends the caller to an async twin, then to the status tool; it
    # gates that polling on `status` as the job_running repair does (#101).
    text = errors.repair_table()["timeout"].alternative
    assert text and _ASYNC_POLL_PHRASE in text and "terminal status" in text
    assert "then poll amicus_job_status and fetch amicus_job_result" not in text


def test_the_async_description_instrument_can_fail():
    """The phrase check fails against the wording each async description replaced (#101)."""
    old = f"returns a job handle; {_ASYNC_SUPERSEDED}. Same egress."
    assert _ASYNC_POLL_PHRASE not in old


# Issue #44: consume promised job_not_found on every repeat call, while a failed delete
# made that false and was reported as plain success. The description must condition the
# promise on the outcome and point at the follow_up.
_CONSUME_PHRASES: tuple[str, ...] = (
    "meta.consume.discard_outcome",
    "meta.consume.follow_up",
    "otherwise the record may remain",
)
_SUPERSEDED_CONSUME = (
    "Free — no model call. Like amicus_job_result, then delete the record: a repeat call "
    "returns job_not_found, so this is not idempotent. A corrupt or incompatible record "
    "is not deleted."
)


def test_consume_description_conditions_the_repeat_call_promise(wire):
    text = next(t["description"] for t in wire["tools"] if t["name"] == "amicus_job_consume_result")
    for phrase in _CONSUME_PHRASES:
        assert phrase in text, f"consume description does not say {phrase!r}"


def test_the_consume_instrument_can_fail():
    assert [p for p in _CONSUME_PHRASES if p in _SUPERSEDED_CONSUME] == []


# PR #83 review: three more surfaces said meta.consume tells whether the record was deleted,
# which `missing` cannot (a failed expiry cleanup can leave files), and one implied every
# undeleted record carries a follow_up. Each must name discard_outcome, follow_up and every
# outcome that carries one. Two are markdown, read here because nothing else in the gate
# sees them.
_REPO = Path(__file__).resolve().parents[1]
_SUPERSEDED_CONSUME_SURFACES: dict[str, str] = {
    "discovery returns": (
        "the originating tool's envelope; meta.consume says whether the record was deleted."
    ),
    "jobs command": (
        "Fetch a finished result and delete the record: `amicus_job_consume_result` with "
        "`job_id` — use this once you are done with the result. Its `meta.consume` says "
        "whether the record was deleted; when it carries a `follow_up`, the record may remain."
    ),
    "skill reference": (
        "The consumed envelope's `meta.consume.discard_outcome` says whether the deletion "
        "happened; when it did not, the record may remain and `meta.consume.follow_up` names "
        "the call that shows what is left."
    ),
}


def _outcomes_with_a_follow_up() -> tuple[str, ...]:
    """Derived from the helper the tool calls, so a new outcome that gains a follow_up
    must be named on every surface below."""
    return tuple(
        outcome
        for outcome in get_args(DiscardOutcome)
        if "follow_up"
        in delivery.attach_consume_disposition({"meta": {}}, outcome, "j", None)["meta"]["consume"]
    )


def _consume_surface_phrases() -> tuple[str, ...]:
    return ("discard_outcome", "follow_up", *_outcomes_with_a_follow_up())


def _block(text: str, marker: str) -> str:
    """The one paragraph or list item that carries `marker`."""
    blocks = [b for b in re.split(r"\n\n|\n- ", text) if marker in b]
    assert len(blocks) == 1, f"expected exactly one block carrying {marker!r}"
    return blocks[0]


def _consume_outcome_surfaces() -> dict[str, str]:
    jobs_md = (_REPO / "commands" / "amicus" / "jobs.md").read_text(encoding="utf-8")
    skill_ref = _REPO / "skills" / "collaborating-with-amicus" / "references"
    options = (skill_ref / "options-and-errors.md").read_text(encoding="utf-8")
    return {
        "discovery returns": discovery.TOOL_DETAILS["amicus_job_consume_result"]["returns"],
        "jobs command": _block(jobs_md, "`amicus_job_consume_result` with"),
        "skill reference": _block(options, "meta.consume"),
    }


def test_consume_surfaces_report_the_outcome_not_whether_deletion_happened():
    assert _outcomes_with_a_follow_up() == ("not_done", "delete_failed")
    for name, text in _consume_outcome_surfaces().items():
        for phrase in _consume_surface_phrases():
            assert phrase in text, f"{name} does not say {phrase!r}"


def test_the_consume_surface_instrument_can_fail():
    phrases = _consume_surface_phrases()
    for name, old in _SUPERSEDED_CONSUME_SURFACES.items():
        assert [p for p in phrases if p not in old], name


# Issue #94: a failed, cancelled or timed-out job has no stored envelope, so a consume
# returns its terminal error, attempts no discard and attaches no meta.consume. Every
# surface said meta.consume reports what the store did without naming that case. The match
# ignores backticks, case and line wrapping, since the markdown surfaces wrap mid-phrase.
_TERMINAL_CONSUME_PHRASES: tuple[str, ...] = (
    "a failed, cancelled or timed-out job returns its terminal error",
    "no meta.consume",
    "is not deleted",
)
_SUPERSEDED_TERMINAL_CONSUME: dict[str, str] = {
    "tool description": (
        "Free — no model call. Like amicus_job_result, then delete the record; "
        "meta.consume.discard_outcome says what happened. After removed or missing a repeat "
        "call returns job_not_found (not idempotent); otherwise the record may remain, so "
        "follow meta.consume.follow_up. A corrupt or incompatible record is not deleted."
    ),
    "discovery returns": (
        "the originating tool's envelope; meta.consume.discard_outcome is what the store "
        "did, with a follow_up after not_done or delete_failed."
    ),
    "jobs command": (
        "Fetch a finished result and delete the record: `amicus_job_consume_result` with "
        "`job_id` — use this once you are done with the result. Its "
        "`meta.consume.discard_outcome` reports what the store did: after `removed` or "
        "`missing` it no longer serves the record, so a repeat call returns `job_not_found`; "
        "after `not_done` or `delete_failed` the record may remain, and "
        "`meta.consume.follow_up` names the call that shows what is left."
    ),
    "skill reference": (
        "The consumed envelope's `meta.consume.discard_outcome` reports what the store did, "
        "not whether the files are gone: after `removed` or `missing` it no longer serves the "
        "record; after `not_done` or `delete_failed` the record may remain, and "
        "`meta.consume.follow_up` names the call that shows what is left."
    ),
}


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "")).lower()


def _terminal_consume_surfaces(wire) -> dict[str, str]:
    description = next(
        t["description"] for t in wire["tools"] if t["name"] == "amicus_job_consume_result"
    )
    return {"tool description": description, **_consume_outcome_surfaces()}


def test_consume_surfaces_name_the_terminal_error_case(wire):
    surfaces = _terminal_consume_surfaces(wire)
    assert set(surfaces) == set(_SUPERSEDED_TERMINAL_CONSUME)
    for name, text in surfaces.items():
        for phrase in _TERMINAL_CONSUME_PHRASES:
            assert phrase in _plain(text), f"{name} does not say {phrase!r}"


def test_the_terminal_consume_instrument_can_fail():
    """Every surface's wording before #94 fails the check."""
    for name, old in _SUPERSEDED_TERMINAL_CONSUME.items():
        assert [p for p in _TERMINAL_CONSUME_PHRASES if p not in _plain(old)], name
