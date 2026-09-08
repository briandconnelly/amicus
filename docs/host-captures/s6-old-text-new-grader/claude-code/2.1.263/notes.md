# Claude Code 2.1.263 — S6 control: old skill text, new grader

Captured 2026-09-08, closing the M6 review's second round rather than carrying the confound to M7.

## What was controlled, and why it was worth a run

S6's fourth run changed two things at once and passed.
The remedy changed — `reviewing-a-returned-diff.md` and SKILL.md rule 4 stopped asking for an ORDER of generated prose and started requiring an output SHAPE.
The instrument changed too — the grader stopped scanning the whole harness transcript and started reading the model's `RESPONSE` section alone, because the harness's own `LOAD` line had been supplying the deciding "apply" token.
Either change on its own could have produced the pass, and one run cannot say which did.

This control holds the remedy at its OLD value and the instrument at its NEW one.
If the old text passes under the new grader, the grader change explains the earlier pass by itself and the remedy is unproven.
If the old text fails, the remedy is doing work the grader change does not.
That reading was fixed before the run, and the run was made once.

## Outcome

Fail, on assertion 2 alone, so the second branch applies: the remedy is supported.
See `transcript.md` for the mechanical grading, the known-positive check that shows the grader can still pass a response, the graded `RESPONSE`, and every condition that differs from run 4.

## Recovering the old text

`git show f945b3d^:skills/collaborating-with-amicus/SKILL.md` and the same for `references/reviewing-a-returned-diff.md`.
`f945b3d` is the commit that replaced the ordering directive with the `Checks:`/`Verdict:` response contract, so its parent is the last state of the skill before the remedy existed.
Both files were written into a scratch copy of the plugin; every other file in that copy is at branch HEAD.

## The `--from` override

Same technique as the earlier captures: `uv build --wheel --out-dir <scratch>/wheel .`, then the committed `.mcp.json`'s `--from git+https://github.com/briandconnelly/amicus.git@v0.1.0` argument replaced with the built wheel's path in a scratch copy of the manifest.
The committed `.mcp.json` in this worktree was never modified.

## Zero-spend mechanism

`AMICUS_CODEX_BIN`, `AMICUS_KIMI_BIN` and `AMICUS_CLAUDE_BIN` pointed at this repo's `tests/support/fake_codex.py`, `fake_kimi.py` and `fake_claude.py`, so even a paid call made despite the harness instruction would have hit a local stdlib stub rather than a provider.
S6 needs no amicus call at all: its delegate result is supplied inline in the prompt.
`server.log` in this directory confirms that independently — one start line, two shutdown lines, no `tools/call` line of any kind.
The stubs' invocation-capture files were left unset, so there is no on-disk record even of a fake invocation.

## Rule 18 compliance

No prompt input was written to disk.
The harness wrapper, the setup fixture and the user prompt were composed in the shell and piped to the host on stdin; the model's answer was read from a scratch file outside this repository.
This capture names the prompts by id and `sha256` only, per the literal reading of rule 18 adopted on 2026-09-08.
`server.log` carries no arguments: `ConnectionLogMiddleware` logs tool name and protocol facts only (ADR 0011), and no tool call occurred here anyway.
