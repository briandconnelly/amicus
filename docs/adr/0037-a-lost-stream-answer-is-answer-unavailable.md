# ADR 0037: an answer the stream capture lost is `answer_unavailable`

**Status:** Accepted (2026-09-23)

## Context

amicus captures a backend's stdout under `AMICUS_MAX_OUTPUT_BYTES` (10 MB by default) so a runaway process cannot exhaust memory.
The capture keeps a head window and a bounded tail, and any single line longer than the cap is cut short with a `…[line truncated]` marker.
`CommandRun.output_truncated` and `capture_failed` recorded that output was lost, and nothing downstream read them except ADR 0036's stream-substitute check (#198).

Two backends answer on that stream.
Claude's stdout is one JSON envelope.
Kimi's answer for consult and review is the last assistant event, and `extract_final_message` returns the last one that parses.

A zero-spend probe with the fake kimi and a 65,536-byte cap showed what that costs.
A final assistant event larger than what the tail has room for is evicted whole, the interim event before it still parses, and the consult returned the interim message with `ok: true` and `meta.truncated: false`.
With 200 KB cut from the middle instead, the tail kept the true final event and the answer was right.

Both union flags were also set by stderr, which never carries an answer, so a stderr flood alone made ADR 0036 refuse a whole stream.

## Decision

**A stream answer the capture cannot vouch for is not delivered.**
It is `answer_unavailable`, with `error.details.reason` `stream_truncated` or `stream_capture_failed`.
The code already meant "the backend answered and amicus could not read it whole"; the maintainer chose it over a new code or a delivered answer with a warning.

**The refusal is precise, not blunt.**
Only output lost *after* the event the answer was taken from can hide a truer answer, because the tail keeps the newest lines.
Kimi's `lost_after_final_message` reports whether a loss marker, `streamcap.is_loss_marker`, sits after that event, or anywhere when there is none.
A stream cut only in the middle is still delivered, so a run that answers correctly today keeps doing so.
A reader thread that died loses everything after it, so `capture_failed` refuses wherever the answer sat.
Claude's envelope is one JSON document, so a capture that lost any of it leaves nothing that parses, and an envelope that parsed was captured whole.

**The backend decides, because only it knows which record it answered from.**
`ExecResult.answer_loss` carries the finding (`truncated` or `capture_failed`), set through the SDK's `stream_answer_loss`.
An answer read from a file never sets it, since the stream is then only accounting: Codex's last-message file and Kimi's delegate answer file are unaffected.

**Stdout has its own flags.**
`CommandRun.stdout_truncated` and `stdout_capture_failed` cover stdout alone; the union flags keep their meaning.
`stdout_truncated` also counts one line cut at the per-line cap, which evicts nothing and so never set `output_truncated` before.

**A lost stream explains only an empty or unparseable answer.**
A clean exit that Kimi's inspector calls `empty_response`, or Claude's calls `invalid_json`, is `answer_unavailable` when the backend reports a loss, since the loss is why the answer looked absent.
Any other inspector finding on a clean exit is its own fact and wins, as ADR 0036 decided for a refused file.

**A file refusal wins over a stream loss, and a delegate keeps its diff.**
When both happened, the file was the primary channel, so its refusal reason is the one reported.
A delegate whose stream lost its summary still delivers the worktree diff, with amicus's own summary saying so and no `meta.security_warnings` entry, because nothing was refused under ADR 0009.

**The repair follows the cause.**
`stream_truncated` repairs with `reduce_input` and is not temporary: the identical call is likely to produce the same output, and the alternative names `AMICUS_MAX_OUTPUT_BYTES`.
`stream_capture_failed` repairs with `retry_then_report` and is temporary, because a reader dying is not a property of the answer.

## Consequences

This supersedes ADR 0036's sentence that a stream substitutes for a refused file only when the capture was neither truncated nor failed: it now substitutes when the backend reports no `answer_loss`.
A middle-truncated Kimi stream therefore becomes a valid substitute, and a stderr flood no longer blocks one.

`answer_unavailable` is now listed on adversarial review, which only Claude runs, so the tool catalog moves and `FINGERPRINT` with it.
`error.details.reason` is free text on the wire, so the new reasons do not move `RESULT_FORMAT`.

A delivered answer is still silent about a middle cut: the answer is right, but metadata an event in the middle carried, such as usage, can be missing from `meta` without saying so.

Not established: whether a real Kimi or Claude run has produced a final message past the cap.
The probe used the fake at the smallest cap amicus accepts, and 10 MB is a large answer.
