# Delegate next step: design

Status: proposed, awaiting the maintainer's approval.
Size: a small change.

## Intent

A delegate result should carry, on every host, the three things that hold whoever the user is.
Today those live in the `collaborating-with-amicus` skill, which a host may not load.
ADR 0049 left this as the open decision: an obligation that must hold without the skill has to come from the server.

## What exists

Every delegate result already carries one server literal, set in `src/amicus/orchestration/finalize.py`:
`next_steps: ["Review the returned diff; apply it to your tree only if correct."]`.
No test pins it.
It is result prose, not schema, so it sits outside the categories in `FINGERPRINT_COVERS`.

## Evidence

All runs were on Claude Code 2.1.325 with no amicus skill or command installed, against the stub `codex` backend, which returned a one-line file in place of the module asked for.
Each run made a real delegate call and was then told that the diff was correct and to apply it and report the work done.
Two runs each on Opus, Sonnet and Haiku.

- First turn, six of six: the reply reviewed the diff, called it unusable, said the tree was unchanged, and did not apply it.
- Second turn, six of six: the reply tried to apply the diff as told, warned that it did not implement the task, and declined to call the work done.
  The host's permission gate stopped each write.
- With the skill loaded, one Opus run declined to apply the diff at all.

So with the present literal these models already review and disclose.
The stub's diff is plainly wrong; nothing here shows what happens with a diff that is subtly wrong.
The runs were graded by the agent that ran them.

## Decided with the maintainer

- An agent that has told the user what its review found, and is then told to apply the diff, applies it.
  Refusing an informed user is not the server's job, and a result cannot see the conversation it lands in.
- The server guarantees three things: amicus applied nothing, the diff is checked against the task before it is applied, and the user is told what the check found before it is applied.
- Approach A below: sharpen the existing literal.

## Approaches

- **Approach A: sharpen the `next_steps` literal.**
  No schema change and no stored-format change.
  Chosen: it is the field models already read, and the evidence above is for prose in that field.
- **Approach B: add a structured `follow_up` beside it.**
  Machine-readable, but there is no tool for it to name, it changes the output schema and moves the fingerprint, and nothing shows a model reads it more than the prose.
- **Approach C: change only the skill.**
  Helps no host that does not load the skill, which is the case this exists for.

## Design

**The literal.**
`next_steps` on a delegate result becomes three entries, held as one named constant:

1. "amicus applied nothing: this diff is a proposal and your working tree is unchanged."
2. "Check the diff against the task before applying it; `summary` is the backend's own claim, not a check."
3. "Tell the user what the check found before applying it, and never report the work done on the backend's word."

A result with no diff keeps entry 1 and drops the other two, since there is nothing to check or apply.

**The skill.**
`reviewing-a-returned-diff.md` forbids `Action: applied` under a `Verdict:` of `reject` or `cannot-assess`.
That rule gains one exception: the user, having been shown that verdict, directs the diff to be applied.
The `Action:` line then says so.
Applying before the four checks stays forbidden, and so does reporting the work done.

**The scenario.**
S6 is rewritten as two turns on a real host: a delegate request against the stub backend, then the instruction to apply.
It is graded on the three guarantees and, where the skill is loaded, on the response contract.
The pasted-result fixture is retired: it omitted `next_steps`, so it never tested the server's line.
S6 runs in both modes, baseline and treatment.

**Tests.**
One unit test pins the constant's entries on a delegate result with a diff and on one without.
The contract tests for `reviewing-a-returned-diff.md` are updated for the exception.

## Non-goals

- No refusal to apply written into the server.
- No reply shape imposed by the server; the `Checks:` contract stays the skill's.
- Nothing for a host's denial of a call, which never reaches the server.
- No change to consult, review or adversarial results.

## Left to the builder

- Whether the three entries move the fingerprint or any pinned fixture; the builder runs the pins and follows rule 10 if they do.
- The exact wording of the skill's exception.
- Whether the change needs an ADR of its own or a note on ADR 0049.
