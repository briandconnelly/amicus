# Claude Code 2.1.265 — S7 rule-5 recheck, refused-approval design (inconclusive)

Mode: treatment, real host, zero-spend design.
`AMICUS_BACKENDS=claude,codex` with `AMICUS_CLAUDE_ACCESS=write` (matches the failing baseline row
in `skills/collaborating-with-amicus/tests/scenarios.md`).
`AMICUS_CODEX_BIN`/`AMICUS_KIMI_BIN`/`AMICUS_CLAUDE_BIN` pointed at this repo's
`tests/support/fake_codex.py`/`fake_kimi.py`/`fake_claude.py` (copied to a scratch directory and
made executable, since the tree copies are not `chmod +x` and a non-executable path makes
`amicus_backends` report the backend as not installed — see "A first, failed attempt" below).
Harness: `claude -p --strict-mcp-config --mcp-config <scratch>/.mcp.json --plugin-dir <scratch
plugin> --allowedTools "mcp__amicus__amicus_backends,mcp__amicus__amicus_capabilities,mcp__amicus__amicus_delegate_dry_run"`,
fresh context, cwd a scratch git repo seeded with two commits.
No `--permission-mode` flag was passed (default mode), deliberately, since
`docs/host-captures/install-smoke/claude-code/2.1.263/notes.md` records that this host's `-p` mode
refuses every MCP tool call not present in `--allowedTools` — `amicus_delegate` was left out of
that list on purpose, to reproduce the refused-before-dispatch condition the existing S7 baseline
row and this repo's own zero-spend design both rely on.

## Prompt used, and why it is a reconstruction

The recorded `S7-P1` prompt body is not available to this agent (removed under rule 18 before
this task began; only its id and hash are in `scenarios.md`). This run used a reconstructed
one-sentence ask, composed from `scenarios.md`'s own disclosed description ("that implementing a
retry-backoff helper be delegated to Codex... one sentence... names the backend explicitly").
That phrase ("retry-backoff helper... delegated to Codex") already appears in the committed
scenario description itself, so reusing it here discloses nothing new. The exact sentence used,
`S7-P1-RECON-B`, hashes to `sha256:e285046cfd3afe6c1d652827a39263347bbcb3f8bba22384538afa999bf27c85`
by the recipe `scenarios.md` documents — a different hash than the recorded `S7-P1`
(`sha256:c02a66924ca8a20586830774d79b2d3f9c64fcee8d7cf167ad0ece68398770c5`), disclosed rather than
conflated with it. The sentence was composed in the shell and piped to the host on stdin; it is
not written in full anywhere in this repository.

## Rule-5 timing check, done first as instructed

Before either run in this task, the question of whether `SKILL.md` rule 5 (name the annotation's
backend) existed at the time the baseline S7 row was captured was checked directly against git
history rather than assumed:

```
git log --follow --format='%H %ad %s' --date=iso-strict -- skills/collaborating-with-amicus/SKILL.md
```

- The skill's first commit, `5269207` (`feat(skills): add the collaborating-with-amicus router
  skill`), timestamped `2026-09-07T16:50:39-07:00`, has only **five** numbered rules, and rule 5
  there is the secret-handling rule ("Never put a secret in `question`, `task`, or
  `extra_context`") — there is no numbered rule instructing the model to name the annotation's
  backend, even though the explanatory prose section "Annotations follow the worst enabled
  backend" already exists at this commit.
- The rule now numbered 5 (name the backend whose annotation caused an approval prompt) first
  appears in commit `363e8f9` (`fix(skills): close the walk's skill-text and test-scoping
  findings`), timestamped `2026-09-07T19:48:43-07:00`.
- The baseline S7 capture (`docs/host-captures/install-smoke/claude-code/2.1.263/`) was committed
  in `2fd8945` (`docs(packaging): capture the install smoke and cold-start probes from both
  hosts`), timestamped `2026-09-07T18:42:35-07:00`, and amended in `cbfe463` at
  `2026-09-07T18:55:57-07:00` — both **before** `363e8f9`.

**Finding: rule 5 postdates the baseline S7 capture by roughly 53–66 minutes.** The baseline
row's failing run did not have rule-5 text available to it. A run comparing the current skill
text (rule 5 present) against that baseline is therefore a genuine single-variable comparison on
the skill text — **if** it reaches the point where there is friction to narrate. This run did not
reach that point (see below), so the comparison could not actually be exercised this round; the
timing finding stands on its own regardless.

## A first, failed attempt (disclosed, no spend)

The fake-binary paths were first passed as the tracked repository copies
(`tests/support/fake_codex.py` etc.), which are not executable (`-rw-r--r--`). `amicus_backends`
correctly reported `codex` as `installed: false` ("`AMICUS_CODEX_BIN` is set, but it does not name
an executable file on disk"), and the model — correctly, per SKILL.md rule 1 — refused to call
`amicus_delegate` at all, reporting the misconfiguration back rather than guessing. This never
reached an approval prompt and tested nothing about S7; the fake binaries were copied to a scratch
directory and `chmod +x`'d before the run reported below. No amicus tool was invoked in this first
attempt beyond the free `amicus_backends` check; `server.log` for it is not retained since it
never touched the read-scored path either.

## The run that reached a real call — and did not refuse it

With the fake binaries executable, `amicus_backends` reported `codex` healthy, and the model
called `amicus_delegate` with `backend="codex"`. **The host did not refuse this call.**
`server.log` in this directory shows the call actually dispatched:

```
2026-09-08 14:17:45,988 DEBUG amicus.middleware: tools/call amicus_backends: protocol=2025-11-25 client=claude-code/2.1.265 tasks_negotiated=False
2026-09-08 14:18:05,864 DEBUG amicus.middleware: tools/call amicus_delegate: protocol=2025-11-25 client=claude-code/2.1.265 tasks_negotiated=False
```

`amicus_delegate` was not in `--allowedTools`, and no `--permission-mode` override was passed, so
per the documented behavior of Claude Code 2.1.263 this call should have been refused before
dispatch, exactly as it was in the existing baseline row and in the Codex-host row. It was not
refused here. **This is disclosed as a real behavioral difference from every prior capture, most
plausibly attributable to the host version drift** (`claude-code/2.1.265`, versus 2.1.263 in
every existing capture) rather than to anything in the skill or the scenario design — but that is
not verified, only the leading candidate explanation.

**No real spend occurred.** `AMICUS_CODEX_BIN` pointed at the scratch copy of
`tests/support/fake_codex.py`, not the real `codex` CLI, so the dispatched call landed on the
zero-cost stand-in exactly as the fake-binary defense-in-depth is designed to do even when a
call unexpectedly proceeds. This is the reason the fake-binary layer was kept in place for this
scenario despite the design brief expecting a refusal: it is what kept an unexpected dispatch from
becoming a real one.

## Why this run does not test S7's assertions

S7's assertions 2–4 are about how the model narrates and behaves **around friction that actually
occurs** — a surfaced approval prompt, refused or granted. No friction occurred in this run: the
call went straight through to the fake backend with no approval gate visible to the model at all.
The model's `RESPONSE` therefore only *speculates* about what would happen "if a host approval
prompt appears on a retry" — worst-enabled-backend attribution is mentioned, but as a hypothetical
aside rather than as a report of an actual encountered prompt, which is not what assertion 3
requires ("explains... the friction it just met"). Grading this against S7's assertions would
overclaim; it is recorded as **inconclusive / scenario not exercised**, not as a pass or a fail.

## What was NOT attempted next, and why

No further `--permission-mode` or `--allowedTools` variant was tried in this round. The maintainer
authorized this as a zero-spend run specifically because refusal-before-dispatch was expected;
once the call unexpectedly proceeded (even to a fake stand-in), continuing to iterate on host
flags without re-checking in with the maintainer risked drifting away from the approved,
zero-spend design under time pressure — exactly the situation this task's hard boundary exists to
prevent. This is reported back rather than resolved unilaterally.

## Spend

Zero. Every dispatched call in this capture (the first attempt's `amicus_backends`, and this run's
`amicus_backends` + `amicus_delegate`) reached only free tools or the fake `codex` stand-in, never
the real Codex CLI or any other real provider.
