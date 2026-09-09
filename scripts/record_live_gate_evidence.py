#!/usr/bin/env python
"""Run the three live backend gates and record whether they PASSED on this commit.

This is an honest-mistake guard, not an attestation. The record it writes
(`.release-evidence/live-gates.json`) is a gitignored local file a maintainer can hand-edit,
so it proves nothing against a determined author. What it catches is the ordinary slip: tagging
evidence taken on the wrong commit, on a dirty tree, from a partial run, or too long ago.

AGENTS.md rule 20 requires that the three live gates — tests/test_codex_live.py,
tests/test_kimi_live.py and tests/test_claude_live.py — have all PASSED (not merely run) on the
exact commit being tagged, with that outcome recorded here. A record showing a failed suite is
not evidence; it is a reason not to tag.

This script itself is the deliberate, maintainer-run trigger for `-m integration` that
AGENTS.md rule 5 requires: it must never be invoked by the test suite, a pre-commit/pre-push
hook, CI, or anything else automatic. Only a maintainer choosing to spend the live backends'
quota runs it, and only after deciding to in the current session.

Usage:
    AMICUS_REQUIRE_LIVE=1 uv run python scripts/record_live_gate_evidence.py

Behavior (all-or-nothing):
    - Refuses to run at all on a dirty working tree.
    - Runs, for each backend, `AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov
      <test_file>` as a subprocess and captures its exit status and CLI version.
    - Writes EVIDENCE_PATH only when every exit status is 0 and the tree is still clean
      afterwards. Otherwise writes FAILURE_PATH for diagnosis, leaves any previous
      EVIDENCE_PATH untouched (a stale success file surviving a failed run is acceptable and
      intended -- the freshness check in `validate` rejects it on the commit mismatch), and
      exits nonzero.

Record shape:
    The top-level record carries a `batch_id` (a fresh uuid4 hex minted once per run), and
    `main` stamps that same `batch_id` into every backend entry under `backends`. `validate`
    requires every backend entry to CARRY a `batch_id` and to agree with the record's -- this
    is what makes "one shared run produced this whole record" a checkable property instead of
    an assumption. Requiring the field is load-bearing, and was missing until issue #25: while
    `batch_id` was merely checked-if-present, a record that omitted it from all three entries
    passed. Each backend entry's `test_file` must equal the suite that backend's gate
    actually runs (`_TEST_FILES[backend]`); a record whose entries were hand-copied from a
    different backend's run is rejected on this check.

Pure stdlib (no deps): this script must run in any environment without extra setup.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_PATH = Path(".release-evidence/live-gates.json")
FAILURE_PATH = Path(".release-evidence/live-gates.failed.json")

BACKENDS = ("codex", "kimi", "claude")

_TEST_FILES = {name: f"tests/test_{name}_live.py" for name in BACKENDS}
_BINARY_ENV_VARS = {
    "codex": "AMICUS_CODEX_BIN",
    "kimi": "AMICUS_KIMI_BIN",
    "claude": "AMICUS_CLAUDE_BIN",
}

_REQUIRED_TOP_LEVEL_FIELDS = ("batch_id", "recorded_at", "commit", "tree_clean", "backends")
_REQUIRED_BACKEND_FIELDS = ("test_file", "exit_status", "cli_version", "batch_id")

# The outcome enums a JUnit `<testcase>` can carry as a child element. Anything else is a pass.
_NOT_PASSED_OUTCOMES = ("failure", "error", "skipped")

# The ONLY keys `_summarize_junit` may put in the record, and the reason this is an allowlist
# rather than a denylist: a JUnit report also carries `message` and `type` attributes, element
# text (the traceback), and `<system-out>`/`<system-err>` sections, every one of which can hold
# model prose or an echoed prompt. Reading tag names and integers cannot reach any of them.
# `tests/test_live_gate_report.py` proves it on a report built to be full of prose.
_REPORT_KEYS = ("total", "not_passed", "counts")

# A version string is one short line. The longest seen in practice is "codex-cli 0.153.4"; the
# cap is generous against that and still bounds a wrapper that prints something else entirely.
_VERSION_MAX_CHARS = 120


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True)


def _git_head() -> str:
    return _git("rev-parse", "HEAD").stdout.strip()


def _git_dirty_paths() -> list[str]:
    status = _git("status", "--porcelain").stdout
    return [line for line in status.splitlines() if line.strip()]


def _cli_version(backend: str) -> str | None:
    """The backend CLI's own `--version` output, resolved the way the live-ready probe does:
    an AMICUS_<BACKEND>_BIN override, else the bare binary name on PATH."""
    binary = os.environ.get(_BINARY_ENV_VARS[backend], backend)
    resolved = shutil.which(binary) or binary
    try:
        proc = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return _bound_version(proc.stdout)


def _bound_version(raw: str) -> str | None:
    """The first line of `--version` output, length-capped and stripped of control characters.

    The binary is whatever `AMICUS_<BACKEND>_BIN` names, so its stdout is not this repository's
    to trust: a wrapper script can print anything, and whatever it prints lands in a file under
    `.release-evidence/`. A version string is one short line; taking only that, and only its
    printable characters, keeps an unexpected payload out of the record without pretending to
    know every CLI's exact format.
    """
    first_line = raw.strip().splitlines()[0] if raw.strip() else ""
    printable = "".join(ch for ch in first_line if ch.isprintable())
    return printable[:_VERSION_MAX_CHARS].strip() or None


def _summarize_junit(xml_path: Path) -> dict[str, object] | None:
    """Reduce a JUnit report to node ids and counts, reading tag names and integers only.

    Never reads an element's text or its `message`/`type` attributes, and never looks at
    `<system-out>`/`<system-err>`: those carry the traceback and the captured output, which is
    where a model's prose or an echoed prompt would be. What comes back is which test did not
    pass and how it did not pass — enough to rerun that one test instead of respending on all
    three suites, and not enough to leak anything (AGENTS.md rule 18).
    """
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (OSError, ElementTree.ParseError):
        return None

    not_passed: list[dict[str, str]] = []
    counts = dict.fromkeys(_NOT_PASSED_OUTCOMES, 0)
    total = 0
    for case in root.iter("testcase"):
        total += 1
        outcome = next((child.tag for child in case if child.tag in _NOT_PASSED_OUTCOMES), None)
        if outcome is None:
            continue
        counts[outcome] += 1
        # `classname` and `name` are pytest's own identifiers, not model output.
        not_passed.append(
            {
                "test": f"{case.get('classname', '')}::{case.get('name', '')}",
                "outcome": outcome,
            }
        )
    return {"total": total, "counts": counts, "not_passed": not_passed}


def _run_backend_gate(backend: str, batch_id: str) -> dict[str, object]:
    test_file = _TEST_FILES[backend]
    print(f"[{backend}] running {test_file} (AMICUS_REQUIRE_LIVE=1, -m integration) ...")
    env = dict(os.environ)
    env["AMICUS_REQUIRE_LIVE"] = "1"
    with tempfile.TemporaryDirectory() as tmp:
        # The report is read, reduced and discarded with the temp dir; only the reduction is
        # ever written to `.release-evidence/`.
        report = Path(tmp) / "junit.xml"
        proc = subprocess.run(
            [
                "uv",
                "run",
                "pytest",
                "-m",
                "integration",
                "--no-cov",
                f"--junitxml={report}",
                test_file,
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )
        summary = _summarize_junit(report)
    status = "PASSED" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"[{backend}] {status}")
    if summary is not None and summary["not_passed"]:
        for entry in summary["not_passed"]:  # type: ignore[union-attr]
            print(f"[{backend}]   {entry['outcome']}: {entry['test']}")
    entry_record: dict[str, object] = {
        "test_file": test_file,
        "exit_status": proc.returncode,
        "cli_version": _cli_version(backend),
        "batch_id": batch_id,
    }
    if summary is not None:
        entry_record["report"] = summary
    return entry_record


def _write_json(repo_root: Path, path: Path, payload: dict[str, object]) -> None:
    full_path = repo_root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(
    argv: list[str] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    git_head: Callable[[], str] = _git_head,
    git_dirty_paths: Callable[[], list[str]] = _git_dirty_paths,
    run_gate: Callable[[str, str], dict[str, object]] = _run_backend_gate,
) -> int:
    """Run all three live gates and write EVIDENCE_PATH or FAILURE_PATH under `repo_root`.

    `git_head`, `git_dirty_paths` and `run_gate` are injectable seams: tests substitute fakes
    here (no real git repo, no subprocess, no live backend) to exercise the all-or-nothing
    write logic, the dirty-tree refusal and the failure-diagnostics path hermetically. The
    default arguments are what a real release run uses.
    """
    del argv  # this script takes no arguments

    dirty = git_dirty_paths()
    if dirty:
        print("refusing to run: the working tree is dirty:", file=sys.stderr)
        for line in dirty:
            print(f"  {line}", file=sys.stderr)
        return 1

    commit = git_head()
    batch_id = uuid.uuid4().hex
    backends: dict[str, dict[str, object]] = {}
    for backend in BACKENDS:
        backends[backend] = run_gate(backend, batch_id)

    all_passed = all(entry["exit_status"] == 0 for entry in backends.values())
    tree_clean_after = not git_dirty_paths()

    record = {
        "batch_id": batch_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "tree_clean": tree_clean_after,
        "backends": backends,
    }

    if all_passed and tree_clean_after:
        _write_json(repo_root, EVIDENCE_PATH, record)
        print(f"wrote {EVIDENCE_PATH}: all three live gates passed on {commit}.")
        return 0

    _write_json(repo_root, FAILURE_PATH, record)
    if not all_passed:
        failed = [name for name, entry in backends.items() if entry["exit_status"] != 0]
        print(f"one or more live gates failed: {', '.join(failed)}.", file=sys.stderr)
    if not tree_clean_after:
        print("the working tree became dirty during the run.", file=sys.stderr)
    print(
        f"wrote {FAILURE_PATH} for diagnosis; {EVIDENCE_PATH} was left untouched.",
        file=sys.stderr,
    )
    return 1


def _check_commit(record: dict, head: str) -> list[str]:
    commit = record.get("commit")
    if isinstance(commit, str):
        if commit != head:
            return [f"record commit {commit!r} does not match HEAD {head!r}"]
        return []
    if "commit" in record:
        return ["record 'commit' is not a string"]
    return []


def _check_tree_clean(record: dict, tree_clean: bool) -> list[str]:
    problems: list[str] = []
    if not tree_clean:
        problems.append("the working tree is not clean right now; evidence cannot be trusted")
    if "tree_clean" in record and record.get("tree_clean") is not True:
        problems.append("record was taken on a dirty tree ('tree_clean' is not true)")
    return problems


def _check_batch_id(record: dict) -> list[str]:
    batch_id = record.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id:
        return [f"record 'batch_id' must be a non-empty string, got {batch_id!r}"]
    return []


def _check_backends(record: dict) -> list[str]:
    problems: list[str] = []
    backends = record.get("backends")
    if not isinstance(backends, dict):
        if "backends" in record:
            problems.append("record 'backends' is not an object")
        backends = {}

    record_batch_id = record.get("batch_id")

    for name in BACKENDS:
        entry = backends.get(name)
        if entry is None:
            problems.append(f"record is missing an entry for backend '{name}'")
            continue
        if not isinstance(entry, dict):
            problems.append(f"record entry for backend '{name}' is not an object")
            continue
        for field in _REQUIRED_BACKEND_FIELDS:
            if field not in entry:
                problems.append(f"record entry for backend '{name}' is missing '{field}'")
        exit_status = entry.get("exit_status")
        if "exit_status" in entry and exit_status != 0:
            problems.append(f"backend '{name}' exit_status is {exit_status!r}, not 0")
        test_file = entry.get("test_file")
        if "test_file" in entry and test_file != _TEST_FILES[name]:
            problems.append(
                f"backend '{name}' test_file is {test_file!r}, expected {_TEST_FILES[name]!r}"
            )
        entry_batch_id = entry.get("batch_id")
        if "batch_id" in entry and entry_batch_id != record_batch_id:
            problems.append(
                f"backend '{name}' batch_id {entry_batch_id!r} does not match "
                f"record batch_id {record_batch_id!r}"
            )
    return problems


def _check_recorded_at(record: dict, now: datetime, max_age_hours: int) -> list[str]:
    recorded_at = record.get("recorded_at")
    if not isinstance(recorded_at, str):
        if "recorded_at" in record:
            return ["record 'recorded_at' is not a string"]
        return []

    try:
        parsed = datetime.fromisoformat(recorded_at)
    except ValueError:
        return [f"record 'recorded_at' is not a valid ISO 8601 timestamp: {recorded_at!r}"]

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age_seconds = (now - parsed).total_seconds()
    if age_seconds < 0:
        return ["record 'recorded_at' is in the future"]
    if age_seconds > max_age_hours * 3600:
        hours = age_seconds / 3600
        return [f"record is too old: recorded {hours:.1f}h ago, max age is {max_age_hours}h"]
    return []


def validate_record(record: dict, *, head: str, tree_clean: bool) -> list[str]:
    """Every check on an evidence record EXCEPT freshness.

    Split out of `validate` so `scripts/check_release_state.py` can reuse it in the publish
    workflow, where freshness must not be applied: a tag is immutable, so queue time or a slow
    deployment approval could otherwise turn a legitimate tag into one that can never be
    published. Freshness belongs to the local pre-tag procedure, where a stale record can
    still be replaced by re-running the gates.
    """
    if not isinstance(record, dict):
        return ["record is not a JSON object"]

    problems: list[str] = [
        f"record is missing required field '{field}'"
        for field in _REQUIRED_TOP_LEVEL_FIELDS
        if field not in record
    ]
    problems += _check_commit(record, head)
    problems += _check_tree_clean(record, tree_clean)
    problems += _check_batch_id(record)
    problems += _check_backends(record)
    return problems


def validate(
    record: dict, *, head: str, tree_clean: bool, now: datetime, max_age_hours: int = 24
) -> list[str]:
    """Check a live-gate evidence record against the facts of the run about to tag it.

    Pure: reads only its arguments, never the filesystem, never shells out. This is what makes
    the negative controls in tests/test_release_evidence.py ordinary unit tests instead of
    manual mutations of a file on disk.

    Returns a list of human-readable problems; an empty list means the record is usable release
    evidence -- i.e. it shows all three live gates (codex, kimi, claude) PASSED, on this exact
    commit, on a clean tree, recently enough to still be trustworthy, each backend entry
    naming the suite that backend's gate actually runs (`test_file` matches `_TEST_FILES`),
    and all three entries sharing the record's own `batch_id` -- proof they came from the
    same run rather than a hand-repaired mix of entries from different runs.
    """
    problems = validate_record(record, head=head, tree_clean=tree_clean)
    if not isinstance(record, dict):
        return problems
    problems += _check_recorded_at(record, now, max_age_hours)
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
