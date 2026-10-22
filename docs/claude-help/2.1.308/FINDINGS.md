# claude 2.1.308 — amicus evidence

Captured 2026-10-22 on the maintainer's machine by `scripts/check_backend_compat.py --write`, which runs `claude --version`, `claude --help` and the free login probe and nothing else.
No model call was made for this capture.
2.1.308 needs no support change, since `SUPPORTED_MAJORS` admits every 2.x release; it was captured because its `--help` declares a flag the 2.1.278 capture does not, `--desktop`, which no capture had recorded since `check_backend_compat.py` first reported it on 2.1.302 on 2026-10-17.

## What the capture shows

- `claude-version.txt`: `2.1.308`.
- `claude-help.txt`: the 2.1.278 capture with one option added, `--desktop`, one subcommand replaced, and description wording changed on rows amicus does and does not send.
  Every flag amicus sends is still declared, which `tests/test_claude_contract.py` asserts against this file as against every other capture under `docs/claude-help/`.

## The changes against 2.1.278

- `--desktop` opens the session in the Claude Desktop app instead of the terminal.
  amicus never sends it, and it is an interactive-session option that print mode has no use for.
- `--bare`, which amicus sends under `config_mode="bare"`, now says which hooks it skips: those defined in settings and by installed plugins, while features built into Claude Code are unaffected.
  That narrows the wording, not what amicus relies on, which is that no user or project hook runs.
- `--system-prompt-snapshot` now defaults to off under `--bare` outside cloud and background sessions.
  amicus does not send the flag; the change affects whether the rendered system prompt is reused across requests, not what it contains.
- `--agents` accepts, under `--print`, the path to a file that holds the agents' JSON as well as the JSON itself.
  amicus does not send `--agents`.
- `--json-schema` is now documented as working only with `--print`, `--disable-slash-commands` as disabling commands as well as skills, `--restricted` no longer names REPL among the tools it removes, `--resume` accepts a session name, and `--tools "default"` is described as the default set rather than all tools.
  amicus sends `--tools` only with an explicit list (`""` or `Read,Grep,Glob`), so the `default` wording does not reach it.
- The `project` subcommand is replaced by `purge`, which deletes all Claude Code state for a project; `attach` and `logs` accept a session name; and `update` notes that package-manager installs update through the package manager.

## What the capture alone does not establish

Everything that needs a prompt: the JSON result envelope `normalize.py` reads, the budget-stop envelope `docs/claude-help/2.1.274/` records, and the failure signatures in `contract.py`.
The claude live gate exercises those, and rule 5 reserves it for when the maintainer asks.
