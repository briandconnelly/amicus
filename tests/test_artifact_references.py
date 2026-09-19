"""A backend that cites amicus's own temporary files must not pass that on (#140).

Kimi is handed its prompt as a file, so a finding can come back anchored to
`<tmp>/amicus-kimi-handshake-XXXX/prompt.md:28`: a path deleted before the caller reads the
result, and a line number into amicus's framing rather than anything the caller supplied.
"""

from __future__ import annotations

import json
from typing import get_args

from amicus.orchestration import finalize, review
from amicus.schemas.results import FindingReason
from amicus.sdk.backend.protocol import ExecResult

_ART = "/private/var/folders/xx/T/amicus-kimi-handshake-ab12/prompt.md"
_REASON = "backend_artifact_reference_removed"


def _answer(finding: dict, **extra) -> dict:
    return {
        "summary": "s",
        "verdict": "pass",
        "confidence": "high",
        "findings": [finding],
        "questions": [],
        "assumptions": [],
        "next_steps": [],
        **extra,
    }


def _scrubbed(structured: dict, artifacts=(_ART,)) -> ExecResult:
    raw = ExecResult(answer=json.dumps(structured), structured=structured)
    return finalize.scrub_artifact_references(raw, artifacts)


def test_a_finding_anchored_to_an_artifact_loses_file_and_line_and_says_so():
    result = _scrubbed(_answer({"title": "t", "severity": "high", "file": _ART, "line": 28}))
    findings, diagnostics = finalize.coerce_findings(result.structured["findings"])
    [finding] = findings
    assert finding.title == "t" and finding.severity == "high", "the finding survives"
    assert finding.file is None and finding.line is None, "a dead anchor keeps no line"
    assert diagnostics is not None and diagnostics.dropped == 0
    assert diagnostics.reasons == [_REASON]


def test_a_workspace_path_that_merely_looks_like_one_is_left_alone():
    """Exact run-owned paths only: a prefix or temp-root heuristic would clear this real,
    actionable location, which costs the caller more than a leaked dead path does."""
    lookalike = "tests/fixtures/amicus-kimi-handshake-zz99/prompt.md"
    result = _scrubbed(_answer({"title": "t", "file": lookalike, "line": 3}))
    findings, diagnostics = finalize.coerce_findings(result.structured["findings"])
    assert findings[0].file == lookalike and findings[0].line == 3 and diagnostics is None


def test_every_prose_carrier_and_the_raw_answer_are_scrubbed():
    structured = _answer(
        {"title": f"in {_ART}", "evidence": f"see {_ART}:28", "suggestion": f"edit {_ART}"},
        summary=f"read {_ART}",
        questions=[f"why {_ART}?"],
        assumptions=[f"{_ART} is current"],
        next_steps=[f"open {_ART}"],
    )
    result = _scrubbed(structured)
    assert _ART not in json.dumps(result.structured) and _ART not in result.answer
    assert finalize.ARTIFACT_PLACEHOLDER in result.answer
    _, diagnostics = finalize.coerce_findings(result.structured["findings"])
    assert diagnostics is not None and diagnostics.reasons == [_REASON], (
        "a finding whose prose was changed is reported, like one whose anchor was cleared"
    )


def test_scrubbing_top_level_prose_alone_is_not_a_findings_deviation():
    result = _scrubbed(_answer({"title": "t"}, summary=f"read {_ART}"))
    assert _ART not in result.structured["summary"]
    _, diagnostics = finalize.coerce_findings(result.structured["findings"])
    assert diagnostics is None, "findings_diagnostics describes the findings list only"


def test_every_staged_artifact_is_covered_not_just_the_prompt():
    agent = _ART.replace("prompt.md", "readonly-agent.md")
    result = _scrubbed(_answer({"title": "t", "file": agent, "line": 1}), (_ART, agent))
    findings, _ = finalize.coerce_findings(result.structured["findings"])
    assert findings[0].file is None


def test_no_artifacts_means_nothing_is_touched():
    structured = _answer({"title": "t", "file": _ART, "line": 28})
    raw = ExecResult(answer=json.dumps(structured), structured=structured)
    assert finalize.scrub_artifact_references(raw, ()) is raw


def test_the_reason_merges_in_declaration_order_and_never_folds_the_verdict():
    result = _scrubbed(
        _answer({"title": "t", "severity": "HIGH", "file": _ART, "line": 28, "cwe": "x"})
    )
    _, diagnostics = finalize.coerce_findings(result.structured["findings"])
    assert diagnostics is not None
    declared = [r for r in get_args(FindingReason) if r in diagnostics.reasons]
    assert diagnostics.reasons == declared and set(declared) == {
        "severity_normalized",
        "extra_fields_omitted",
        _REASON,
    }
    assert _REASON not in review._REPRESENTATION_LOSS, (
        "the finding survives and no caller-addressable location was lost, so a pass stands"
    )


def test_the_resolved_spelling_of_a_staged_path_is_covered_too(tmp_path):
    """macOS hands out temp paths under /var that resolve under /private/var, and a backend
    may cite either. The artifact is named through a symlink here; the answer uses the
    resolved path, which differs as a string."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "prompt.md").write_text("x")
    link = tmp_path / "link"
    link.symlink_to(real)
    staged, cited = str(link / "prompt.md"), str(real / "prompt.md")
    assert staged != cited
    result = _scrubbed(_answer({"title": "t", "file": cited, "line": 2}), (staged,))
    findings, diagnostics = finalize.coerce_findings(result.structured["findings"])
    assert findings[0].file is None and diagnostics is not None
