# kimi-code 2.4.0 — amicus evidence

Captured 2026-10-29 on the maintainer's machine by running the binary, with the same probes as `docs/kimi-help/2.3.0/`: `kimi --version`, `kimi --help`, `kimi provider list --json`, `kimi session --help` and `kimi session list --all --json`.
The binary was installed from npm into a scratch prefix, not over the global install.
No model call was made for this capture.
It was made because Kimi Code 2.4.0 was published on 2026-10-28, when `SUPPORTED_VERSIONS` stopped at `(2, 3)` (#400).
The kimi live gate requires the installed version to equal the newest supported minor, so until `(2, 4)` was added no release evidence could pass on 2.4.0.
2.3.1, 2.3.2 and 2.3.3 came between 2.3.0 and 2.4.0, and their notes were read with 2.4.0's.

## What the captures show

- `kimi-version.txt`: `2.4.0`.
- `kimi-help.txt`: the 2.3.0 capture with two changes.
  The `--auto` row now reads "everything runs and is decided automatically; only plans in Plan mode wait for your review."
  The commands list adds `import-sessions`, which imports recent Claude Code and Codex sessions into Kimi Code.
  Every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still declared.
  `tests/test_kimi_contract.py` asserts those flags against this file as against every other capture under `docs/kimi-help/`.
- `provider-list-shape.json`: the same top-level keys, container types, seven model-entry keys and `model_count` as the 2.3.0 capture.
  Only key names and types were captured; provider details (API keys, base URLs) were never written to disk.

## Session persistence and rule 18

AGENTS.md rule 18 requires the carrier re-check on the CLI release an amicus release is validated against.
On 2.4.0:

- `kimi --help` gained no option, and its one new subcommand, `import-sessions`, adds sessions rather than suppressing them.
- `kimi session --help` still offers `list` only: no delete, and no way to suppress a session.
- `kimi session list --all --json` returns 221 sessions, each with a `sessionDir`, from the same store 2.3.0 read; it held 211 on 2026-10-22.
  Their contents were counted, not read, because rule 18 binds them.

`docs/RELEASING.md` also requires the release notes since the previous check.
Every entry of the 2.3.1, 2.3.2, 2.3.3 and 2.4.0 notes in `apps/kimi-code/CHANGELOG.md` was read.
None adds a flag, setting or environment variable that stops a session being kept, moves the store, or hands kimi its prompt without a file.
The English `configuration/env-vars.md`, `configuration/config-files.md`, `configuration/overrides.md` and `configuration/data-locations.md` were also compared between the 2.3.0 and 2.4.0 tags; `data-locations.md` is unchanged.
The others rename the `[background]` section to `[task]` (the old name still read), add `[mcp]` reconnect delays and their `KIMI_MCP_RECONNECT_*` variables, and add `KIMI_CODE_REGION_MARKER`, `KIMI_CODE_SESSION_IDLE_RECLAIM_MS` and `KIMI_CODE_SESSION_LOCK`.
`KIMI_CODE_SESSION_LOCK=0` turns off the cross-process lock 2.3.0 added, not the store, and `KIMI_CODE_SESSION_IDLE_RECLAIM_MS` unloads an idle `kimi web` session from memory; neither keeps a session from being written.

So no documented or observed way to avoid the session-store carrier was found on 2.4.0, which is the condition rule 18 sets.
That is a statement about what was looked for and not found.
What this did not do is watch 2.4.0 write a session, since a run that creates one spends quota.

## The commits since 2.3.0

The `@moonshot-ai/kimi-code@2.3.0..@moonshot-ai/kimi-code@2.4.0` range has 49 commits and 722 changed files.
Under `apps/kimi-code/src/cli/`, all but two of the changed files are the self-update path (`sub/upgrade.ts`, `sub/update-download.ts`, `update/`) and telemetry, which amicus never invokes.
The other two:

- `cli/commands.ts` rewords the `--auto` help, registers `import-sessions`, and adds channel options to the hidden self-update worker.
- `cli/v2/run-v2-print.ts`, the print path, changed in three ways.

Of the four prompt-mode files `docs/kimi-help/2.1.0/FINDINGS.md` names, `options.ts` and `prompt-render.ts` are unchanged, and `commands.ts` changed only as above.
In `run-v2-print.ts`:

- A new session that `default_plan_mode` opened in Plan mode has its plan cancelled, with `default_plan_mode is not applied in print mode, because Plan mode waits for your review.` on stderr (#4247).
  A user config with `default_plan_mode = true` therefore no longer leaves an amicus run in Plan mode.
- A resumed session still in Plan mode prints a note to stderr and stays in Plan mode.
  amicus starts a fresh session on every run and refuses `-S/--session` and `-c/--continue`, so this is not reachable from amicus.
- Telemetry initialization now also records the resolved region and its source.
  It carries no prompt input.
- Listing trust-gated MCP servers now holds a lease on the workspace instance and releases it, rather than creating the instance outright; which servers it lists is unchanged.

How the prompt is read and how stream-json events are rendered (`runNativeTurn`) are unchanged.
As in 2.3.0, this establishes that the print path's own code is unchanged in those respects, not that every agent-core event it renders is.

`import-sessions` is wired into the CLI's subcommands and the TUI's `/import-sessions` only; nothing in the print path calls it.

## Release-note entries that bear on what amicus relies on

- Plan mode starts only when the user turns it on, the agent can no longer enter it by itself, and `kimi -p` skips `default_plan_mode` (#4247).
  amicus refuses `--plan`, and its read-only `--agent-file` tool list has no plan tools.
  A delegate run uses kimi's default agent, so after this change that agent can no longer put it in Plan mode, where its plan would wait for a review print mode cannot give.
- Agent swarms start only in swarm mode, so `AgentSwarm` is no longer available in `kimi -p` (2.3.2, #4384), and tasks are handled directly instead of by proactive subagents (2.3.2, #4386).
  A read-only run's tool list offers neither; a delegate run, on kimi's default agent, now does its task itself unless the task asks for delegation.
- A text a subagent wrote before it stopped is now passed back to the parent, marked incomplete (#4430).
  A read-only run's tool list has no subagent tool; on a delegate run this can change what the agent reports, not the shape amicus reads.
- Workspace MCP servers now reconnect with backoff (#4283).
  amicus scrubs `KIMI_CODE_TRUST_WORKSPACE` (#354), so project MCP servers stay trust-gated; reconnection applies only to servers that already load.
- The server's WebSocket approval and question events and endpoints are replaced by one `interaction` frame (#4428).
  That is the `kimi web` server, not the print path.
- Cross-tool imports stop importing standalone `.claude/AGENTS.md`, project `.codex/AGENTS.md`, `.codex/CLAUDE.md` and loose skill files (#4331).
  Those are what `kimi migrate` and `import-sessions` copy, not what a run loads.
- A session left locked by an exited process can be taken over, and the holding client is named in the error (2.3.1, #4348, #4356).
  Both outcomes need a resumed session, which amicus never runs.

## What the capture alone does not establish

Everything that needs a prompt: the stream-json event shape `normalize.py` reads, whether the read-only agent profile still reports exactly `Read`, `Glob` and `Grep`, whether `--agent-file` and `--session` are still incompatible, and the failure signatures in `contract.py`.
That the Plan-mode and lock outcomes are unreachable from amicus was read from the source, not observed.
The kimi live gate exercises most of these, and rule 5 reserves it for when the maintainer asks.
