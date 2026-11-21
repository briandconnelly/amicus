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

## The RPC model listing (issue #554)

Probed on 2026-11-21 for issue #554, to find a source for model prices, which the `--list-models` table does not carry.
Every run used the suppression flags and `--offline`, sent no prompt and made no model call.
Apart from the first run, which read the maintainer's own configuration, every run used a scratch `PI_CODING_AGENT_DIR`, an empty working directory and fake provider keys in the environment.

- `rpc-models-shape.txt`: the keys of one model object from the reply, with the count of rows carrying each key in the 36-provider run below; it records names only, never a value.
- `echo '{"type":"get_available_models"}' | pi --mode rpc --no-session` with the suppression flags printed exactly one stdout line, `{"type":"response","command":"get_available_models","success":true,"data":{"models":[...]}}`, and exited 0 at stdin EOF in about 0.2 seconds with empty stderr.
  The command and the model object are documented in `docs/rpc-commands.md` of `@earendil-works/pi-coding-agent`, which states that costs are in US dollars per million tokens.
- Every row carried `id`, `provider`, `contextWindow` and `maxTokens` as exact integers, and `cost` with `input`, `output`, `cacheRead` and `cacheWrite`; some carried `cost.tiers`, at most two on a row, each with `inputTokensAbove` and the same four rates.
  `calculateCost` in `dist/models.js` of `@earendil-works/pi-ai` selects a tier by `usage.input + usage.cacheRead + usage.cacheWrite`, taking the highest `inputTokensAbove` that sum exceeds, so cached tokens count toward the threshold.
  Over 1 332 rows the table's `context` and `max-out` cells agreed with those integers under `formatTokenCount`, with no mismatch.
- The slug set, `provider` joined to `id` with `/`, was identical to the table's in every configuration compared: no credentials, one, two and 36 providers credentialed by fake keys, a `models.json` adding a custom provider, a `models.json` with `modelOverrides`, and three malformed `models.json` files.
  A provider without credentials was hidden by both.
- The row order differs.
  The table sorts by provider and then id with `localeCompare`; the reply is unsorted, with built-in providers first and `models.json` providers after them in file order.
  amicus therefore keeps the table as the authority on which rows exist and in what order, and reads the reply only for the fields the table lacks.
- With 36 providers credentialed the reply was one line of 752 807 bytes for 1 332 rows, the largest model object 952 bytes, and no slug appeared twice.
- With no credentialed provider the reply was `success: true` with `models: []`, where the table prints `No models available` and no header.
- The reply is framed by a line feed alone, and `JSON.stringify` leaves U+2028 and U+2029 unescaped inside a string, so a reader must split on `\n` and not on every Unicode line separator.
- With empty stdin, `/dev/null` or a closed stdin, pi exited 0 and printed nothing, so the absence of a reply is a failure to read rather than an empty catalog.
  Unparseable input was answered with `{"type":"response","command":"parse","success":false,...}`.
- A `models.json` model with no `cost` was reported with all four rates `0`, exactly as a free model is, so a zero price cannot be read as free.
- A `models.json` that fails its schema is reported on stderr by the table and not at all by the reply; both then list the same reduced set.
- The fake `apiKey` and header values placed in `models.json` and the environment appeared nowhere in the reply, which does carry each model's `baseUrl`.
  In the 36-provider run some built-in rows carried a `headers` object of fixed client identifiers and a `providers[].credential` field naming a credential source, neither holding a key; amicus reads none of them.
- Neither command wrote to the working directory or created a session; the first run of either in a fresh agent directory created `auth.json` and `models-store.json`, each `{}`.
- Under `sandbox-exec` with `(deny network*)` the reply was byte-identical to the unsandboxed one, with and without `--offline`.
  That shows the listing needs no network; it does not show that no connection was attempted.
- A working directory holding `.pi/commands/` was migrated to `.pi/prompts/` by the RPC command as by `--list-models`, so it too must run from amicus's probe directory.
- pi 1.5.0 and 1.5.2, installed from npm into a scratch directory, answered the same request with the same reply shape, exit status and row keys, and their slug sets matched their own tables.

Not tested: a provider that discovers or refreshes its models at run time, an OAuth-credentialed provider, the listing with network allowed and no `--offline`, and whether the table's order changes with the locale.
The reply is built from `getAvailableSnapshot()` and the table from `await getAvailable()`, so the first two are where the two sets could differ.

## Advertised reasoning levels (issue #559)

`getSupportedThinkingLevels` in `node_modules/@earendil-works/pi-ai/dist/models.js` of the 1.6.0 install, lines 702-713, returns `off` alone for a model whose `reasoning` is falsy.
Otherwise it keeps each of `off`, `minimal`, `low`, `medium`, `high`, `xhigh` and `max` unless the model's `thinkingLevelMap` maps it to `null`, and keeps `xhigh` and `max` only when the map names them.
`clampThinkingLevel`, lines 714-732, keeps a supported level, searches upward from the requested level for a supported one, then downward, and falls back to the first supported level or `off`.
amicus's `advertised_efforts` follows the first function, and ADR 0052 records where it is stricter: only a literal `true` for `reasoning`, and a map that is present and not an object is unknown.
This was read from the source only; no live call tested which level a provider actually ran.

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
- Whether `models.json` existed during these captures and the live suite was not recorded at the time, so it is unknown.
