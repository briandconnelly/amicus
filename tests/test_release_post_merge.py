"""`scripts/release.py post-merge`: the checks between the release merge and the tag push (#377).

The fixture is real git with three repositories: a bare `origin`, the release PR's checkout
(where the evidence record and the local annotated tag live, as after RELEASING step 3), and a
`github` clone that stands in for GitHub merging the PR. Because the merge is pushed from that
other clone, the release checkout's `origin/main` is stale until `post-merge` fetches it, the
way it is after `gh pr merge`. Only `check_release_state.py` is stubbed.

The positive control runs first, so a broken fixture cannot make a refusal pass vacuously.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")

NEXT = "1.3.0"
TAG = f"v{NEXT}"
BRANCH = f"chore/release-{NEXT}"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit_file(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class Release:
    def __init__(self, tmp_path: Path):
        self.origin = tmp_path / "origin.git"
        self.checkout = tmp_path / "amicus-wt-release"
        self.github = tmp_path / "github"
        self.sha = ""

    @property
    def record(self) -> Path:
        return self.checkout / release.EVIDENCE_PATH

    def on_github(self, *args: str) -> str:
        return _git(self.github, *args)

    def push_main(self) -> None:
        self.on_github("push", "-q", "origin", "HEAD:main")

    def merge(self, ref: str = f"origin/{BRANCH}") -> None:
        """What `gh pr merge --merge` does: an ordinary merge commit, pushed to main."""
        self.on_github("fetch", "-q", "origin")
        self.on_github("merge", "-q", "--no-ff", "-m", "Merge pull request #1", ref)
        self.push_main()

    def tracking_main(self) -> str:
        return _git(self.checkout, "rev-parse", "refs/remotes/origin/main")


@pytest.fixture
def rel(tmp_path) -> Release:
    """After RELEASING step 3: the release commit pushed, its evidence recorded and tagged."""
    rel = Release(tmp_path)
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(rel.origin))
    _git(tmp_path, "clone", "-q", str(rel.origin), str(rel.checkout))
    _git(rel.checkout, "switch", "-q", "-c", "main")
    (rel.checkout / ".gitignore").write_text(".release-evidence/\n", encoding="utf-8")
    _git(rel.checkout, "add", ".gitignore")
    _commit_file(rel.checkout, "pyproject.toml", 'version = "1.2.2"\n', "previous release")
    _git(rel.checkout, "push", "-q", "origin", "main")
    _git(rel.checkout, "switch", "-q", "-c", BRANCH)
    rel.sha = _commit_file(rel.checkout, "pyproject.toml", f'version = "{NEXT}"\n', "release")
    _git(rel.checkout, "push", "-q", "origin", BRANCH)

    rel.record.parent.mkdir()
    record = json.dumps({"commit": rel.sha, "backends": {}}, indent=2) + "\n"
    rel.record.write_text(record, encoding="utf-8")
    _git(rel.checkout, "tag", "-a", TAG, "--cleanup=verbatim", "-F", str(rel.record), rel.sha)

    _git(tmp_path, "clone", "-q", str(rel.origin), str(rel.github))
    return rel


class FakeRun:
    """`check_release_state.py`, recorded; anything else fails the test loudly."""

    def __init__(self, returncode: int = 0):
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, cmd, *args, **kwargs):
        cmd = [str(part) for part in cmd]
        self.calls.append(cmd)
        if cmd[1].endswith("scripts/check_release_state.py"):
            return subprocess.CompletedProcess(cmd, self.returncode)
        raise AssertionError(f"unexpected command {cmd!r}")


def _post_merge(rel: Release, run: FakeRun | None = None, *, sha: str | None = None) -> int:
    ctx = release.Context(repo_root=rel.checkout, run=run or FakeRun())
    argv = ["post-merge", "--release-sha", sha or rel.sha, "--version", NEXT]
    return release.main(argv, context=ctx)


def _assert_refused(rel: Release, capsys, *reasons: str, **kwargs) -> str:
    assert _post_merge(rel, **kwargs) == 1
    err = capsys.readouterr().err
    assert f"do not push {TAG}" in err
    for reason in reasons:
        assert reason in err
    return err


# --- positive control ------------------------------------------------------------------


def test_an_ordinary_merge_of_the_release_commit_holds(rel, capsys):
    rel.merge()
    run = FakeRun()
    assert _post_merge(rel, run) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert "post-merge checks hold" in out.out
    assert "not proof they ran" in out.out  # rule 23
    assert [c[1:] for c in run.calls] == [
        [str(rel.checkout / "scripts/check_release_state.py"), "--tag", TAG, "--commit", rel.sha]
    ]


def test_a_stale_tracking_ref_is_fetched_first(rel, capsys):
    stale = rel.tracking_main()
    rel.merge()
    assert rel.tracking_main() == stale  # what `gh pr merge` leaves behind
    assert _post_merge(rel) == 0
    assert rel.tracking_main() == rel.on_github("rev-parse", "HEAD")


def test_a_short_release_sha_is_resolved(rel, capsys):
    rel.merge()
    assert _post_merge(rel, sha=rel.sha[:12]) == 0


def test_a_failed_fetch_stops_everything(rel, capsys):
    rel.merge()
    _git(rel.checkout, "remote", "set-url", "origin", str(rel.origin.parent / "gone.git"))
    run = FakeRun()
    _assert_refused(rel, capsys, "`git fetch origin` failed", run=run)
    assert run.calls == []


# --- acceptance: how the PR was merged ---------------------------------------------------


def test_a_squash_merge_is_refused(rel, capsys):
    rel.on_github("fetch", "-q", "origin")
    rel.on_github("merge", "-q", "--squash", f"origin/{BRANCH}")
    rel.on_github("commit", "-q", "-m", "release (#1)")
    rel.push_main()
    err = _assert_refused(rel, capsys, "squashed or rebased")
    assert "origin/main's tree differs" not in err  # a squash keeps the tree; the shape fails it
    assert "is not in origin/main's history" in err


def test_a_rebase_merge_is_refused(rel, capsys):
    _commit_file(rel.github, "other.txt", "x\n", "unrelated work on main")
    rel.push_main()
    rel.on_github("fetch", "-q", "origin")
    rel.on_github("cherry-pick", rel.sha)  # GitHub's rebase merge rewrites each commit
    rel.push_main()
    _assert_refused(rel, capsys, "squashed or rebased", "is not in origin/main's history")


def test_a_fast_forward_is_named_as_such(rel, capsys):
    rel.on_github("fetch", "-q", "origin")
    rel.on_github("merge", "-q", "--ff-only", f"origin/{BRANCH}")
    rel.push_main()
    err = _assert_refused(rel, capsys, "was fast-forwarded")
    assert "squashed" not in err


def test_a_changed_pr_tip_is_not_called_a_squash(rel, capsys):
    rel.on_github("fetch", "-q", "origin")
    rel.on_github("switch", "-q", "-c", BRANCH, f"origin/{BRANCH}")
    _commit_file(rel.github, "late.txt", "x\n", "pushed after the evidence")
    late = rel.on_github("rev-parse", "HEAD")
    rel.on_github("switch", "-q", "main")
    rel.merge(BRANCH)
    err = _assert_refused(rel, capsys, f"but of {late}", "gained a commit", "tree differs")
    assert "squashed" not in err


def test_unrelated_work_merged_after_the_release_is_refused(rel, capsys):
    rel.merge()
    rel.on_github("switch", "-q", "-c", "other")
    _commit_file(rel.github, "other.txt", "x\n", "unrelated")
    rel.on_github("switch", "-q", "main")
    rel.merge("other")
    err = _assert_refused(rel, capsys, "merged after the release merge", "tree differs")
    assert "squashed" not in err
    assert "gained a commit" not in err


# --- the tag ---------------------------------------------------------------------------


def test_a_lightweight_tag_is_refused(rel, capsys):
    rel.merge()
    _git(rel.checkout, "tag", "-d", TAG)
    _git(rel.checkout, "tag", TAG, rel.sha)
    _assert_refused(rel, capsys, "is a lightweight tag")


def test_a_missing_tag_is_refused(rel, capsys):
    rel.merge()
    _git(rel.checkout, "tag", "-d", TAG)
    _assert_refused(rel, capsys, f"there is no local tag {TAG}")


def test_a_tag_message_other_than_the_record_is_refused(rel, capsys):
    rel.merge()
    rel.record.write_text(rel.record.read_text(encoding="utf-8") + " ", encoding="utf-8")
    _assert_refused(rel, capsys, "byte for byte")


def test_a_missing_record_is_refused(rel, capsys):
    rel.merge()
    rel.record.unlink()
    _assert_refused(rel, capsys, f"could not read {release.EVIDENCE_PATH}")


def test_a_tag_on_another_commit_is_refused(rel, capsys):
    rel.merge()
    _git(rel.checkout, "tag", "-d", TAG)
    other = f"{rel.sha}~1"
    _git(rel.checkout, "tag", "-a", TAG, "--cleanup=verbatim", "-F", str(rel.record), other)
    _assert_refused(rel, capsys, "not the release commit")


# --- this checkout and the release-state check --------------------------------------------


def test_a_checkout_not_at_the_release_commit_is_refused(rel, capsys):
    rel.merge()
    _git(rel.checkout, "switch", "-q", "--detach", f"{rel.sha}~1")
    _assert_refused(rel, capsys, "not the release commit; run this in the release PR's worktree")


def test_a_dirty_checkout_is_refused(rel, capsys):
    rel.merge()
    _git(rel.checkout, "config", "status.showUntrackedFiles", "no")
    (rel.checkout / "stray.txt").write_text("x\n", encoding="utf-8")
    _assert_refused(rel, capsys, "the tree is not clean")


def test_a_failing_release_state_check_is_refused(rel, capsys):
    rel.merge()
    _assert_refused(rel, capsys, "check_release_state.py --tag", run=FakeRun(returncode=1))


def test_an_unknown_release_sha_is_refused(rel, capsys):
    rel.merge()
    _assert_refused(rel, capsys, "names no commit", sha="0" * 40)


def test_a_malformed_version_is_refused(rel, capsys):
    rel.merge()
    ctx = release.Context(repo_root=rel.checkout, run=FakeRun())
    argv = ["post-merge", "--release-sha", rel.sha, "--version", "1.3"]
    assert release.main(argv, context=ctx) == 1
    assert "is not X.Y.Z" in capsys.readouterr().err
