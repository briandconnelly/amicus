"""`_summarize_junit` must record which test did not pass, and nothing a model wrote.

A failed live gate used to record only `exit_status`, so diagnosing one meant respending quota on
all three backends (issue #24). The reduction below adds node ids and counts. The risk it
introduces is the reason these tests exist: a JUnit report holds the traceback, the assertion
message, and the captured stdout of a run that talked to a model, so a careless reader of that
file would write model prose — or an echoed prompt — into `.release-evidence/`, which AGENTS.md
rule 18 forbids.

Every test here works on a report built to be full of prose, so a negative result means the
reduction dropped it, not that there was nothing to drop.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "record_live_gate_evidence.py"
_spec = importlib.util.spec_from_file_location("record_live_gate_evidence", _SCRIPT)
assert _spec is not None and _spec.loader is not None
evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evidence)

# Distinctive strings standing in for what a real report carries: the model's answer, an echoed
# prompt, a traceback line, and captured backend output. Each is placed in a different part of
# the report, so a reduction that reaches any of them is caught by the string it finds.
PROSE = {
    "summary_attr": "MODELPROSE-the-code-looks-broadly-correct-but",
    "traceback_text": "MODELPROSE-assert-body-summary-equals-a-long-answer",
    "system_out": "MODELPROSE-captured-stdout-with-the-whole-prompt-echoed",
    "system_err": "MODELPROSE-captured-stderr",
    "error_attr": "MODELPROSE-error-message-attribute",
}

JUNIT_WITH_PROSE = f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="177.3">
    <testcase classname="tests.test_kimi_live" name="test_consult_live" time="10.0"/>
    <testcase classname="tests.test_kimi_live" name="test_review_changes_live" time="20.0">
      <failure message="{PROSE["summary_attr"]}">{PROSE["traceback_text"]}</failure>
      <system-out>{PROSE["system_out"]}</system-out>
      <system-err>{PROSE["system_err"]}</system-err>
    </testcase>
    <testcase classname="tests.test_kimi_live" name="test_models_live" time="1.0">
      <error message="{PROSE["error_attr"]}" type="RuntimeError">boom</error>
    </testcase>
    <testcase classname="tests.test_kimi_live" name="test_safe_mode_live" time="0.0">
      <skipped message="no auth" type="pytest.skip"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def _write_report(tmp_path: Path, body: str = JUNIT_WITH_PROSE) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_fixture_really_contains_prose(tmp_path):
    """The instrument first: if the report were prose-free, every assertion below would pass
    vacuously and prove nothing."""
    raw = _write_report(tmp_path).read_text()
    for value in PROSE.values():
        assert value in raw


def test_it_names_the_tests_that_did_not_pass(tmp_path):
    summary = evidence._summarize_junit(_write_report(tmp_path))
    assert summary is not None
    assert summary["total"] == 4
    assert summary["counts"] == {"failure": 1, "error": 1, "skipped": 1}
    assert summary["not_passed"] == [
        {"test": "tests.test_kimi_live::test_review_changes_live", "outcome": "failure"},
        {"test": "tests.test_kimi_live::test_models_live", "outcome": "error"},
        {"test": "tests.test_kimi_live::test_safe_mode_live", "outcome": "skipped"},
    ]


def test_no_prose_survives_the_reduction(tmp_path):
    """The point of the whole design: serialize the reduction and search it for every string."""
    summary = evidence._summarize_junit(_write_report(tmp_path))
    serialized = json.dumps(summary)
    leaked = [name for name, value in PROSE.items() if value in serialized]
    assert leaked == [], leaked
    # Belt and braces: nothing in the reduction even mentions the marker prefix.
    assert "MODELPROSE" not in serialized


def test_the_reduction_carries_only_allowlisted_keys(tmp_path):
    summary = evidence._summarize_junit(_write_report(tmp_path))
    assert summary is not None
    assert set(summary) == set(evidence._REPORT_KEYS)
    for entry in summary["not_passed"]:
        assert set(entry) == {"test", "outcome"}
        assert entry["outcome"] in evidence._NOT_PASSED_OUTCOMES


def test_a_passing_run_lists_nothing(tmp_path):
    clean = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1">
  <testcase classname="tests.test_codex_live" name="test_consult_live" time="1.0"/>
</testsuite></testsuites>
"""
    summary = evidence._summarize_junit(_write_report(tmp_path, clean))
    assert summary == {
        "total": 1,
        "counts": {"failure": 0, "error": 0, "skipped": 0},
        "not_passed": [],
    }


def test_a_missing_or_unparsable_report_is_not_fatal(tmp_path):
    """pytest can die before writing a report; the gate's exit status still stands on its own."""
    assert evidence._summarize_junit(tmp_path / "absent.xml") is None
    assert evidence._summarize_junit(_write_report(tmp_path, "<not-xml")) is None
