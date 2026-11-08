# claude 2.1.319 — amicus evidence

Captured 2026-11-08 on the maintainer's machine by `scripts/check_backend_compat.py --write`, which runs `claude --version`, `claude --help` and the free login probe and nothing else.
No model call was made for this capture.
2.1.319 needs no support change, since `SUPPORTED_MAJORS` admits every 2.x release; it was captured because `check_backend_compat.py watch` filed #407 for it, and the claude watch's baseline is the newest capture under `docs/claude-help/`.
2.1.314, 2.1.316, 2.1.317 and 2.1.318 came between 2.1.312 and 2.1.319, and were not captured.

## What the capture shows

- `claude-version.txt`: `2.1.319`.
- `claude-help.txt`: the 2.1.312 capture with one row reworded.
  `auto-mode` now reads "Inspect or reset auto mode configuration" rather than naming the classifier.
  amicus never runs `auto-mode`.
  Every flag amicus sends is still declared, which `tests/test_claude_contract.py` asserts against this file as against every other capture under `docs/claude-help/`.

## Release-note entries that bear on what amicus relies on

The `CHANGELOG.md` entries for 2.1.314 through 2.1.319 in `anthropics/claude-code` were read for the print-mode surface amicus sends: `-p --output-format json`, `--tools`, `--disallowed-tools`, `--no-session-persistence`, `--max-budget-usd`, `--effort`, `--model`, `--append-system-prompt`, the MCP and settings-source flags, `--safe-mode` and `--bare`.
None removes or changes the meaning of one of those flags.

- `claude -p` JSON results add `credential_expires_at`, the date a stored claude.ai sign-in ends (2.1.318).
  `normalize.py` reads the envelope's keys with `dict.get`, so an added key changes nothing it reads.
  The matching stderr warning is for text output only, which amicus never requests.
- Several failures that used to exit 0 now exit 1 with an error: a failed startup (2.1.314), lost transcript or `~/.claude.json` writes on a full disk or quota (2.1.317), and actions refused in auto mode for want of a safety check (2.1.319).
  These turn silent failures into nonzero exits, which amicus already classifies as failures.
- A non-interactive launch now fails rather than replacing a `~/.claude.json` that is not valid JSON (2.1.318).
  That is a new failure a broken user config can produce; it surfaces as a nonzero exit.
- A settings file excluded with `--setting-sources` no longer supplies auto-mode rules and saved permission consents (2.1.314).
  That makes the scoped mode's exclusion stricter, not looser.
- `claude -p` run inside a cloud or self-hosted runner session no longer shares that session's ID or transcript (2.1.317); `CLAUDE_CODE_DISABLE_NESTED_SESSION_ID=1` restores the old behavior.
  amicus sends `--no-session-persistence` and does not set that variable.
- Custom slash commands that fail no longer print nothing in `claude -p` (2.1.318), and `claude -p` and SDK sessions no longer report success when an API error cut off a reply while a mod hooked `turn.step` (2.1.318).
  Both remove a false success rather than adding a failure shape.

## What the capture alone does not establish

Everything that needs a prompt: the JSON result envelope `normalize.py` reads, the budget-stop envelope `docs/claude-help/2.1.274/` records, and the failure signatures in `contract.py`.
The release-note entries above were read, not observed.
The claude live gate exercises those, and rule 5 reserves it for when the maintainer asks.
