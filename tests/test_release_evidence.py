"""The release-evidence record is checked by `validate`, so these controls are real tests.

The record itself is a gitignored local file a maintainer can hand-write, so it proves
nothing against a determined author. It is an honest-mistake guard: it catches evidence
taken on the wrong commit, on a dirty tree, from a partial run, too long ago, or hand-repaired
from a mix of entries that never ran together (a missing/mismatched `batch_id`) or against
the wrong suite (a `test_file` that does not match the backend it is filed under). Every
rejection path below is exercised, because a validator that cannot fail is not a check.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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
                "batch_id": "b" * 32,
            }
            for name in evidence.BACKENDS
        },
    }
    record.update(overrides)
    return record


def test_a_complete_fresh_record_is_accepted():
    assert evidence.validate(_record(), head=HEAD, tree_clean=True, now=NOW) == []


def test_a_record_whose_entries_omit_batch_id_entirely_is_rejected():
    """The gap issue #25 found: `batch_id` was checked only when present.

    A record that simply left the field out of all three entries validated clean, so the
    property the docstring claimed -- one shared run produced this whole record -- was not
    actually checkable. Omission and disagreement must both be rejected; the test below covers
    disagreement.
    """
    record = _record()
    for entry in record["backends"].values():
        del entry["batch_id"]
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert [p for p in problems if "batch_id" in p], problems


def test_validate_record_accepts_a_stale_record_that_validate_rejects():
    """The split `validate` relies on: everything but freshness.

    `scripts/check_release_state.py` uses `validate_record` in the publish workflow precisely
    so an immutable tag cannot age out of publishability between the push and the deployment
    approval.
    """
    stale = _record(recorded_at=(NOW - timedelta(days=400)).isoformat())
    assert evidence.validate_record(stale, head=HEAD, tree_clean=True) == []
    assert evidence.validate(stale, head=HEAD, tree_clean=True, now=NOW) != []


def test_validate_record_still_rejects_a_failed_suite():
    """The negative control for the split: dropping freshness dropped nothing else."""
    record = _record()
    record["backends"]["codex"]["exit_status"] = 1
    assert evidence.validate_record(record, head=HEAD, tree_clean=True) != []


@pytest.mark.parametrize("bad", [123, None, "not-a-date", "2026-13-45T99:00:00", ""])
def test_validate_record_rejects_a_malformed_recorded_at(bad):
    """The "except freshness" promise covers the age limit only, not the shape.

    A `recorded_at` that is not a parseable timestamp is a broken record whoever reads it, and
    dropping the age check at publish time must not drop that too.
    """
    problems = evidence.validate_record(_record(recorded_at=bad), head=HEAD, tree_clean=True)
    assert [p for p in problems if "recorded_at" in p], problems


def test_validate_does_not_report_a_malformed_timestamp_twice():
    problems = evidence.validate(_record(recorded_at=123), head=HEAD, tree_clean=True, now=NOW)
    assert len([p for p in problems if "recorded_at" in p]) == 1, problems


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


@pytest.mark.parametrize("bad", [123, None, ["a" * 40], {"sha": "a" * 40}])
def test_a_non_string_commit_is_rejected(bad):
    """Issue #19 item 1: `_check_commit`'s wrong-type branch, which a missing `commit` never
    reaches (that is reported as a missing required field instead)."""
    problems = evidence.validate(_record(commit=bad), head=HEAD, tree_clean=True, now=NOW)
    assert "record 'commit' is not a string" in problems, problems


@pytest.mark.parametrize("bad", [[], "codex kimi claude", None, 0])
def test_a_non_object_backends_is_rejected(bad):
    """Issue #19 item 1: a present `backends` that is not an object is named as such, and
    still leaves every backend reported missing rather than raising."""
    problems = evidence.validate(_record(backends=bad), head=HEAD, tree_clean=True, now=NOW)
    assert "record 'backends' is not an object" in problems, problems
    for name in evidence.BACKENDS:
        assert f"record is missing an entry for backend '{name}'" in problems, problems


@pytest.mark.parametrize("bad", [[], "passed", 0, True])
def test_a_non_object_backend_entry_is_rejected(bad):
    """Issue #19 item 1: an entry that is not an object is rejected by name, and only that
    backend is: the other two entries are still read and still pass."""
    record = _record()
    record["backends"]["kimi"] = bad
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert problems == ["record entry for backend 'kimi' is not an object"], problems


def test_a_future_timestamp_is_rejected():
    record = _record(recorded_at=(NOW + timedelta(hours=2)).isoformat())
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert problems, "a record from the future is a clock or forgery problem, not evidence"


def test_a_missing_batch_id_is_rejected():
    record = _record()
    del record["batch_id"]
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("batch_id" in p for p in problems), problems


def test_an_empty_batch_id_is_rejected():
    problems = evidence.validate(_record(batch_id=""), head=HEAD, tree_clean=True, now=NOW)
    assert any("batch_id" in p for p in problems), problems


def test_a_non_string_batch_id_is_rejected():
    problems = evidence.validate(_record(batch_id=0), head=HEAD, tree_clean=True, now=NOW)
    assert any("batch_id" in p for p in problems), problems


def test_a_backend_entry_with_a_mismatched_batch_id_is_rejected():
    record = _record()
    record["backends"]["kimi"]["batch_id"] = "different-batch"
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("kimi" in p and "batch_id" in p for p in problems), problems


def test_a_backend_entry_with_the_wrong_test_file_is_rejected():
    record = _record()
    record["backends"]["codex"]["test_file"] = "tests/test_kimi_live.py"
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("codex" in p and "test_file" in p for p in problems), problems


def test_a_codex_entry_duplicated_from_kimis_is_rejected():
    """The honest-mistake case the module docstring calls out: hand-repairing a record after
    one gate failed by copying a sibling backend's entry instead of re-running the gate."""
    record = _record()
    record["backends"]["codex"] = dict(record["backends"]["kimi"])
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("codex" in p and "test_file" in p for p in problems), problems


# --- main(): hermetic coverage of the all-or-nothing write logic, injected instead of shelling
# out. No real git repo mutation and no `-m integration` anywhere below.


VERSION = "9.9.9"
_ARGV = ["--version", VERSION]
# The wrong-checkout seams, answering as the release worktree for VERSION would.
_RELEASE_TREE = {"declared_version": lambda: VERSION, "tag_exists": lambda tag: False}


def _passing_gate(backend, batch_id):
    return {
        "test_file": f"tests/test_{backend}_live.py",
        "exit_status": 0,
        "cli_version": "x 1.0",
        "batch_id": batch_id,
    }


def _failing_gate(failing_backend):
    def run_gate(backend, batch_id):
        exit_status = 1 if backend == failing_backend else 0
        return {
            "test_file": f"tests/test_{backend}_live.py",
            "exit_status": exit_status,
            "cli_version": "x 1.0",
            "batch_id": batch_id,
        }

    return run_gate


def test_main_writes_evidence_when_all_three_pass_on_a_clean_tree(tmp_path):
    rc = evidence.main(
        _ARGV,
        repo_root=tmp_path,
        **_RELEASE_TREE,
        git_head=lambda: HEAD,
        git_dirty_paths=list,
        run_gate=_passing_gate,
    )
    assert rc == 0
    evidence_path = tmp_path / evidence.EVIDENCE_PATH
    failure_path = tmp_path / evidence.FAILURE_PATH
    assert evidence_path.exists()
    assert not failure_path.exists()
    record = json.loads(evidence_path.read_text())
    assert record["commit"] == HEAD
    assert set(record["backends"]) == set(evidence.BACKENDS)
    batch_ids = {record["batch_id"]} | {entry["batch_id"] for entry in record["backends"].values()}
    assert batch_ids == {record["batch_id"]}, "one batch_id must be shared by every entry"
    assert evidence.validate(record, head=HEAD, tree_clean=True, now=datetime.now(UTC)) == []


def test_main_writes_failure_not_evidence_when_one_backend_fails(tmp_path):
    rc = evidence.main(
        _ARGV,
        repo_root=tmp_path,
        **_RELEASE_TREE,
        git_head=lambda: HEAD,
        git_dirty_paths=list,
        run_gate=_failing_gate("kimi"),
    )
    assert rc == 1
    assert not (tmp_path / evidence.EVIDENCE_PATH).exists()
    failure_path = tmp_path / evidence.FAILURE_PATH
    assert failure_path.exists()
    record = json.loads(failure_path.read_text())
    assert record["backends"]["kimi"]["exit_status"] == 1
    assert record["backends"]["codex"]["exit_status"] == 0


def test_main_does_not_clobber_a_stale_success_file_on_a_failed_run(tmp_path):
    evidence_path = tmp_path / evidence.EVIDENCE_PATH
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    stale_bytes = b'{"commit": "stale-from-an-earlier-run"}\n'
    evidence_path.write_bytes(stale_bytes)

    rc = evidence.main(
        _ARGV,
        repo_root=tmp_path,
        **_RELEASE_TREE,
        git_head=lambda: HEAD,
        git_dirty_paths=list,
        run_gate=_failing_gate("claude"),
    )

    assert rc == 1
    assert evidence_path.read_bytes() == stale_bytes, "a failed run must not touch EVIDENCE_PATH"
    assert (tmp_path / evidence.FAILURE_PATH).exists()


def test_main_refuses_on_a_dirty_tree_before_running_anything(tmp_path, capsys):
    calls: list[str] = []

    def run_gate(backend, batch_id):
        calls.append(backend)
        return _passing_gate(backend, batch_id)

    rc = evidence.main(
        _ARGV,
        repo_root=tmp_path,
        **_RELEASE_TREE,
        git_head=lambda: HEAD,
        git_dirty_paths=lambda: [" M dirty_file.py", "?? untracked.py"],
        run_gate=run_gate,
    )

    assert rc == 1
    assert calls == [], "no gate should run when the tree starts dirty"
    assert not (tmp_path / evidence.EVIDENCE_PATH).exists()
    assert not (tmp_path / evidence.FAILURE_PATH).exists()
    err = capsys.readouterr().err
    assert "dirty_file.py" in err
    assert "untracked.py" in err


def _never_called(label: str, calls: list[str]):
    def fake(*args):
        calls.append(label)
        raise AssertionError(f"{label} ran; argument parsing must finish before anything else")

    return fake


@pytest.mark.parametrize(
    ("argv", "expected_rc"),
    [
        (["--help"], 0),
        (["-h"], 0),
        (["--he"], 0),
        (["--bogus", "--help"], 0),
        (["--bogus"], 2),
        (["extra-positional"], 2),
        ([], 2),
        (["--version"], 2),
        (["--version", "1.2"], 2),
        (["--version", "v1.2.3"], 2),
        (["--version", "1.2.3rc1"], 2),
        (["--version", "1.2.3", "extra-positional"], 2),
    ],
)
def test_main_parses_arguments_before_touching_git_or_any_gate(tmp_path, argv, expected_rc):
    """Issue #242: `--help` used to start all three live gates, because `main` ignored argv.

    Neither git nor any gate may run for `--help` or for an argument the script does not
    accept, and neither may write a record.
    """
    calls: list[str] = []
    rc = evidence.main(
        argv,
        repo_root=tmp_path,
        git_head=_never_called("git_head", calls),
        git_dirty_paths=_never_called("git_dirty_paths", calls),
        run_gate=_never_called("run_gate", calls),
        declared_version=_never_called("declared_version", calls),
        tag_exists=_never_called("tag_exists", calls),
    )

    assert rc == expected_rc
    assert calls == []
    assert not (tmp_path / evidence.EVIDENCE_PATH).exists()
    assert not (tmp_path / evidence.FAILURE_PATH).exists()


def _refused_before_any_gate(tmp_path, capsys, **seams):
    """Run main as the release tree would, with `seams` overridden; return stderr.

    Asserts the run was refused with exit 1 before any gate ran or any record was written.
    """
    calls: list[str] = []
    rc = evidence.main(
        _ARGV,
        repo_root=tmp_path,
        git_head=lambda: HEAD,
        git_dirty_paths=list,
        run_gate=_never_called("run_gate", calls),
        **{**_RELEASE_TREE, **seams},
    )
    assert rc == 1
    assert calls == []
    assert not (tmp_path / evidence.EVIDENCE_PATH).exists()
    assert not (tmp_path / evidence.FAILURE_PATH).exists()
    return capsys.readouterr().err


def test_main_refuses_in_a_checkout_declaring_another_version(tmp_path, capsys):
    """Issue #241: the main checkout between releases still declares the previous release."""
    err = _refused_before_any_gate(tmp_path, capsys, declared_version=lambda: "9.9.8")
    assert "declares version 9.9.8, not 9.9.9" in err
    assert "worktree" in err


def test_main_refuses_when_the_release_tag_already_exists(tmp_path, capsys):
    asked: list[str] = []

    def tag_exists(tag):
        asked.append(tag)
        return True

    err = _refused_before_any_gate(tmp_path, capsys, tag_exists=tag_exists)
    assert asked == ["v9.9.9"]
    assert "v9.9.9 already exists" in err
    assert "git tag -d v9.9.9" in err


def _raises(exc):
    def fake(*args):
        raise exc

    return fake


@pytest.mark.parametrize(
    "exc", [FileNotFoundError("pyproject.toml"), KeyError("project"), ValueError("bad toml")]
)
def test_main_refuses_when_the_declared_version_cannot_be_read(tmp_path, capsys, exc):
    err = _refused_before_any_gate(tmp_path, capsys, declared_version=_raises(exc))
    assert "cannot read this checkout's declared version" in err


@pytest.mark.parametrize(
    "exc", [subprocess.CalledProcessError(128, ["git"]), FileNotFoundError("git")]
)
def test_main_refuses_when_the_tag_lookup_fails(tmp_path, capsys, exc):
    """A failed lookup is not an absent tag: treating it as one would let the run go on."""
    err = _refused_before_any_gate(tmp_path, capsys, tag_exists=_raises(exc))
    assert "cannot tell whether the tag v9.9.9 exists" in err


def test_the_declared_version_is_this_checkouts_project_version():
    import tomllib

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert evidence._declared_version() == expected


def test_tag_exists_sees_annotated_and_lightweight_tags_only_when_present(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c")
    git("tag", "v1.0.0")
    git("-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v1.1.0", "-m", "record")
    monkeypatch.setattr(evidence, "REPO_ROOT", tmp_path)

    assert evidence._tag_exists("v1.0.0") is True
    assert evidence._tag_exists("v1.1.0") is True
    assert evidence._tag_exists("v1.2.0") is False


def test_tag_exists_raises_outside_a_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(subprocess.CalledProcessError):
        evidence._tag_exists("v1.0.0")


def test_help_describes_the_spend(tmp_path, capsys):
    calls: list[str] = []
    rc = evidence.main(
        ["--help"],
        repo_root=tmp_path,
        git_head=_never_called("git_head", calls),
        git_dirty_paths=_never_called("git_dirty_paths", calls),
        run_gate=_never_called("run_gate", calls),
        declared_version=_never_called("declared_version", calls),
        tag_exists=_never_called("tag_exists", calls),
    )
    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert out.startswith("usage: record_live_gate_evidence.py")
    assert "AMICUS_REQUIRE_LIVE=1" in out
    assert "--version X.Y.Z" in out
    assert "quota" in out


def test_the_script_entry_point_passes_its_command_line_to_main(tmp_path):
    """The entry point, not only `main`, must hand over argv: before #242 it called `main()`.

    PATH names an empty directory, so if `--help` were ignored again the script would fail at
    its first `git` call with no `uv`, `codex`, `kimi` or `claude` reachable, rather than spend.
    """
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env={"PATH": str(tmp_path)},
        timeout=30,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("usage: record_live_gate_evidence.py")


@pytest.mark.skipif(
    os.environ.get("AMICUS_RELEASE_CHECK") != "1",
    reason="release-only: reads the gitignored evidence file, which CI cannot have",
)
def test_the_recorded_evidence_covers_this_exact_commit():
    """Run with AMICUS_RELEASE_CHECK=1 on the commit about to be tagged."""
    path = Path(__file__).resolve().parent.parent / evidence.EVIDENCE_PATH
    assert path.exists(), (
        f"no live-gate evidence at {path}; run scripts/record_live_gate_evidence.py --version X.Y.Z"
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
