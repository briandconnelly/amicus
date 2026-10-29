# claude 2.1.312 — amicus evidence

Captured 2026-10-29 on the maintainer's machine by `scripts/check_backend_compat.py --write`, which runs `claude --version`, `claude --help` and the free login probe and nothing else.
No model call was made for this capture.
2.1.312 needs no support change, since `SUPPORTED_MAJORS` admits every 2.x release; it was captured because `check_backend_compat.py watch` filed #393 for it, and the claude watch's baseline is the newest capture under `docs/claude-help/`.
2.1.309, 2.1.310 and 2.1.311 came between 2.1.308 and 2.1.312, and were not captured.

## What the capture shows

- `claude-version.txt`: `2.1.312`.
- `claude-help.txt`: the 2.1.308 capture with one row reworded.
  `purge` now says it deletes a project's Claude Code data, including its entry in `~/.claude.json`, from this computer only.
  amicus never runs `purge`.
  Every flag amicus sends is still declared, which `tests/test_claude_contract.py` asserts against this file as against every other capture under `docs/claude-help/`.

## Release-note entries that bear on what amicus relies on

The `CHANGELOG.md` entries for 2.1.309 through 2.1.312 in `anthropics/claude-code` were read for the print-mode surface amicus sends: `-p --output-format json`, `--tools`, `--disallowed-tools`, `--no-session-persistence`, `--max-budget-usd`, `--effort`, `--model`, `--append-system-prompt`, the MCP and settings-source flags, `--safe-mode` and `--bare`.
None removes or changes the meaning of one of those flags.

- `--output-format json` and `stream-json` now write DEL, C1 control and Unicode format characters inside strings as `\uXXXX` escapes, with parsed values unchanged (2.1.310).
  `normalize.py` parses the envelope as JSON, so what it reads is unchanged.
- A command with an invalid name no longer stops every command from loading, which could leave `claude -p` with no output (2.1.312).
  That removes an empty-output failure rather than adding one.
- Requests the API marked not to retry are no longer retried (2.1.310), which can end a failing turn sooner.
- `claude -p` sessions no longer save transcript messages out of order (2.1.311).
  amicus always sends `--no-session-persistence`, so no transcript is written.

## What the capture alone does not establish

Everything that needs a prompt: the JSON result envelope `normalize.py` reads, the budget-stop envelope `docs/claude-help/2.1.274/` records, and the failure signatures in `contract.py`.
The release-note entries above were read, not observed.
The claude live gate exercises those, and rule 5 reserves it for when the maintainer asks.
