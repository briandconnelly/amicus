# ADR 0033: an unreadable review answer is delivered as `unstructured`

**Status:** Accepted (2026-09-17)

## Context

`_parse_reviewed` (`src/amicus/orchestration/finalize.py`) was strict about the shape of a review's answer.
Exit-0 output that was not one JSON object, or that repeated a key (#51), became an `invalid_json` or `schema_violation` error carrying a 300-character preview.
The docstring called that "never a prose downgrade".

Issue #139 showed the cost.
A Kimi review of a 435-line diff ran for about four minutes, exited 0, and produced what its preview showed was a substantive review.
amicus kept 300 characters of it and discarded the rest.
The error carried `temporary: true` and `repair: retry_then_report`, so a caller was told to pay for the same run again with no reason to expect a different answer.
Issue #116 recorded the same envelope for a Claude review that wrote tool-call markup instead of the object, where a retry at the default settings cost about $3.
Neither `detail="full"` nor the job record could return the lost text: `raw_response` exists only on a success envelope, and `ErrorDetail` has no carrier for it and omits values by policy.

A prose consult already took the other path.
Since #52 it is delivered with the answer in `summary`, `missing_findings` in `findings_diagnostics`, and `missing_member` on every prose list, so the diagnostics say nothing was parsed rather than claiming the backend reported none (ADR 0024).

## Decision

**A non-empty review answer that amicus cannot read as one object is delivered, not discarded.**
`amicus_review_changes` and `amicus_adversarial_review` return `ok: true` with the new `review_status: unstructured`.
`verdict` and `confidence` are `unknown`, since nothing was read that could supply either (ADR 0017, ADR 0026).
`findings` and the prose lists are empty.
`findings_diagnostics` reports `missing_findings` and every `lists_diagnostics` member reports `missing_member`, as they do for a prose consult.
`coverage` still describes the input.
`summary` is a fixed sentence saying where the answer is, and the answer itself is `raw_response.text`, redacted as that field always is.
That text follows the existing detail rules: delivered at `detail="full"`, stripped at `summary`, and kept on the job record so `amicus_job_result` returns it later for free.
The summary does not carry the answer the way a consult's does.
A consult's answer is its result, but a review's result is its verdict and findings, and a large unparsed answer does not belong at `detail="summary"`.

The alternative, keeping the error and adding the full text to it, was rejected.
It would need a new error-side field and parallel detail semantics for errors.
It would also keep a result that holds the backend's whole answer behind `ok: false`, where a caller that branches on `ok` never looks.

**Only an empty answer is still an error.**
It stays `invalid_json` with the shared table's `retry_then_report`, which is honest there: an empty answer is the case a retry can plausibly change.
`schema_violation` is no longer a review outcome and leaves the review tools' `error_codes`.
That also settles #116's point about a deterministic `invalid_json`: the deterministic cases now reach the caller as `unstructured`, carrying no retry advice.

**An answer that encloses exactly one object is read as that object.**
When the answer is not JSON as a whole, `classify_structured` parses the span from its first `{` to its last `}`.
Nothing outside that span can contain a brace, so the span can never start inside a larger object: a truncated answer cannot have one of its complete findings promoted to the whole review.
Two objects never parse as one.
Prose around the object that itself contains a brace makes the span unparseable, and the answer is `unstructured` rather than guessed at.
The repeated-key refusal of #51 applies inside the span too, so #139's proposal to keep the last value of a repeated key is not adopted: that is exactly the silent collapse #51 exists to prevent.
The prose outside an accepted object is not reported anywhere but `raw_response.text`.

## Consequences

`ReviewStatus` gains a value, so `FINGERPRINT` moves.
`RESULT_FORMAT` moves from 6 to 7, because a format-6 reader's closed enum rejects a record carrying `unstructured`, which is the reader-acceptance criterion ADR 0026 applies.
A caller that branched on `ok` and then read `verdict` must now handle `review_status: unstructured`, which the skill binds as a rule: read `raw_response.text` before concluding or paying again.
tools/list grows by 832 bytes on every profile, itemized in `tests/test_discovery_cost.py`.
The finalize docstring's "never a prose downgrade" is superseded by this record.
The captured sibling differentials keep their recorded error envelopes, and amicus's divergence from them is listed beside each case.
