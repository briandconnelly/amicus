# Reading results

A result tells you three separable things: whether the call succeeded, what it covered, and what
the model claimed. Reading only the first is the common mistake — an `ok: true` result can cover
nothing at all.

## Rules

Branching on `ok`, branching on the concrete tool, reading the coverage fields, treating results
as unverified claims, and matching verification to the claim are governed by SKILL.md → Binding
rules → Results, which is their authoritative statement. This file explains what each of those
means; it adds two obligations of its own:

- **Read `questions` and `assumptions` before treating an answer as responsive.** An answer built
  on a wrong assumption is not a wrong answer to your question; it is an answer to a different
  one.
- **Run this project's full gate before calling implementation work complete**, whatever a
  returned result claims.

`diffstat` is not an integrity check on `diff`; that rule lives in
[reviewing a returned diff](reviewing-a-returned-diff.md), and the reason is under Semantics
below.

## Three different facts about a job

| Field | Question it answers |
| --- | --- |
| `ok` (on the envelope) | Did *this MCP call* succeed? |
| `status` (on a job) | Is the job `running`, `done`, `failed`, `cancelled`, or `timeout`? |
| `result_available` | Is there a stored payload to fetch? |
| `result_ok` | Is that stored payload a success envelope, or a stored *error*? |

A job can be `done` with `result_ok: false`: the run completed and stored an error envelope. A
successful `amicus_job_result` call can therefore hand you a failed paid call. Branch on the
fetched envelope's own `ok`, not on the fetch having worked.

## Coverage: `ok: true` is not "it was reviewed"

`review_status` is `completed` or `not_run`. **`not_run` means no reviewable changes were
gathered for the requested scope** — the review did not happen and no quota was spent, but the
envelope is still `ok: true` with a `summary`. Treating that as a clean review is the single
easiest way to report a passing review of nothing. When it happens, read the summary: it names
how many untracked files were detected and omitted, and the remedy.

When a review *did* run but saw only part of the intended changes, amicus records why in fixed
vocabulary: `untracked_omitted`, `tree_changed_during_gather`, `truncated`, `redacted`.

**The degradation is one-directional, and this matters.** A model `pass` over partly reviewed
code is delivered as `verdict: unknown`, `confidence: low`, with the coverage reasons named in the
summary. A `concerns` or `fail` verdict is **passed through unchanged** — it is not degraded,
because a concrete finding stands on its own. So a `concerns` verdict over a truncated diff looks
exactly like a `concerns` verdict over a complete one. Read the coverage fields yourself; the
verdict will not tell you.

## `findings_diagnostics`: what the backend said that amicus could not carry

Coverage is about what the model saw. This is the opposite axis: the model saw everything and
amicus could not relay all of what it said. `findings_diagnostics` is `null` when nothing was
lost, and otherwise carries a `dropped` count and reasons from a fixed vocabulary:

| Reason | What it means |
| --- | --- |
| `severity_normalized` | A severity differed only in case or surrounding space. The finding is intact. |
| `extra_fields_omitted` | The backend added keys amicus's `Finding` has no home for. Every field amicus recognizes survives; whatever those extra keys said does not. |
| `invalid_entry` | An entry could not be represented at all and was dropped. Its content is not in the result. |
| `invalid_container` | The `findings` member was present but was not a list. Nothing could be read from it. |
| `missing_findings` | The `findings` member was absent. The output schema requires it, so this is not the backend saying "none". |

**`dropped` counts whole entries, and `dropped: null` is not `dropped: 0`.** `0` says no entry
was dropped — it is not a promise that nothing was lost, because `extra_fields_omitted` reports
content that went with keys amicus has no home for, and that is reported at `dropped: 0`. `null`
says amicus could not assess the list at all, so the count is unknowable. Never read `null` as
"none": read the reasons, not the count alone.

An `invalid_entry`, `invalid_container` or `missing_findings` also stops a `pass` from standing:
the verdict is
delivered as `unknown`/`low` with its own sentence in the summary, separate from any coverage
sentence. A `fail` or `concerns` keeps its verdict **and its confidence** — missing output does not
refute a negative the model did reach, so read `findings_diagnostics` on those yourself.

## `confidence`: whose rating it is

`confidence` answers how sure the review is, and two different parties can set it. Usually it is
the backend's own `low|medium|high`. amicus substitutes `low` in exactly the cases where it also
withholds the verdict as `unknown`, and there are three: partial coverage, findings it could not
carry, and `review_status: not_run`, where no backend was called and there is no rating to carry.
The two move together or not at all — so a `low` beside `verdict: unknown` may be amicus's own,
and a `low` beside any other verdict is the backend's word.

**A high confidence is not evidence that coverage was complete or findings intact.** A `fail` or
`concerns` verdict keeps the backend's rating whatever was lost, by design: missing output does
not refute a negative the model did reach. So `fail`/`high` is exactly what a truncated diff with
a dropped finding looks like. Read the coverage fields and `findings_diagnostics` yourself.

`unknown` is the fourth value and means something else entirely: the backend supplied nothing
amicus could read there, and no such lowering applied. **It is the absence of a rating, not a low one.**
Reading it as low inverts it — amicus declined to invent a rating precisely so that you would not
infer one. The verdict beside it is untouched: a backend that reported `fail` and said nothing
readable about its certainty is delivered as `fail`/`unknown`, neither softened nor promoted.

The dropped content is not echoed back in any form. For a job whose record still exists, a
`detail="full"` read returns `raw_response.text`, which is where the backend's own words survive.

## Meta fields that change a result's meaning

- `meta.truncated` / `meta.truncation_hint` — the payload was cut to a byte cap. On a delegate
  result the hint names the environment variable that raises the cap.
- `meta.redacted_paths` — secret-scrubbing altered content on these paths. The model may have
  reviewed a masked version of the code you think it reviewed.
- `meta.security_warnings` — a backend-specific hazard was detected. On `claude`, this is where
  workspace hooks are reported: under `inherit` and `scoped` config modes hooks run **outside**
  the tool allowlist, so a "read-only" Claude run can still execute them.
- `meta.compat_warnings` — the backend CLI drifted from the version amicus was verified against.
  Findings are still returned; their reliability is not vouched for.
- `meta.context_summary` — files changed and lines added/removed for the gathered input.

## Semantics: why `diffstat` is not a checksum

On a delegate result, `diffstat` and `meta.context_summary` are computed from the **raw** diff the
backend produced. Redaction and truncation are applied afterwards, to the `diff` field only. So a
`diffstat` reporting more files or lines than the `diff` shows is the expected result of
redaction or a byte cap — not evidence the model contradicted itself. Read `meta.redacted_paths`
and `meta.truncated` to tell the two apart. If neither is set and the counts still disagree, then
the inconsistency is in the diff itself and is worth investigating.

## Verification: match the check to the claim

"Verify it" is not one action, and running the full project gate is not always the relevant one.
A gate that could not have failed for this change is not evidence.

| Claim | What verifying it means |
| --- | --- |
| A design critique, an architectural objection, a missing requirement | Inspect the code or document the claim is about. A test run neither confirms nor refutes it. |
| A specific bug, with a file and line | Read that location. Reproduce it if a cheap targeted reproduction exists. |
| A proposed diff | Apply it to a disposable worktree and run the checks the change actually touches — see [reviewing a returned diff](reviewing-a-returned-diff.md). |
| Implementation work you are about to call complete | This project's full gate, per `AGENTS.md`. Nothing less closes out implementation. |

Verifying a claim in the working tree and applying a change to the working tree are different
acts. Do the first freely; the second is governed by the delegate rules.
