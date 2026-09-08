# Claude Code 2.1.263 — amicus M6 free-scenario re-run (fix round 1)

Captured 2026-09-07 on the maintainer's machine, as part of Task 9's fix round.

## Why this capture exists

The first pass at Task 9 (S3, S4, S5, S6, S8) recorded verdicts from prose alone, with no durable artifact.
A reviewer flagged that as a gap: the zero-spend claim and every per-scenario verdict rested only on the executing agent's report, with nothing an outside reader could re-derive.
This capture re-runs all five scenarios with `AMICUS_LOG_LEVEL=DEBUG` and a real `AMICUS_LOG_FILE`, and commits the resulting `server.log` alongside a scrubbed `transcript.md`, following the layout and disclosure style of `docs/host-captures/install-smoke/claude-code/2.1.263/`.

## Honesty constraint on this re-run

The instruction for this re-run was explicit: record the new run's results as the results, whatever they are, even if they diverge from the first, uncaptured pass.
No scenario was re-run more than once to force a match with the earlier verdict.
All five verdicts from this capture match the first pass exactly: S3 pass (both modes), S4 pass, S5 pass (both modes), S6 fail, S8 pass.
S6's failure reproduced with the same root cause both times — the model's first sentence states its conclusion ("I didn't apply it") before naming any diff-review checklist item — which is itself evidence the ordering failure is a stable behavior, not a one-off fluke.

## The `--from` override

Same technique as the install-smoke capture: `uv build --wheel --out-dir <scratch>/wheel .`, then the committed `.mcp.json`'s `--from git+https://github.com/briandconnelly/amicus.git@v0.1.0` argument was replaced with `--from <scratch>/wheel/amicus-0.1.0-py3-none-any.whl` in a scratch copy of the manifest.
The committed `.mcp.json` in this worktree was never modified; `git status` stayed clean for that file throughout.

## Zero-spend mechanism

`AMICUS_CODEX_BIN`, `AMICUS_KIMI_BIN`, and `AMICUS_CLAUDE_BIN` were pointed at `tests/support/fake_codex.py`, `fake_kimi.py`, and `fake_claude.py` for every run in this capture.
This is defense in depth: even a paid call the model made despite the harness's describe-only instruction would have hit a local stdlib stub process, never a real provider.
For S3, S4, and S8 the harness prompt also instructed the model not to invoke any paid verb, only to describe the call it would make; `server.log` in this directory independently confirms no paid `tools/call` line appears for any of those three scenarios.
For S6 no tool call was needed at all, since the scenario supplies a fabricated `amicus_delegate` result inline in the prompt.
For S5 the correct answer is the free `amicus_backends` tool, and both of its runs really did call it — a free tool never reaches a backend process, so real dispatch of it costs nothing.
The fake binaries' own optional invocation-capture files (`FAKE_CODEX_ARGV_FILE`, `FAKE_KIMI_ARGV_FILE`, `FAKE_CLAUDE_ARGV_FILE`) were left unset for every run, so there is no on-disk evidence even of a fake invocation, confirming none of the three stubs was ever exec'd.

## Rule 18 compliance

The model's constructed prompt-carrying arguments (the described `question`/`task`/`extra_context` contents, and S6's synthetic delegate-result framing) were read only in the terminal via the Bash tool's output and never written to a file.
`transcript.md` and this file quote only tool names, argument shapes, the scenario's own already-committed prompts and synthetic placeholders, server-log lines, and grading prose.

## Corrected Step-3 verification script

The M6 plan's own Step-3 verification script splits `scenarios.md` on `### S` and checks each resulting text block for the literal substring `harness version`.
That check is broken independent of anything this task did: every scenario's actual run evidence lives in the shared `## Run log` table, which falls outside every scenario's own `### S<n>` block except the last one, since a block runs only up to the next `### S` heading.
Running the script verbatim on the file, before and after this fix round's edits, fails on `S1` for that reason, which predates this task.
A corrected script that checks the Run log table directly for a row per scenario id — rather than splitting the file per heading — is included in the Task 9 fix report (`task-9-report.md`), was run against the current `scenarios.md`, and printed `ok — 8 scenarios checked, 8 have run-log rows`.
The corrected script was also verified to catch a known positive: a scratch copy of the file with a fabricated `S9` scenario claiming `status: pass` and no matching Run log row was rejected with `FAIL: S9 claims pass with no row in the Run log table`.
The plan file itself was not edited, per the fix-round instruction that its committed copy is reviewed and gets fixed by whoever next revises the plan.

## Spend

Zero paid calls were made across all seven runs in this capture (S3 treatment, S3 baseline, S4, S5 baseline, S5 treatment, S6, S8).
See "Zero-spend mechanism" above for how that is verified rather than merely asserted.
