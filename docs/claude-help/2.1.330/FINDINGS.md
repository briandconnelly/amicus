# claude 2.1.330 — amicus evidence

Captured 2026-11-21 on the maintainer's machine by `scripts/check_backend_compat.py --write`, which runs `claude --version`, `claude --help` and the free login probe and nothing else.
No model call was made for this capture.
2.1.330 needs no support change, since `SUPPORTED_MAJORS` admits every 2.x release; it was captured because `check_backend_compat.py watch` filed #524 for 2.1.329, and 2.1.330 was the installed and newest release when the capture ran.
2.1.326 through 2.1.329 came between 2.1.325 and 2.1.330, and were not captured.

## What the capture shows

- `claude-version.txt`: `2.1.330`.
- `claude-help.txt`: the 2.1.325 capture with the same flags and subcommands, and many descriptions reworded.
  The rewording that touches a flag amicus sends changes no meaning: `--append-system-prompt`, `--model`, `--no-session-persistence` and `--tools` say the same thing in plainer words.
  `--bare` and `--safe-mode` now say the hooks of an organization's managed plugins still run, and `--safe-mode` now also starts no plugin language servers.
  Every flag amicus sends is still declared, which `tests/test_claude_contract.py` asserts against this file as against every other capture under `docs/claude-help/`.

## Release-note entries that bear on what amicus relies on

The `CHANGELOG.md` entries for 2.1.326 through 2.1.330 in `anthropics/claude-code` were read for the print-mode surface amicus sends: `-p --output-format json`, `--tools`, `--disallowed-tools`, `--no-session-persistence`, `--max-budget-usd`, `--effort`, `--model`, `--append-system-prompt`, the MCP and settings-source flags, `--safe-mode` and `--bare`.
None removes or changes the meaning of one of those flags, and none moves the prompt onto argv or into a file.

- `claude -p` whose output went to a file on a full disk now prints an error and exits 1 instead of exiting 0 with no message (2.1.330).
  That turns a silent failure into a nonzero exit, which amicus already classifies as a failure.
- Some `--disallowedTools` rules with parentheses in their content were fixed (2.1.327).
  amicus's `--disallowed-tools` value is plain tool names, with no parentheses.
- A startup warning now names an `--allowedTools`, `--disallowedTools` or `--tools` entry that does not look like a complete rule (2.1.326).
  amicus's values are complete tool names.
- `claude -p` no longer hangs before its first request when fetching a model's settings stalls; it goes on without them after 10 seconds (2.1.327).
- `claude -p` now shows retries of an overloaded or failing request on the terminal, including when its output is captured (2.1.326).
  The entry does not say which stream carries it; amicus reads the result from stdout as json.
- Managed-settings plugins from a git marketplace load sooner on a fresh machine in `claude -p`, and a short run may exit up to 30 seconds later (2.1.328).
- `-p` runs fewer git commands before the first request (2.1.327).

## What the capture alone does not establish

Everything that needs a prompt: the JSON result envelope `normalize.py` reads, the budget-stop envelope `docs/claude-help/2.1.274/` records, and the failure signatures in `contract.py`.
The release-note entries above were read, not observed.
The claude live gate exercises those, and rule 5 reserves it for when the maintainer asks.
