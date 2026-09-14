# ADR 0024: prose-list loss is disclosed as a field and never folded into the verdict

**Status:** Accepted (2026-09-14)

## Context

`_str_list` (`src/amicus/orchestration/finalize.py`) built the `questions`, `assumptions` and `next_steps` lists of every structured result by keeping string and numeric entries and discarding everything else.
A non-list member became `[]`.
Nothing recorded either loss, so a backend that structured a next step as `{"step": ..., "why": ...}` lost it entirely, and a caller reading `next_steps: []` could not tell whether the backend had no next steps or amicus had failed to carry them.
Issue #52 named this as #38's defect on the prose lists rather than on findings.

The path is live for the same reason #38's was: only `codex` is held to the output schema natively, and `claude` and `kimi` receive it as prompt text.
The schema requires all three members as arrays of strings, so a number, an object, a null or an absent member is a deviation on two of three backends by ordinary operation, not by malfunction.

#38 established the shape a disclosure takes: count what was lost, name a reason from a fixed vocabulary, never echo the omitted content, and return null only when nothing deviated.
What it left open, and what a Codex design consult on 2026-09-14 was asked to argue, was whether the prose lists should reuse `FindingsDiagnostics`, get three fields of their own, or share one; whether an absent member should be reported when backends may routinely omit `assumptions`; whether a stringified number is a deviation; and whether losing a next step should touch the verdict, as losing a finding does.

## Decision

**One field, `lists_diagnostics`, with one nullable member per list.**
It is null when all three lists were carried intact, so the outer null keeps the meaning `findings_diagnostics` gave it.
A member is null when that list was clean and `{dropped, reasons}` when it was not, so a caller learns which list lost what without three top-level fields or a diagnostics object whose absence has to be inferred per list.
The type is the prose lists' own rather than a generalization of `FindingsDiagnostics`: the two vocabularies differ, a shared type would need a union of reasons that neither field can produce, and the published schemas inline every model per tool, so sharing a type saves no wire bytes.

**Every deviation from the schema is reported, including the ones amicus repairs.**
A number is still delivered as its string, for compatibility, and reported as `number_stringified` at `dropped: 0`; a null diagnostic beside a value amicus changed would claim schema-faithful output that was not.
A bool is not a number amicus will stringify: `bool` subclasses `int`, so the old code delivered `True` as a next step, and it is now dropped and counted as `invalid_entry` with nulls, objects and arrays.
An absent member is `missing_member` and a present non-list one is `invalid_container`, told apart with the same `ABSENT` sentinel #38 introduced, because `[]` is how a conforming backend says "none" and absence is how amicus learns it cannot know.
A backend that routinely omits `assumptions` will routinely say so in this field; that is the honest signal, and collapsing it into `[]` would be the defect again.
The same reading covers a consult answered in prose rather than the requested object, which Codex's review of the branch found the first draft delivering with a null diagnostic beside three empty lists.
Nothing was parsed from such an answer, so every required member was absent: it now reports `missing_member` on all three lists, and `findings_diagnostics` reports `missing_findings` on the same path, which #38 had left null.
The answer itself is carried whole in `summary`, so nothing is lost; what changes is that the empty lists no longer claim to be the backend's answer.

**A `not_run` review keeps both diagnostics null, and `review_status` is the signal.**
Copilot's review of the branch named the other constructor site that parses nothing: a review or critique over an empty scope returns `review_status: not_run` with no backend call.
That is not the prose-consult case.
There, output existed and its members were absent, which `missing_member` and `missing_findings` state exactly; here, nothing ran, and a reason vocabulary about the backend's output would describe output that never existed.
`review_status` already carries the fact on the wire as a first-class field, the skill's rules say to check it, and the published descriptions of both diagnostics now name the case rather than leaving null to be read as a measurement.

**Nothing folds into the verdict or confidence.**
A finding is the review's correctness signal, so `apply_findings_loss` stops a `pass` from standing over a finding amicus could not carry.
A next step is advice: no verdict is computed from it, no confidence rests on it, and a `pass` delivered with two lost next steps is still the backend's `pass`.
Folding would make the verdict say something about a field it does not measure, and the invariant ADR 0017 published, that amicus substitutes `low` exactly where it withholds the verdict, would gain a fourth cause for no gain in honesty.
The diagnostic is the whole disclosure, and the skill's binding rule says to read it before treating an empty list as the backend's answer.

**Delegate does not carry the field.**
`DelegateResult` builds its `next_steps` from amicus's own literal and never parses a backend list, so a diagnostic there would describe output that never existed.
The field lives on a base shared by the three results whose lists are parsed from backend output; delegate stays on the base below it.

**The meaning is published once per tool, on the field.**
`publish._strip_schema_noise` keeps only registered descriptions, and the member schema is inlined three times per tool.
The first draft carried the reason prose on each member's `reasons` and cost 2400 bytes more than carrying it once on the field; the field carries it now.

## Declined

Stringifying an object entry as JSON, so that `{"step": "run it", "why": "because"}` reaches the caller as text.
That is amicus deciding what a backend's structure reads as, which is the guess #38 declined to make for findings, and rule 18 forbids the diagnostic from echoing it.

Three top-level fields, one per list.
They would cost three descriptions per tool for the same disclosure, and a caller would have to check three nulls to learn that nothing deviated.

## Consequences

`FINGERPRINT` moves to `schema-23` (`tool_output_schemas`, `value_enums`) and `RESULT_FORMAT` to 6.
A format-5 record still validates against the new model, because the new field has a default, and that is exactly why the format gate must refuse it: its defaulted null would assert that every prose list was carried intact by a run that never measured it.

`tools/list` grows 5181 bytes on the `all` profile, about 1750 of it prose and the rest the object inlined on three tools; `tests/test_discovery_cost.py` records the split.
It is kept for the reason #38's prose was kept: an MCP-only caller has no skill file to fall back on, and the two misreadings the field exists to prevent, that a null member beside an empty list means the backend said none and that `dropped: 0` means nothing changed, have to reach it on the wire.

The skill's `Results` rules name the field and the misreading; `tests/test_skill_contract.py` asserts the rule against the binding-rules slice and maps `ListReason` to the reference section that owns it, so a reason added to the enum fails the gate until the reference documents it.
