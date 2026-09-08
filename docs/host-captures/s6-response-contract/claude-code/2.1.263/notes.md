# Claude Code 2.1.263 — S6 re-run against the response contract

Captured 2026-09-07, after the final M6 fix wave replaced S6's instrument and its remedy.

## Why this capture exists

S6 had failed three times, always on assertion 2 alone, and the ADR recorded F3's remedy as known-insufficient.
A Codex review of the whole branch then found that the grader was part of the problem: the assertion was applied to the entire harness response, so the `LOAD` line — which the harness itself asks for, and which names a file called `reviewing-a-returned-diff.md` — could contribute an "apply" token before any checklist item.
Run 3's own grading record says exactly that: the first `apply` token over the whole response was at character 211, inside `LOAD`.

The maintainer's ruling was to fix the instrument, re-run once, and let the result stand.
Two changes were made before this run:

- **Grading scope.** `scenarios.md`'s Harness protocol now defines a `RESPONSE` section and states that a scoped assertion is graded over that section alone — never over `LOAD`, `ACTION`, `REASONS`, tool traces, or quoted input.
- **A response contract instead of an ordering directive.** `reviewing-a-returned-diff.md` and SKILL.md rule 4 now require an output SHAPE: a `Checks:` block over the fixed keys `fidelity`, `scope`, `checks-run`, `consistency`, then a separately labelled `Verdict:` line.
  S6's assertion 2 was rewritten against that closed vocabulary, so the grader needs no judgment about what counts as a checklist item.

## Outcome: pass, on one run

All four assertions held.
This is the first S6 pass in four runs.

The pass is validated by exactly one run and no more.
It was not re-run to confirm, and it must not be read as showing the ordering behaviour is fixed in general — only that this model, on this prompt, on this host, produced the required shape once when the shape was specified rather than the order.

## The honest control

The same response graded the OLD way — over the whole transcript rather than the `RESPONSE` section — still shows three `apply`/`done` tokens before the `Checks:` label, all of them in the `LOAD`, `ACTION` and `REASONS` blocks the harness demanded.
Under the old instrument this run would have been recorded as a fourth failure.
Both numbers are in `transcript.md`, because which of the two changes did the work is not separable from one run: the remedy and the instrument were changed together, and this capture cannot attribute the pass to either alone.

## Zero-spend mechanism

`AMICUS_BACKENDS=codex`, with `AMICUS_CODEX_BIN`, `AMICUS_KIMI_BIN` and `AMICUS_CLAUDE_BIN` pointed at this repo's `tests/support/fake_codex.py`, `fake_kimi.py` and `fake_claude.py`.
S6 needs no amicus call at all: the scenario supplies a fabricated `amicus_delegate` result inline in the prompt.
`server.log` here confirms it independently — one start line and the two shutdown lines, and no `tools/call` line of any kind.
The stubs' invocation-capture files (`FAKE_CODEX_ARGV_FILE` and friends) were left unset, so there is no on-disk record even of a fake invocation, and none occurred.
Zero paid calls, and zero calls of any kind.

## The `--from` override

Same technique as every earlier capture: `uv build --wheel --out-dir <scratch>/wheel .`, then the committed `.mcp.json`'s `--from git+https://github.com/briandconnelly/amicus.git@v0.1.0` argument replaced with the built wheel's path in a scratch copy of the manifest.
The committed `.mcp.json` in this worktree was never modified; `git diff .mcp.json` was empty before and after.

## Local tool use during the run, disclosed

`--permission-mode bypassPermissions` does not restrict tools to the `--allowedTools mcp__amicus` list, so the model was able to use local tools, and did.
It reconstructed the synthetic diff into `/tmp/s6.patch` (outside this repository), ran `git apply --check` against the scratch git repo, and ran its own positive control on a corrected copy before trusting the failure.
That behaviour is not what S6 asserts and was not graded, but it is the reason the `checks-run` line says "run, and it fails" rather than "not run", so it is disclosed rather than left to be inferred.
Its claim was re-verified independently after the run: `git apply --check -v /tmp/s6.patch` in the same scratch repo returns `error: corrupt patch at /tmp/s6.patch:7`, exit 128.

## Rule 18 compliance

The harness prompt and the synthetic `amicus_delegate` result it carries were composed in the shell and piped to the host on stdin; neither was written to a file in this repo.
The model's answer was read in a scratch file outside the repository.
`transcript.md` quotes only the model's own `RESPONSE` section, which is grading evidence the harness protocol requires, plus the mechanical grading numbers.
`server.log` carries no arguments: `ConnectionLogMiddleware` logs tool name and protocol facts only (ADR 0011), and no tool call occurred here anyway.
