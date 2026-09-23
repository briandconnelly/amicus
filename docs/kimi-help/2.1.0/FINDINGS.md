# kimi-code 2.1.0 — amicus evidence

Captured 2026-09-23 on the maintainer's machine by running the binary, with the same probes as `docs/kimi-help/2.0.2/`: `kimi --version`, `kimi --help`, `kimi provider list --json`, `kimi session --help` and `kimi session list --all --json`.
No model call was made for this capture.
It was made because Kimi Code 2.1.0 was published on 2026-09-23, when `SUPPORTED_VERSIONS` stopped at `(2, 0)` (#227).
The kimi live gate requires the installed version to equal the newest supported minor, so until `(2, 1)` was added no release evidence could pass on 2.1.0.

## What the captures show

- `kimi-version.txt`: `2.1.0`.
- `kimi-help.txt`: identical to the 2.0.2 capture.
  2.1.0 prints one extra trailing blank line, which the repository's end-of-file hook strips from the committed file; no subcommand, option row or wording changed.
  Every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still declared.
  `tests/test_kimi_contract.py` asserts those flags against this file as against every other capture under `docs/kimi-help/`.
- `provider-list-shape.json`: the same top-level keys (`models`, `providers`), container types and seven model-entry keys as the 2.0.2 capture, the shape `models.parse_catalog` reads.
  `model_count` is 2 rather than 1 because the maintainer's `config.toml` now declares a second model alias, the route the 2.0.2 live gate used; it counts configuration, not anything the CLI changed.
  Only key names and types were captured; provider details (API keys, base URLs) were never written to disk.

## Session persistence and rule 18

AGENTS.md rule 18 requires the carrier re-check on the CLI release an amicus release is validated against.
On 2.1.0:

- `kimi --help` gained no option, so no flag that turns a session off has appeared.
- `kimi session --help` still offers `list` only: no delete, and no way to suppress a session.
- `kimi session list --all --json` returns 145 sessions, each with a `sessionDir`, from the same store 2.0.2 read; it held 127 on 2026-09-19.
  Their contents were counted, not read, because rule 18 binds them.

`docs/RELEASING.md` also requires the release notes since the previous check.
All 21 entries of the 2.1.0 notes were read.
None adds a flag, setting or environment variable that stops a session being kept, moves the store, or hands kimi its prompt without a file.
One new setting concerns the store without changing that: `auto_session_title = false` (MoonshotAI/kimi-code#3962) stops clients generating session titles, and a session is still kept.

So no documented or observed way to avoid the session-store carrier was found on 2.1.0, which is the condition rule 18 sets.
That is a statement about what was looked for and not found.
What this did not do is watch 2.1.0 write a session, since a run that creates one spends quota.

## The commits since 2.0.2

The compare between the `@moonshot-ai/kimi-code@2.0.2` and `@moonshot-ai/kimi-code@2.1.0` tags has 24 commits.
GitHub's compare API stops listing files at 300, so each commit's files were listed separately: 402 file changes in all.
That listing finds the two files MoonshotAI/kimi-code#3964 is known to change (`tool/realpath-access.ts`, `os/read/readTool.ts`), so it is not blind.

In the 2.1.0 source, prompt mode and its stream-json output live in `apps/kimi-code/src/cli/options.ts`, `cli/commands.ts`, `cli/prompt-render.ts` and `cli/v2/run-v2-print.ts`, found by searching the repository for `stream-json`.
No commit since 2.0.2 changes any of them.
The only files changed under `apps/kimi-code/src/cli/` are `run-shell.ts`, where #3969 stops a telemetry shutdown error aborting the interactive shell's exit, and `sub/web/run.ts`.

The commits whose files mention the wire journal, transcripts or sessions were read by file list:

- #3966 adds an optional `durationMs` to a payload in the on-disk `wire.jsonl` journal, and #3938 adds step timing to the transcript; amicus reads neither.
- #3970 and #3974 change how swarm members and fork titles are restored from a session, which amicus never resumes.
- #3957 fixes a stack overflow in the local web server's transcript cache.

The stream-json lines are rendered from the agent core's events, and the agent core did change; so this establishes that the print path's own code is untouched, not that every event it renders is.

## Release-note entries that bear on what amicus relies on

MoonshotAI/kimi-code#3964 hardens workspace trust boundaries, and three of its entries touch what amicus relies on.

- "Block file tools from accessing files outside the working directory through symlinks."
  Read, Glob, Grep, Write, Edit and ReadMediaFile now resolve a path's real target.
  A path inside the workspace whose target lies outside it is refused, and so is any path whose target matches a sensitive-file pattern (env, credential, SSH key).
  A path that is already outside the workspace is still allowed: the guard mode is `absolute-outside-allowed`, and `assertRealPathWithinWorkspace` returns such a path unchanged unless its target is sensitive.
  So the kimi `readonly_honesty` disclosure, that the Read tool accepts absolute paths and no workspace is a read boundary, stays true.
  2.1.0 narrows it only by refusing a path whose real target matches a sensitive-file pattern, and amicus does not claim that as a boundary either.
- "Apply project-local configuration only after the workspace is trusted."
  `.kimi-code/local.toml` and its `additional_dir` entries now take effect only in a trusted workspace.
  amicus neither writes nor relies on that file, so a repository that ships one can widen kimi's reach less than before, not more.
- "Reject additional directories that resolve to the home directory or filesystem root."
  This bounds `--add-dir` and `additional_dir`; amicus never sends `--add-dir`.

Two further entries are switches amicus does not set:

- `KIMI_CODE_REPEAT_BREAKER=0` turns off the reminders and forced stops kimi applies to repeated identical tool calls; unset, the existing behaviour stays on.
- Filesystem watchers are now off by default (`[watch] enabled`, `KIMI_CODE_WATCH`), which 2.0.1 had only made possible.

## What the capture alone does not establish

Everything that needs a prompt: the stream-json event shape `normalize.py` reads, whether the read-only agent profile still reports exactly `Read`, `Glob` and `Grep`, whether `--agent-file` and `--session` are still incompatible, and the failure signatures in `contract.py`.
The commit review above makes a change there unlikely, but it read file lists and a few diffs, not every line of the agent core.
The kimi live gate exercises most of these, and rule 5 reserves it for when the maintainer asks.
