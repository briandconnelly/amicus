"""`scripts/release.py preflight`: the checks that run before live-gate evidence spends (#377).

The evidence was recorded in the main checkout for 0.3.0, 0.6.0 and 0.7.0, each time spending
the quota of all three backends before a later check noticed (#241). `preflight` runs first.

The fixture is real git: a bare `origin`, a main checkout, and the release PR's branch checked
out in a linked worktree. The main checkout is detached at the very same commit, so the only
thing that separates the two is which checkout they are; that is what the acceptance test needs.
`gh` and `check_backend_compat.py` are stubbed, and the stub fails the test loudly if anything
tries to run the evidence script.

The positive control runs first, so a broken fixture cannot make a refusal pass vacuously.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from tests.support.releasefixture import NEXT, TODAY, build_released_repo
from tests.support.releasefixture import git as _git

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")

BRANCH = f"chore/release-{NEXT}"

PR = 42


class Layout:
    def __init__(self, tmp_path: Path):
        self.origin = tmp_path / "origin.git"
        self.main = tmp_path / "amicus"
        self.worktree = tmp_path / "amicus-wt-release"
        self.head = ""


def _uv_lock(cmd, *args, **kwargs):
    """`prepare`'s `uv lock` and `uv lock --check`, which would otherwise resolve an index."""
    assert list(cmd) in (["uv", "lock"], ["uv", "lock", "--check"]), cmd
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


@pytest.fixture
def layout(tmp_path) -> Layout:
    """PR C as `prepare` leaves it, committed and pushed, checked out in a linked worktree."""
    lay = Layout(tmp_path)
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(lay.origin))
    build_released_repo(lay.main, release)
    (lay.main / ".gitignore").write_text(".release-evidence/\n", encoding="utf-8")
    _git(lay.main, "add", ".gitignore")
    _git(lay.main, "commit", "-q", "-m", "ignore the evidence record")
    _git(lay.main, "remote", "add", "origin", str(lay.origin))
    _git(lay.main, "push", "-q", "origin", "main")
    _git(lay.main, "switch", "-q", "-c", BRANCH)
    ctx = release.Context(repo_root=lay.main, run=_uv_lock, today=lambda: TODAY)
    assert release.main(["prepare", NEXT], context=ctx) == 0
    _git(lay.main, "commit", "-q", "-am", f"chore(release): {NEXT}")
    _git(lay.main, "push", "-q", "origin", BRANCH)
    lay.head = _git(lay.main, "rev-parse", "HEAD")
    # The main checkout sits at the same commit, so only "which checkout" tells them apart.
    _git(lay.main, "switch", "-q", "--detach", lay.head)
    _git(lay.main, "worktree", "add", "-q", str(lay.worktree), BRANCH)
    return lay


class FakeRun:
    """`gh pr view`, `uv lock --check` and `check_backend_compat.py`; anything else fails loudly."""

    def __init__(
        self, head: str, *, state="OPEN", base="main", gh_returncode=0, compat=0, lock_check=0
    ):
        self.calls: list[list[str]] = []
        self.pr = {
            "headRefOid": head,
            "headRefName": f"chore/release-{NEXT}",
            "state": state,
            "baseRefName": base,
        }
        self.gh_returncode = gh_returncode
        self.compat = compat
        self.lock_check = lock_check

    def __call__(self, cmd, *args, **kwargs):
        cmd = [str(part) for part in cmd]
        self.calls.append(cmd)
        assert not any("record_live_gate_evidence" in part for part in cmd), "never spend"
        if cmd[:3] == ["gh", "pr", "view"]:
            assert cmd[3] == str(PR)
            stdout = self.pr if isinstance(self.pr, str) else json.dumps(self.pr)
            return subprocess.CompletedProcess(
                cmd, self.gh_returncode, stdout=stdout, stderr="gh: not found\n"
            )
        if cmd == ["uv", "lock", "--check"]:
            return subprocess.CompletedProcess(
                cmd, self.lock_check, stdout="", stderr="error: the lockfile needs updating\n"
            )
        if cmd[1].endswith("scripts/check_backend_compat.py"):
            assert cmd[0] == sys.executable
            assert kwargs["cwd"] == Path(cmd[1]).parent.parent  # its --docs-root is relative
            if isinstance(self.compat, Exception):
                raise self.compat
            return subprocess.CompletedProcess(cmd, self.compat)
        raise AssertionError(f"unexpected command {cmd!r}")

    def ran(self, *cmd: str) -> bool:
        return list(cmd) in self.calls

    def ran_compat(self) -> bool:
        return any(c[1].endswith("scripts/check_backend_compat.py") for c in self.calls)


def _preflight(checkout: Path, run: FakeRun, *, version: str = NEXT) -> int:
    ctx = release.Context(repo_root=checkout, run=run)
    return release.main(["preflight", "--pr", str(PR), "--version", version], context=ctx)


def _assert_refused(layout, capsys, run: FakeRun, reason: str, **kwargs) -> None:
    checkout = kwargs.pop("checkout", layout.worktree)
    assert _preflight(checkout, run, **kwargs) == 1
    out = capsys.readouterr()
    assert "does NOT hold" in out.err
    assert reason in out.err
    assert "record_live_gate_evidence" not in out.out


# --- positive control ------------------------------------------------------------------


def test_preflight_holds_in_the_release_worktree_and_prints_the_command(layout, capsys):
    run = FakeRun(layout.head)
    assert _preflight(layout.worktree, run) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert f"preflight holds for {NEXT} at {layout.head}" in out.out
    command = release.evidence_command(layout.worktree, NEXT)
    assert command in out.out
    assert command.startswith(f"cd {layout.worktree} && ")
    assert command.endswith(f"scripts/record_live_gate_evidence.py --version {NEXT}")
    assert run.ran_compat()
    assert run.ran("uv", "lock", "--check")
    assert [c[:3] for c in run.calls if c[0] == "gh"] == [["gh", "pr", "view"]]


def test_the_evidence_path_is_the_one_the_evidence_script_writes():
    evidence = release.release_state._load_evidence_module()
    assert Path(release.EVIDENCE_PATH) == evidence.EVIDENCE_PATH


# --- acceptance: the main checkout --------------------------------------------------------


def test_preflight_fails_in_the_main_checkout(layout, capsys):
    """Same commit, same PR, clean, same version: only the checkout is wrong, and it fails."""
    _assert_refused(
        layout, capsys, FakeRun(layout.head), "is the main checkout", checkout=layout.main
    )


# --- the PR's head ---------------------------------------------------------------------


def test_a_head_other_than_the_prs_is_refused(layout, capsys):
    _assert_refused(layout, capsys, FakeRun("f" * 40), f"but PR #{PR}'s head on GitHub is")


def test_an_unpushed_commit_is_refused(layout, capsys):
    _git(layout.worktree, "commit", "-q", "--allow-empty", "-m", "not pushed")
    _assert_refused(layout, capsys, FakeRun(layout.head), "HEAD is")


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_a_pr_that_is_not_open_is_refused(layout, capsys, state):
    _assert_refused(layout, capsys, FakeRun(layout.head, state=state), f"is {state}, not OPEN")


def test_a_pr_not_against_main_is_refused(layout, capsys):
    _assert_refused(layout, capsys, FakeRun(layout.head, base="develop"), "targets 'develop'")


def test_a_failed_gh_lookup_is_a_failure(layout, capsys):
    _assert_refused(layout, capsys, FakeRun(layout.head, gh_returncode=1), "gh: not found")


@pytest.mark.parametrize(
    "payload", ["not json", json.dumps({"state": "OPEN"}), json.dumps({"headRefOid": "main"})]
)
def test_an_unreadable_gh_answer_is_a_failure(layout, capsys, payload):
    run = FakeRun(layout.head)
    run.pr = payload
    _assert_refused(layout, capsys, run, f"could not read PR #{PR}")


# --- the tree and the version ------------------------------------------------------------


def test_a_modified_file_is_refused(layout, capsys):
    (layout.worktree / ".gitignore").write_text("changed\n", encoding="utf-8")
    _assert_refused(layout, capsys, FakeRun(layout.head), "the tree is not clean")


def test_an_untracked_file_is_refused_even_when_status_hides_untracked_files(layout, capsys):
    _git(layout.worktree, "config", "status.showUntrackedFiles", "no")
    (layout.worktree / "stray.txt").write_text("x\n", encoding="utf-8")
    assert _git(layout.worktree, "status", "--porcelain") == ""  # the hole #385 is about
    _assert_refused(layout, capsys, FakeRun(layout.head), "stray.txt")


def test_an_ignored_evidence_record_does_not_make_the_tree_dirty(layout, capsys):
    (layout.worktree / ".release-evidence").mkdir()
    (layout.worktree / release.EVIDENCE_PATH).write_text("{}\n", encoding="utf-8")
    assert _preflight(layout.worktree, FakeRun(layout.head)) == 0


def test_a_version_the_checkout_does_not_declare_is_refused(layout, capsys):
    _assert_refused(
        layout, capsys, FakeRun(layout.head), f"declares '{NEXT}', not '1.4.0'", version="1.4.0"
    )


@pytest.mark.parametrize("version", ["1.3", "v1.3.0", " 1.3.0"])
def test_a_malformed_version_is_refused(layout, capsys, version):
    _assert_refused(layout, capsys, FakeRun(layout.head), "is not X.Y.Z", version=version)


# --- tags ------------------------------------------------------------------------------


def test_a_tag_already_on_origin_is_refused(layout, capsys):
    _git(layout.main, "tag", f"v{NEXT}", layout.head)
    _git(layout.main, "push", "-q", "origin", f"v{NEXT}")
    _git(layout.main, "tag", "-d", f"v{NEXT}")
    _assert_refused(layout, capsys, FakeRun(layout.head), f"v{NEXT} already exists on origin")


def test_an_unreachable_origin_is_a_failure_not_an_absent_tag(layout, capsys):
    _git(layout.worktree, "remote", "set-url", "origin", str(layout.origin.parent / "gone.git"))
    _assert_refused(layout, capsys, FakeRun(layout.head), "could not ask origin")


def test_a_local_tag_is_refused(layout, capsys):
    _git(layout.worktree, "tag", "-a", f"v{NEXT}", "-m", "earlier attempt")
    _assert_refused(layout, capsys, FakeRun(layout.head), f"git tag -d v{NEXT}")


# --- the release-state checks `prepare` ran ------------------------------------------------


def test_a_pre_tag_release_state_problem_fails_preflight(layout, capsys):
    init = layout.worktree / "src/amicus/__init__.py"
    init.write_text(init.read_text().replace(NEXT, "9.9.9"), encoding="utf-8")
    _git(layout.worktree, "commit", "-q", "-am", "a literal that disagrees")
    head = _git(layout.worktree, "rev-parse", "HEAD")
    _assert_refused(layout, capsys, FakeRun(head), "src/amicus/__init__.py")


def test_a_stale_lock_fails_preflight(layout, capsys):
    run = FakeRun(layout.head, lock_check=1)
    _assert_refused(layout, capsys, run, "`uv lock --check` failed")


# --- the backend-CLI check -----------------------------------------------------------------


def test_a_failing_backend_compat_check_is_refused(layout, capsys):
    _assert_refused(layout, capsys, FakeRun(layout.head, compat=1), "check_backend_compat.py")


def test_a_backend_compat_check_that_cannot_run_is_refused(layout, capsys):
    run = FakeRun(layout.head, compat=OSError("no python"))
    _assert_refused(layout, capsys, run, "no python")
