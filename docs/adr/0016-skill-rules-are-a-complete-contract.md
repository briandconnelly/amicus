# ADR 0016: the skill's rule block is the complete contract, and ported guarantees are re-verified

**Status:** Accepted (2026-09-09)

## Context

A Codex review of `skills/collaborating-with-amicus` on 2026-09-09 raised ten material findings.
Every one was checked against the source and held.
Two of them are the reason for this record; the rest were ordinary corrections that need no ADR.

**The rule block was not the contract it appeared to be.**
`SKILL.md` presented six numbered rules under a `Rules` heading, which reads as a complete list of what binds.
It was not: a structural audit found ten further obligations distributed through the `Context` section and the references — "check `status`, not just `enabled`", "honor the returned `poll_after_ms`", "read `carriers`", "run this project's own checks", and others.
An agent that read the six rules and skimmed the prose would miss them, which is exactly the failure mode `separating-context-from-constraints` exists to catch.
The same audit found the converse problem inside the rules: they carried enough factual explanation to obscure the action each one demanded.

**A guarantee was ported across backends that does not hold for all of them.**
`reviewing-a-returned-diff.md` said "Delegate runs have no network egress", and concluded that an install, a remote git operation, `gh`, or a publish step could not have happened inside a run.
That is true for `codex`, where amicus pins `sandbox_workspace_write.network_access=false` (`src/amicus/backends/codex/cli.py:67`).
It is false for `kimi`, which has no sandbox at all (`src/amicus/backends/kimi/contract.py:7`); a worktree changes kimi's working directory, not its reach.

The sentence descends from the single-backend ancestor skills in `codex-in-claude` and `moonbridge`, where the same wording appears in `references/active-workflows.md`.
It is worth recording that this was not simply mis-generalized on the way into amicus: `moonbridge`'s copy carries the claim while `moonbridge`'s own `SKILL.md` states the opposite in bold, so the ancestor is internally inconsistent and the false half is the one that was inherited.
A safety-relevant guarantee had been carried between documents on the strength of the documents rather than the implementation.

## Decision

**The rule block is the complete contract.**
Every obligation that binds an agent using this skill appears under a labelled rules heading — `Binding rules` in `SKILL.md`, or a `Rules` heading in the reference that owns a route-specific obligation.
No obligation lives only in explanatory prose.
Each rule is atomic, signals its strength, and is checkable against a tool call, a result, or the agent's own output.

**Rules carry actions; semantics carry facts.**
A rule states its action, the observable condition that triggers it, and whatever is needed to distinguish compliance from violation — and nothing else.
The facts that motivate a rule move to a `Semantics` section placed immediately after the rules, not to a distant file: separation is about distinguishability, not about making the reasons hard to reach.

**A backend guarantee is verified against this repository's implementation before it is stated.**
No guarantee about sandboxing, network egress, write scope, or read scope is carried in from a sibling skill, from a prior version of this skill, or from a backend's own documentation without checking the contract and adapter in `src/amicus/backends/<id>/`.
Where backends differ, the skill states the difference per backend rather than choosing the reassuring generalization.

## Consequences

The root `SKILL.md` grew a complete rules block and lost the prose obligations, and five references were added — `reading-results.md`, `active-workflows.md`, `options-and-errors.md`, and adapted ports of `independent-attempt.md` and `review-revise.md` — so that route-specific obligations have a labelled home.
`server-down-fallback.md` was written rather than ported: the ancestors' fallbacks put prompt text on argv or on disk, which rule 18 does not permit for a command amicus's own skill tells an agent to compose.
There is consequently no hand-rolled `kimi` fallback, because kimi ignores stdin and every remaining carrier is barred; that gap is stated in the file rather than filled.

The scenario suite follows the skill rather than the other way round.
`reviewing-a-returned-diff.md`'s response contract now separates the assessment of a proposal (`Verdict: accept | reject | cannot-assess`) from the action taken on the working tree (`Action: applied | not applied`), because the previous single line conflated them.
S6's recorded pass was graded against the superseded contract; it stands in the run log unamended and is **not** carried forward as a pass against the new one.
Six prospective scenarios (S9–S14) were defined before any run.

This ADR does not resolve F3.
The ordering-experiment history that `reviewing-a-returned-diff.md` used to carry has been removed from that file rather than relocated, because ADR 0012 already holds the same history in a more careful form — the reference asserted that three graded runs showed an ordering directive does not move generation order, which is stronger than ADR 0012's own account of runs that "cannot be attributed to the response contract or to the grading scope alone".
The qualified account in ADR 0012 stands as the record; the overstatement is gone.

`moonbridge`'s inconsistency is not fixed here.
AGENTS.md rule 17 forbids editing a sibling checkout, so it is recorded in this ADR and reported to the maintainer rather than repaired from this repository.

## What the review round demonstrated about both decisions

A Codex review of the finished branch returned `verdict: fail` with twenty-two findings, and its two largest classes are the two decisions above failing on their first application.

**The rules-as-contract fix reproduced the original defect one level down.**
Ten obligations were moved out of the root's prose and into labelled rules, and the newly written references then placed ten obligations of their own outside their `Rules` blocks — the workspace-content prohibition on `instructions_append`, the provider-configuration prohibition, the git-state restriction, the contact check, the complementary-review constraints, and the fallback's disclosure-only exclusion among them.
Fixing the advertised contract in one file does not make the contract complete; every file an agent is routed to has to be audited the same way, and the check is mechanical enough to run (search for imperative wording outside a `Rules` heading) that there is no excuse for asserting it instead.
The follow-up pass also showed the opposite failure once a rule is promoted: a rule restated in adjacent prose is two copies that can drift, so the prose keeps the explanation and drops the imperative.

**The verify-before-stating rule failed because the instrument tested a weaker claim than the text made.**
`server-down-fallback.md` said every flag in its command is one "amicus itself always sends", and the check written to verify it asserted only that those flags appear in `ALWAYS_SEND_FLAGS`.
That constant is a *classification* — guarantee-bearing rather than help-gated — and not a statement that a flag is emitted on every call: `isolation_flags()` returns nothing at the default `inherit` isolation, and `--skip-git-repo-check` is conditional.
The check passed, the claim was false, and the passing check was reported as verification.
A verification instrument must assert the proposition the text actually states; where a claim is stronger than its source supports, the counterexamples belong in the check as their own assertions, which is how they are recorded now.

Three rule conflicts surfaced in the same pass and are worth naming, because each was a rule that read as absolute and was contradicted by another part of the contract: a one-call cap that made the documented two-call workflow impossible, a prohibition on running both call forms that contradicted the timeout repair `claude` itself prescribes, and a prohibition on applying a diff that its own validation step required.
An obligation stated without its exception is not stricter, it is unfollowable.
