"""The skill's result vocabulary is asserted against source, because the gate cannot see it.

ADR 0016 makes the SKILL.md rules block the contract an agent is held to, and nothing else
in this repository reads markdown. So a value enum can gain a member, the published schema
and every unit test can stay green, and the skill can go on describing a surface that no
longer exists. These tests close that specific gap: they fail when a documented vocabulary
drifts from the Literal it claims to describe."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from amicus.schemas.results import Confidence, FindingReason, Verdict

_SKILL = Path(__file__).resolve().parents[1] / "skills" / "collaborating-with-amicus"
_RESULTS_REF = (_SKILL / "references" / "reading-results.md").read_text(encoding="utf-8")
_SKILL_MD = (_SKILL / "SKILL.md").read_text(encoding="utf-8")


def _section(heading_contains: str) -> str:
    """The one `##` section of reading-results.md that owns a field's vocabulary."""
    sections = _RESULTS_REF.split("\n## ")
    owning = [s for s in sections if heading_contains in s.split("\n", 1)[0]]
    assert len(owning) == 1, f"expected exactly one section for {heading_contains!r}"
    return owning[0]


# A member counts as documented when it appears in a code span IN THE SECTION THAT OWNS ITS
# FIELD, as a whole token of one - alone (`unknown`), in a compound (`low|medium|high`), or
# beside a field name (`verdict: unknown`). Pooling spans across fields would defeat this:
# `unknown` belongs to both Verdict and Confidence, so a shared pool would call Confidence's
# `unknown` documented on the strength of the verdict prose alone - which is exactly the
# drift this asserts against. Bare prose never counts, because "low" is a substring of
# "below", "follow" and "allow", and accepting it would make the assertion unable to fail.
_VOCABULARY = {
    "Confidence": (Confidence, _section("`confidence`")),
    "Verdict": (Verdict, _section("Coverage")),
    "FindingReason": (FindingReason, _section("`findings_diagnostics`")),
}


def _tokens(text: str) -> set[str]:
    return {
        token
        for span in re.findall(r"`([^`]+)`", text)
        for token in re.split(r"[|:,\s]+", span)
        if token
    }


def test_the_skill_documents_every_value_beside_the_field_that_carries_it():
    """A member absent from its own section is a value the skill never tells an agent how
    to read - which is how `unknown` confidence would have shipped as an undocumented
    fourth state, indistinguishable from the `unknown` verdict that was already there."""
    for name, (enum, owner) in _VOCABULARY.items():
        documented = _tokens(owner)
        for member in get_args(enum):
            assert member in documented, (
                f"{name} member {member!r} is undocumented in the section that owns it"
            )


def test_an_unknown_confidence_is_documented_as_an_absence_not_a_low_rating():
    """The one misreading the value exists to prevent. A rule that merely LISTS `unknown`
    satisfies the test above while leaving an agent free to treat it as a low rating."""
    assert 'Never read `confidence: "unknown"` as a low rating.' in _SKILL_MD
    assert "It is the absence of a rating, not a low one." in _RESULTS_REF
