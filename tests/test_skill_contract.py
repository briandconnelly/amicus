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

from amicus.orchestration import review as review_mod
from amicus.schemas.results import Confidence, CoverageReason, FindingReason, Verdict

_SKILL = Path(__file__).resolve().parents[1] / "skills" / "collaborating-with-amicus"
_RESULTS_REF = (_SKILL / "references" / "reading-results.md").read_text(encoding="utf-8")
_SKILL_MD = (_SKILL / "SKILL.md").read_text(encoding="utf-8")


def _binding_rules() -> str:
    """SKILL.md's `## Binding rules` section alone. ADR 0016: an obligation that lives in
    explanatory prose does not bind, so asserting a rule against the whole file would pass
    on a document that had demoted it to `## Semantics` - the exact regression to catch."""
    head, sep, rest = _SKILL_MD.partition("\n## Binding rules\n")
    assert sep, "SKILL.md has no `## Binding rules` heading"
    return rest.split("\n## ", 1)[0]


_BINDING_RULES = _binding_rules()


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
    "CoverageReason": (CoverageReason, _section("Coverage")),
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
    satisfies the test above while leaving an agent free to treat it as a low rating.

    Asserted against the BINDING RULES slice, not the whole file: a sentence demoted to
    `## Semantics` still reads as guidance and would satisfy a whole-file search, which is
    precisely the failure ADR 0016 exists to prevent."""
    assert 'Never read `confidence: "unknown"` as a low rating.' in _BINDING_RULES
    assert "It is the absence of a rating, not a low one." in _RESULTS_REF


def test_the_coverage_field_is_named_in_the_binding_rules():
    """#65: `coverage` is the machine-readable disclosure. Under ADR 0016 a signal named only
    in reading-results.md does not bind, so the rules block must name it itself."""
    assert "`coverage`" in _BINDING_RULES


def test_the_high_confidence_misreading_is_a_rule_of_its_own():
    """The second misreading, and it binds separately. Bundled into the `unknown` rule as a
    trailing clause it would be read as commentary on that rule rather than an obligation
    about every rating, which is the compound-rule failure `separating-context-from-
    constraints` names."""
    assert (
        "Never read a high `confidence` as evidence that coverage was complete or findings "
        "intact." in _BINDING_RULES
    )


def test_every_amicus_substituted_low_sits_beside_an_unknown_verdict():
    """The invariant the published `confidence` description rests on, asserted against the
    source that has to keep it. Every `low` amicus writes itself - the two folds and both
    `_not_run` envelopes - is paired with an `unknown` verdict, which is what makes "a
    `low` beside any other verdict is the backend's word" true rather than merely tidy.

    A fourth site that wrote `low` beside a concrete verdict would silently make the
    published description a lie, and no other test in this repository would notice: the
    description is prose, and prose is what the gate cannot read (issue #53, Copilot's
    review of PR #55 having found `_not_run` as an unnamed third source)."""
    source = Path(review_mod.__file__).read_text(encoding="utf-8")
    lines = source.splitlines()
    lows = [i for i, line in enumerate(lines) if re.search(r'(confidence=)?"low",?$', line.strip())]
    assert len(lows) == 4, f"expected 4 amicus-written `low` sites in review.py, found {len(lows)}"
    for i in lows:
        window = "\n".join(lines[max(0, i - 3) : i + 1])
        assert '"unknown"' in window, (
            f"review.py:{i + 1} writes `low` with no `unknown` verdict beside it; the "
            "published confidence description says every substituted low has one"
        )
