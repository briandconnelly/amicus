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

Pure stdlib (no deps): this script must run in any environment without extra setup.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
_REQUIRED_BACKEND_FIELDS = ("test_file", "exit_status", "cli_version")


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
    return proc.stdout.strip() or None


def _run_backend_gate(backend: str) -> dict[str, object]:
    test_file = _TEST_FILES[backend]
    print(f"[{backend}] running {test_file} (AMICUS_REQUIRE_LIVE=1, -m integration) ...")
    env = dict(os.environ)
    env["AMICUS_REQUIRE_LIVE"] = "1"
    proc = subprocess.run(
        ["uv", "run", "pytest", "-m", "integration", "--no-cov", test_file],
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    status = "PASSED" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"[{backend}] {status}")
    return {
        "test_file": test_file,
        "exit_status": proc.returncode,
        "cli_version": _cli_version(backend),
    }


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
    run_gate: Callable[[str], dict[str, object]] = _run_backend_gate,
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
        backends[backend] = run_gate(backend)

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


def _check_backends(record: dict) -> list[str]:
    problems: list[str] = []
    backends = record.get("backends")
    if not isinstance(backends, dict):
        if "backends" in record:
            problems.append("record 'backends' is not an object")
        backends = {}

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


def validate(
    record: dict, *, head: str, tree_clean: bool, now: datetime, max_age_hours: int = 24
) -> list[str]:
    """Check a live-gate evidence record against the facts of the run about to tag it.

    Pure: reads only its arguments, never the filesystem, never shells out. This is what makes
    the negative controls in tests/test_release_evidence.py ordinary unit tests instead of
    manual mutations of a file on disk.

    Returns a list of human-readable problems; an empty list means the record is usable release
    evidence -- i.e. it shows all three live gates (codex, kimi, claude) PASSED, on this exact
    commit, on a clean tree, recently enough to still be trustworthy.
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
    problems += _check_backends(record)
    problems += _check_recorded_at(record, now, max_age_hours)
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
