"""Behavioral fixtures for WorktreeConfig — the per-consumer knobs.

Each bridge pins its own prefix, commit identity, and extra exclude pathspecs
so adopting this library changes no observable behavior. These tests prove the
knobs actually reach the places consumers depend on: the temp parent dir name,
the baseline commit's author, and the captured diff's pathspec filter.
"""

from __future__ import annotations

from pathlib import Path

from tests.sdk.conftest import run_git

from amicus.sdk.core import worktree


def _init_repo(path: Path) -> None:
    run_git(path, "init", "-q")
    run_git(path, "config", "user.email", "t@t.co")
    run_git(path, "config", "user.name", "t")
    (path / "a.txt").write_text("one\n")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-qm", "init")


def test_default_config_values():
    cfg = worktree.DEFAULT_CONFIG
    assert cfg.prefix == worktree.WORKTREE_PREFIX == "pontonier-worktree-"
    assert cfg.identity_name == "pontonier"
    assert cfg.identity_email == "pontonier@local"
    assert cfg.extra_excludes == ()


def test_custom_prefix_names_the_parent_dir(tmp_path: Path):
    _init_repo(tmp_path)
    cfg = worktree.WorktreeConfig(prefix="bridge-x-worktree-")
    wt = worktree.create(str(tmp_path), timeout=30, config=cfg)
    try:
        assert Path(wt.parent).name.startswith("bridge-x-worktree-")
    finally:
        worktree.remove(str(tmp_path), wt, timeout=30)


def test_custom_identity_signs_the_baseline_commit(tmp_path: Path):
    """A consumer's pinned identity (e.g. codex-in-claude@local) must be what the
    baseline commit records — commit authorship is git-visible in delegate
    worktree history."""
    _init_repo(tmp_path)
    # An uncommitted tracked change forces the baseline commit to be created.
    (tmp_path / "a.txt").write_text("changed\n")
    cfg = worktree.WorktreeConfig(identity_name="bridge-x", identity_email="bridge-x@local")
    wt = worktree.create(str(tmp_path), timeout=30, config=cfg)
    try:
        head = run_git(wt.path, "log", "-1", "--format=%an <%ae> %s")
        assert head.stdout.strip() == "bridge-x <bridge-x@local> baseline: live uncommitted state"
    finally:
        worktree.remove(str(tmp_path), wt, timeout=30)


def test_extra_excludes_filter_the_captured_diff(tmp_path: Path):
    """A consumer-specific pathspec (e.g. a handshake dir) never appears in the
    diff offered for review, while ordinary work does."""
    _init_repo(tmp_path)
    cfg = worktree.WorktreeConfig(extra_excludes=(":(exclude,glob)**/.bridge-x/**",))
    wt = worktree.create(str(tmp_path), timeout=30, config=cfg)
    try:
        (Path(wt.path) / "work.txt").write_text("real change\n")
        secret_dir = Path(wt.path) / ".bridge-x"
        secret_dir.mkdir()
        (secret_dir / "handshake.md").write_text("plumbing\n")
        diff = worktree.capture_diff(wt.path, timeout=30, config=cfg)
        assert "work.txt" in diff
        assert ".bridge-x" not in diff
    finally:
        worktree.remove(str(tmp_path), wt, timeout=30)


def test_default_excludes_still_apply_alongside_extra(tmp_path: Path):
    """extra_excludes APPENDS to the built-in artifact exclusions, not replaces."""
    _init_repo(tmp_path)
    cfg = worktree.WorktreeConfig(extra_excludes=(":(exclude,glob)**/.bridge-x/**",))
    wt = worktree.create(str(tmp_path), timeout=30, config=cfg)
    try:
        cache = Path(wt.path) / "__pycache__"
        cache.mkdir()
        (cache / "junk.pyc").write_text("x")
        (Path(wt.path) / "kept.txt").write_text("kept\n")
        diff = worktree.capture_diff(wt.path, timeout=30, config=cfg)
        assert "kept.txt" in diff
        assert "__pycache__" not in diff
    finally:
        worktree.remove(str(tmp_path), wt, timeout=30)
