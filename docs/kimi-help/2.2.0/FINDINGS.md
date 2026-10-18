# kimi-code 2.2.0 — amicus evidence

Captured 2026-10-17 on the maintainer's machine by running the binary, with the same probes as `docs/kimi-help/2.1.0/`: `kimi --version`, `kimi --help`, `kimi provider list --json`, `kimi session --help` and `kimi session list --all --json`.
No model call was made for this capture.
It was made because Kimi Code 2.2.0 was published on 2026-10-14, when `SUPPORTED_VERSIONS` stopped at `(2, 1)`.
The kimi live gate requires the installed version to equal the newest supported minor, so until `(2, 2)` was added no release evidence could pass on 2.2.0.
This record covers 2.1.1 as well, the one release between 2.1.0 and 2.2.0, which `(2, 1)` already admitted without a check of its own.

## What the captures show

- `kimi-version.txt`: `2.2.0`.
- `kimi-help.txt`: the 2.1.0 capture plus one subcommand row, `app [path]`, which opens a chat in the Kimi Code desktop app (MoonshotAI/kimi-code#4145).
  No option row changed.
  Every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still declared.
  `tests/test_kimi_contract.py` asserts those flags against this file as against every other capture under `docs/kimi-help/`.
- `provider-list-shape.json`: the same top-level keys, container types, seven model-entry keys and `model_count` as the 2.1.0 capture.
  Only key names and types were captured; provider details (API keys, base URLs) were never written to disk.

## Session persistence and rule 18

AGENTS.md rule 18 requires the carrier re-check on the CLI release an amicus release is validated against.
On 2.2.0:

- `kimi --help` gained no option, so no flag that turns a session off has appeared.
- `kimi session --help` still offers `list` only: no delete, and no way to suppress a session.
- `kimi session list --all --json` returns 207 sessions, each with a `sessionDir`, from the same store 2.1.0 read; it held 145 on 2026-09-23.
  Their contents were counted, not read, because rule 18 binds them.

`docs/RELEASING.md` also requires the release notes since the previous check.
Both entries of the 2.1.1 notes and all 27 entries of the 2.2.0 notes were read.
None adds a flag, setting or environment variable that stops a session being kept, moves the store, or hands kimi its prompt without a file.
The English `configuration/env-vars.md` and `configuration/config-files.md` were also compared between the 2.1.0 and 2.2.0 tags.
They add `KIMI_CODE_TRUST_WORKSPACE` and `KIMI_CODE_LLM_HEADERS_TIMEOUT_MS`, flip the watcher default, and drop the local.toml trust paragraph; none of that concerns the session store.

So no documented or observed way to avoid the session-store carrier was found on 2.2.0, which is the condition rule 18 sets.
That is a statement about what was looked for and not found.
What this did not do is watch 2.2.0 write a session, since a run that creates one spends quota.

## The commits since 2.1.0

The compare between the `@moonshot-ai/kimi-code@2.1.0` and `@moonshot-ai/kimi-code@2.2.0` tags has 40 commits, with 729 file changes listed commit by commit.
That listing finds the files MoonshotAI/kimi-code#4145 is known to change (`cli/commands.ts`, `cli/sub/app.ts`), so it is not blind.

Of the four prompt-mode files `docs/kimi-help/2.1.0/FINDINGS.md` names, two changed:

- `apps/kimi-code/src/cli/commands.ts`, where #4145 registers the `app` subcommand.
- `apps/kimi-code/src/cli/v2/run-v2-print.ts`, where #4059 adds `KIMI_CODE_TRUST_WORKSPACE=1` to the wording of the warning printed when an untrusted folder's project-level MCP servers are skipped.

Neither change touches how the prompt is read or how the stream-json lines are written.
As in 2.1.0, this establishes that the print path's own code is unchanged in those respects, not that every agent-core event it renders is.

## 2.1.1 rolled back the 2.1.0 trust hardening

MoonshotAI/kimi-code#4013 ("Roll back some of the overly defensive changes in 2.1.0") removed all three of the #3964 entries that `docs/kimi-help/2.1.0/FINDINGS.md` describes:

- `tool/realpath-access.ts` is deleted, so Read, Glob, Grep, Write, Edit and ReadMediaFile no longer resolve a path's real target or refuse one whose target is outside the workspace or matches a sensitive-file pattern.
- `.kimi-code/local.toml` and its `additional_dir` entries take effect whether or not the workspace is trusted, and the config-files page no longer says otherwise.
- `additional_dir` entries that resolve to the home directory or the filesystem root are accepted again.

The 2.2.0 tag still lacks all three: `realpath-access.ts` is absent there while `path-access.ts` beside it is present, and `projectLocalConfigService.ts` has no `isBroadScopeDir`, which the 2.1.0 tag's copy has.
amicus relied on none of them.
The kimi `readonly_honesty` disclosure, that the Read tool accepts absolute paths and no workspace is a read boundary, was true with the symlink guard and is true without it.
amicus never writes `.kimi-code/local.toml` or sends `--add-dir`, and with no sandbox in prompt mode an `additional_dir` widens nothing Bash could not already reach.

## Release-note entries that bear on what amicus relies on

- `KIMI_CODE_TRUST_WORKSPACE` (#4059) marks the workspace trusted for one process without writing a trust record.
  In a trusted workspace kimi loads the repository's project-level MCP servers (`.mcp.json`, `.kimi-code/mcp.json`); in an untrusted one, such as a fresh delegate worktree, it skips them and prints the warning above.
  amicus passes kimi the caller's environment unchanged (`KimiBackend.scrub_env`), so a server started with this variable set would load the project-level MCP servers of every repository it runs kimi in.
  amicus does not set it.
  Since #354, amicus drops it from the environment of every paid kimi run, whatever its value, so a server started with it set no longer passes that trust on.
- The agent's in-turn wait for background tasks is capped at 90 seconds (#4061).
  This bounds a wait inside one turn, not the run, which amicus's own deadline still bounds.
- `executor = "kaos"` is removed from MCP stdio server configuration (#4184), and a config that uses it now fails validation at load time.
  amicus writes no MCP configuration; an operator config that used it would fail the run, and the failure is the operator's to fix.
- Tower mode lets a message sent mid-turn abort the running turn (#3998, #4074); prompt mode receives no mid-turn message.
- Filesystem watchers are on by default again (2.1.1, #4015), as they were before 2.1.0.

## What the capture alone does not establish

Everything that needs a prompt: the stream-json event shape `normalize.py` reads, whether the read-only agent profile still reports exactly `Read`, `Glob` and `Grep`, whether `--agent-file` and `--session` are still incompatible, and the failure signatures in `contract.py`.
Whether project-level MCP servers start when amicus runs kimi in a trusted workspace was read from the source, not observed.
The kimi live gate exercises most of these, and rule 5 reserves it for when the maintainer asks.
