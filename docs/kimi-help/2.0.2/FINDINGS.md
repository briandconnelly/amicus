# kimi-code 2.0.2 — amicus evidence

Captured 2026-09-19 on the maintainer's machine by running the binary (`kimi --version`, `kimi --help`, `kimi provider list --json`), the same three probes as `docs/kimi-help/0.43.1/`, plus `kimi session --help` and `kimi session list`.
No model call was made for this capture.
It was made because the release precondition added in #188 has the maintainer run `kimi upgrade` before recording release evidence, and that took Kimi Code from 0.43.1 to 2.0.2 (#202).
The kimi live gate requires the installed version to equal the newest supported minor, so 0.5.0's evidence run could not pass until `(2, 0)` was supported.

## The version jump

Kimi Code went from 0.43.1 to 2.0.2 in one upgrade.
No 1.x shipped: the project's GitHub releases (`MoonshotAI/kimi-code`) run 0.43.0, 0.43.1, 2.0.0, 2.0.1, 2.0.2, published 2026-09-14 to 2026-09-19.
PyPI's `kimi-cli` is a different distribution, and its 1.50.0 says nothing about Kimi Code.
So `SUPPORTED_VERSIONS` gains `(2, 0)` and no `(1, *)`.
The major number overstates the change: 2.0.0's only "Major Changes" entry is a `/desktop` slash command and an `install-app` subcommand that open the desktop app's page.

## What the captures show

- `kimi-version.txt`: `2.0.2`.
- `kimi-help.txt`: every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still declared as an option.
  The only difference from the 0.43.1 capture is one new subcommand, `install-desktop`, which amicus never invokes; no option row was added or removed.
  `tests/test_kimi_contract.py` asserts the flags against this file and every other capture under `docs/kimi-help/`, after first proving a known-absent control flag is not matched.
  `scripts/check_backend_compat.py` reports the same, by declared option rows.
- `provider-list-shape.json`: byte-identical to the 0.43.1 capture, an object with `models` and `providers` maps whose model entry carries `supportEfforts` (the shape `models.parse_catalog` reads).
  Only key names and types were captured; provider details (API keys, base URLs) were never written to disk.

## Session persistence and rule 18

AGENTS.md rule 18 requires the carrier re-check on the CLI release an amicus release is validated against.
On 2.0.2:

- `kimi --help` gained no option, so no flag that turns a session off has appeared.
- `kimi session --help` still offers `list` only: no delete, and no way to suppress a session.
- `kimi session list --all --json` returns the 127 sessions that were under `~/.kimi-code/sessions` before the upgrade, each with a `sessionDir`, so 2.0.2 reads the same store at the same place.
  Their contents were counted, not read, because rule 18 binds them.

`docs/RELEASING.md` also requires the release notes since the previous amicus release, because a setting documented only there would not show in any of those probes.
All 49 entries of the 2.0.0, 2.0.1 and 2.0.2 notes were read, and searched for sessions, persistence, history, transcripts, prompt mode and tools, after confirming the search finds an entry known to be there.
None adds a flag, setting or environment variable that stops a session being kept, moves the store, or hands kimi its prompt without a file.
Two entries concern the store without changing that: 2.0.1 compacts the session index when entries point to deleted sessions, and fixes "deleting or archiving a session sometimes never finishing", so deletion exists somewhere in the product, while `kimi session` on the command line still offers `list` only.
Deleting afterwards is not avoiding the carrier, and no non-interactive route to it was found.

So no documented or observed way to avoid the session-store carrier was found on 2.0.2, which is the condition rule 18 sets.
That is a statement about what was looked for and not found; it is not an observation that the carrier behaves as it did on 0.43.1.
What this did not do is watch 2.0.2 WRITE a session, since a run that creates one spends quota; that it still does is inferred from the store, the subcommand and the help all being unchanged.

## Release-note entries that bear on what amicus relies on

None changes a flag or a file amicus uses, and each is behaviour only a prompt can exercise, so they are listed for whoever reads the live gate's result.

- 2.0.1: "Remove the system-prompt rule that forbade all file access outside the working directory."
  amicus's `readonly_honesty` for kimi already says its Read tool accepts absolute paths and that no workspace is a read boundary, so the disclosure stays true and the model is now less discouraged from doing it.
- 2.0.2: "The agent no longer assumes the current working directory is the project root."
  amicus runs kimi with the worktree or workspace as its cwd.
- 2.0.1: "Fix `kimi -p` exiting early and cancelling the active turn when a cron task fires."
  `-p` is the mode amicus uses.
- 2.0.1: "Stop workspace file watchers from scanning an unbounded project root, and add `[watch] enabled` / `KIMI_CODE_WATCH` to disable watching entirely."

## What is not established here

Everything that needs a prompt, which is where a major version is likeliest to move: the stream-json event shape `normalize.py` reads (the version line, assistant events, the `session.resume_hint`), whether the read-only agent profile still reports exactly `Read`, `Glob` and `Grep`, whether `--agent-file` and `--session` are still incompatible, and the failure signatures in `contract.py`.
The behavioural findings carried from moonbridge's 0.39.1 probes, listed in `docs/kimi-help/0.41.0/FINDINGS.md`, were not re-run.

## Live gate outcome

Not run as part of this capture.
AGENTS.md rule 5 reserves the live suites for when the maintainer asks, and the PR that adds this file asks the maintainer to run `tests/test_kimi_live.py` on its branch before merging, because a zero-spend check says the CLI's surface held, not that its behaviour did.
If that run happens, its outcome belongs in this section.
It would still not be rule-20 release evidence, which `scripts/record_live_gate_evidence.py` records against the release commit itself.
