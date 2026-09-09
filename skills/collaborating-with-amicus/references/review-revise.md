# Declared review–revise

Use this pattern when you create an artifact, a backend critiques it, and you revise. The critique
improves the work; it does not certify it.

## Rules

- **Declare the pattern and a one-call cap before the first paid call.**
- **Run the relevant local checks before spending**, so the critique is about the artifact rather
  than about a mistake you could have caught for free.
- **Verify each material finding before acting on it**, and record why any disputed finding was
  declined.
- **Take a second paid pass only when the work was classified high risk and a two-call cap was
  declared before call one.**
- **Hold `instructions_append` identical across passes** whenever the pattern uses it.
- **Never add a pass because a result was reassuring, inconvenient, or inconclusive.**

## Default pass

1. Declare the pattern and the cap.
2. Draft the artifact and run this project's relevant local checks.
3. Choose the route: `amicus_review_changes` when the artifact is in git;
   `amicus_consult` for a design, document, or other non-diff artifact;
   `amicus_adversarial_review` when the artifact is a plan, claim, or decision and you want a
   fixed adversarial critic rather than a balanced reviewer. The adversarial verb is an *eligible
   route here, never a mandatory one* — it is `claude`-only in v1, and a critic instructed to
   attack is not the right instrument for every artifact.
4. Scope the call to the decision, and run the free dry run where one exists.
5. Verify each material finding, revise what you accept, and record why you declined the rest.
6. Run this project's checks and stop.

## Optional high-risk second pass

Allowed only when the work was explicitly classified high risk *before* the first call and the
declared cap was two. Spend it on the revised artifact, verify any new findings, rerun checks, and
stop.

Do not turn the sequence into an open-ended conversation. A clean critique means only that the
backend reported no issue under the shared scope and framing.

## Keeping two passes comparable

`instructions_append` is part of the framing. When the pattern uses it, fix the text before the
first call and keep it byte-identical across both passes — critiques under different stances are
not comparable, and a changed stance quietly turns the second pass into a different review.

`meta.instructions_append` on each result carries a `{sha256, bytes}` fingerprint, which checks
exactly that half: equal fingerprints mean both passes **carried** the same `instructions_append`
text — that amicus accepted and staged it. It does not mean the backend weighted it alike, or at
all. It attests nothing else.

The rest of the framing is your own bookkeeping. Hold the review intent and scope framing stable
while the target-bearing part — the diff scope, or the artifact carried in `question` /
`extra_context` — legitimately moves to the revised artifact in pass two.

## What a critique is not

A backend's critique is not verification. It ran read-only, it did not run your tests, and its
`verdict` is a claim under the coverage rules in [reading results](reading-results.md). Closing
out the work still requires this project's own gate.
