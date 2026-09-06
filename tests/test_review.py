"""Diff gathering before any spend, gitdiff error mapping, and the coverage fold."""

from __future__ import annotations

import subprocess

import pytest
from pontonier.core.gitdiff import DiffResult, DiffSummary, InvalidUntrackedError
from tests.support import fakeplugin

from amicus.orchestration import review
from amicus.request import RunSpec, meta_for


def _spec(cwd, **kw):
    base = dict(
        backend="fake",
        kind="review_changes",
        tool="amicus_review_changes",
        cwd=cwd,
        workspace_source="param",
        roots_source="client",
        host_name="H",
        timeout_seconds=10,
        scope="working_tree",
    )
    base.update(kw)
    return RunSpec(**base)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.co")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "m.py").write_text("a = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_gather_returns_the_diff_and_stamps_meta(repo):
    (repo / "m.py").write_text("a = 2\n")
    spec = _spec(str(repo))
    meta = meta_for(spec)
    diff = review.gather(spec, meta, fakeplugin.make_plugin())
    assert isinstance(diff, DiffResult) and "+a = 2" in diff.text
    assert meta.context_summary is not None and meta.context_summary.files_changed == 1
    assert meta.truncated is False


def test_gather_not_run_on_a_clean_tree_and_discloses_omitted_untracked(repo):
    spec = _spec(str(repo))
    out = review.gather(spec, meta_for(spec), fakeplugin.make_plugin())
    assert isinstance(out, dict) and out["ok"] is True
    assert (out["review_status"], out["verdict"], out["confidence"]) == (
        "not_run",
        "unknown",
        "low",
    )
    (repo / "new.py").write_text("n = 1\n")
    out = review.gather(spec, meta_for(spec), fakeplugin.make_plugin())
    assert (
        out["review_status"] == "not_run"
        and "1 untracked" in out["summary"]
        and 'untracked="include"' in out["summary"]
    )
    out = review.gather(
        _spec(str(repo), untracked="exclude"), meta_for(spec), fakeplugin.make_plugin()
    )
    assert "name them in paths" not in out["summary"]


def test_gather_maps_gitdiff_errors(repo, tmp_path_factory):
    spec = _spec(str(repo), scope="branch", base="no-such-ref")
    out = review.gather(spec, meta_for(spec), fakeplugin.make_plugin())
    assert (
        out["ok"] is False
        and out["error"]["code"] == "invalid_base"
        and out["error"]["details"]["field"] == "base"
    )
    # A directory outside `repo`: nested inside it, git would resolve the ancestor .git and
    # this would silently become an empty diff rather than exercise not_a_git_repo.
    plain = tmp_path_factory.mktemp("plain")
    out = review.gather(_spec(str(plain)), meta_for(spec), fakeplugin.make_plugin())
    assert out["error"]["code"] == "not_a_git_repo"


def test_gather_rebounds_extra_context(repo):
    spec = _spec(str(repo), extra_context="x" * 2000, max_input_bytes=1000)
    out = review.gather(spec, meta_for(spec), fakeplugin.make_plugin())
    assert out["error"]["code"] == "input_too_large" and out["error"]["limit_bytes"] == 1000


def test_gitdiff_error_invalid_untracked_never_echoes_and_redacts():
    from amicus.schemas.envelope import Meta

    out = review.gitdiff_error(
        InvalidUntrackedError("untracked must be one of [...], got 'bogus'"),
        Meta(),
        fakeplugin.make_plugin(),
    )
    assert (
        out["error"]["code"] == "invalid_arguments"
        and out["error"]["details"]["field"] == "untracked"
    )
    assert "bogus" not in str(out) and out["error"]["invalid_arguments"][0]["allowed_values"] == [
        "explicit_only",
        "include",
        "exclude",
    ]
    secret = "sk-" + "c" * 32
    out = review.gitdiff_error(
        RuntimeError(f"git failed token={secret}"), Meta(), fakeplugin.make_plugin()
    )
    assert secret not in str(out) and out["error"]["code"] == "git_unavailable"


def test_coverage_reasons_and_fold():
    clean = DiffResult(text="d", summary=DiffSummary(1, 1, 0), untracked_detected=0)
    assert review.coverage_reasons("working_tree", clean) == []
    partial = DiffResult(
        text="d",
        summary=DiffSummary(1, 1, 0),
        untracked_detected=2,
        truncated=True,
        redacted_paths=[".env"],
        tree_changed_during_gather=True,
    )
    assert review.coverage_reasons("working_tree", partial) == [
        "untracked_omitted",
        "tree_changed_during_gather",
        "truncated",
        "redacted",
    ]
    assert review.coverage_reasons("commit", partial) == ["truncated", "redacted"]
    assert review.apply_coverage("pass", "high", "fine", []) == ("pass", "high", "fine")
    v, c, s = review.apply_coverage("pass", "high", "fine", ["truncated"])
    assert (
        (v, c) == ("unknown", "low")
        and s.startswith("Overall verdict is unknown because coverage is partial (truncated)")
        and s.endswith("fine")
    )
    assert review.apply_coverage("fail", "high", "bad", ["truncated"]) == ("fail", "high", "bad")
