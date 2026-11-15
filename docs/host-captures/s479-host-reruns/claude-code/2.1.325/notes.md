# Claude Code 2.1.325 — host reruns for issue #479

Captured 2026-11-14 on the maintainer's machine, against the skill at commit `bfde839`.
Six runs: S1 three times, S2, S6 and S7.
The scenarios, their assertions and each run's grade are in `skills/collaborating-with-amicus/tests/scenarios.md`; this directory is the evidence those rows point to.

## Harness

Every run was one `claude -p --model opus` process with the prompt on stdin and a scratch git repository as its working directory.
`--setting-sources project` kept user settings out, so no user plugin, hook or permission default loaded; the init event of each run lists only built-in plugins and, for treatment, `amicus@inline`.
`--strict-mcp-config --mcp-config` pointed at a server started as `uvx --from <scratch>/wheel/amicus-0.14.0-py3-none-any.whl amicus-mcp`, the wheel built from this branch.
Treatment runs added `--plugin-dir` on this checkout; the baseline run did not, so it had no amicus skill and no amicus command.
`--tools` limited the built-in tools to Read, Skill and ToolSearch, and S6 added Bash.
`--allowedTools` granted Read, Skill and the amicus tools each run was meant to reach; S7 left the delegate tools ungranted and S6 left Bash ungranted.
The permission mode each run reported was `default`.
The model each run reported was `claude-opus-5-5`.

## What was verified before the runs

A free probe run, with `codex` alone enabled against the fake binary, asked which backends were enabled.
It reached `amicus_backends` and answered from the result, which showed that the rig connects, that the isolation holds and that the stream parser reports calls.
That probe is not a scenario run and has no row.

## Spend

Three paid calls, one per S1 run: two to `codex` and one to `pi` on `openrouter/moonshotai/kimi-k3`.
S2, S6 and S7 ran with `AMICUS_CODEX_BIN` and `AMICUS_CLAUDE_BIN` pointed at executable copies of `tests/support/fake_codex.py` and `fake_claude.py`.
`server.log` shows S2's repaired call spawning the fake binary, and shows no delegate call for S7 and no call at all for S6.

## Rule 18

Prompts were piped on stdin from the shell and are recorded in `scenarios.md` by id and `sha256` only.
The runner printed each tool call with every prompt-bearing argument reduced to its length, and wrote nothing of the stream to a file.
`transcript.md` carries tool names, non-prompt arguments, host and server messages, and short quotations of the subjects' replies about what they did.
The S1 answers relay a backend's answer to the question asked and are not reproduced.
`server.log` is the six runs' server logs joined under one heading each, with the scratch path replaced by `<scratch>`.

## Finding: the skill was installed and never loaded

In the five runs with the plugin loaded, no subject invoked `amicus:collaborating-with-amicus` and none read a file under the skill.
S1's two treatment runs and S7 invoked a command, `/amicus:consult` or `/amicus:delegate`, through the Skill tool.
Those commands name the skill's routing rules and do not tell the model to load the skill.
S2 and S6 invoked nothing.
So no host run had the binding rules or any required reading in context.
S1 and S2 are graded on call shape and pass; the baseline S1 run passes the same way with nothing installed.
S6 and S7 are graded on what `reviewing-a-returned-diff.md` and `options-and-errors.md` ask for, and fail.
A control for S6, run in a subagent told to read the skill, produced the response contract.
This capture does not show why the skill did not trigger; it shows that it did not, in five runs of five.
