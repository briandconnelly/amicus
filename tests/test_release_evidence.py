"""The release-evidence record is checked by `validate`, so these controls are real tests.

The record itself is a gitignored local file a maintainer can hand-write, so it proves
nothing against a determined author. It is an honest-mistake guard: it catches evidence
taken on the wrong commit, on a dirty tree, from a partial run, or too long ago. Every
rejection path below is exercised, because a validator that cannot fail is not a check.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "record_live_gate_evidence.py"
_spec = importlib.util.spec_from_file_location("record_live_gate_evidence", _SCRIPT)
assert _spec is not None and _spec.loader is not None
evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evidence)

HEAD = "a" * 40
NOW = datetime(2026, 9, 8, 18, 0, 0, tzinfo=UTC)


def _record(**overrides):
    record = {
        "batch_id": "b" * 32,
        "recorded_at": (NOW - timedelta(hours=1)).isoformat(),
        "commit": HEAD,
        "tree_clean": True,
        "backends": {
            name: {
                "test_file": f"tests/test_{name}_live.py",
                "exit_status": 0,
                "cli_version": f"{name}-cli 1.0.0",
            }
            for name in evidence.BACKENDS
        },
    }
    record.update(overrides)
    return record


def test_a_complete_fresh_record_is_accepted():
    assert evidence.validate(_record(), head=HEAD, tree_clean=True, now=NOW) == []


def test_a_record_for_another_commit_is_rejected():
    problems = evidence.validate(_record(commit="c" * 40), head=HEAD, tree_clean=True, now=NOW)
    assert any("commit" in p for p in problems), problems


def test_a_dirty_tree_now_is_rejected():
    problems = evidence.validate(_record(), head=HEAD, tree_clean=False, now=NOW)
    assert any("clean" in p for p in problems), problems


def test_a_record_taken_on_a_dirty_tree_is_rejected():
    problems = evidence.validate(_record(tree_clean=False), head=HEAD, tree_clean=True, now=NOW)
    assert any("clean" in p for p in problems), problems


def test_a_missing_backend_is_rejected():
    record = _record()
    del record["backends"]["kimi"]
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("kimi" in p for p in problems), problems


def test_a_nonzero_exit_status_is_rejected():
    record = _record()
    record["backends"]["claude"]["exit_status"] = 1
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("claude" in p for p in problems), problems


def test_an_expired_record_is_rejected():
    record = _record(recorded_at=(NOW - timedelta(hours=25)).isoformat())
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("old" in p or "age" in p for p in problems), problems


def test_a_malformed_record_is_rejected_without_raising():
    problems = evidence.validate({"nonsense": True}, head=HEAD, tree_clean=True, now=NOW)
    assert problems, "a record missing every required field must be rejected, not accepted"


def test_a_future_timestamp_is_rejected():
    record = _record(recorded_at=(NOW + timedelta(hours=2)).isoformat())
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert problems, "a record from the future is a clock or forgery problem, not evidence"


@pytest.mark.skipif(
    os.environ.get("AMICUS_RELEASE_CHECK") != "1",
    reason="release-only: reads the gitignored evidence file, which CI cannot have",
)
def test_the_recorded_evidence_covers_this_exact_commit():
    """Run with AMICUS_RELEASE_CHECK=1 on the commit about to be tagged."""
    path = Path(__file__).resolve().parent.parent / evidence.EVIDENCE_PATH
    assert path.exists(), (
        f"no live-gate evidence at {path}; run scripts/record_live_gate_evidence.py"
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()
    problems = evidence.validate(
        json.loads(path.read_text()),
        head=head,
        tree_clean=not dirty,
        now=datetime.now(UTC),
    )
    assert problems == [], "; ".join(problems)
