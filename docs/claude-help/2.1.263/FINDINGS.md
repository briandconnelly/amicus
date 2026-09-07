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

Run once on 2026-09-07 under the maintainer's authorization: `AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_claude_live.py -v`.
Result: 5 passed, 1 failed in 146 s.
No raw model text and no account details are recorded here.

| Test | Outcome |
| --- | --- |
| `test_backends_reports_claude_ready_live` | passed (installed, authenticated, version `2.*`, no warnings; static model catalog non-empty) |
| `test_consult_in_a_repo_spends_and_reports_it_live` | passed (structured consult, `meta.usage.cost_usd > 0`, `backend_details` exactly `config_mode=inherit`, `access=toolless`, `max_budget_usd=1.0`) |
| `test_toolless_is_enforced_live` | passed (asked to name its tools, the answer named none of `bash`, `write`, `edit`, `read`, `glob`, `grep`, `shell`) |
| `test_review_changes_live` | FAILED with `code=invalid_json`, `temporary=true` (see below) |
| `test_adversarial_review_live` | passed (`review_status=completed`, verdict in the enum, `context_summary` null, no `instructions_append` on meta, non-empty findings/questions/next_steps) |
| `test_safe_mode_consult_live` | passed (`config_mode=safe` completed and is echoed on `backend_details`) |

The one failure is a model-quality failure, not a contract failure, and it was reported rather than retried.
On that call the model ignored the requested JSON output schema and answered with a hallucinated tool-invocation block in prose, even though the run was toolless and no tool call could have been made.
`orchestration.finalize._parse_reviewed` refused the answer as designed — shape-strict, never a prose downgrade — and returned the `invalid_json` envelope with `temporary=true`, so the advertised repair is to retry the call.
No spend limit, rate limit, permission denial or contract-drift signal was involved, and the toolless guarantee held on the call that probes it directly.
The behaviour to watch in M5 is how often a toolless Claude review answers with tool-call prose instead of the schema; a retry is the current remedy.
