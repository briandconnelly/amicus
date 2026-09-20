"""A backend that cites amicus's own temporary files must not pass that on (#140).

Kimi is handed its prompt as a file, so a finding can come back anchored to
`<tmp>/amicus-kimi-handshake-XXXX/prompt.md:28`: a path deleted before the caller reads the
result, and a line number into amicus's framing rather than anything the caller supplied.
"""

from __future__ import annotations

import json
from typing import get_args

import pytest

from amicus.orchestration import finalize, review
from amicus.schemas.results import FindingReason
from amicus.sdk.backend.protocol import ClassifiedFailure

_DIR = "/private/var/folders/xx/T/amicus-kimi-handshake-ab12"
_ART = f"{_DIR}/prompt.md"
_REASON = "backend_artifact_reference_removed"
_REFS = finalize.artifact_refs((_ART,))
_P = finalize.ARTIFACT_PLACEHOLDER


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


def _coerced(structured: dict, refs=_REFS):
    scrubbed, touched = finalize.scrub_structured(structured, refs)
    findings, diagnostics = finalize.coerce_findings(scrubbed["findings"], touched)
    return scrubbed, findings, diagnostics


def test_a_finding_anchored_to_an_artifact_loses_file_and_line_and_says_so():
    _, [finding], diagnostics = _coerced(
        _answer({"title": "t", "severity": "high", "file": _ART, "line": 28})
    )
    assert finding.title == "t" and finding.severity == "high", "the finding survives"
    assert finding.file is None and finding.line is None, "a dead anchor keeps no line"
    assert diagnostics is not None and diagnostics.dropped == 0
    assert diagnostics.reasons == [_REASON]


def test_a_workspace_path_that_merely_looks_like_one_is_left_alone():
    """Exact run-owned paths only: a prefix or temp-root heuristic would clear this real,
    actionable location, which costs the caller more than a leaked dead path does."""
    lookalike = "tests/fixtures/amicus-kimi-handshake-zz99/prompt.md"
    _, [finding], diagnostics = _coerced(_answer({"title": "t", "file": lookalike, "line": 3}))
    assert finding.file == lookalike and finding.line == 3 and diagnostics is None


def test_the_placeholder_is_ordinary_text_and_proves_nothing():
    """What changed travels beside the object as indexes, never inside it: a backend can
    write the placeholder itself, and a real file can be named with it."""
    real = f"docs/{_P}/example.py"
    for refs in (finalize.NO_ARTIFACTS, _REFS):
        _, [finding], diagnostics = _coerced(
            _answer({"title": f"about {_P}", "file": real, "line": 7}), refs
        )
        assert finding.file == real and finding.line == 7 and diagnostics is None


def test_every_prose_carrier_is_scrubbed():
    structured = _answer(
        {"title": f"in {_ART}", "evidence": f"see {_ART}:28", "suggestion": f"edit {_ART}."},
        summary=f"read {_ART}",
        questions=[f"why {_ART}?"],
        assumptions=[f"{_ART} is current"],
        next_steps=[f"open {_ART}"],
    )
    scrubbed, [finding], diagnostics = _coerced(structured)
    assert _DIR not in json.dumps(scrubbed)
    assert finding.evidence == f"see {_P}:28" and finding.suggestion == f"edit {_P}."
    assert diagnostics is not None and diagnostics.reasons == [_REASON], (
        "a finding whose prose was changed is reported, like one whose anchor was cleared"
    )


def test_scrubbing_top_level_prose_alone_is_not_a_findings_deviation():
    scrubbed, _, diagnostics = _coerced(_answer({"title": "t"}, summary=f"read {_ART}"))
    assert scrubbed["summary"] == f"read {_P}"
    assert diagnostics is None, "findings_diagnostics describes the findings list only"


def test_only_the_changed_finding_is_reported_and_an_unreadable_one_still_counts():
    structured = _answer({"title": "clean"})
    structured["findings"] += [{"title": "t", "file": _ART, "line": 1}, f"see {_ART}"]
    scrubbed, touched = finalize.scrub_structured(structured, _REFS)
    assert touched == {1, 2}
    findings, diagnostics = finalize.coerce_findings(scrubbed["findings"], touched)
    assert [f.title for f in findings] == ["clean", "t"]
    assert diagnostics is not None and diagnostics.dropped == 1
    assert diagnostics.reasons == [_REASON, "invalid_entry"]


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (f"{_ART}:28", f"{_P}:28"),
        (f"see {_ART}.", f"see {_P}."),
        (f"({_ART})", f"({_P})"),
        (f"{_ART}.bak", f"{_ART}.bak"),
        (f"{_ART}x", f"{_ART}x"),
        (f"{_DIR}/other.md", f"{_DIR}/other.md"),
    ],
)
def test_a_listed_file_is_matched_at_its_boundaries_and_nowhere_else(text, want):
    assert _REFS.scrub(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (f"{_DIR}/other.md:3 and {_DIR}", f"{_P}:3 and {_P}"),
        (f"ls {_DIR}/", f"ls {_P}"),
        (f"{_DIR}c/prompt.md", f"{_DIR}c/prompt.md"),
        (f"{_DIR}.bak", f"{_DIR}.bak"),
    ],
)
def test_a_staging_dir_takes_everything_beneath_it_and_no_longer_sibling(text, want):
    assert finalize.artifact_refs((_ART,), _DIR).scrub(text) == want


def test_every_staged_artifact_is_covered_not_just_the_prompt():
    agent = f"{_DIR}/readonly-agent.md"
    refs = finalize.artifact_refs((_ART, agent))
    _, [finding], _ = _coerced(_answer({"title": "t", "file": agent, "line": 1}), refs)
    assert finding.file is None


def test_no_artifacts_means_nothing_is_touched():
    structured = _answer({"title": "t", "file": _ART, "line": 28})
    assert finalize.artifact_refs(()) is finalize.NO_ARTIFACTS
    scrubbed, touched = finalize.scrub_structured(structured, finalize.NO_ARTIFACTS)
    assert scrubbed is structured and touched == frozenset()
    assert finalize.scrub_answer(_ART, finalize.NO_ARTIFACTS) == _ART


def test_the_reason_merges_in_declaration_order_and_never_folds_the_verdict():
    _, _, diagnostics = _coerced(
        _answer({"title": "t", "severity": "HIGH", "file": _ART, "line": 28, "cwe": "x"})
    )
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
    refs = finalize.artifact_refs((staged,))
    _, [finding], diagnostics = _coerced(_answer({"title": "t", "file": cited, "line": 2}), refs)
    assert finding.file is None and diagnostics is not None


def _spellings(obj: dict) -> dict[str, str]:
    plain = json.dumps(obj)
    return {
        "plain": plain,
        "solidus": plain.replace("/", "\\/"),
        "unicode": plain.replace(_ART, "".join(f"\\u{ord(c):04x}" for c in _ART)),
    }


@pytest.mark.parametrize("spelling", ["plain", "solidus", "unicode"])
def test_a_json_escaped_path_does_not_survive_in_the_raw_answer(spelling):
    """JSON lets a backend write the same path as `\\/tmp\\/x` or `\\u002ftmp`. Text
    replacement cannot see those, and a review re-parses the raw answer, so the raw text is
    judged by what it DECODES to."""
    obj = _answer({"title": "t", "file": _ART, "line": 3})
    text = _spellings(obj)[spelling]
    assert json.loads(text) == obj, "control: every spelling is the same object"
    raw = finalize.scrub_answer(text, _REFS)
    assert "amicus-kimi-handshake-" not in json.dumps(json.loads(raw))
    assert json.loads(raw)["findings"][0]["title"] == "t", "still the same answer"


def test_prose_answers_and_failures_are_scrubbed_as_text():
    assert finalize.scrub_answer(f"I read {_ART}:28.", _REFS) == f"I read {_P}:28."
    failure = ClassifiedFailure(
        code="nonzero_exit", detail=f"kimi exited 1: cannot read {_ART}", details={"reason": _ART}
    )
    scrubbed = finalize.scrub_failure(failure, _REFS)
    assert scrubbed.detail == f"kimi exited 1: cannot read {_P}"
    assert scrubbed.details == {"reason": _P} and scrubbed.code == "nonzero_exit"
    assert finalize.scrub_failure(failure, finalize.NO_ARTIFACTS) is failure


@pytest.mark.parametrize("spelling", ["plain", "solidus", "unicode"])
def test_a_path_used_as_an_object_key_is_scrubbed_in_every_spelling(spelling):
    """#207: the decoded-value pass walked values only, so a key the backend escaped came
    through whole. A key is as much the backend's text as a value is."""
    obj = _answer({"title": "t", "file": None, "line": None}, **{_ART: "x", "notes": {_ART: 1}})
    text = _spellings(obj)[spelling]
    assert json.loads(text) == obj, "control: every spelling is the same object"
    raw = json.loads(finalize.scrub_answer(text, _REFS))
    assert "amicus-kimi-handshake-" not in json.dumps(raw)
    assert raw[_P] == "x" and raw["notes"] == {_P: 1}, "the values keep their place"


def test_keys_that_scrub_to_the_same_text_are_numbered_not_merged():
    """Two staged files, or a key that already reads as the placeholder, scrub to one string;
    a plain dict would keep the last and drop the rest without a trace."""
    other = f"{_DIR}/other.md"
    refs = finalize.artifact_refs((_ART,), _DIR)
    scrubbed, _ = finalize.scrub_structured({_P: 0, _ART: 1, other: 2, "findings": []}, refs)
    assert scrubbed == {_P: 0, f"{_P} (2)": 1, f"{_P} (3)": 2, "findings": []}


@pytest.mark.parametrize("slash", ["\\/", "\\u002f", "\\u002F"])
def test_an_escaped_path_inside_prose_is_scrubbed_where_the_slash_is_what_was_escaped(slash):
    """An answer that is prose around a JSON fragment is never decoded, so the text pass has
    to know the fragment's spelling. It knows the solidus escapes, the one spelling ordinary
    encoders emit; a path spelled entirely in \\uXXXX inside prose is not chased."""
    escaped = _ART.replace("/", slash)
    text = f'Here is what I found: {{"file": "{escaped}", "line": 28}} and nothing else.'
    assert "handshake" in text, "control"
    assert finalize.scrub_answer(text, _REFS) == (
        f'Here is what I found: {{"file": "{_P}", "line": 28}} and nothing else.'
    )
    under = f'{{"file": "{_DIR.replace("/", slash)}{slash}notes.txt"}}'
    assert "handshake" not in finalize.artifact_refs((_ART,), _DIR).scrub(f"x {under} y")


@pytest.mark.parametrize(
    ("refs", "owned", "tail", "decoded_tail"),
    [
        (finalize.artifact_refs((), _DIR), _DIR, "\\u002ebak", ".bak"),
        (finalize.artifact_refs((), _DIR), _DIR, "\\u0063", "c"),
        (finalize.artifact_refs((_ART,)), _ART, "\\u0078", "x"),
        (finalize.artifact_refs((_ART,)), _ART, "\\u002ebak", ".bak"),
    ],
)
def test_an_escaped_character_after_a_path_is_not_mistaken_for_its_end(
    refs, owned, tail, decoded_tail
):
    """Codex's review of #209: the boundary guards read the next ENCODED character, and a
    `\\u002e` begins with a backslash, which is no word character, so `<dir>\\u002ebak`
    passed as the directory's end although it decodes to a longer sibling. The text pass now
    declines what it cannot read, and the decoded pass, whose boundaries are exact, decides."""
    escaped = owned.replace("/", "\\/")
    fragment = json.dumps({"summary": "S"}).replace("S", escaped + tail)
    assert json.loads(fragment)["summary"] == owned + decoded_tail, "control: longer, unowned"
    mine = json.dumps({"summary": "S"}).replace("S", escaped)
    # Whole JSON is decoded, where boundaries are exact; prose is where the text pass, and so
    # these guards, decide. Both must leave the unowned path and take the owned one.
    for wrap in ("{}", "I saw {} in the log."):
        text = wrap.format(fragment)
        assert finalize.scrub_answer(text, refs) == text, wrap
        assert "handshake" not in finalize.scrub_answer(wrap.format(mine), refs), wrap


@pytest.mark.parametrize("spelling", ["plain", "solidus", "unicode"])
def test_a_whole_json_answer_is_never_left_with_duplicate_keys(spelling):
    """Copilot's review of #209: the text pass ran first, and it turns two owned keys into
    one key written twice, which amicus's own reader refuses (#51), so `raw_response.text`
    stopped being the JSON it was. A whole-JSON answer is decoded FIRST, where collisions are
    numbered; the text pass is for what cannot be decoded."""
    other = f"{_DIR}/other.md"
    obj = {_P: 0, _ART: 1, other: 2, "findings": []}
    text = json.dumps(obj)
    if spelling == "solidus":
        text = text.replace("/", "\\/")
    elif spelling == "unicode":
        text = text.replace(_ART, "".join(f"\\u{ord(c):04x}" for c in _ART))
    assert finalize.classify_structured(text) == ("ok", obj), "control"
    raw = finalize.scrub_answer(text, finalize.artifact_refs((_ART,), _DIR))
    status, parsed = finalize.classify_structured(raw)
    assert status == "ok", raw
    assert parsed == {_P: 0, f"{_P} (2)": 1, f"{_P} (3)": 2, "findings": []}
