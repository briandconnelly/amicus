# kimi-code 2.3.0 — amicus evidence

Captured 2026-10-22 on the maintainer's machine by running the binary, with the same probes as `docs/kimi-help/2.2.0/`: `kimi --version`, `kimi --help`, `kimi provider list --json`, `kimi session --help` and `kimi session list --all --json`.
No model call was made for this capture.
It was made because Kimi Code 2.3.0 was published on 2026-10-21, when `SUPPORTED_VERSIONS` stopped at `(2, 2)`.
The kimi live gate requires the installed version to equal the newest supported minor, so until `(2, 3)` was added no release evidence could pass on 2.3.0.
There was no release between 2.2.0 and 2.3.0.

## What the captures show

- `kimi-version.txt`: `2.3.0`.
- `kimi-help.txt`: byte-for-byte the 2.2.0 capture.
  No option or subcommand row changed.
  Every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still declared.
  `tests/test_kimi_contract.py` asserts those flags against this file as against every other capture under `docs/kimi-help/`.
- `provider-list-shape.json`: the same top-level keys, container types, seven model-entry keys and `model_count` as the 2.2.0 capture.
  Only key names and types were captured; provider details (API keys, base URLs) were never written to disk.

## Session persistence and rule 18

AGENTS.md rule 18 requires the carrier re-check on the CLI release an amicus release is validated against.
On 2.3.0:

- `kimi --help` gained no option, so no flag that turns a session off has appeared.
- `kimi session --help` still offers `list` only: no delete, and no way to suppress a session.
- `kimi session list --all --json` returns 211 sessions, each with a `sessionDir`, from the same store 2.2.0 read; it held 207 on 2026-10-17.
  Their contents were counted, not read, because rule 18 binds them.

`docs/RELEASING.md` also requires the release notes since the previous check.
All 22 entries of the 2.3.0 notes in `apps/kimi-code/CHANGELOG.md` were read.
None adds a flag, setting or environment variable that stops a session being kept, moves the store, or hands kimi its prompt without a file.
The English `configuration/env-vars.md`, `configuration/config-files.md` and `configuration/data-locations.md` were also compared between the 2.2.0 and 2.3.0 tags.
They add `KIMI_CODE_EXPERIMENTAL_TOWER`, the `disable_feedback_survey` and `[mcp] default_deferred` keys, a model `upgrade` field, a wider `dangerous_command_guard`, and a `locks/sessions/` directory beside `sessions/`.
The lock directory holds occupancy locks while a client writes a session, not the session's content; none of the rest concerns the session store.

So no documented or observed way to avoid the session-store carrier was found on 2.3.0, which is the condition rule 18 sets.
That is a statement about what was looked for and not found.
What this did not do is watch 2.3.0 write a session, since a run that creates one spends quota.

## The commits since 2.2.0

The `@moonshot-ai/kimi-code@2.2.0..@moonshot-ai/kimi-code@2.3.0` range has 33 commits and 469 changed files.
Under `apps/kimi-code/src/cli/` only two files changed:

- `cli/sub/provider.ts`, where a doc comment names the new home of the provider-model refresh; no code changed.
- `cli/v2/run-v2-print.ts`, the print path, changed by #4246 alone.

Of the four prompt-mode files `docs/kimi-help/2.1.0/FINDINGS.md` names, `options.ts`, `commands.ts` and `prompt-render.ts` are unchanged.
In `run-v2-print.ts`, #4246 adds a cross-process session occupancy lock:

- The turn now runs inside `reloadOnStale`, which reloads the session and runs it again when another client has updated it, printing `Session "<id>" was updated by another client; reloaded it.` to stderr.
- When another process holds the session, the run writes one `{"type":"error","code":...,"message":...,"details":...}` line to stdout under `stream-json` and exits with status 4.
- The goal path is split into creating the goal and running its turn, so a rerun after a reload does not create the goal twice.

Both new outcomes need a session that another client is writing.
amicus starts a fresh session on every run and refuses `-S/--session` and `-c/--continue`, so no other client holds the session it runs in, and neither outcome is reachable from amicus.
How the prompt is read and how stream-json events are rendered (`runNativeTurn`) are unchanged.
As in 2.2.0, this establishes that the print path's own code is unchanged in those respects, not that every agent-core event it renders is.

## Release-note entries that bear on what amicus relies on

- `dangerous_command_guard = false` now turns off the sensitive-file and git-control-path confirmations as well as the dangerous-command one (#4250).
  amicus does not set it, and the read-only posture rests on the `--agent-file` tool list, not on those confirmations, which print mode's auto permission skips anyway.
- Hooks such as `PreToolUse` and `Stop` now run in the session's project directory (#4242).
  The fix is in the server, not the CLI print path.
- Plugin skills are listed only under their qualified `<pluginId>:<skillName>` name (#4188).
  amicus never invokes a skill by name, and under `isolation="ignore-skills"` its `--skills-dir` points at an empty directory; a run that keeps skill discovery sees the user's plugin skills under the new names, which is the user's configuration rather than anything amicus sends.
- The automatic session title (#4200) is generated by the TUI only; the print path has no title code, so it adds no model call to an amicus run.
- The todo-list reminder now fires after 5 steps instead of 10, and asks the agent to update the list before its final reply (#4239).
  That can change what a run does, not the shape amicus reads.
- The default workspace for chats without a project (#4224, #4277) was reverted before the release (#4295).

## What the capture alone does not establish

Everything that needs a prompt: the stream-json event shape `normalize.py` reads, whether the read-only agent profile still reports exactly `Read`, `Glob` and `Grep`, whether `--agent-file` and `--session` are still incompatible, and the failure signatures in `contract.py`.
That neither occupancy outcome is reachable from amicus was read from the source, not observed.
The kimi live gate exercises most of these, and rule 5 reserves it for when the maintainer asks.
