# pi 1.6.0 — amicus evidence

Captured 2026-11-20 on the maintainer's machine by running the binary, to check the latest pi release against the 1.5.0 contract.
No model call was made for the captures; the live suite below did spend quota.

## What the captures show

- `pi-version.txt`: `1.6.0`.
- `pi-help.txt`: from `pi --help` with the resource-suppression flags, as for 1.5.0 and 1.5.2.
  Against `../1.5.2/pi-help.txt` it differs only in its environment-variable list: the two Qwen Token Plan keys are replaced by four (team and individual, each with an international and a China region), and the output gained a trailing blank line, which the repository's end-of-file hook stripped from the capture.
  Every flag the amicus contract sends is still advertised with the same text, and the `--thinking` vocabulary is unchanged.
- `list-models-shape.txt`: the first four lines of `pi --list-models kimi-k3` with the suppression flags.
  The columns are unchanged; trailing whitespace was stripped.
- `formatTokenCount` in `dist/cli/list-models.js` of `@earendil-works/pi-coding-agent` is byte-identical to 1.5.2's, so `amicus.backends.pi.models.tokens` still decodes the same rounded display format, within the rounding error that 1.5.2's findings state; the catalog does not expose exact limits.
- `pi auth check --json --no-refresh --model openrouter/moonshotai/kimi-k3` printed `{"status":"ready","provider":"openrouter","authType":"oauth"}` and exited 0, the shape amicus reads.

- The events the spend cap gates on (#454) were re-read in the installed 1.6.0 release on 2026-11-20.
  Every line of `dist/core/agent-session.js` that names `auto_retry_start`, `compaction_start`, `compaction_end` or `willRetry` is identical to 1.5.2's.
  The rest of that file's diff concerns tool loadouts on reload, extension rebinding and which reply `getLastAssistantText` returns; amicus runs pi with `--no-extensions` and `--no-session` and reads none of them.
  `usage.cost.totalFromProvider` is still set to `true` only in `dist/utils/openrouter-cost.js` of `@earendil-works/pi-ai`.

## The live suite

`tests/test_pi_live.py`, run as `AMICUS_REQUIRE_LIVE=1 AMICUS_PI_MODEL=openrouter/moonshotai/kimi-k3 uv run pytest -m integration --no-cov tests/test_pi_live.py`, passed its four paid tests on pi 1.6.0, including `test_delegate_stops_at_the_budget_cap_live`.
`test_backends_reports_pi_ready_live` failed in that run only because it requires the installed minor to be the newest in `SUPPORTED_VERSIONS`, which was still `(1, 5)`; it was re-run after the bump recorded beside this file.
This is a compatibility check, not rule-20 release evidence.

## A precondition the first run hit

The first run failed every paid test with an OpenRouter 402, and pi 1.5.2 failed the same call the same way, so it is not a 1.6.0 change.
pi requests the model's whole output limit as `max_tokens` (943 718 for kimi-k3, per OpenRouter's model listing; `--list-models` shows it rounded as `943.7K`), and OpenRouter refuses a request whose worst-case cost exceeds the account balance, here about $15 at $16 per million output tokens.
A live run on kimi-k3 therefore needs a balance above that worst case, whatever the run actually spends.

## What was not tested

- The zero-spend probe on issue #423 was not repeated on 1.6.0, so the flags' effects are inferred from the unchanged help and the passing live suite.
- No `find` comparison of `~/.pi` was taken for this capture.
- The budget-cap test holds only the `message_end` path; the retry and compaction gates rest on the source reading above.
