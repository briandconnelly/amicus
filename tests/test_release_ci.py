"""`scripts/release.py ci`: the AGENTS.md rule-2 gate as CI ran it on the release commit.

The release steps read the gate's result from GitHub rather than running it again by hand
(docs/RELEASING.md step 3). `gh api` is stubbed; the gate's job names are read from the
repository's own workflows, so a change to them that this no longer reads fails here.

The positive control runs first, so a broken stub cannot make a refusal pass vacuously.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("release", _SCRIPTS / "release.py")
assert _spec is not None and _spec.loader is not None
release = importlib.util.module_from_spec(_spec)
sys.modules["release"] = release
_spec.loader.exec_module(release)

REPO = Path(__file__).resolve().parent.parent
SHA = "a" * 40
GATE = release.gate_checks(REPO)
PATH = f"repos/{release.REPOSITORY}/commits/{SHA}/check-runs?per_page=100"


def _run(name: str, run_id: int, status="completed", conclusion="success") -> dict:
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/{release.REPOSITORY}/runs/{run_id}",
    }


class FakeGh:
    """`gh api --paginate --slurp` for the check runs on SHA; anything else fails the test."""

    def __init__(self, pages: list[list[dict]], returncode: int = 0):
        self.pages = [{"total_count": len(page), "check_runs": page} for page in pages]
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        cmd = [str(part) for part in cmd]
        self.calls.append(cmd)
        assert cmd == ["gh", "api", "--paginate", "--slurp", PATH], cmd
        return subprocess.CompletedProcess(
            cmd, self.returncode, json.dumps(self.pages), "gh: Not Found (HTTP 404)\n"
        )


MAIN = "b" * 40


class FakeGit:
    """The fetch of origin's main and the two questions asked of it; anything else fails."""

    def __init__(self, *, fetch: int = 0, contained: int = 0):
        self.fetch = fetch
        self.contained = contained
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        cmd = [str(part) for part in cmd]
        self.calls.append(cmd)
        if cmd[:2] == ["git", "fetch"]:
            assert cmd[-1] == "+refs/heads/main:refs/remotes/origin/main", cmd
            return subprocess.CompletedProcess(cmd, self.fetch, "", "fatal: unreachable\n")
        if cmd == ["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}"]:
            return subprocess.CompletedProcess(cmd, 0, MAIN + "\n", "")
        if cmd == ["git", "merge-base", "--is-ancestor", MAIN, SHA]:
            return subprocess.CompletedProcess(cmd, self.contained, "", "")
        raise AssertionError(f"unexpected git {cmd!r}")


def _ci(run: FakeGh, sha: str = SHA, git: FakeGit | None = None) -> int:
    ctx = release.Context(repo_root=REPO, run=run, git=git or FakeGit())
    return release.main(["ci", "--sha", sha], context=ctx)


def _passing(start: int = 1) -> list[dict]:
    return [_run(name, start + n) for n, name in enumerate(GATE)]


# --- positive control ------------------------------------------------------------------


def test_every_gate_job_passing_passes_and_names_them(capsys):
    others = [_run("analyze (python)", 90, conclusion="failure"), _run("test / marketplace", 91)]
    # Two pages, as --paginate --slurp gives them, with other checks around the gate's.
    run = FakeGh([[*_passing()[:2], others[0]], [*_passing()[2:], others[1]]])
    git = FakeGit()
    assert _ci(run, git=git) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert all(name in out.out for name in GATE)
    assert len(run.calls) == 1
    assert ["git", "merge-base", "--is-ancestor", MAIN, SHA] in git.calls


def test_the_gate_is_one_job_per_python_version_ci_tests():
    """Read from the workflows: every version in the matrix, under the job ci.yml calls."""
    workflow = (REPO / release.GATE_WORKFLOW).read_text(encoding="utf-8")
    assert len(GATE) >= 2
    for name in GATE:
        assert name.startswith("test / lint + types + tests (py3."), name
        assert f'"{name.rsplit("(py", 1)[1].rstrip(")")}"' in workflow, name


# --- refusals ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"status": "in_progress", "conclusion": None}, "still in_progress"),
        ({"status": "queued", "conclusion": None}, "still queued"),
        ({"conclusion": "failure"}, "failure (https://github.com/"),
        ({"conclusion": "cancelled"}, "cancelled"),
        ({"conclusion": "skipped"}, "skipped"),
    ],
)
def test_a_gate_job_that_has_not_succeeded_fails(capsys, change, reason):
    runs = _passing()
    runs[-1] = {**runs[-1], **change}
    assert _ci(FakeGh([runs])) == 1
    err = capsys.readouterr().err
    assert "has NOT passed" in err
    assert f"{GATE[-1]}: {reason}" in err


def test_a_gate_job_that_never_ran_fails():
    assert _ci(FakeGh([_passing()[1:]])) == 1


def test_no_check_runs_at_all_fails_rather_than_passing_vacuously(capsys):
    assert _ci(FakeGh([[]])) == 1
    assert capsys.readouterr().err.count("has not run on") == len(GATE)


def test_the_newest_run_of_a_job_decides():
    failed_then_passed = [_run(GATE[0], 1, conclusion="failure"), *_passing(start=10)]
    assert _ci(FakeGh([failed_then_passed])) == 0
    passed_then_failed = [*_passing(start=10), _run(GATE[0], 99, conclusion="failure")]
    assert _ci(FakeGh([passed_then_failed])) == 1


def test_ci_on_a_release_main_has_moved_past_did_not_test_its_tree(capsys):
    """Copilot on #580: CI on a pull request tests the head merged with main. Only when main
    is in the release commit's history is that merge the release commit's own tree."""
    assert _ci(FakeGh([_passing()]), git=FakeGit(contained=1)) == 1
    err = capsys.readouterr().err
    assert f"origin/main ({MAIN}) is not in {SHA}'s history" in err
    assert "needs new evidence" in err


@pytest.mark.parametrize(
    ("git", "reason"),
    [
        (FakeGit(fetch=128), "`git fetch origin` failed"),
        (FakeGit(contained=128), "could not tell whether origin/main"),
    ],
)
def test_a_tree_that_cannot_be_checked_fails(capsys, git, reason):
    assert _ci(FakeGh([_passing()]), git=git) == 1
    assert reason in capsys.readouterr().err


def test_a_failed_lookup_fails(capsys):
    assert _ci(FakeGh([], returncode=1)) == 1
    assert "could not read the check runs" in capsys.readouterr().err


@pytest.mark.parametrize("sha", ["abc123", "A" * 40, "HEAD"])
def test_only_a_full_sha_is_looked_up(capsys, sha):
    run = FakeGh([_passing()])
    assert _ci(run, sha) == 1
    assert run.calls == []
    assert "is not a full commit SHA" in capsys.readouterr().err


def test_workflows_this_cannot_read_fail_rather_than_guess(tmp_path, capsys):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("jobs:\n  test:\n    uses: ./.github/workflows/test.yml\n")
    (workflows / "test.yml").write_text("jobs:\n  gate:\n    name: tests\n")
    with pytest.raises(ValueError, match="matrix"):
        release.gate_checks(tmp_path)
    run = FakeGh([_passing()])
    ctx = release.Context(repo_root=tmp_path, run=run, git=FakeGit())
    assert release.main(["ci", "--sha", SHA], context=ctx) == 1
    assert run.calls == []
    assert "could not tell which jobs are the gate" in capsys.readouterr().err


@pytest.mark.parametrize("edit", ["include", "exclude"])
def test_a_matrix_with_include_or_exclude_is_refused_rather_than_read_short(tmp_path, edit):
    """Copilot on #580: a version moved into `include` still runs a job the list omits."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text((REPO / release.CI_WORKFLOW).read_text())
    gate = (REPO / release.GATE_WORKFLOW).read_text()
    listed = '        python-version: ["3.11", "3.12", "3.13", "3.14", "3.15"]\n'
    assert gate.count(listed) == 1, "the fixture edits the committed matrix"
    moved = '        python-version: ["3.11", "3.12", "3.13", "3.14"]\n'
    moved += f'        {edit}:\n          - python-version: "3.15"\n'
    (workflows / "test.yml").write_text(gate.replace(listed, moved))
    with pytest.raises(ValueError, match="include or exclude"):
        release.gate_checks(tmp_path)
    # The committed workflow, unedited, reads as before.
    (workflows / "test.yml").write_text(gate)
    assert release.gate_checks(tmp_path) == GATE


def test_only_the_gate_jobs_own_matrix_and_name_are_read(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text((REPO / release.CI_WORKFLOW).read_text())
    gate = (REPO / release.GATE_WORKFLOW).read_text()
    # Another job's include, after the gate job, is not the gate's.
    other = "\n  other:\n    name: other\n    strategy:\n      matrix:\n        include:\n"
    (workflows / "test.yml").write_text(gate + other + "          - x: 1\n")
    assert release.gate_checks(tmp_path) == GATE
