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
from amicus.schemas.results import Coverage

_COMPLETE = Coverage(status="complete")
_TRUNCATED = Coverage(status="partial", omission_reasons=["truncated"])


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
    out = fz.review_result(ExecResult(answer="prose"), Meta(), _COMPLETE, plugin)
    assert (
        out["ok"] is False
        and out["error"]["code"] == "invalid_json"
        and "prose" in out["error"]["message"]
    )
    out = fz.review_result(ExecResult(answer="[1]"), Meta(), _COMPLETE, plugin)
    assert out["error"]["code"] == "schema_violation"
    secret = "sk-" + "d" * 32
    out = fz.review_result(ExecResult(answer=f"prose token={secret}"), Meta(), _COMPLETE, plugin)
    assert secret not in str(out)
    out = fz.review_result(ExecResult(answer="z" * 5000), Meta(), _COMPLETE, plugin)
    assert out["error"]["message"].count("z") <= 300
    payload = _structured()
    ok = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload), Meta(), _COMPLETE, plugin
    )
    assert ok["ok"] is True and (ok["verdict"], ok["confidence"], ok["review_status"]) == (
        "pass",
        "high",
        "completed",
    )
    assert ok["findings"][0]["title"] == "t" and ok["tool"] == "amicus_review_changes"
    partial = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload), Meta(), _TRUNCATED, plugin
    )
    assert (partial["verdict"], partial["confidence"]) == (
        "unknown",
        "low",
    ) and "partial" in partial["summary"]
    # The fold and the disclosure read one object, so the reason it acted on is on the wire.
    assert ok["coverage"]["status"] == "complete"
    assert partial["coverage"]["omission_reasons"] == ["truncated"]
    # A bare object deviates on every field. verdict and confidence still coerce to their
    # honest defaults, and the missing findings member then takes confidence the rest of
    # the way down: a response that said nothing does not get to claim medium certainty.
    defaults = fz.review_result(ExecResult(answer="{}", structured={}), Meta(), _COMPLETE, plugin)
    assert (defaults["verdict"], defaults["confidence"]) == ("unknown", "low")
    assert defaults["summary"].endswith("(no summary)")
    assert defaults["findings_diagnostics"]["reasons"] == ["missing_findings"]


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


def test_coerce_findings_reports_every_entry_it_could_not_represent():
    """The loss is REPORTED, never silent (issue #38). A finding that cannot be carried
    contributes a count and a reason code, so a caller can tell a clean review from a
    review whose findings amicus failed to relay."""
    findings, diag = fz.coerce_findings(
        [
            {"title": "ok", "severity": "low"},
            {"severity": "high"},  # no title: unrepresentable, nothing to invent
            "junk",  # not an object
            {"title": "bad sev", "severity": "nope"},  # not a severity, and not guessable
        ]
    )
    assert [f.title for f in findings] == ["ok"]
    assert diag is not None
    assert diag.dropped == 3
    assert diag.reasons == ["invalid_entry"]


def test_coerce_findings_reports_nothing_when_every_entry_conforms():
    findings, diag = fz.coerce_findings([{"title": "ok", "severity": "low"}])
    assert [f.title for f in findings] == ["ok"] and diag is None


def test_coerce_findings_normalizes_severity_case_and_surrounding_space():
    """Two of three backends are only ASKED for the schema (schema_instruction), never
    held to it, so `HIGH` is an ordinary return. Case is not meaning: normalize it and
    keep the finding, but say that we did."""
    findings, diag = fz.coerce_findings([{"title": "shouty", "severity": " HIGH "}])
    assert [(f.title, f.severity) for f in findings] == [("shouty", "high")]
    assert diag is not None and diag.dropped == 0
    assert diag.reasons == ["severity_normalized"]


def test_coerce_findings_does_not_repair_a_control_split_severity():
    """The module's standing rule: a control-split machine value degrades, it is not
    repaired. Normalization is case and space only."""
    findings, diag = fz.coerce_findings([{"title": "t", "severity": "hi\x00gh"}])
    assert findings == [] and diag is not None and diag.dropped == 1
    assert diag.reasons == ["invalid_entry"]


def test_coerce_findings_keeps_a_finding_whose_extra_keys_it_cannot_carry():
    """`category`/`cwe`/`confidence` are ordinary additions. Losing the whole finding
    over one is the defect; the finding survives and the omission is reported."""
    findings, diag = fz.coerce_findings(
        [{"title": "t", "severity": "high", "category": "security", "cwe": "CWE-79"}]
    )
    assert [(f.title, f.severity) for f in findings] == [("t", "high")]
    assert diag is not None and diag.dropped == 0
    assert diag.reasons == ["extra_fields_omitted"]


def test_coerce_findings_never_echoes_the_content_it_omitted():
    """Reason codes are a fixed vocabulary. Extra-key NAMES and values never ride the
    result: backend output can echo caller input, so it does not get a free pass."""
    findings, diag = fz.coerce_findings(
        [{"title": "t", "severity": "high", "leaked_key": "sekrit-value"}]
    )
    assert findings and diag is not None
    blob = diag.model_dump_json()
    assert "leaked_key" not in blob and "sekrit-value" not in blob


def test_coerce_findings_distinguishes_an_unusable_container_from_an_empty_one():
    """`findings: []` is a backend saying "nothing found". `findings: {...}` or a missing
    key is a backend whose output we could not read - and the count is unknowable, so it
    is reported as null rather than as zero."""
    empty, empty_diag = fz.coerce_findings([])
    assert empty == [] and empty_diag is None
    for bad in ({"a": 1}, "x", 3):
        findings, diag = fz.coerce_findings(bad)
        assert findings == [], bad
        assert diag is not None and diag.dropped is None, bad
        assert diag.reasons == ["invalid_container"], bad
    absent, absent_diag = fz.coerce_findings(fz.ABSENT)
    assert absent == []
    assert absent_diag is not None and absent_diag.dropped is None
    assert absent_diag.reasons == ["missing_findings"], "absence is its own deviation"
    null, null_diag = fz.coerce_findings(None)
    assert null == [], "an explicit null is a present container, not an absent key"
    assert null_diag is not None and null_diag.dropped is None
    assert null_diag.reasons == ["invalid_container"]


def test_coerce_findings_deduplicates_and_orders_reasons():
    findings, diag = fz.coerce_findings(
        [
            {"title": "a", "severity": "HIGH", "extra": 1},
            {"title": "b", "severity": "LOW"},
            {"severity": "low"},
            "junk",
        ]
    )
    assert [f.title for f in findings] == ["a", "b"]
    assert diag is not None and diag.dropped == 2
    assert diag.reasons == ["severity_normalized", "extra_fields_omitted", "invalid_entry"]


def test_consult_reports_findings_it_could_not_carry():
    payload = _structured(findings=[{"title": "t", "severity": "nope"}])
    out = fz.consult_result(ExecResult(answer=json.dumps(payload), structured=payload), Meta())
    assert out["findings"] == []
    assert out["findings_diagnostics"] == {"dropped": 1, "reasons": ["invalid_entry"]}


def test_a_clean_result_carries_no_diagnostics_at_all():
    payload = _structured()
    out = fz.consult_result(ExecResult(answer=json.dumps(payload), structured=payload), Meta())
    review = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert out["findings_diagnostics"] is None and review["findings_diagnostics"] is None


def test_a_lost_finding_stops_a_pass_verdict_from_standing():
    """The defect: the finding is discarded while the verdict survives, so the caller is
    told a review is clean that the backend did not report as clean (issue #38)."""
    payload = _structured(verdict="pass", confidence="high", findings=[{"severity": "high"}])
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")
    assert out["findings_diagnostics"]["dropped"] == 1
    assert "could not be fully represented" in out["summary"]
    assert out["summary"].endswith("Looks fine")


def test_a_lost_finding_never_softens_a_negative_verdict():
    """A concrete negative stands on its own: missing output does not refute it, and
    downgrading its confidence would be the same dishonesty in the other direction."""
    for verdict in ("fail", "concerns"):
        payload = _structured(verdict=verdict, confidence="high", findings=["junk"])
        out = fz.review_result(
            ExecResult(answer=json.dumps(payload), structured=payload),
            Meta(),
            _COMPLETE,
            fakeplugin.make_plugin(),
        )
        assert (out["verdict"], out["confidence"]) == (verdict, "high"), verdict
        assert out["findings_diagnostics"]["dropped"] == 1, verdict
        assert out["summary"] == "Looks fine", verdict


def test_an_unusable_findings_container_stops_a_pass_verdict():
    payload = _structured(verdict="pass", confidence="high", findings={"one": "two"})
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")
    assert out["findings_diagnostics"] == {"dropped": None, "reasons": ["invalid_container"]}


def test_a_surviving_finding_does_not_disturb_the_verdict():
    """Extra keys and shouted severities are reported, not punished: the finding's
    substance reached the caller, so a `pass` still means what the backend said."""
    payload = _structured(
        verdict="pass",
        confidence="high",
        findings=[{"title": "t", "severity": "HIGH", "category": "security"}],
    )
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"], out["summary"]) == ("pass", "high", "Looks fine")
    assert out["findings"][0]["severity"] == "high"
    assert out["findings_diagnostics"]["reasons"] == [
        "severity_normalized",
        "extra_fields_omitted",
    ]


def test_partial_coverage_and_a_lost_finding_are_reported_as_separate_causes():
    """They are opposite axes - the model did not see everything, versus amicus could not
    relay what it said - so neither sentence may stand in for the other."""
    payload = _structured(verdict="pass", findings=["junk"])
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _TRUNCATED,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")
    assert "coverage is partial (truncated)" in out["summary"]
    assert "could not be fully represented" in out["summary"]


def test_adversarial_review_folds_findings_loss_the_same_way():
    payload = _structured(verdict="pass", confidence="high", findings=["junk"])
    out = fz.adversarial_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")
    assert out["findings_diagnostics"]["dropped"] == 1


def test_an_explicit_null_findings_member_stops_a_pass_verdict():
    """`s.get("findings")` cannot tell an absent key from an explicit null, so a backend
    answering `"findings": null` used to look exactly like a backend that said nothing -
    and a `pass` stood over it. The schema requires an array; null is a deviation."""
    payload = _structured(verdict="pass", confidence="high", findings=None)
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")
    assert out["findings_diagnostics"] == {"dropped": None, "reasons": ["invalid_container"]}


def test_an_omitted_findings_member_stops_a_pass_verdict():
    """`findings` is REQUIRED by the output schema, so a backend that omits it has not
    said "no findings" - it has left amicus unable to know. A verdict the backend did
    supply would otherwise stand over that silence, which is issue #38 by another route.
    Distinct from `invalid_container`, which is a member that is present and unusable."""
    payload = {"summary": "ok", "verdict": "pass", "confidence": "high"}
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")
    assert out["findings_diagnostics"] == {"dropped": None, "reasons": ["missing_findings"]}


# --- issue #53: an unreadable confidence may not be invented -----------------------------

_UNREADABLE_CONFIDENCE = {
    "absent": {},
    "null": {"confidence": None},
    "wrong_type": {"confidence": 3},
    "invalid_string": {"confidence": "very high"},
}


def test_an_unreadable_confidence_is_reported_as_unknown_not_invented():
    """Issue #53. `low` is the lowest confidence a backend can REPORT, not the absence of
    a report, so defaulting to it manufactures a claim just as `medium` did - smaller, and
    in the same direction. `unknown` declines to make one, exactly as `verdict` does."""
    for label, over in _UNREADABLE_CONFIDENCE.items():
        payload = _structured(**over)
        if label == "absent":
            payload.pop("confidence")
        out = fz.review_result(
            ExecResult(answer=json.dumps(payload), structured=payload),
            Meta(),
            _COMPLETE,
            fakeplugin.make_plugin(),
        )
        assert out["confidence"] == "unknown", label
        assert out["findings_diagnostics"] is None, label


def test_an_unreadable_confidence_never_disturbs_the_verdict():
    """Confidence answers how sure the backend was, not what it found. A backend that
    reported a concrete judgment and said nothing readable about its certainty still
    reported that judgment - neither softened nor promoted."""
    for verdict in ("pass", "concerns", "fail", "unknown"):
        payload = _structured(verdict=verdict)
        payload.pop("confidence")
        out = fz.review_result(
            ExecResult(answer=json.dumps(payload), structured=payload),
            Meta(),
            _COMPLETE,
            fakeplugin.make_plugin(),
        )
        assert (out["verdict"], out["confidence"]) == (verdict, "unknown"), verdict
        assert out["summary"] == "Looks fine", verdict


def test_a_reported_low_confidence_is_not_reported_as_unknown():
    """The control for the test above: `low` still means the backend said `low`. Without
    this, defaulting the whole enum to `unknown` would pass the honesty test by erasing
    the distinction it exists to draw."""
    payload = _structured(confidence="low")
    out = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("pass", "low")


def test_a_fold_still_states_low_over_an_unreadable_confidence():
    """The folds speak for amicus, not for the backend: partial coverage and lost findings
    are bases amicus HAS for distrusting the delivered review, so `low` there is its own
    assessment rather than an invented reading of the backend's. `unknown` survives only
    where nothing - backend or fold - had anything to say."""
    payload = _structured(verdict="pass")
    payload.pop("confidence")
    partial = fz.review_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _TRUNCATED,
        fakeplugin.make_plugin(),
    )
    assert (partial["verdict"], partial["confidence"]) == ("unknown", "low")
    lost = _structured(verdict="pass", findings=["junk"])
    lost.pop("confidence")
    out = fz.review_result(
        ExecResult(answer=json.dumps(lost), structured=lost),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("unknown", "low")


def test_adversarial_review_declines_to_invent_a_confidence_the_same_way():
    payload = _structured(verdict="concerns")
    payload.pop("confidence")
    out = fz.adversarial_result(
        ExecResult(answer=json.dumps(payload), structured=payload),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("concerns", "unknown")


def test_confidence_is_lowered_only_where_the_verdict_is_withheld():
    """What the published `confidence` description now promises, pinned. Both folds lower
    the rating and withhold the verdict together or not at all, so a `low` beside any
    verdict other than `unknown` is the backend's own word - and a high confidence is
    never evidence that coverage was complete. A characterization test: it holds today,
    and the description would be false the moment it stopped holding."""
    for verdict in ("fail", "concerns"):
        payload = _structured(verdict=verdict, confidence="high", findings=["junk"])
        out = fz.review_result(
            ExecResult(answer=json.dumps(payload), structured=payload),
            Meta(),
            Coverage(status="partial", omission_reasons=["truncated", "redacted"]),
            fakeplugin.make_plugin(),
        )
        assert (out["verdict"], out["confidence"]) == (verdict, "high"), verdict
        assert out["findings_diagnostics"]["reasons"] == ["invalid_entry"], verdict
    # An addition amicus reshaped rather than lost never lowers anything on its own.
    kept = _structured(
        verdict="pass", confidence="high", findings=[{"title": "t", "category": "sec"}]
    )
    out = fz.review_result(
        ExecResult(answer=json.dumps(kept), structured=kept),
        Meta(),
        _COMPLETE,
        fakeplugin.make_plugin(),
    )
    assert (out["verdict"], out["confidence"]) == ("pass", "high")
