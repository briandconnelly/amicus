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


def test_not_run_discloses_the_omitted_untracked_file_as_coverage(repo):
    """#65: the omission reaches the caller as a field it can branch on, not only as prose."""
    (repo / "new.py").write_text("n = 1\n")
    spec = _spec(str(repo))
    out = review.gather(spec, meta_for(spec), fakeplugin.make_plugin())
    assert out["review_status"] == "not_run"
    assert out["coverage"] == {
        "status": "partial",
        "untracked_files_detected": 1,
        "untracked_files_included": 0,
        "untracked_files_omitted": 1,
        "omission_reasons": ["untracked_omitted"],
        "redaction": None,
    }


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


def test_build_coverage_and_the_fold_that_reads_it():
    clean = DiffResult(text="d", summary=DiffSummary(1, 1, 0), untracked_detected=0)
    complete = review.build_coverage("working_tree", clean, focused=False)
    assert complete.model_dump() == {
        "status": "complete",
        "untracked_files_detected": 0,
        "untracked_files_included": 0,
        "untracked_files_omitted": 0,
        "omission_reasons": [],
        "redaction": None,
    }
    partial = DiffResult(
        text="d",
        summary=DiffSummary(1, 1, 0),
        untracked_detected=2,
        truncated=True,
        redacted_paths=[".env"],
        tree_changed_during_gather=True,
    )
    everything = review.build_coverage("working_tree", partial, focused=True)
    assert (everything.status, everything.untracked_files_omitted) == ("partial", 2)
    assert everything.omission_reasons == [
        "untracked_omitted",
        "tree_changed_during_gather",
        "truncated",
        "redacted",
        "focused",
    ]
    commit = review.build_coverage("commit", partial, focused=False)
    assert commit.untracked_files_detected is None and commit.omission_reasons == [
        "truncated",
        "redacted",
    ]
    # A critique with no attached scope gathered nothing, so only a focus can make it partial.
    assert review.build_coverage(None, None, focused=False).status == "complete"
    assert review.build_coverage(None, None, focused=True).omission_reasons == ["focused"]
    assert review.apply_coverage("pass", "high", "fine", complete) == ("pass", "high", "fine")
    v, c, s = review.apply_coverage("pass", "high", "fine", commit)
    assert (
        (v, c) == ("unknown", "low")
        and s.startswith(
            "Overall verdict is unknown because coverage is partial (truncated, redacted)"
        )
        and s.endswith("fine")
    )
    assert review.apply_coverage("fail", "high", "bad", commit) == ("fail", "high", "bad")


def test_build_coverage_breaks_redaction_down_only_from_what_the_split_fields_saw():
    split = DiffResult(
        text="d",
        summary=DiffSummary(2, 1, 0),
        untracked_detected=0,
        redacted_paths=[".env", "a.py"],
        withheld_paths=[".env"],
        masked_paths=["a.py"],
        inline_masks=2,
    )
    cov = review.build_coverage("working_tree", split, focused=False)
    assert cov.omission_reasons == ["redacted"] and cov.redaction is not None
    assert cov.redaction.model_dump() == {
        "withheld_paths": [".env"],
        "masked_paths": ["a.py"],
        "inline_masks": 2,
    }
    # Redaction that fell wholly past the byte cap: the reason stands, no breakdown is invented.
    capped = DiffResult(
        text="d",
        summary=DiffSummary(1, 1, 0),
        untracked_detected=0,
        truncated=True,
        redacted_paths=[".env"],
    )
    cov = review.build_coverage("working_tree", capped, focused=False)
    assert cov.omission_reasons == ["truncated", "redacted"] and cov.redaction is None
