# kimi-code 2.5.0 — amicus evidence

Captured 2026-11-08 on the maintainer's machine by running the binary, with the same probes as `docs/kimi-help/2.4.0/`: `kimi --version`, `kimi --help`, `kimi provider list --json`, `kimi session --help` and `kimi session list --all --json`.
The binary was installed from npm into a scratch prefix, not over the global install.
No model call was made for this capture.
It was made because Kimi Code 2.5.0 was published on 2026-11-04, when `SUPPORTED_VERSIONS` stopped at `(2, 4)` (#412).
The kimi live gate requires the installed version to equal the newest supported minor, so until `(2, 5)` was added no release evidence could pass on 2.5.x.
2.4.1 came between 2.4.0 and 2.5.0, and 2.5.1 and 2.5.2 after it; their notes were read with 2.5.0's.
The globally installed 2.5.2 was also probed: its `kimi --help` and `kimi session --help` are byte-identical to 2.5.0's, and its provider-list shape is the same.

## What the captures show

- `kimi-version.txt`: `2.5.0`.
- `kimi-help.txt`: identical to the 2.4.0 capture.
  2.5.0 adds `--environment <id>` and `--environment-cwd <path>` to the root command, but both are hidden from `--help` (see below).
  Every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still declared.
  `tests/test_kimi_contract.py` asserts those flags against this file as against every other capture under `docs/kimi-help/`.
- `provider-list-shape.json`: the same top-level keys and container types as the 2.4.0 capture, but 362 models instead of 2, and a different union of model-entry keys.
  `maxInputSize`, `maxOutputSize`, `offEffort` and `reasoningKey` appear, and `defaultEffort` appears on no entry.
  That difference is the maintainer's provider configuration, not the version.
  Between the 2.4.0 capture and this one the configured provider was switched from a self-hosted proxy to OpenRouter, and the 2.4.0 binary, installed into its own scratch prefix and run against today's configuration, produces a shape identical to 2.5.0's.
  Only key names, types and counts were captured; provider details (API keys, base URLs) were never printed or written to disk.

362 models is more than `MODELS_CACHE_MAX_ENTRIES` (256), so `parse_catalog` keeps only the first 256 aliases of this configuration.
That is a consequence of the configuration on any kimi version, not of 2.5.0, and is recorded here because this capture is where it was first seen.

## Session persistence and rule 18

AGENTS.md rule 18 requires the carrier re-check on the CLI release an amicus release is validated against.
On 2.5.0:

- `kimi --help` is unchanged from 2.4.0, so it gained no option.
- `kimi session --help` still offers `list` only: no delete, and no way to suppress a session.
- `kimi session list --all --json` returns 230 sessions, each with a `sessionDir`, from the same store 2.4.0 read; it held 221 on 2026-10-29.
  The session directories on disk number 230 as well, so 2.5.1's hiding of sessions that belong to deleted workspaces (#4678) hid none here.
  Their contents were counted, not read, because rule 18 binds them.

`docs/RELEASING.md` also requires the release notes since the previous check.
Every entry of the 2.4.1, 2.5.0, 2.5.1 and 2.5.2 notes in `apps/kimi-code/CHANGELOG.md` was read.
None adds a flag, setting or environment variable that stops a session being kept, moves the store, or hands kimi its prompt without a file.
The English `configuration/env-vars.md`, `configuration/config-files.md`, `configuration/overrides.md` and `configuration/data-locations.md` were also compared between the 2.4.0 and 2.5.2 tags; none changed between 2.5.0 and 2.5.2.
`data-locations.md` now keys a session directory by workspace id, which for a managed workspace is a generated `wm_<uuid>` rather than a hash of the path; the store's root is unchanged.
`overrides.md` renames "Runtime switches" to "Environment switches" and nothing else.
`env-vars.md` and `config-files.md` add `[database] global_search` and `KIMI_CODE_GLOBAL_SEARCH`, both off by default, add `[workspace] require_trust`, add `[environments]`, remove `[secondary_model] force`, lower the `[read]` `max_chars` default from 500,000 to 100,000, derive the plugin marketplace URL from the provider's base URL, and record that `local.toml` is no longer written.
`global_search` off means past sessions are no longer scanned into a full-text index by default (#4516); it governs an index built from the store, not whether a session is written.

So no documented or observed way to avoid the session-store carrier was found on 2.5.0, which is the condition rule 18 sets.
That is a statement about what was looked for and not found.
What this did not do is watch 2.5.0 write a session, since a run that creates one spends quota.

## The commits since 2.4.0

The `@moonshot-ai/kimi-code@2.4.0..@moonshot-ai/kimi-code@2.5.0` range has 69 commits and 1507 changed files; `2.5.0..2.5.2` has 8 commits and changes nothing under `apps/kimi-code/src/cli/`.
Under `apps/kimi-code/src/cli/`, the 2.5.0 changes outside the print path are the self-update path, telemetry, `acp`, the web server entry, a new hidden `exec-server` command (the remote-environment executor), `main.ts`, and the move of `createKimiCodeHostIdentity` from `version.ts` to `host-identity.ts`, which `export`, `fork`, `provider` and `session` follow with one import line each.
`session.ts` otherwise changes only the spelling of its control-character regex.

Of the four prompt-mode files `docs/kimi-help/2.1.0/FINDINGS.md` names, `prompt-render.ts` is unchanged.
`options.ts` adds `environment` and `environmentCwd` to the options and validates them: neither may be empty, `--environment-cwd` requires `--environment`, and `--environment` cannot be combined with `--session` or `--continue`.
`commands.ts` registers those two options as hidden, and registers the hidden `exec-server` command.
`run-v2-print.ts`, the print path, changed in two ways:

- It no longer calls the engine's `bootstrap()` itself; it builds an `SDKRpcClientV2` from `@moonshot-ai/kimi-code-sdk`, whose constructor calls `bootstrap()` with the same `homeDir`, identity, request headers, `nonInteractive`, `skillDirs` (`--skills-dir`) and `agentFiles` (`--agent-file`), and the same log seed, that 2.4.0 passed directly.
- A new session is created with `environmentId` and `environmentCwd` from those options.

How the prompt is read, how the trust-gated MCP warning is produced, and how stream-json events are rendered (`runNativeTurn`) are unchanged apart from taking the SDK client's service accessor in place of the app scope.
As in 2.4.0, this establishes that the print path's own code is unchanged in those respects, not that every agent-core event it renders is.

## Release-note entries that bear on what amicus relies on

- Remote environments (#4062): `[environments]` in the user's `config.toml` declares SSH, Docker or custom-command targets, and its optional `default` names the environment a session binds to when creation names none.
  The remote-environment guide says that default applies to "a cold start, print mode, or an API create", so with a `default` configured, a `kimi -p` run amicus starts would execute its tools on that target, in that entry's `defaultCwd`, not in the workspace or worktree amicus chose.
  A read-only run would then read a different tree, and a delegate run would edit files amicus never diffs.
  amicus sends no `--environment`, and the guide says that explicitly selecting `local` still creates a local session; whether amicus should send `--environment local` on 2.5 and later is left to its own change, since the flag is hidden and earlier versions reject it.
  This was read from the documentation and the option wiring, not observed: observing it needs a run, and a run spends quota.
- `[workspace] require_trust = false` in the user's `config.toml` treats every workspace as trusted (#4517).
  amicus scrubs `KIMI_CODE_TRUST_WORKSPACE` (#354) so that project-level MCP servers stay trust-gated, but that scrub does not reach this setting, and the documentation says a falsy `KIMI_CODE_TRUST_WORKSPACE` does not restore the gate when it is set.
  The setting is user-level only; a repository cannot set it.
- Model error messages are shown verbatim, and quota exhaustion is no longer inferred from message wording (#4477).
  `contract.py` classifies a rate limit by text (`429`, "rate limit", "too many requests", "quota exceeded"); whether a 2.5 provider error still carries one of those tokens in what kimi prints depends on the provider's own message and was not observed.
- A single file read returns at most 100,000 characters or about 25,000 tokens, down from 500,000 characters (2.4.1, #4553).
  A review over a large file may now need several reads; `[read] max_chars` raises the limit.
- The implicit `primary` subagent model choice is gone and `[secondary_model] force` is ignored with a warning (#4418).
  A read-only run's tool list has no subagent tool; on a delegate run this can change which model a subagent uses, not the shape amicus reads.
- Skills from every configured directory of a multi-directory project are merged (#4520).
  amicus refuses `--add-dir` and passes `--skills-dir`, which the print path still hands to the engine as an explicit replacement for discovery.
- The global full-text search index is off by default (#4516), and git status is never read through a `git` or `gh` executable inside the opened folder (#4649).
  Neither touches the print path's output.
- Built-in tool and subagent prompts, and repeated goal and Plan-mode reminders, are shorter (2.4.1, #4521), and incremental edits no longer require Edit over Bash `sed` (#4609).
  These change what the agent is told, not the stream amicus reads.
- The server's WebSocket frames and REST endpoints change in several entries (#4470, #4535, #4606).
  That is the `kimi web` server, not the print path.

## What the capture alone does not establish

Everything that needs a prompt: the stream-json event shape `normalize.py` reads, whether the read-only agent profile still reports exactly `Read`, `Glob` and `Grep`, whether `--agent-file` and `--session` are still incompatible, the failure signatures in `contract.py`, and whether a configured `[environments] default` moves an amicus run off the workspace.
The kimi live gate exercises most of these, and rule 5 reserves it for when the maintainer asks; the maintainer's `config.toml` sets no `[environments]` table and no `require_trust`, which was checked by counting those keys, not by reading the file.
