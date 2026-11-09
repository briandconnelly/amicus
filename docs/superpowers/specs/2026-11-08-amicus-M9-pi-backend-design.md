# M9: the pi backend

Issue #423.
Decided with the maintainer on 2026-11-08.

## Why

The kimi model amicus uses (`moonshotai/kimi-k3`, through OpenRouter) is reachable from [pi](https://github.com/badlogic/pi-mono), so the only thing unique to the `kimi` backend is the Kimi Code harness.
Pi carries the prompt on stdin and can run without a session store, which the kimi CLI cannot, so a `pi` backend needs none of the rule-18 carrier exemptions `kimi` holds.
Neither CLI has a sandbox: on both, read-only means a tool allowlist, and delegate writes are not confined by the worktree.

M9 adds `pi` at `kimi`'s parity.
Retiring `kimi` is out of scope: it follows a paid A/B of the two harnesses on the same model and a one-release deprecation window, each its own change under #423.

## Scope

- A `pi` backend under `src/amicus/backends/pi/` behind the existing `BackendPlugin` seam, serving `consult`, `review_changes` and `delegate` and their `_async` twins and dry runs.
- `pi` joins `BACKEND_IDS` and `DelegateBackendId`, and so the default profile; `adversarial_review` stays `claude`-only.
- A fourth live suite, `tests/test_pi_live.py`, and the release tooling that records and checks it.
- Captured CLI evidence for pi 1.5.0 under `docs/pi-help/1.5.0/`.

Out of scope: any change to `kimi`; a `backend_options` key for `pi`; an `AMICUS_PI_EXTRA_ARGS` passthrough; adversarial review on `pi`.

## The invocation

Every run is one process:

```
<pi> -p --mode json --no-session --no-context-files --no-skills --no-extensions --no-mcp
     --no-prompt-templates --no-themes --no-approve --offline
     --system-prompt <PI_SYSTEM_PROMPT> --append-system-prompt ""
     --tools <tier tools> --model <provider>/<id> [--thinking <level>]
```

with the whole prompt on stdin and `cwd` set to the workspace or the delegate worktree.

- Read-only tier (consult, review): `--tools read,grep,find,ls`.
- Write tier (delegate): `--tools read,bash,edit,write,grep,find,ls`.
- `PI_SYSTEM_PROMPT` is a fixed amicus literal, so argv carries no prompt input.
  Pi reads a file when the value names an existing path, so the literal contains no `/` and is longer than 255 bytes: it is then a single path component longer than any filesystem allows, and cannot exist relative to any working directory.
- `--append-system-prompt ""` is required: without it, a user-level `APPEND_SYSTEM.md` reaches the provider.
- The child environment adds `PI_TELEMETRY=0` and `PI_SKIP_VERSION_CHECK=1` and drops `PI_CODING_AGENT_SESSION_DIR`; provider credentials and `PI_CODING_AGENT_DIR` are inherited, because they are what authenticate the run.
- The framing, any `instructions_append` section and the structured-output instruction are composed into the stdin prompt the way the kimi adapter composes its prompt file.

The zero-spend probe on #423 verified each flag's effect on 1.5.0 against a fake OpenAI-compatible provider, including a negative control in which a hostile workspace's extension ran, its tools and system prompt were applied and a session file was written to a path it chose, none of which happened under these flags.

## Model and reasoning effort

- `AMICUS_PI_MODEL` is the default model; a call's `model` overrides it.
- Both take an exact `provider/id`.
- With neither set, the call is refused before spending, as `invalid_arguments` on field `model`, because pi's own default comes from ambient settings and fuzzy matching.
- Before spending, the model is checked in two free steps, because `pi --list-models` lists only models of providers that have credentials:
  1. `pi auth check --model <model> --json --no-refresh` resolves the provider, including a provider id that itself contains `/`; an unresolvable model is `invalid_model`, and `not_ready` or `invalid` is `pi_auth_required`.
  2. With the provider ready, `pi --list-models <id>` must hold a row whose provider column and model column join to exactly `<model>`; no exact row, or a listing that could not be read, is `invalid_model`.
- Pi sends an unknown id anyway, so this check fails closed, unlike kimi's.
- A model that begins with `-` or `@` is refused as `invalid_model` before either step, because the probes pass the model to pi as a bare argument, which pi would read as a flag or a file.
- When the binary cannot be resolved, or the first probe finds it missing, validation skips both probes, so the run reports `backend_not_found` rather than a model error; the checks that need no probe, such as the effort's place in the vocabulary below, still run.
- `AMICUS_PI_REASONING_EFFORT` is the default effort; a call's `reasoning_effort` overrides it; with neither, `--thinking` is not sent.
- An effort must be one of `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, and only `off` is accepted for a model whose catalog row says `thinking: no`.
- Pi clamps an effort the model does not support, so when the final message's `thinkingLevel` differs from the requested one, the result carries a warning naming both.

## Reading the result

`--mode json` writes JSONL events to stdout.

- The answer is the text content of the last `message_end` whose message has `role: "assistant"`.
- `usage` sums `input`, `output`, `cacheRead` and `cacheWrite` over every assistant `message_end`, counting each response once; `turn_end` and `agent_end` repeat those messages and are not counted.
- `cost_usd` is reported only when `usage.cost.totalFromProvider` is true, because otherwise pi computed it from its own price table.
- `session_id` is the `session` event's `id`, opportunistic metadata as on the other backends.
- The stream echoes the system prompt and the user message, so it is held in memory only, like every backend's stream.

## Failure

- **A provider failure exits 0.**
  When the last assistant message has `stopReason: "error"`, the outcome inspector classifies it from `errorMessage` and stderr: auth, rate limit and invalid model by pattern, and anything else as `nonzero_exit` with the sanitized message.
  Pi retries a failing request three times on its own before reporting it.
- A zero-exit run with no assistant text and no error is `empty_response`, as on kimi.
- A last assistant message with `stopReason: "length"` was cut off at the model's output-token limit, so the adapter marks its answer `answer_loss: "truncated"` and amicus withholds it as `answer_unavailable`, prose or structured, even when the cut-off text parses as complete JSON.
- `Model "<id>" not found` on stderr is classified as `invalid_model`, a backstop behind the pre-spend check.
- A rejected flag is `cli_contract_changed`.

## Readiness

- Installed: `pi --version` prints a version.
- Authenticated: `pi auth check --model <AMICUS_PI_MODEL> --json --no-refresh`; `ready` is true, `not_ready` and `invalid` are false, anything else is unknown.
  With no `AMICUS_PI_MODEL`, authentication is unknown and `amicus_backends` says that calls must pass `model`.
  `--no-refresh` keeps discovery from refreshing, and so writing, OAuth credentials.
- Supported versions: `(1, 5)`, advisory, overridable by `AMICUS_PI_SUPPORTED_VERSIONS`.
- The help probe expects every flag in the invocation above in `pi --help`.
- Pi builds its runtime and loads resources before it handles `--help` or `--list-models`, so every probe that can load resources (`--help`, `--list-models`) carries the same resource-suppression flags as a run: `--no-context-files --no-skills --no-extensions --no-mcp --no-prompt-templates --no-themes --no-approve --offline`.
- The login hint names pi's interactive `/login <provider>` or the provider's API-key environment variable; pi 1.5.0 has no `pi auth login`.

## Disclosures

- **egress:** the prompt and, for reviews, the secret-redacted diff go to the provider the model's prefix names, through pi; pi can read files outside the workspace, up to everything the OS user can read.
- **carriers:** the prompt rides stdin; argv carries only amicus's fixed system prompt, the model, the effort and flags; with `--no-session` pi wrote no session file on 1.5.0 after a success, a provider failure or a SIGTERM mid-request.
- **readonly honesty:** read-only means pi has no shell, edit or write tool; it does not confine reads, it is no OS sandbox, and it does not stop pi's startup rename of `.pi/commands/` below.
- **implicit context:** pi adds the working directory to its system prompt; user-level settings, `models.json` (whose `!command` key values pi runs) and credentials load; context files, skills, extensions, MCP, prompt templates, themes and trust-gated project resources do not; a project `sessionDir` setting is read before trust is resolved, and under `--no-session` nothing was written there on 1.5.0.
  At startup pi renames the workspace's `.pi/commands/` to `.pi/prompts/` when the latter does not exist (`runMigrations(cwd)`, before it handles anything but `--version` and `pi auth`), so a consult or review in such a repository changes it; amicus cannot suppress this, and runs its own free probes (`--help`, `--list-models`, `auth check`, `--version`) from its state directory so that they never do.

## Release

- Rule 20 grows a fourth suite, `tests/test_pi_live.py`, and rule 18's text names no pi exemption.
  Both change in a governance PR of their own (rule 9).
- This milestone's PR makes the release tooling require the pi suite: `scripts/record_live_gate_evidence.py`, `scripts/check_release_state.py`, the spend notice in `scripts/release.py`, and `scripts/check_backend_compat.py`, including its `watch` streams.
  Tooling stricter than rule 20's text is harmless, and the reverse is not, so the milestone PR merges first and the governance PR immediately after it, with no release between the two merges.
- `FINGERPRINT` moves once, in its own commit with the regenerated pins (rule 10); `RESULT_FORMAT` does not move, because no stored result shape changes.

## Gate

The rule-2 gate green; `tests/test_pi_contract.py` passes against the 1.5.0 captures after a perturbed capture fails it; `tests/test_pi_live.py` passes under rule 5 on the branch head, run by the maintainer.
The four-suite requirement binds the next release, under rule 20, not this milestone.
