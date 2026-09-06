"""ExecResult → success envelopes: prose passthrough (consult), strict review, delegate
diff bounding."""

from __future__ import annotations

import json

from pontonier.backend.protocol import ExecResult, Usage
from pontonier.core import worktree
from pontonier.core.runtime import CommandRun
from tests.support import fakeplugin

from amicus.orchestration import finalize as fz
from amicus.schemas.envelope import Meta


def _structured(**over):
    base = {
        "summary": "Looks fine",
        "verdict": "pass",
        "confidence": "high",
        "findings": [
            {
                "title": "t",
                "severity": "high",
                "file": "a.py",
                "line": 3,
                "evidence": "e",
                "suggestion": None,
            }
        ],
        "questions": ["q"],
        "assumptions": [],
        "next_steps": [1, "x"],
    }
    base.update(over)
    return base


def test_stamp_run_reconciles_a_dropped_model():
    meta = Meta(model="gpt-5.5")
    fz.stamp_run(meta, CommandRun("", "", 0, 42, False), ("--model",))
    assert (
        meta.model is None
        and meta.compat_warnings == ["--model"]
        and meta.elapsed_ms == 42
        and meta.command_exit_code == 0
    )


def test_consult_structured_and_prose_and_sanitization():
    payload = _structured(
        summary="s\x1b[31m",
        findings=[{"title": "t\x07", "severity": "pa\x07ss", "file": "f\x07.py"}],
    )
    res = ExecResult(
        answer=json.dumps(payload),
        structured=payload,
        usage=Usage(1, 2, 3, cached_input_tokens=1),
        session_id="s1",
    )
    out = fz.consult_result(res, Meta())
    assert out["ok"] is True and out["tool"] == "amicus_consult" and out["summary"] == "s[31m"
    assert (
        out["findings"] == []
    )  # severity is a machine field: a control-split value degrades, never repairs
    assert out["questions"] == ["q"] and out["next_steps"] == ["1", "x"]
    assert out["meta"]["usage"]["cached_input_tokens"] == 1 and out["meta"]["session_id"] == "s1"
    assert out["raw_response"]["text"] == json.dumps(
        payload
    )  # closest-to-source carrier keeps its bytes
    prose = fz.consult_result(ExecResult(answer="A plain\x1b answer."), Meta())
    assert (
        prose["summary"] == "A plain answer."
        and prose["raw_response"]["text"] == "A plain\x1b answer."
    )
    empty = fz.consult_result(ExecResult(answer=""), Meta())
    assert empty["summary"] == "(the backend returned no message)"


def test_review_is_strict_and_folds_coverage():
    plugin = fakeplugin.make_plugin()
    out = fz.review_result(ExecResult(answer="prose"), Meta(), [], plugin)
    assert (
        out["ok"] is False
        and out["error"]["code"] == "invalid_json"
        and "prose" in out["error"]["message"]
    )
    out = fz.review_result(ExecResult(answer="[1]"), Meta(), [], plugin)
    assert out["error"]["code"] == "schema_violation"
    secret = "sk-" + "d" * 32
    out = fz.review_result(ExecResult(answer=f"prose token={secret}"), Meta(), [], plugin)
    assert secret not in str(out)
    out = fz.review_result(ExecResult(answer="z" * 5000), Meta(), [], plugin)
    assert out["error"]["message"].count("z") <= 300
    payload = _structured()
    ok = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload), Meta(), [], plugin
    )
    assert ok["ok"] is True and (ok["verdict"], ok["confidence"], ok["review_status"]) == (
        "pass",
        "high",
        "completed",
    )
    assert ok["findings"][0]["title"] == "t" and ok["tool"] == "amicus_review_changes"
    partial = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload), Meta(), ["truncated"], plugin
    )
    assert (partial["verdict"], partial["confidence"]) == (
        "unknown",
        "low",
    ) and "partial" in partial["summary"]
    defaults = fz.review_result(ExecResult(answer="{}", structured={}), Meta(), [], plugin)
    assert (defaults["verdict"], defaults["confidence"], defaults["summary"]) == (
        "unknown",
        "medium",
        "(no summary)",
    )


def test_delegate_relativizes_redacts_and_bounds(tmp_path):
    wt = str(tmp_path / "amicus-wt-x" / "tree")
    aliases = worktree.path_aliases(wt)
    message = f"Created [f.md]({wt}/f.md)."
    diff = "diff --git a/f.md b/f.md\n+x\n"
    meta = Meta()
    out = fz.delegate_result(
        ExecResult(answer=message), meta, diff=diff, aliases=aliases, max_diff_bytes=10_000
    )
    assert out["ok"] is True and out["tool"] == "amicus_delegate"
    assert (
        out["summary"] == "Created [f.md](./f.md)."
        and out["raw_response"]["text"] == "Created [f.md](./f.md)."
    )
    assert (
        out["diff"] == diff and out["diffstat"] == "1 file changed, 1 insertion(+), 0 deletions(-)"
    )
    assert out["meta"]["context_summary"]["files_changed"] == 1 and out["next_steps"]
    none = fz.delegate_result(ExecResult(answer=""), Meta(), diff="", aliases=(), max_diff_bytes=10)
    assert none["diff"] is None and none["summary"].startswith("The backend made no changes.")
    secret_diff = "diff --git a/.env b/.env\n+API_KEY=sk-" + "e" * 40 + "\n"
    meta = Meta()
    redacted = fz.delegate_result(
        ExecResult(answer="ok"), meta, diff=secret_diff, aliases=(), max_diff_bytes=10_000
    )
    assert "sk-" + "e" * 40 not in redacted["diff"]
    assert redacted["meta"]["redacted_paths"] and redacted["meta"]["truncated"] is False
    big = "diff --git a/f.py b/f.py\n" + "+x\n" * 200
    meta = Meta()
    bounded = fz.delegate_result(
        ExecResult(answer="ok"), meta, diff=big, aliases=(), max_diff_bytes=100
    )
    assert bounded["meta"]["truncated"] is True
    assert (
        "AMICUS_MAX_DELEGATE_DIFF_BYTES" in bounded["meta"]["truncation_hint"]
        and len(bounded["diff"].encode()) <= 100
    )
    assert bounded["meta"]["redacted_paths"] == []


def test_delegate_redacts_before_bounding_a_diff_that_still_exceeds_the_budget():
    """Pins redact-then-bound with a byte cap that lands INSIDE the secret token. Under
    bound-then-redact the cut leaves `sk-` plus a few characters, too short for the
    redactor's minimum value length, so a partial key would reach the wire; under
    redact-then-bound the whole token is replaced before the cap applies. (A cap that
    keeps the whole token passes under both orderings and pins nothing.)"""
    prefix = "diff --git a/f.py b/f.py\n+x = 1\n"
    secret = "sk-" + "e" * 40
    secret_line = f'+TOKEN = "{secret}"\n'
    trailer = "+y = 2\n" * 20
    diff = prefix + secret_line + trailer
    keep = 10  # characters of the token that would survive a raw cut
    cap = len(prefix.encode()) + len(b'+TOKEN = "sk-') + keep
    meta = Meta()
    out = fz.delegate_result(
        ExecResult(answer="ok"), meta, diff=diff, aliases=(), max_diff_bytes=cap
    )
    assert out["meta"]["truncated"] is True
    assert out["diff"].startswith(prefix)  # the cut happened past the prefix, as designed
    assert "sk-e" not in out["diff"]  # bound-then-redact would leave 'sk-eeeeeeeeee'


def test_coerce_findings_drops_malformed_entries():
    findings = fz.coerce_findings(
        [
            {"title": "ok", "severity": "low"},
            {"severity": "high"},
            "junk",
            {"title": "bad sev", "severity": "nope"},
        ]
    )
    assert [f.title for f in findings] == ["ok"]
    assert fz.coerce_findings(None) == [] and fz.coerce_findings("x") == []
