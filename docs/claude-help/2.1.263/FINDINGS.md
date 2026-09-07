# Claude Code 2.1.263 — amicus M4 evidence

Captured 2026-09-07 on the maintainer's machine by running the binary (`claude --version`, `claude --help`).
No model call was made for this capture.
`claude auth status --text` was run only for its exit code; its output names the account and was not recorded.

## What the captures show

- `claude-version.txt`: `2.1.263 (Claude Code)`; major 2 is in `SUPPORTED_MAJORS`.
- `claude-help.txt`: every flag the amicus contract sends is advertised: `-p/--print`, `--output-format`, `--no-chrome`, `--append-system-prompt`, `--max-budget-usd`, `--no-session-persistence`, `--tools` (the help documents `""` as "disable all tools", the toolless mechanism), `--disallowed-tools`, `--strict-mcp-config`, `--mcp-config`, `--setting-sources`, `--safe-mode`, `--bare`, `--effort` (`low, medium, high, xhigh, max`) and `--model`.
  `tests/test_claude_contract.py` asserts this against the file, after first proving a known-absent control flag is not matched.
- `envelope-shape.json`: the key names of the recorded real `claude -p --output-format json` envelope (`is_error`, `subtype`, `result`, `session_id`, `total_cost_usd`, `usage`, `modelUsage`, `type`) and of its `usage` block (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`).
  The envelope itself is `tests/fixtures/claude_golden_envelope.json`, copied from claude-in-codex `tests/golden/claude_envelope.json`; `tests/test_claude_golden_envelope.py` drives it through the adapter and the loop.

## What is inherited, not re-verified here

The behavioural findings claude-in-codex documents in `COMPATIBILITY.md` and in its code comments (`--tools ""` grants no tools; `--tools Read,Grep,Glob` with `--disallowed-tools Edit,Write,NotebookEdit,Bash` is read-only but not a sandbox and `Read` accepts absolute paths; hooks in `.claude/settings*.json` run outside the tool allowlist under `inherit`/`scoped`; `--bare` reads only `ANTHROPIC_API_KEY`; errors ride a zero-exit envelope with `is_error`/`subtype`; `--max-budget-usd` is a best-effort stop threshold) are carried into the amicus contract unchanged.
They were not re-run as standalone probes on 2.1.263.
The live gate (`tests/test_claude_live.py`, run once in this milestone) re-checks the two guarantees it can observe from an answer: a toolless consult asked to list its tools names none, and a `config_mode=safe` consult completes.
Its outcome is recorded below after the run.

## Live gate outcome

(Filled in by Task 10.)
