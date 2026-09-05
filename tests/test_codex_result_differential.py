"""Hot-path result differential: the same raw CommandRun/events through amicus's loop with
the real codex plugin vs codex-in-claude's finalizers (captured fixture). Compared on the
shared projection; codes are compared after amicus's `backend_*` generalization."""

from __future__ import annotations

import pytest
from pontonier.core.gitdiff import DiffResult, DiffSummary
from tests.support import codexfixtures as cf

from amicus.orchestration import review
from amicus.orchestration import run as run_mod
from amicus.request import RunSpec
from amicus.schemas.codes import generalize_code

# Codes whose `temporary` deliberately differs from the sibling (pontonier's shared table
# is the amicus default). Empty until a run of this test proves a difference; then record
# the pair here AND in the PR body. Value is (sibling_temporary, amicus_temporary).
KNOWN_TEMPORARY_DEVIATIONS: dict[str, tuple[bool, bool]] = {
    # codex-in-claude's own classifier marks a generic nonzero exit as non-retryable
    # (temporary=False); pontonier's shared repair table defaults `nonzero_exit` to
    # temporary=True (an inspect-and-retry code), and amicus keeps that default rather
    # than special-casing one backend's classifier.
    "nonzero_exit": (False, True),
}


def _spec(kind, effort):
    return RunSpec(
        backend="codex",
        kind=kind,
        tool=f"amicus_{kind}",
        cwd="/repo",
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=60,
        reasoning_effort=effort,
        options={"isolation": "inherit"},
        question="q",
        scope="working_tree",
    )


@pytest.mark.parametrize("case", sorted(cf.FIXTURE["envelopes"]))
async def test_envelope_projection_matches_the_sibling(pinned_codex_bin, monkeypatch, case):
    entry = cf.FIXTURE["envelopes"][case]
    inp, theirs = entry["input"], entry["sibling"]
    plugin, _ = cf.make_backend()
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        cf.scripted_run_async(
            stdout=inp["stdout"],
            stderr=inp["stderr"],
            exit_code=inp["exit_code"],
            last_message=inp["last_message"],
            timed_out=inp.get("timed_out", False),
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
    ours = await run_mod.run_request(_spec(inp["kind"], inp.get("effort")), plugin)
    assert ours["ok"] == theirs["ok"], ours
    if theirs["ok"]:
        for key in ("summary", "verdict", "confidence", "review_status"):
            if key in theirs:
                assert ours[key] == theirs[key], key
        assert ours["findings"] == theirs["findings"]
    else:
        assert generalize_code(theirs["error"]["code"], "codex") == ours["error"]["code"]
        expected_temporary = theirs["error"]["temporary"]
        if ours["error"]["code"] in KNOWN_TEMPORARY_DEVIATIONS:
            expected_temporary = KNOWN_TEMPORARY_DEVIATIONS[ours["error"]["code"]][1]
        assert ours["error"]["temporary"] == expected_temporary
        assert ours["error"]["retry_after_ms"] == theirs["error"]["retry_after_ms"]
        assert not theirs["message_has_secret"] and "sk-" + "c" * 32 not in ours["error"]["message"]
    m, tm = ours["meta"], theirs["meta"]
    assert (
        m.get("session_id") == tm["session_id"]
        and m.get("command_exit_code") == tm["command_exit_code"]
    )
    if tm["usage"] is None:
        assert m.get("usage") is None
    else:
        for key, value in tm["usage"].items():
            assert m["usage"][key] == value, key
