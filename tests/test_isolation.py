"""DirectSite and WorktreeSite: the amicus-wt- policy, aliases, capture, teardown."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pontonier.backend.contract import IsolationPolicy
from tests.support import fakeplugin

from amicus.orchestration import isolation
from amicus.request import RunSpec


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.co")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _spec(kind, cwd):
    return RunSpec(
        backend="fake",
        kind=kind,
        tool="amicus_consult",
        cwd=cwd,
        workspace_source="param",
        roots_source="client",
        host_name="H",
        timeout_seconds=10,
    )


def test_direct_site_is_a_passthrough(tmp_path):
    with isolation.DirectSite(str(tmp_path)) as site:
        assert site.cwd == str(tmp_path) and site.aliases == () and site.security_warnings == ()
        assert site.capture_diff() is None


def test_worktree_site_creates_captures_and_tears_down(repo):
    parents: list[str] = []
    with isolation.WorktreeSite(str(repo), git_timeout=30, on_parent=parents.append) as site:
        assert site.cwd != str(repo) and Path(site.cwd).is_dir()
        assert Path(parents[0]).name.startswith(isolation.WORKTREE_PREFIX)
        assert site.aliases and all(a.startswith(("/", "file://")) for a in site.aliases)
        Path(site.cwd, "a.py").write_text("x = 2\n")
        diff = site.capture_diff()
        assert diff and "+x = 2" in diff
        wt_path = site.cwd
    assert not Path(wt_path).exists() and not Path(parents[0]).exists()
    assert (repo / "a.py").read_text() == "x = 1\n"


def test_worktree_site_maps_git_failures_to_site_errors(tmp_path):
    with (
        pytest.raises(isolation.SiteError) as exc,
        isolation.WorktreeSite(str(tmp_path), git_timeout=30),
    ):
        pass  # pragma: no cover
    assert exc.value.code == "not_a_git_repo" and exc.value.field == "workspace_root"
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q")
    with (
        pytest.raises(isolation.SiteError) as exc2,
        isolation.WorktreeSite(str(empty), git_timeout=30),
    ):
        pass  # pragma: no cover
    assert exc2.value.code == "worktree_error"


def test_select_site_by_kind_and_policy(tmp_path):
    plugin = fakeplugin.make_plugin()
    assert isinstance(
        isolation.select_site(_spec("consult", str(tmp_path)), plugin), isolation.DirectSite
    )
    assert isinstance(
        isolation.select_site(_spec("delegate", str(tmp_path)), plugin), isolation.WorktreeSite
    )
    import dataclasses

    all_tiers = fakeplugin.make_plugin(
        contract=dataclasses.replace(
            fakeplugin.make_contract(), isolation_policy=IsolationPolicy.WORKTREE_ALL_TIERS
        )
    )
    # Non-repo consult under WORKTREE_ALL_TIERS now runs in an EmptyDirSite (Task 6, ADR
    # 0009), not a WorktreeSite: see test_select_site_uses_the_empty_dir_only_... below.
    assert isinstance(
        isolation.select_site(_spec("consult", str(tmp_path)), all_tiers), isolation.EmptyDirSite
    )


def test_worktree_config_is_orchestration_policy():
    assert isolation.WORKTREE_CONFIG.prefix == "amicus-wt-"
    assert (isolation.WORKTREE_CONFIG.identity_name, isolation.WORKTREE_CONFIG.identity_email) == (
        "amicus",
        "amicus@local",
    )


def test_empty_dir_site_is_isolated_warned_and_torn_down():
    with isolation.EmptyDirSite() as site:
        assert Path(site.cwd).is_dir() and Path(site.cwd).name.startswith(isolation.WORKTREE_PREFIX)
        assert site.security_warnings == (isolation.NO_REPO_WARNING,)
        assert site.aliases and site.capture_diff() is None
        Path(site.cwd, "scratch.txt").write_text("x")
        cwd = site.cwd
    assert not Path(cwd).exists()


def test_select_site_uses_the_empty_dir_only_for_a_non_repo_consult_under_all_tiers(
    tmp_path_factory, repo
):
    import dataclasses

    # `repo` git-inits `tmp_path` in place and returns it, so a non-repo directory for this
    # test has to live outside that tree entirely (a subdirectory would still resolve to the
    # same repository, since git discovery walks upward) — a fresh tmp_path_factory dir.
    non_repo = tmp_path_factory.mktemp("non_repo")

    all_tiers = fakeplugin.make_plugin(
        contract=dataclasses.replace(
            fakeplugin.make_contract(), isolation_policy=IsolationPolicy.WORKTREE_ALL_TIERS
        )
    )
    assert isinstance(
        isolation.select_site(_spec("consult", str(non_repo)), all_tiers), isolation.EmptyDirSite
    )
    assert isinstance(
        isolation.select_site(_spec("consult", str(repo)), all_tiers), isolation.WorktreeSite
    )
    assert isinstance(
        isolation.select_site(_spec("review_changes", str(non_repo)), all_tiers),
        isolation.WorktreeSite,
    )
    assert isinstance(
        isolation.select_site(_spec("delegate", str(non_repo)), all_tiers), isolation.WorktreeSite
    )
    sandboxed = fakeplugin.make_plugin()
    assert isinstance(
        isolation.select_site(_spec("consult", str(non_repo)), sandboxed), isolation.DirectSite
    )
