# ADR 0048: the skill body carries what binds every use, and sends the rest to a rules block that must be read

**Status:** Accepted (2026-11-14)

Amends [ADR 0016](0016-skill-rules-are-a-complete-contract.md), which stands except where this record says otherwise.

## Context

ADR 0016 made the rules of `skills/collaborating-with-amicus` a complete contract, and allowed an obligation to live either in `SKILL.md`'s `Binding rules` or under a `Rules` heading in "the reference that owns a route-specific obligation".
In practice every obligation that was not specific to one route went into the body, because a reference's block was not guaranteed to be read.
Issue #487 measured the result at `477baba`: a body of 22.7 KB carrying 55 bolded rules, loaded in full on every trigger, including a question about whether a backend is available.
A plain consult also read `active-workflows.md`, `choosing-a-backend.md` and `reading-results.md`, about 65 KB before its first call.
The routing procedure was written out in the body and again in `choosing-a-backend.md`, and the two had drifted: the `reasoning_effort` rule was in one only.
Two rules were not checkable against a call, a result or the agent's output, which ADR 0016 requires of every rule.
The effect of the body's size on compliance has not been measured, here or in the issue.

A Codex design critique was taken before any edit, on a proposal to move the result, job, approval and composed-workflow rules out of the body.
It held that the direction was sound and that the proposal, as written, lost obligations: each loss was a rule moved behind a read trigger narrower than the rule itself.
The defect-reporting rule covers a failed free call and a failed resource read, which a trigger of "a paid result" never reaches.
The ban on reading the job store binds an ordinary sync call, which is a job too and never reads the polling reference.
The synthesis rules and the ban on asking a backend to invoke another agent bound every route, not only the three named workflows.
A row in the route table is a map entry, not a rule, so it does not make a block mandatory.
Each of those was checked against the files and held.

## Decision

**The body carries the rules that bind every use of the skill.**
Those are discovery, routing, spend, scope and inputs, data exposure, the choice of a composed workflow, and the short prohibitions an agent can break without ever opening a reference: reading the job store, and applying a returned diff unreviewed.

**A rule that binds only at a later moment lives in the `Rules` block of the reference that owns that moment.**
Reading a result, recovering from a failure or a host's denial, polling a job, briefing a call, and running a composed workflow are such moments.

**A reference's `Rules` block binds only because a body rule makes reading it mandatory, and the trigger of that body rule is at least as wide as every rule in the block.**
`SKILL.md` → Binding rules → Required reading holds those body rules, one per block, each naming the moment by which the block must have been read.
A route-table row, the shared workflow and a link in prose do not satisfy this: only a rule under `Binding rules` does.
A rule whose trigger is wider than its block's stays in the body or moves to a block whose trigger covers it.

**A procedure has one statement.**
The routing procedure is `SKILL.md` → Binding rules → Routing, and `choosing-a-backend.md` keeps only worked examples of it and the rules that bind a `pi` or `kimi` route.

**A rule turns on something a transcript can show.**
The workspace rule no longer tests what the agent would be willing to hand a provider.
It forbids a paid call from a workspace the user or the project's instructions have excluded from disclosure to that provider, the routing rules require naming the provider before the first paid call, and the consent rule for an unrequested call already requires saying what would be sent.

## Consequences

The body is 18.1 KB, down from 24.9 KB at `de9602a`, and what a single-route consult with inline evidence must read is 46.2 KB, down from 67.2 KB, counted as whole files.
`choosing-a-backend.md` is no longer read on every call: it is required for a `pi` or `kimi` route, for a choice among several routes, and for a call that needs the backend to read files or sets `backend_options`.
`tests/test_skill_contract.py` asserts each moved rule against the block that now owns it, asserts that every reference's `Rules` block is named by a Required reading rule, and holds the body and the plain-consult read under byte ceilings so the size cannot return unnoticed.
The ceilings are regrowth guards, set just above the measured sizes, not targets.

The workspace rule is narrower than the one it replaces, and that is a policy change rather than a rewording.
The old rule asked the agent to judge what it would hand over, and nothing could show whether it had; the new one binds only where the user or the project has said something.
The cases between are left to the disclosure the other rules require, on which the user decides.

The kimi disk rule, "never send `kimi` text you would not leave on this machine's disk", has the same counterfactual form and is left as it is.
`kimi` is deprecated and is removed at or after 0.15.0, and the rule goes with it.

The frontmatter description is shorter and drops the triggers a host also uses for its own model switching and subagents.
Whether that changes when a host loads the skill has not been measured.

The scenario suite follows the skill, as ADR 0016 said it would: the scenarios that cite a moved rule cite its new owner.
