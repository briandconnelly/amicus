"""Positive control for the GIT_HOOK_ENV scrub in conftest.py: proves the instrument can
fail (a redirected git actually gets redirected) before proving the fixture fixes it."""

from __future__ import annotations

import os
import subprocess

from tests.conftest import GIT_HOOK_ENV, _scrub_git_hook_env


def test_git_hook_env_is_scrubbed_during_a_test():
    assert not (set(GIT_HOOK_ENV) & set(os.environ))


def test_scrub_undoes_a_redirected_git_dir(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)

    monkeypatch.setenv("GIT_DIR", str(elsewhere))

    # Before scrubbing: the instrument can fail. GIT_DIR points at a directory that is not
    # a git dir, so `git -C <repo> rev-parse --git-dir` must fail (non-zero).
    redirected = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert redirected.returncode != 0

    # After scrubbing (what the autouse fixture does): the same command resolves the
    # repo's own .git, unaffected by the stale GIT_DIR.
    _scrub_git_hook_env(monkeypatch)
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert resolved.stdout.strip() == ".git"
