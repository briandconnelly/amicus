"""The agent-friendly-mcp walk artifact must satisfy the checklist's Done Criteria.

The walk is an M6 gate item, so a token document must not be able to pass for it.

Two deviations from the parser the M6 plan's Task 10 brief supplies, both because
the briefed form contained an assertion that could not fail:

1. The coverage-row regex captures a THIRD column. The brief matched only through
   the second `|`, so `row.group(0).split("|")[3]` was always the empty string
   after the trailing pipe and the `not-checked` reason check could never pass --
   which would have made `not-checked` an unusable status rather than one of the
   three the workflow allows. Widening the match by one column makes the brief's
   own reason line work verbatim.
2. The severity scan tolerates markdown emphasis. `severity:\\s*(critical|major)`
   never matches `- **Severity:** Major`, so the clean-report branch would have
   fired on a report that is not clean, and the residual-risk assertion would have
   passed for the wrong reason.

Two further holes, found by review of this file and closed here. Both let a
SKIPPED probe stand in for a RUN one, which is the one substitution the Done
Criteria do not allow:

3. The mandatory cold-start and first-repair probes required only the substring
   `docs/host-captures/` somewhere in the block. A skip whose reason happened to
   name that path satisfied it, so both mandatory probes could be skipped and the
   suite still passed. They must be RUN, so a skipped block is now rejected.
4. The further-probe count counted headings. Three probes, all skipped with
   reasons, satisfied a criterion that asks for at least three other APPLICABLE
   probes; being skipped-with-a-reason is excused by the next clause of the
   criterion, not a substitute for this one. Skipped bodies are now filtered out
   before counting, and the test name no longer encodes the misreading.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = next(
    (Path(__file__).resolve().parents[1] / "docs" / "reviews").glob("*agent-friendly-mcp-walk.md")
)
TEXT = DOC.read_text()
SECTIONS = [f"§{n}" for n in range(1, 10)]
FINDING_FIELDS = ("severity:", "section:", "summary:", "evidence:", "remediation:")
# Deviation 2: `**` between the label and the value.
SEVERITY_RE = re.compile(r"severity:\W*(critical|major)", re.I)
# A probe body opens with this marker when the walk declined to run it.
SKIP_MARKER = "**Skipped."
MANDATORY_PROBES = ("cold-start", "first-repair")


def _probes() -> list[tuple[str, str]]:
    """(name, body) for every probe section, in document order."""
    return [
        (name.strip(), body)
        for name, body in re.findall(r"### Probe: (.+?)\n(.+?)(?=\n### |\n## |\Z)", TEXT, re.S)
    ]


def _is_skipped(body: str) -> bool:
    return SKIP_MARKER in body


@pytest.mark.parametrize("section", SECTIONS)
def test_every_checklist_section_is_accounted_for(section):
    # Deviation 1: two capture groups, so group(0) spans the notes column too.
    row = re.search(rf"^\|\s*{re.escape(section)}\s*\|([^|]*)\|([^|]*)\|", TEXT, re.M)
    assert row, f"{section} has no coverage-table row"
    status = row.group(1).strip().lower()
    assert status in {"covered", "ok", "not-checked"}, f"{section}: bad status {status!r}"
    if status == "not-checked":
        assert len(row.group(0).split("|")[3].strip()) > 10, (
            f"{section}: not-checked needs a reason"
        )


def test_the_two_mandatory_probes_were_run_with_evidence():
    """These two must be RUN, not merely present. A skip that happens to name a
    capture path is not evidence the probe was answered (hole 3)."""
    bodies = dict(_probes())
    for probe in MANDATORY_PROBES:
        body = next((b for n, b in bodies.items() if n.lower() == probe), None)
        assert body is not None, f"no {probe} probe section"
        assert not _is_skipped(body), (
            f"{probe} is a mandatory probe and was skipped; the Done Criteria require it run"
        )
        assert "docs/host-captures/" in body, f"{probe} probe cites no captured evidence"


def test_at_least_three_further_probes_were_run():
    """The criterion asks for at least three other APPLICABLE probes. A probe
    skipped with a reason is excused by the criterion's next clause; it does not
    count toward this one (hole 4)."""
    further = [(name, body) for name, body in _probes() if name.lower() not in MANDATORY_PROBES]
    run = [name for name, body in further if not _is_skipped(body)]
    skipped = [name for name, body in further if _is_skipped(body)]
    assert len(run) >= 3, (
        f"only {len(run)} further probes were run: {run} (skipped, which do not count: {skipped})"
    )


def test_every_skipped_probe_records_an_inapplicability_reason():
    """A probe the walk declines must say why; silence is the defect the workflow names."""
    for name, body in _probes():
        if not _is_skipped(body):
            continue
        assert "Inapplicability reason:**" in body, f"{name}: skipped with no reason"


def test_every_finding_carries_all_five_labeled_lines():
    findings = re.findall(r"#### Finding \d+(.+?)(?=\n#### |\n## |\Z)", TEXT, re.S)
    assert findings, "the walk records no findings at all"
    for finding in findings:
        missing = [f for f in FINDING_FIELDS if f not in finding.lower()]
        assert not missing, f"finding missing {missing}"


def test_a_clean_report_names_residual_risks():
    if not SEVERITY_RE.search(TEXT):
        assert "residual risk" in TEXT.lower(), "a clean report must name residual risks"


def test_the_severity_scan_can_see_this_report_s_own_severities():
    """Known positive for the instrument above: a broken scan and a clean report
    look identical, so pin that the scan actually matches the document's format."""
    assert SEVERITY_RE.search(TEXT), (
        "the severity scan matched nothing in a report that records findings; either "
        "every finding is Minor/Nit or the scan no longer understands the format"
    )
