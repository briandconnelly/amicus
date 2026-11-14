# claude 2.1.325 — amicus evidence

Captured 2026-11-14 on the maintainer's machine by `scripts/check_backend_compat.py --write`, which runs `claude --version`, `claude --help` and the free login probe and nothing else.
No model call was made for this capture.
2.1.325 needs no support change, since `SUPPORTED_MAJORS` admits every 2.x release; it was captured because `check_backend_compat.py watch` filed #452 for it, and the claude watch's baseline is the newest capture under `docs/claude-help/`.
2.1.321, 2.1.322 and 2.1.323 came between 2.1.319 and 2.1.325, and were not captured.

## What the capture shows

- `claude-version.txt`: `2.1.325`.
- `claude-help.txt`: the 2.1.319 capture with one row reworded.
  `rm` now says it removes a background session from the list and keeps its conversation for `claude --resume`, rather than deleting the session.
  amicus never runs `rm`.
  Every flag amicus sends is still declared, which `tests/test_claude_contract.py` asserts against this file as against every other capture under `docs/claude-help/`.

## Release-note entries that bear on what amicus relies on

The `CHANGELOG.md` entries for 2.1.321 through 2.1.325 in `anthropics/claude-code` were read for the print-mode surface amicus sends: `-p --output-format json`, `--tools`, `--disallowed-tools`, `--no-session-persistence`, `--max-budget-usd`, `--effort`, `--model`, `--append-system-prompt`, the MCP and settings-source flags, `--safe-mode` and `--bare`.
None removes or changes the meaning of one of those flags, and none moves the prompt onto argv or into a file.

- Long tool results no longer stay on disk after a run with `--no-session-persistence`; they are removed on normal exit, Ctrl+C or SIGTERM (2.1.323).
  Before this release such results could outlive a run despite the flag.
  A tool result is the backend's output rather than a prompt input under rule 18, and the fix narrows what the flag leaves behind; a run killed with SIGKILL may still leave them.
- `claude -p` on Linux now exits 1 with an error, in text and json output, when a full NFS export or used-up quota lost transcript lines (2.1.321).
  That turns a silent failure into a nonzero exit, which amicus already classifies as a failure.
- `claude -p` now warns on stderr, in text output, when settings block the requested `--model` and another is used (2.1.323).
  The entry names text output only; amicus requests json and reads the model actually used from `modelUsage`.
- `--max-budget-usd` and the cost metrics now count a mod's `$.model.complete` and `$.model.classify` calls (2.1.325).
  That can only make the reported `total_cost_usd` larger and the budget stop earlier.
- `claude -p` and SDK runs now stop at start-up, naming the setting, when `--settings` or SDK settings that turn the sandbox on fail validation (2.1.323), and start-up stops when a `--settings` file with a `sandbox` key is not valid JSON (2.1.323).
  amicus does not pass `--settings`.
- `claude -p` with no cached account data now waits for it before its first request (2.1.325), so a first run in a clean environment can start a few seconds later.
- `-p` runs in a worktree or submodule mounted into a container apply `.claude/settings.local.json` allow rules only once the folder is trusted (2.1.325).
  That makes allow rules stricter, not looser.

## What the capture alone does not establish

Everything that needs a prompt: the JSON result envelope `normalize.py` reads, the budget-stop envelope `docs/claude-help/2.1.274/` records, and the failure signatures in `contract.py`.
The release-note entries above were read, not observed.
The claude live gate exercises those, and rule 5 reserves it for when the maintainer asks.
