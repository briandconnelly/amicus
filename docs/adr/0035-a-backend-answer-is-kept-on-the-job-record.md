# ADR 0035: a backend's answer is kept on the job record, and rule 18 does not reach it

**Status:** Accepted (2026-09-17)

## Context

AGENTS.md rule 18 says a prompt input is never written to disk, to a worker's argv or to a log, and its last sentence said no exemption reaches text "copied, derived or replayed from a prompt anyone sent".
That sentence was added after ADR 0012, where the maintainer conceded that the rule binds committed eval prompt bodies and host captures literally; it exists to stop prompt text being laundered into a fixture by relabelling it.

A backend's answer often quotes the caller's inputs: a `question`, a `focus`, a line of a `task`.
Since M2 every successful result has carried `raw_response.text`, the backend's whole answer passed through the secret-pattern redactor, and the job worker writes the whole envelope to `result.json` (`src/amicus/_worker.py`).
`jobs/delivery.apply_detail` nulls the text only on delivery at `detail="summary"`; the record keeps it, which is what makes `amicus_job_result(detail="full")` free later and is the recovery ADR 0033 relies on.
A prose consult's answer is also its `summary` (ADR 0024), and findings, the prose lists and a delegate's diff are backend output too, so an echoed input can reach disk through several stored fields.

Copilot raised the conflict twice on #161, and #163 asked whether rule 18's clause was meant to reach a model's echo.
Codex and Kimi were consulted independently on 2026-09-17 with the same brief, and Claude formed its view before reading theirs.
All three read the clause as reaching an echo as written, since every answer is derived from its prompt, and all three recommended keeping the record.

## Decision

**A backend's answer is output, not a prompt input, and rule 18 does not reach it even where it quotes or paraphrases one.**
The rule exists to stop amicus itself from making extra copies of caller-supplied text in places with worse visibility or retention than the disclosed carrier: a log, argv, `spec.json`, a committed artifact.
The job record is not such a place.
The answer is what the caller paid for and was told is recorded as a job; it sits in a user-only directory under `AMICUS_STATE_DIR`, expires under `AMICUS_JOB_TTL` or the per-workspace cap, and `amicus_job_consume_result` discards it on read, reporting `delete_failed` when it cannot.
An echoed input has already transited the disclosed egress, and storing what came back adds no observer beyond the record the caller asked to exist.

**The exception is narrow: amicus keeps the answer only as the job's `result.json`.**
The result amicus builds from the answer is covered the same way: its parsed fields and, for a delegate, the diff amicus captures from the worktree, which a task can shape as directly as an answer can.
It still goes to no log, no argv and no other file, so `obs.py`'s exception-text policy, the fixed `FindingReason` vocabulary and the hashed host captures stay as they are.
What the repository commits of an answer stays bound wherever the answer repeats a prompt anyone sent.
Rule 18 is amended in its own governance PR to say both things, and its "copied, derived or replayed" clause now names its subject: amicus itself, or anyone working in this repository.

**The retention is disclosed where the spend is.**
Every paid tool description, sync and async, carries one sentence (`tools/_resolve.RECORD_RETENTION`): the record keeps the whole answer, secret-redacted and able to quote the caller's inputs, whatever `detail` delivered, until `AMICUS_JOB_TTL`, the cap or consume removes it.
The `detail` parameter says it shapes delivery only.
The README's Safety section and the skill's retention paragraph say the same.
The sentence names the whole answer rather than `raw_response.text`, because a prose consult's answer is stored in `summary` too.
It does not go on `amicus_backends`, which carries per-backend facts; this one is not backend-specific.

**Scrubbing was rejected.**
Removing each input's text from stored output misses paraphrase, which is the more dangerous case, and can corrupt a result; keeping the raw text in memory only gives up the recovery ADR 0033 exists to provide.
A reading of the rule that retroactively covered every result stored since M2 would have been a policy change made as a clarification.

## Consequences

The boundary is checked by carrier, not by semantic derivation: `tests/test_sync_tools.py` runs a consult whose fake backend deliberately echoes a marker and asserts the marker appears in `result.json` and in no other file of the job record, while a second marker in the question appears in none.
`tests/test_surface_honesty.py` pins the disclosure sentence on every paid tool and the delivery-only clause on `detail`.
Statements that were overbroad under the exception are narrowed to the input half: `request.py`'s module docstring and the design spec's "Jobs and tasks" section.
`FINGERPRINT` moves to schema-35 for the description text; `RESULT_FORMAT` does not move, since nothing stored changes.
Kimi's own session log, which keeps the full prompt and answer outside amicus's retention, is a separate disclosure gap filed as #179.
