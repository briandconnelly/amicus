"""Hot-path result differential: the same raw CommandRun/events through amicus's loop with
the real kimi plugin (a real worktree in a tmp repo) vs moonbridge's runspace finisher and
finalizers (captured fixture). Compared on the shared projection; codes are compared after
amicus's `backend_*` generalization."""

from __future__ import annotations

import subprocess

import pytest
from pontonier.core.gitdiff import DiffResult, DiffSummary
from tests.support import kimifixtures as kf

from amicus.orchestration import review
from amicus.orchestration import run as run_mod
from amicus.request import RunSpec
from amicus.schemas.codes import generalize_code

FIXTURE = kf.load_fixture()
SECRET = "sk-" + "c" * 32

# Codes whose `temporary` deliberately differs from the sibling (pontonier's shared table is
# the amicus default). Empty until a run of this test proves a difference; then record the
# pair here AND in the PR body. Value is (sibling_temporary, amicus_temporary).
KNOWN_TEMPORARY_DEVIATIONS: dict[str, tuple[bool, bool]] = {
    # moonbridge's own classifier marks a generic nonzero exit as non-retryable
    # (temporary=False, same reasoning as M1's codex `nonzero_exit` deviation); pontonier's
    # shared repair table defaults `nonzero_exit` to temporary=True (an inspect-and-retry
    # code), and amicus keeps that default rather than special-casing one backend's
    # classifier.
    "nonzero_exit": (False, True),
}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.co")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _spec(kind, cwd):
    return RunSpec(
        backend="kimi",
        kind=kind,
        tool=f"amicus_{kind}",
        cwd=str(cwd),
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=60,
        options={"isolation": "inherit"},
        question="q",
        scope="working_tree",
    )


@pytest.mark.parametrize("case", sorted(FIXTURE["envelopes"]))
async def test_envelope_projection_matches_the_sibling(pinned_kimi_bin, monkeypatch, repo, case):
    entry = FIXTURE["envelopes"][case]
    inp, theirs = entry["input"], entry["sibling"]
    plugin, _ = kf.make_backend()
    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        kf.scripted_run_async(
            stdout=inp["events"],
            stderr=inp["stderr"],
            exit_code=inp["exit_code"],
            timed_out=inp.get("timed_out", False),
            calls=calls,
        ),
    )
    if inp["kind"] == "review_changes":
        monkeypatch.setattr(
            review.gitdiff,
            "gather_diff",
            lambda *a, **k: DiffResult(
                text="DIFF", summary=DiffSummary(1, 1, 0), untracked_detected=0
            ),
        )
    ours = await run_mod.run_request(_spec(inp["kind"], repo), plugin)
    assert ours["ok"] == theirs["ok"], ours
    if theirs["ok"]:
        for key in ("summary", "verdict", "confidence", "review_status"):
            if key in theirs:
                assert ours[key] == theirs[key], key
        assert ours["findings"] == theirs["findings"]
    else:
        assert generalize_code(theirs["error"]["code"], "kimi") == ours["error"]["code"]
        expected_temporary = theirs["error"]["temporary"]
        if ours["error"]["code"] in KNOWN_TEMPORARY_DEVIATIONS:
            expected_temporary = KNOWN_TEMPORARY_DEVIATIONS[ours["error"]["code"]][1]
        assert ours["error"]["temporary"] == expected_temporary
        assert ours["error"]["retry_after_ms"] == theirs["error"]["retry_after_ms"]
        message = ours["error"]["message"]
        assert not theirs["message_has_secret"] and SECRET not in message
        assert not theirs["message_has_secret_prefix"] and "sk-cccc" not in message
        worktree_path = calls[0]["cwd"]
        assert not theirs["message_has_worktree_path"] and worktree_path not in message
        assert ("src/a.py" in message) == theirs["message_has_relative_path"]
    m, tm = ours["meta"], theirs["meta"]
    assert m.get("session_id") == tm["session_id"]
    assert m.get("command_exit_code") == tm["command_exit_code"]
    if tm["usage"] is None:
        assert m.get("usage") is None
    else:
        for key, value in tm["usage"].items():
            assert m["usage"][key] == value, key
