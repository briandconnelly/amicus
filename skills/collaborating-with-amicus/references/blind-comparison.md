# Blind comparison

Use this pattern when two or more finalized candidate artifacts exist, nothing cheaper can tell
them apart, and you want a backend that produced none of them to compare them. The comparison is
a critique with a preference attached. It is not a verdict, not a score, and not a vote: the
backend reads the candidates, it does not run them, and you own the decision.

The case this pattern exists for is the one [independent attempt](independent-attempt.md) leaves
open: when you wrote one of the candidates, your own synthesis is conflicted, and a reader with no
stake in either is the instrument that addresses that.

## Rules

Cap declaration, call counting and synthesis are governed by SKILL.md → Binding rules → Spend and
Composed workflows; the brief, `extra_context` and `instructions_append` by
[active workflows](active-workflows.md) → Rules; backend identity claims by
[choosing a backend](choosing-a-backend.md) → Rules. These are this file's own:

- **Compare only finalized candidates, and only when no cheaper discriminator exists.** Name the
  discriminators you considered — a test, this project's gate, a direct inspection — and why each
  cannot settle the question, before the call.
- **Select a comparison backend that produced no candidate.** A backend that wrote one of them is
  a candidate's author, whatever the label says.
- **Record whether the comparison backend's model family is verified distinct from each
  candidate's author, and say `unverified` when it is not.** Backend IDs do not establish
  families.
- **Blind the candidates.** Neutral labels, no authorship, no provenance, no marker of which one
  you wrote or prefer, in any field of the call. Say in the report what you could not remove.
- **Fix the criteria before the call and carry them in `question`; carry the candidates in
  `extra_context`.** A criterion added after reading the result is a new comparison, not a
  reading of this one.
- **Ask for a per-criterion comparison with reasons and one stated preference.** Never ask for,
  and never report, a score, a grade, a rank order beyond the preference, or a probability.
- **Treat the preference as a finding.** Verify each reason it rests on against the candidates
  before it moves the decision; a reason you cannot trace to the candidates carries no weight,
  whatever the preference says.
- **Disclose the presentation order with the result.** Report the comparison as
  position-controlled only after the order-swapped second call below.
- **Take the second call only under a two-call cap declared before the first, with the brief
  byte-identical except for candidate order.** Stop after it, whatever it says.
- **Never run this pattern as a vote across backends, as a substitute for a test that can
  discriminate, or in a loop with regeneration.**

## Order of work

1. Declare the pattern and the cap. One call is the default; two only when position control
   matters enough to pay for it, decided now.
2. Confirm every candidate is finalized. A candidate that changes after the call was not the
   one compared.
3. Name the cheaper discriminators and why none applies. If one does, run it instead and stop.
4. Choose the comparison backend from `amicus_backends`, excluding every candidate's author.
   Record the family-diversity status as verified or `unverified`.
5. Write the brief: the decision the comparison informs, the criteria a good candidate must
   satisfy, the deliverable (per criterion, which candidate satisfies it better and why; one
   overall preference; the inspection or experiment that would settle the largest disagreement),
   and the presentation order you will use. This is fixed before the call.
6. Blind the candidates. Give them neutral labels, strip authorship markers you can remove
   without changing substance, and note what remains.
7. Call `amicus_consult`, or `amicus_consult_async` when the candidates are large, with the
   candidates in `extra_context`. Omit `instructions_append`, or fix neutral output-shape
   guidance before the first call and hold it identical across both.
8. Read the result under SKILL.md → Binding rules → Results, including `findings_diagnostics`
   and `lists_diagnostics`.
9. Verify the load-bearing reasons against the candidates, decide, and report with the order,
   the diversity status, and any disagreement preserved.

## Why a preference and not a score

A comparison backend is subject to the biases a reader of two texts has: it tends to prefer the
candidate it saw first or last, the longer one, and the one written in its own style. A number
hides which of those moved it. A per-criterion reason can be traced to the candidates and checked;
a score cannot. `amicus_consult` also returns no `verdict` or `confidence` field, so a score would
arrive as prose amicus does not parse, and the Results rules give it no standing that the reasons
lack.

The same biases are why the pattern is blind. Blinding removes the backend's pointer to
authorship; it does not remove yours. When one candidate is your own, say so in the report even
though the backend was not told, and verify the reasons against that candidate with the same care
as against the other.

## The order-swapped second call

Position bias is the one bias a second call can measure. The second call presents the candidates
in reverse order and is otherwise byte-identical: same criteria, same labels swapped with their
content, same `instructions_append` if any. `meta.instructions_append` carries a
`{sha256, bytes}` fingerprint that checks that half, as [review–revise](review-revise.md)
describes; the rest of the brief is your own bookkeeping.

The same preference under both orders is weak evidence that the preference is stable. Opposite
preferences under the two orders are a finding in their own right: the criteria did not
discriminate, and the decision rests on your verification rather than on either call. Neither
outcome buys a third call.

## What this pattern is not

- **Not a vote.** Three backends preferring the same candidate are three claims from three
  readers of the same brief, each subject to the same biases. The root rule against tallying
  votes applies.
- **Not a test.** For an implementation that a test, the gate, or a reproduction can
  discriminate, the discriminator is the instrument and this pattern is the wrong spend.
  [Independent attempt](independent-attempt.md) → Independent test design is the route for
  obtaining such a test without showing the backend the implementations.
- **Not a loop.** Generate, compare, regenerate is the open-ended conversation
  [review–revise](review-revise.md) forbids. The cap ends the sequence.
- **Not independence.** The comparison backend sees every candidate. Nothing here establishes
  that the candidates were produced independently of each other; that is
  [independent attempt](independent-attempt.md)'s subject, and its reclassification triggers
  are unaffected by a comparison made afterwards.

## Data exposure

Every candidate reaches the comparison backend's provider raw, in `extra_context`, which
redaction does not cover. Blinding is a change to what you send, not a protection applied to it;
a candidate you would not hand to that provider with its author's name on it is one you should
not hand over with a label instead.
