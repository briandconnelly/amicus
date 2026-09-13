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

from amicus import errors
from amicus.orchestration import review as review_mod
from amicus.schemas.results import Confidence, CoverageReason, FindingReason, Verdict

_SKILL = Path(__file__).resolve().parents[1] / "skills" / "collaborating-with-amicus"
_RESULTS_REF = (_SKILL / "references" / "reading-results.md").read_text(encoding="utf-8")
_SKILL_MD = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
_OPTIONS_REF = (_SKILL / "references" / "options-and-errors.md").read_text(encoding="utf-8")
_OPTIONS_RULES = _OPTIONS_REF.partition("\n## Rules\n")[2].split("\n## ", 1)[0]


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


def test_the_skill_names_every_code_that_carries_no_repair():
    # Issue #42: an agent told every envelope carries error.repair cannot recover from one
    # that does not. A code added to NO_CORRECTIVE_CALL fails here until the skill says so.
    section = _OPTIONS_REF.partition("\n## The error envelope\n")[2].split("\n## ", 1)[0]
    assert section, "options-and-errors.md has no `## The error envelope` section"
    assert set(errors.NO_CORRECTIVE_CALL) <= set(re.findall(r"`([a-z_]+)`", section))


def test_no_rule_reads_a_repair_the_envelope_may_not_carry():
    # Codex's second review of #42: two codes carry no error.repair, so a rule that reads or
    # follows one unconditionally strands the agent on exactly those codes.
    assert _OPTIONS_RULES, "options-and-errors.md has no `## Rules` section"
    unconditional = re.compile(
        r"read `error\.code` and `error\.repair`|\*\*Follow `repair\.next_step`\*\*", re.IGNORECASE
    )
    for rules in (_BINDING_RULES, _OPTIONS_RULES):
        assert not unconditional.search(rules)
    assert "With no `error.repair`, fix what `error.details` names" in _OPTIONS_RULES


# Issue #84: the Discovery rule told an agent to confirm `features` names the verb it was about
# to call, but `features` never names `consult` or `review_changes` - only the verbs the server
# gates (FEATURE_FOR_VERB) plus non-verb capabilities. A host following the rule literally
# concluded the two baseline verbs were unsupported on every backend.
_SYNC_REF = (_SKILL / "references" / "sync-vs-async.md").read_text(encoding="utf-8")
_BACKENDS_REF = (_SKILL / "references" / "choosing-a-backend.md").read_text(encoding="utf-8")


def _rules_section(heading: str) -> str:
    """One `###` subsection of SKILL.md's binding rules."""
    body = _BINDING_RULES.partition(f"\n### {heading}\n")[2].split("\n### ", 1)[0]
    assert body, f"SKILL.md's binding rules have no `### {heading}` subsection"
    return body


def _bullets(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n(?=- )", text) if b.strip().startswith("- ")]


def test_the_discovery_rule_gates_exactly_the_verbs_the_server_gates():
    from amicus.schemas.codes import VERBS
    from amicus.tools._resolve import FEATURE_FOR_VERB

    bullets = [b for b in _bullets(_rules_section("Discovery")) if "`features`" in b]
    assert len(bullets) == 1, "expected exactly one Discovery rule about `features`"
    rule = bullets[0]
    bold = re.search(r"\*\*(.+?)\*\*", rule, re.DOTALL)
    assert bold, "the `features` rule has no bold obligation"
    # `features` carries feature names (the mapping's values); the rule tells the agent which
    # verbs to look for. The two coincide only because every gated verb's feature is named
    # after it, so pin that too: a gate whose feature name diverged would need new wording.
    assert set(FEATURE_FOR_VERB) <= set(VERBS)
    assert all(verb == feature for verb, feature in FEATURE_FOR_VERB.items())
    gated = set(re.findall(r"`([a-z_]+)`", bold.group(1))) - {"features"}
    assert gated == set(FEATURE_FOR_VERB.values()), (
        f"the rule gates {sorted(gated)}; the server gates {sorted(FEATURE_FOR_VERB.values())}"
    )
    rest = rule[bold.end() :]
    ungated = set(VERBS) - set(FEATURE_FOR_VERB)
    assert ungated <= set(re.findall(r"`([a-z_]+)`", rest)), (
        "the rule must name every ungated verb as one `features` never lists"
    )
    assert "never" in rest, "the rule must say the ungated verbs never appear in `features`"


def test_no_contract_declares_a_baseline_verb_as_a_feature():
    # The rule and the reference say consult and review_changes never appear in `features`.
    # That is a fact about the contracts, not the docs, so assert it there: a backend that
    # declared one would make the text wrong while every docs-reading test stayed green.
    from amicus.backends.claude.contract import CONTRACT as claude
    from amicus.backends.codex.contract import CONTRACT as codex
    from amicus.backends.kimi.contract import CONTRACT as kimi
    from amicus.schemas.codes import VERBS
    from amicus.tools._resolve import FEATURE_FOR_VERB

    ungated = set(VERBS) - set(FEATURE_FOR_VERB)
    for backend_id, contract in (("codex", codex), ("kimi", kimi), ("claude", claude)):
        assert not (ungated & contract.supported_features), (
            f"{backend_id} declares an ungated verb in supported_features; the skill says none do"
        )


def test_the_backend_reference_names_every_declared_feature():
    from amicus.backends.claude.contract import CONTRACT as claude
    from amicus.backends.codex.contract import CONTRACT as codex
    from amicus.backends.kimi.contract import CONTRACT as kimi
    from amicus.schemas.codes import VERBS
    from amicus.tools._resolve import FEATURE_FOR_VERB

    section = _BACKENDS_REF.partition("\n## What `features` contains\n")[2].split("\n## ", 1)[0]
    assert section, "choosing-a-backend.md has no `## What `features` contains` section"
    named = set(re.findall(r"`([a-z_]+)`", section))
    declared = codex.supported_features | kimi.supported_features | claude.supported_features
    assert declared <= named, f"undocumented features: {sorted(declared - named)}"
    assert set(VERBS) <= named, "every verb must be placed as gated or baseline"
    assert "(the verbs it supports)" not in _BACKENDS_REF, (
        "`features` is not the verb list; consult and review_changes never appear in it"
    )
    # The gate table itself, per backend: a verb listed as reachable on a backend whose
    # contract does not declare its feature would send an agent into feature_unsupported.
    for verb, feature in FEATURE_FOR_VERB.items():
        bullet = next(b for b in _bullets(section) if b.startswith(f"- `amicus_{verb}`"))
        first_sentence = bullet.partition(":")[2].partition(".")[0]
        for backend_id, contract in (("codex", codex), ("kimi", kimi), ("claude", claude)):
            listed = f"`{backend_id}`" in first_sentence
            assert listed == (feature in contract.supported_features), (
                f"{verb} on {backend_id}: reference says {listed}, contract says not"
            )


def test_the_polling_reference_states_the_hint_ceiling():
    # The hint grows with elapsed time only up to pontonier's cap; a job that runs for
    # minutes is polled at the cap for nearly its whole life, which is what the issue #84
    # reporter observed as "no back-off". Read from the installed library so a pin bump
    # that moves the cap fails here until the skill follows it.
    from pontonier.core.jobs import MAX_POLL_AFTER_MS

    polling = _SYNC_REF.partition("\n## Polling\n")[2].split("\n## ", 1)[0]
    assert polling, "sync-vs-async.md has no `## Polling` section"
    assert f"`{MAX_POLL_AFTER_MS // 1000} s`" in polling, "the poll hint's ceiling is unstated"


def test_the_deadline_reference_states_both_sync_bounds_and_names_the_keyed_alternative():
    # The bounds are asserted against source. The keyed alternative is checked for presence
    # only - that it is offered beside `_async` where the deadline is explained, and that its
    # ADR 0020 limit is stated; its behaviour (job deadline, the run outliving the wait,
    # reattachment, separate sync/async identities) is exercised in tests/test_lifecycle.py.
    from amicus.config import DEFAULT_TIMEOUT_SECONDS
    from amicus.schemas.params import MAX_TIMEOUT_SECONDS

    deadline = _SYNC_REF.partition("\n## The deadline\n")[2].split("\n## ", 1)[0]
    assert deadline, "sync-vs-async.md has no `## The deadline` section"
    deadline = " ".join(deadline.split())  # the reference wraps at 100 columns
    assert f"default {DEFAULT_TIMEOUT_SECONDS}s" in deadline
    assert f"at most {MAX_TIMEOUT_SECONDS}s" in deadline, "the raise-able ceiling is unstated"
    assert "`idempotency_key`" in deadline
    assert "separate identities (ADR 0020)" in deadline, "the keyed form's limit is unstated"
    spend = _rules_section("Spend")
    assert "`idempotency_key`" in next(b for b in _bullets(spend) if "`_async`" in b), (
        "the sync-deadline rule must offer the keyed sync call beside the `_async` twin"
    )
