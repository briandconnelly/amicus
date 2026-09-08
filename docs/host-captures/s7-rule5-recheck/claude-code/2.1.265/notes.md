# Claude Code 2.1.265 — S7 rule-5 recheck, notes

Captured 2026-09-08 in the M7 release worktree, Task 8 Step 2/4
(`.superpowers/sdd/2026-09-08-amicus-M7-release/task-8-brief.md`), following the maintainer's
approval of Run B from `task-8-run-brief.md` and the coordinator's explicit hard boundary: zero
real amicus backend calls this round.

## Summary

The rule-5 timing question was resolved first (see `transcript.md`): rule 5 postdates the S7
baseline capture by about an hour, so a comparison against that baseline would have been a
genuine single-variable isolation of the skill text — **if** the run had reached the point of
observing approval friction. It did not. The host (`claude-code/2.1.265`, not the 2.1.263 every
prior capture used) dispatched `amicus_delegate` to the fake `codex` stand-in without ever
refusing the call or surfacing an approval prompt, contrary to the documented behavior this
design relied on. No amicus assertion for S7 could be graded from this run as a result.

## Disposition

This run is recorded as **inconclusive**, not as a pass or a fail, and does not move S7's
`status` off `fail`. The scenario's remedy (SKILL.md rule 5) remains untested in the sense that
matters: no run to date, including this one, has observed the model narrate real approval
friction under the current skill text. What is new is the rule-5 timing fact (now settled) and
the host-version-drift finding (new information for whoever next attempts this).

## `--from` override

Same technique as every prior capture: a locally built wheel substituted for the committed
`.mcp.json`'s `--from` argument only. `git diff .mcp.json` empty before and after.

## Spend

Zero real backend calls. See `transcript.md`'s closing section for the full accounting of both
the failed first attempt and the run that actually dispatched to the fake `codex` stand-in.

## Rule 18 compliance

The reconstructed one-sentence ask was composed in the shell and piped to the host on stdin, never
written to a file in this repository. `server.log` in this directory carries no arguments —
`ConnectionLogMiddleware` (ADR 0011) logs tool name and protocol facts only. This capture's own
prose was checked against rule 18's amended wording (`INPUT_FIELDS` in `src/amicus/request.py`,
now naming `question`, `task`, `extra_context`, `instructions_append`, `focus`, `target`,
`evidence`) before being written; the model's `amicus_delegate` call in this run necessarily
carried a `task` value (an `INPUT_FIELD`), and that value is not reproduced anywhere in this
capture — only the fact that the call was made and its `backend` argument are recorded.

## Follow-up this leaves open

- Why the host did not refuse an ungranted, non-read-only MCP tool call in `-p` mode here, where
  the 2.1.263 captures show it consistently did. Candidate explanations: the host version drift
  itself (2.1.265 vs. 2.1.263), a difference in how this session's `--allowedTools` wildcard vs.
  explicit tool names is parsed, or some other configuration difference not yet identified. Not
  resolved here.
- The actual S7 remedy check (does the model narrate worst-enabled-backend attribution when a
  real approval prompt occurs) is still outstanding and still zero-spend-achievable in principle —
  it just needs a harness configuration on this host version that reliably reproduces the refusal,
  which this round did not find.
