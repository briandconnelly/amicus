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


# A member counts as documented when it appears in a code span, either alone (`unknown`) or
# as one alternative of a compound the skill writes idiomatically (`low|medium|high`). Bare
# prose does not count: "low" is a substring of "below", "follow" and "allow", so accepting
# it would make this assertion unable to fail.
_SPANNED = {
    token
    for span in re.findall(r"`([^`]+)`", _RESULTS_REF + _SKILL_MD)
    for token in span.split("|")
}


def test_the_skill_names_every_value_a_result_can_carry():
    """A member absent here is a value the skill never tells an agent how to read - which
    is how `unknown` confidence would have shipped as an undocumented fourth state."""
    for enum, name in ((Confidence, "Confidence"), (Verdict, "Verdict"), (FindingReason, "reason")):
        for member in get_args(enum):
            assert member in _SPANNED, f"{name} member {member!r} is undocumented in the skill"


def test_an_unknown_confidence_is_documented_as_an_absence_not_a_low_rating():
    """The one misreading the value exists to prevent. A rule that merely LISTS `unknown`
    satisfies the test above while leaving an agent free to treat it as a low rating."""
    assert 'Never read `confidence: "unknown"` as a low rating.' in _SKILL_MD
    assert "It is the absence of a rating, not a low one." in _RESULTS_REF
