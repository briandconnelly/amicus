"""Hot-path result differential: the same raw stdout/stderr through amicus's loop with the
real claude plugin (a DirectSite in a tmp dir) vs claude-in-codex's normalize_envelope /
classify_failure (captured fixture). Compared on the shared projection; codes are compared
after amicus's `backend_*` generalization; deviations are pinned per CASE."""

from __future__ import annotations

import pytest
from pontonier.core.gitdiff import DiffResult, DiffSummary
from tests.support import claudefixtures as cf

from amicus.orchestration import review
from amicus.orchestration import run as run_mod
from amicus.request import RunSpec
from amicus.schemas.codes import generalize_code

FIXTURE = cf.load_fixture()
SECRET = "sk-" + "c" * 32

# Deliberate differences from the sibling, keyed by case. Each entry names what amicus
# returns instead; the assertion below uses it in place of the sibling's value. Every entry
# is an ADR 0010 decision, and the PR body repeats this table.
KNOWN_DEVIATIONS: dict[str, dict[str, object]] = {
    # Decision 3: rate limits are minted, not degraded to a retryable nonzero_exit.
    "zero_exit_rate_limited": {"code": "backend_rate_limited", "temporary": True},
    "zero_exit_is_error_subtype_success": {"code": "backend_rate_limited", "temporary": True},
    # The strict review path (ADR 0007/0009): exit-0 prose on a review is invalid_json, never
    # a verdict=unknown success.
    "review_prose": {"ok": False, "code": "invalid_json"},
    # pontonier's shared table defaults a PROCESS nonzero_exit to temporary=True (M1/M3 kept
    # it); the sibling's classifier says False. Zero-exit envelope errors are False on both.
    "nonzero_secret": {"temporary": True},
    "nonzero_secret_straddles_cut": {"temporary": True},
    # Same default for a zero-exit stdout that is not a JSON envelope at all (invalid_json is
    # retry_then_report in the shared table; the sibling's classifier says not retryable).
    "zero_exit_not_json": {"temporary": True},
    "zero_exit_non_object": {"temporary": True},
}


def _spec(kind, cwd):
    return RunSpec(
        backend="claude",
        kind=kind,
        tool=f"amicus_{kind}",
        cwd=str(cwd),
        workspace_source="param",
        roots_source="client",
        host_name="Codex",
        timeout_seconds=60,
        options={"config_mode": "inherit", "access": "toolless", "max_budget_usd": 1.0},
        question="q",
        scope="working_tree",
    )


@pytest.mark.parametrize("case", sorted(FIXTURE["envelopes"]))
async def test_envelope_projection_matches_the_sibling(
    pinned_claude_bin, monkeypatch, tmp_path, case
):
    entry = FIXTURE["envelopes"][case]
    inp, theirs = entry["input"], entry["sibling"]
    deviation = KNOWN_DEVIATIONS.get(case, {})
    plugin, _ = cf.make_backend()
    calls: list = []
    stderr = inp["stderr"]
    if stderr == "claude_not_found":
        # The sibling's runner smuggles binary-missing through stderr; amicus's loop synthesizes
        # the pontonier BINARY_NOT_FOUND run when the resolver returns None.
        plugin, _ = cf.make_backend({"AMICUS_CLAUDE_BIN": "/nonexistent/claude"})
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        cf.scripted_run_async(
            stdout=inp["stdout"],
            stderr="" if stderr in ("claude_not_found", "timeout") else stderr,
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
    ours = await run_mod.run_request(_spec(inp["kind"], tmp_path), plugin)
    expected_ok = deviation.get("ok", theirs["ok"])
    assert ours["ok"] == expected_ok, ours
    if expected_ok:
        for key in ("summary", "verdict", "confidence"):
            if key in theirs:
                assert ours[key] == theirs[key], key
        assert len(ours["findings"]) == theirs["findings_count"]
        assert ours["meta"].get("session_id") == theirs["session_id"]
    else:
        expected_code = deviation.get(
            "code", generalize_code((theirs.get("error") or {}).get("code", ""), "claude")
        )
        assert ours["error"]["code"] == expected_code, ours["error"]
        if "temporary" in deviation or theirs["ok"] is False:
            expected_temporary = deviation.get("temporary", theirs["error"]["temporary"])
            assert ours["error"]["temporary"] == expected_temporary
            assert ours["error"]["retry_after_ms"] == theirs["error"]["retry_after_ms"]
        message = ours["error"]["message"]
        if theirs["ok"] is False:
            assert not theirs["message_has_secret"] and not theirs["message_has_secret_prefix"]
        assert SECRET not in message and "sk-cccc" not in message
    if theirs["usage"] is None:
        assert ours["meta"].get("usage") is None
    else:
        for key, value in theirs["usage"].items():
            # Error envelopes drop null meta keys (serialize_error's exclude_none), so read
            # with .get: an absent key and a null value mean the same thing on the wire.
            assert ours["meta"]["usage"].get(key) == value, key


def test_every_deviation_names_a_captured_case():
    assert set(KNOWN_DEVIATIONS) <= set(FIXTURE["envelopes"])
