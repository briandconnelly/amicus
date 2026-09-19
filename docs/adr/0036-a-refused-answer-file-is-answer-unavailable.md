# ADR 0036: an answer file amicus refuses to read is `answer_unavailable`

**Status:** Accepted (2026-09-19)

## Context

amicus reads a backend's answer file through a bounded reader: `O_NOFOLLOW`, regular files only, at most 1,000,000 bytes (ADR 0009).
The reader returned an empty string for a file it refused, and the run loop dropped empty texts, so a refusal was indistinguishable from a backend that wrote nothing (#162).
ADR 0033 recorded the consequence for reviews, `invalid_json` with a message hedged to cover both cases.
It did not record the worse one: a Codex consult in the same state returned `ok: true` with the summary "(the backend returned no message)".

The reader also made a single `read` call, which may return short, so a prefix of an answer could be delivered as the whole of it.

## Decision

**A refusal is its own error, `answer_unavailable`.**
No code in the closed catalog was honest for it.
`empty_response` is declared per feature and listed only where Kimi can be selected, it means "exit 0 with no answer", and it repairs with a retry, which is wrong for a deterministic oversize.
`invalid_json` is wrong for consult and delegate, `internal_error` says amicus broke, and `input_too_large` and `context_too_large` are about input.
A Codex design consult reached the same conclusion, and the maintainer chose a new code over reusing one.

**The code is amicus's own, not the SDK's.**
It lives in `LOCAL_CODES` and `errors._LOCAL_RULES`, because `UNIVERSAL_CODES` is the intersection the sibling bridges emit and this comes from amicus's orchestration (ADR 0030).

**`error.details.reason` is a fixed token, and nothing else identifies the file.**
`artifact_oversize` carries `limit_bytes`, and `actual_bytes` when `fstat` knew the size; `artifact_not_regular` and `artifact_unreadable` stay apart, because one is a security invariant holding and the other an operational failure.
The path, an errno and exception text never appear: a delegate's answer path is model-controlled (ADR 0009).
It is never temporary; oversize repairs with `reduce_input`, the others with `inspect_and_retry`.

**An absent or empty file is not a refusal.**
The backend writing nothing is a different fact from amicus refusing what it wrote, and keeps its old meaning.

**Only a refusal of an answer artifact counts.**
`PreparedRun.answer_artifacts` names them; Codex stages its input schema in `artifact_paths` too, and refusing that says nothing about the answer.

**Every other failure wins, with one exception.**
A non-zero exit, a timeout, a missing binary and any failure an inspector reports are the more accurate account.
The exception is a clean exit an inspector diagnosed as `empty_response`: the refusal is why the run looked empty, so it is what is reported.
The first draft superseded any clean-exit failure, which would have hidden an inspector's auth or rate-limit finding; a Codex review and a Copilot review both caught it.

**Another channel is a substitute only if it was captured whole.**
Kimi's stream can carry the answer when its answer file is refused.
It is delivered, with a `meta.security_warnings` entry and `meta.truncated` false, only when the capture was neither truncated nor failed, because a damaged capture can lose the true final message while an earlier one still parses.

**A delegate keeps its diff.**
The diff is captured from the worktree, not read from the answer file, so it is still the honest primary result.
The summary is amicus's own and says so, `raw_response.text` stays null rather than carry amicus's words as the backend's, and the summary makes no claim about the diff's completeness, which `meta.truncated` and `meta.redacted_paths` describe.
With no diff either, it is `answer_unavailable`.

**Nothing is truncated to fit.**
A truncated structured consult would fall into the prose branch and be delivered as a successful answer, and a truncated review cannot be parsed.

**The reader reads to the end.**
It loops up to one byte past the cap, which bounds memory, tolerates a short `read`, and notices a file that grew after `fstat`.

## Consequences

`error.code` is a closed enum, so a reader of the previous result format rejects a stored error carrying the new value: `RESULT_FORMAT` moves 8 to 9, and `FINGERPRINT` to schema-37.
`tools/list` does not carry error codes, so its measured size does not move.
The code is listed on every paid tool that can select a backend answering through a file, and not on adversarial review, which only Claude runs and which answers on stdout.
ADR 0033's sentence about a refused answer file is superseded by this record.

Not established: whether a real backend's answer file can reach the cap.
Stdout is capped separately at 10 MB, and the short-read fix is a property of `read(2)` rather than an observed failure.
