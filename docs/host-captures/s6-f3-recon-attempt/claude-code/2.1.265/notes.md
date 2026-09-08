# Claude Code 2.1.265 — S6 F3-isolation attempt, notes

Captured 2026-09-08 in the M7 release worktree, as Task 8 Step 2 of the M7 plan
(`.superpowers/sdd/2026-09-08-amicus-M7-release/task-8-brief.md`), following the maintainer's
approval of Run A from `task-8-run-brief.md`.

## Why this run was attempted, and why it falls short of the design

The run brief proposed comparing the current skill text against run 5's exact conditions (the committed `S6-F1` rendering, the scoped grader, the tightened clause 2), with the skill text as the single differing variable.
That design assumed this agent could reuse run 5's actual fixture and wrapper-prompt bytes.
It cannot: `S6-F1`'s committed rendering was authored and consumed in an earlier task/session this agent has no access to, and the repository holds only its `sha256`, by rule 18 design.
This agent reconstructed an equivalent fixture and ask from `scenarios.md`'s own prose description instead (see `transcript.md` for the exact reconstruction and its own hashes).
That reconstruction is provably not byte-identical to `S6-F1` — the malformed-hunk-header design intent ("declares ten added lines over a two-line body", meant to be caught) turned out to be *applyable* by `git apply` in this run, whereas run 4's disclosed transcript shows `git apply --check` failing outright on the true fixture.
This is strong indirect evidence the two fixtures are not equivalently malformed, which is exactly the kind of divergence the reconstruction disclaimer in `scenarios.md`'s Harness protocol warns about.

A second, independent confound showed up only once the run was made: this environment's `claude` resolves to **2.1.265**, not the 2.1.263 every existing S6 capture used.
That was not a choice — it is whatever version is on `PATH` here — and it is disclosed rather than suppressed.

## The `--from` override

Same technique as every prior capture: `uv build --wheel --out-dir <scratch>/wheel .`, then a scratch copy of the committed `.mcp.json` with only its `--from` argument replaced by the built wheel's path.
`git diff .mcp.json` was empty before and after; the committed manifest was never touched.

## Zero-spend mechanism

Matches every prior S6 capture: the scenario supplies its `amicus_delegate` result inline, so no amicus tool call is needed to answer it.
`server.log` here independently confirms this — one start line, two shutdown lines, no `tools/call` line of any kind.
The fake-binary environment variables were set as defense in depth and were not invoked.

## Rule 18 compliance

The reconstructed fixture and ask were composed in the shell and piped to the host on stdin; neither was written to any file in this repository.
`transcript.md` quotes only the model's `RESPONSE` section, with every fixture-derived span (the invented file path, the invented function body, and the invented `summary` wording — none of which existed in this repository before this run, and none of which is written here in full) replaced by a bracketed placeholder, following the same convention `docs/host-captures/s6-response-contract/claude-code/2.1.263/transcript.md` established.
This capture's `notes.md` and `transcript.md` were checked against rule 18's current wording — "every field in `INPUT_FIELDS` (`src/amicus/request.py`)" — before being written; no `INPUT_FIELDS` value was constructed for this run at all, since no amicus tool call was made.

## What this does and does not license

See `transcript.md`'s closing section.
In one line: this run adds a disclosed, negative data point under the current skill text, but two independent confounds (fixture reconstruction, host version) mean it cannot be read as isolating F3, and F3 remains open exactly as `docs/adr/0012-m6-packaging-decisions.md`'s "Known gaps" section already states.
