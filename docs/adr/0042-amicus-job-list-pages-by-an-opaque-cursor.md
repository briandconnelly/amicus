# ADR 0042: amicus_job_list pages by an opaque cursor

**Status:** Accepted (2026-09-25)

## Context

`amicus_job_list` could not page: omitting `limit` returned every retained match, and setting it truncated to the newest N with `truncated: true` and no way to reach an older job except fetching them all (#249, `[8.house-pagination]`).
The 2026-09-07 review judged house pagination unnecessary because no tool returned an unbounded list; the list is held to the per-workspace cap `AMICUS_JOB_MAX_COUNT`, which an operator may raise to 1,000, and which server processes sharing a state root can each exceed by one start, because the lock that enforces it is process-local (`JobStore._make_room`).

## Decision

**A page that omits matching jobs carries `has_more: true` and `next_cursor`, and `cursor` returns the jobs after it under the same filters.**
`has_more` and `next_cursor` are a house pagination convention in the tool's own result, not protocol fields (`[8.house-pagination]`).
`truncated` and `truncation_hint` keep their 0.6.0 values as a compatibility alias of `has_more` on this tool, and their descriptions say so: under `[8.truncation]` `truncated` should mean rows paging can never return, and no job the listing omits is beyond reach, so a caller should read `has_more`; changing what `truncated` reports would instead tell a 0.6.0 caller it holds every job.
The cursor is the last returned row's `started_epoch` and `job_id`, joined by a colon; the listing sorts by that pair, newest first, so a page after an anchor is every row that sorts below it, and an anchor that was consumed or evicted between pages still resolves.
The text is opaque to callers, and only this tool mints it, but only its form is checked: a cursor that is not a finite epoch, a colon and a 32-hex job id is `invalid_arguments` on `cursor` with a repair naming the tool, and a well-formed one is used as an anchor whether or not the tool issued it.
Signing the cursor would add a server secret to protect nothing: a forged anchor can only select a page of the caller's own workspace listing, which the same call without `cursor` already returns.

**"Omit `limit` for all" stays the default.**
The list is held to the per-workspace cap, so a bounded default page would change a documented default for little protection; the description now names the cap and its per-process overshoot.

## Consequences

- `JobListResult` gains `has_more` and `next_cursor`, the tool gains `cursor`, and the listing's sort gains a tiebreak, so `FINGERPRINT` moves; `RESULT_FORMAT` stays 9, since a job list is never stored.
- The `truncation_hint` names the cursor rather than "omit `limit`".
- `amicus_capabilities.tool_details` lists `cursor` among the tool's optional parameters.
