# ADR 0026: a `not_run` review carries no confidence rating

**Status:** Accepted (2026-09-14)

## Context

When a review scope gathers no changes, `review._not_run` (`src/amicus/orchestration/review.py`) returns the zero-spend envelope for `amicus_review_changes` and `amicus_adversarial_review`: `review_status: not_run`, `verdict: unknown`, and until now `confidence: low`.
No backend was called, so nothing was assessed and there was no rating to carry.

Issue #53 added `unknown` to the published `Confidence` enum as the absence of a rating (ADR 0017), and Codex's design consult for that issue said a `not_run` result should carry it because no assessment occurred.
ADR 0017 filed that as issue #54 rather than deciding it, with the counter-argument recorded there: `unknown`/`low` is this repository's established "do not rely on this" idiom, and in the `not_run` case amicus positively knows the result is worthless, which is a basis for `low` rather than an absence of one.
The two folds that substitute `low`, `apply_coverage` and `apply_findings_loss`, were kept on exactly that reasoning: each speaks for amicus about a review that was delivered, on a basis amicus has.

The question is what the field is for, not whether a value is wrong.
If `confidence` rates the delivered review, `low` is right and ADR 0017 should say so.
If `unknown` means no assessment occurred, `not_run` is its clearest case and `low` overstates.

## Decision

**A `not_run` review carries `confidence: unknown`.**

The published description defines the field as how sure this review is, and defines `unknown` as the absence of a rating.
A `not_run` result has no review to be sure about, so it fits the second definition exactly; the only thing that kept it out was the description's own clause "and no such substitution", which carved the implementation out of the meaning rather than describing it.
The counter-argument conflates two facts.
That amicus knows a `not_run` result cannot support a conclusion is a fact about execution, and `review_status` already carries it as the machine-readable branch key.
`low` is the lowest rating a backend can report, and ADR 0017's own reasoning applies: stating it where nothing was rated manufactures a claim in the same direction as the `medium` that issue #53 removed, smaller and harder to notice.
The folds are different in kind, not in degree: they rate a review that happened, over a diff the model did not fully see or with findings amicus could not relay, and `unknown` there would discard an assessment amicus can make.
Here there is none to discard.

**The substituted `low` now has two sources, and the invariant is kept.**
Both folds still lower the rating and withhold the verdict together or not at all, so a `low` beside any verdict other than `unknown` remains the backend's word, and `tests/test_skill_contract.py` still asserts that every `low` amicus writes in `review.py` sits beside an `unknown` verdict; the count it pins moves from four sites to two.
The published description names both remaining sources and puts `not_run` under `unknown`, beside the unreadable-rating case, so an MCP-only caller reads one meaning for the value rather than a third.

**A caller that reads only `low` as "do not rely on this" was already wrong.**
Since ADR 0017 an unreadable backend rating is delivered as `unknown` on a completed review, so such a caller has to handle `unknown` on every result and branch on `review_status` for execution state.
This change removes the one case where `low` was doing that job, which is the change log's business rather than a reason to keep the conflation.

## Consequences

The permitted enum and the stored-result schema are unchanged, so `RESULT_FORMAT` stays 6: a format-6 reader accepts `unknown` where it accepted `low`, and that acceptance is the criterion, not whether the value a result carries changed, which it did.
The published `confidence` description moves, so `FINGERPRINT` moves to `schema-25` (`tool_output_schemas`) and the manifest pins are regenerated in their own commit; the value a result carries is not part of that fingerprinted surface, its description is.
The `wire_shape_snapshot` fixture is untouched: its `low` values belong to completed partial-coverage reviews, not to a `not_run` result.

Codex was consulted once on the decision, at high reasoning effort, and committed to `unknown` on the argument recorded above; it named the one thing that would change its mind, a deliberate redefinition of `confidence` as an envelope-level reliance grade across the whole published schema, which nothing in the description, the skill or ADR 0017 supports.
ADR 0017 stands; its closing paragraph now points here.
