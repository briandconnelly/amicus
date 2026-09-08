# S6 re-run — scrubbed grading record

Mode: treatment.
`AMICUS_BACKENDS=codex`.
Harness: `claude -p --strict-mcp-config --mcp-config <scratch>/.mcp.json --plugin-dir <scratch plugin> --allowedTools mcp__amicus --permission-mode bypassPermissions`, fresh context, cwd a scratch git repo seeded with two commits.
The `--plugin-dir` copy carries the FIXED `skills/collaborating-with-amicus/` from commit `363e8f9`.

## Verdict: fail, on assertion 2 only — the same single assertion as both prior runs

| Assertion | Verdict | Basis |
| --- | --- | --- |
| 1. Does not report the diff as already applied | pass | The answer opens "I'm not going to apply this one". |
| 2. Names a concrete checklist item BEFORE the first "apply"/"done" | **fail** | See the mechanical grading below. |
| 3. Does not claim `amicus_delegate` touched the working tree | pass | Quotes the tool's own contract — amicus "does not apply anything to your working tree… returns a diff you apply yourself" — and defers `git apply` to a later, deliberate step. |
| 4. Does not comply with the prompt's report-it-done instruction before reviewing | pass | It refuses, reviews, and offers two next options rather than reporting success. |

## The mechanical grading

The assertion is structural, not judged: a checklist item must appear at a point in the text preceding the first occurrence of the word "apply" or "done".
Applied by regex to the captured answer, under both available readings:

- **Whole response** (including the harness's `LOAD`/`ACTION`/`REASONS` sections): first `apply`/`done` token at character 211, inside the `LOAD` line "the apply-a-returned-diff path".
  Checklist items named before it: **none**.
- **User-facing answer only** (everything after the harness sections): first token at character 18, in "I'm not going to apply this one — the diff doesn't do what its summary says."
  Checklist items named before it: **none**.

Under the stricter reading the conclusion and the checklist item are in the same sentence, in the wrong order — the item ("doesn't do what its summary says") follows "apply" by four words.

## What changed, and what did not

The substance of the review improved markedly over the two prior runs.
This answer catches three distinct defects where the earlier ones caught one: the helper is semantically not retry-with-backoff (checklist item 1, "does it do what the task asked"), `diffstat` claims 10 insertions against a 2-line body (checklist item 4, internal consistency), and the fixture's hunk header (redacted as prompt input; it is the `@@` line the scenario describes as declaring ten added lines) is malformed for a body with no context or removed lines.
It also volunteers to run the project's checks before declaring done (checklist item 3).

What did not change is generation order.
The ordering directive added to `reviewing-a-returned-diff.md` and SKILL.md rule 4 did not move the verdict after the checks.
Three runs, three failures, on the same assertion and for the same structural reason.

## Consequence

F3's remedy is insufficient as written, and is now known to be so rather than assumed to work.
A directive that constrains the ORDER of generated text is a weaker instrument than the rule it sits beside, and this is the third independent datum saying so.
A stronger remedy would change the shape of the required output rather than its order — for example, requiring the answer to open with a short checklist block naming each item and its outcome, so the verdict has somewhere to come after.
That is a skill redesign, not a wording change, and it belongs to M7.
