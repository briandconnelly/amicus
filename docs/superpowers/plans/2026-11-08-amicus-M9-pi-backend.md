# M9 pi backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pi` backend at `kimi`'s parity (consult, review_changes, delegate) behind the existing `BackendPlugin` seam.

**Architecture:** A new package `src/amicus/backends/pi/` mirrors `src/amicus/backends/kimi/` file for file (`contract`, `config`, `binary`, `options`, `models`, `cli`, `normalize`, `adapter`, `status`, `__init__`), with the prompt on stdin, a hardened fixed flag set, an exact `provider/id` model validated before spending, and exit-0 provider failures caught by the outcome inspector.
Unit tests drive a stand-in executable, `tests/support/fake_pi.py`, never the real CLI.

**Tech Stack:** Python, FastMCP, the in-tree `amicus.sdk`, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-08-amicus-M9-pi-backend-design.md` (issue #423).

## Global Constraints

- Work in `~/projects/amicus-wt-m9-pi` on `feat/m9-pi`; one draft PR (rule 7).
- The gate is rule 2 of `AGENTS.md`; a task is done only when it passes.
- Never change `AGENTS.md`, `CLAUDE.md` or `.github/**` here (rule 9): the rule-18 and rule-20 text changes ride a separate governance PR, merged before this one.
- No prompt input reaches argv, disk or a log (rule 18); the only argv text is the literal `PI_SYSTEM_PROMPT`.
- Commit scope for backend code is `backends`; for docs, `docs`; for the release scripts, `release`.
- Never run `-m integration` without the maintainer's go-ahead in the session (rule 5).
- Supported pi versions: `{(1, 5)}`.
- Reasoning-effort vocabulary: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
- Read-only tools: `read,grep,find,ls`; write tools: `read,bash,edit,write,grep,find,ls`.
- Child environment: set `PI_TELEMETRY=0` and `PI_SKIP_VERSION_CHECK=1`; drop `PI_CODING_AGENT_SESSION_DIR`.

## Review Focus

- A configured `AMICUS_PI_MODEL` whose provider is not authenticated: `amicus_backends` must report `authenticated: false`, and a paid call must fail as `backend_auth_required`, not `nonzero_exit` (Task 6, Task 8).
- A model id that is a fuzzy match but not an exact row (`moonshotai/kimi-k3` without its `openrouter/` prefix): refused pre-spend as `invalid_model`, never passed through (Task 3, Task 6).
- A provider failure after pi's own three retries: the result must be a classified failure, never `ok: true` with an empty answer, even though pi exits 0 (Task 5, Task 6).
- A stream with several assistant turns (tool calls before the answer): the answer is the last assistant text, and usage counts each response once (Task 5).
- A `PI_SYSTEM_PROMPT` edit that turns it into something path-shaped: a contract test asserts it contains a newline and does not exist as a path (Task 1).

---

### Task 1: Captured evidence and the contract module

**Files:**
- Create: `docs/pi-help/1.5.0/pi-version.txt`, `docs/pi-help/1.5.0/pi-help.txt`, `docs/pi-help/1.5.0/list-models-shape.txt`, `docs/pi-help/1.5.0/FINDINGS.md`
- Create: `src/amicus/backends/pi/__init__.py` (empty docstring only for now), `src/amicus/backends/pi/contract.py`
- Test: `tests/test_pi_contract.py`

**Interfaces:**
- Produces in `contract.py`: `PI_BIN = "pi"`; `PI_SYSTEM_PROMPT: str`; `READ_ONLY_TOOLS = ("read", "grep", "find", "ls")`; `WRITE_TOOLS = ("read", "bash", "edit", "write", "grep", "find", "ls")`; `HARDENING_FLAGS: tuple[str, ...]` (every flag in the spec's invocation that takes no value, in that order); `ALWAYS_SEND_FLAGS: tuple[str, ...]` (the long flags the help probe must find, including `--system-prompt`, `--append-system-prompt`, `--tools`, `--model`, `--mode`); `THINKING_FLAG = "--thinking"`; `EFFORTS: tuple[str, ...]` (the vocabulary, in order); `VERSION_ARGS`, `HELP_ARGS`, `LIST_MODELS_FLAG = "--list-models"`, `AUTH_CHECK_ARGS = ("auth", "check")`; `SUPPORTED_VERSIONS = frozenset({(1, 5)})`; `SANDBOX_READ_ONLY`, `SANDBOX_WORKSPACE_WRITE` (same labels as kimi); `RUN_ENV_SET: dict[str, str]`; `RUN_ENV_DROP: tuple[str, ...]`; the predicates `is_auth_failure`, `is_rate_limited`, `parse_retry_after_ms`, `is_invalid_model`, `is_contract_drift` (same signatures as kimi's); the disclosure strings `READ_ONLY_HONESTY`, `IMPLICIT_CONTEXT_DISCLOSURE`, `EGRESS`, `CARRIERS` (spec → Disclosures, verbatim in meaning); and `CONTRACT: BackendContract` with `backend_id="pi"`, `display_name="Pi"`, `env_prefix="AMICUS_PI_"`, `supported_features={"delegate", "model_validation", "empty_response_detection"}`, `structured_output="prompt_append"`, `isolation_policy=WORKTREE_ALL_TIERS`, `needs_orphan_sweep=True`, `effort_silently_ignored_upstream=True`, and a `ModelCatalog(strategy="live_probe", model_identifier_authority="authoritative", effort_metadata_authority="advisory")`.

- [ ] **Step 1: Capture the evidence (zero spend)**

Run `pi --version > docs/pi-help/1.5.0/pi-version.txt` and `pi --help > docs/pi-help/1.5.0/pi-help.txt` from a scratch directory, then `pi --list-models kimi-k3 | head -4 > docs/pi-help/1.5.0/list-models-shape.txt`.
Before committing, confirm none of the three holds a credential, a home path or a provider URL.
Write `FINDINGS.md` summarizing the #423 probe in the format of `docs/kimi-help/0.43.1/FINDINGS.md`: what was run, what each capture shows, and what was not tested; one sentence per line (rule 16).
Record there whether `pi --help` wrote any file (compare `find ~/.pi -newer <marker>` before and after); if it did, the help probe in Task 7 runs with `--offline`.

- [ ] **Step 2: Write the failing tests**

```python
def test_every_sent_flag_is_in_every_capture():  # parametrized over docs/pi-help/*/pi-help.txt
    help_text = capture.read_text()
    assert "--definitely-not-a-pi-flag" not in help_text  # negative control first
    for flag in (*contract.HARDENING_FLAGS, *contract.ALWAYS_SEND_FLAGS, contract.THINKING_FLAG):
        assert flag in help_text

def test_system_prompt_cannot_be_read_as_a_path():
    assert "\n" in contract.PI_SYSTEM_PROMPT
    assert not Path(contract.PI_SYSTEM_PROMPT).exists()

def test_read_only_tools_cannot_write_or_run():
    assert not {"bash", "edit", "write"} & set(contract.READ_ONLY_TOOLS)

def test_efforts_match_the_captured_thinking_flag():
    for level in contract.EFFORTS:
        assert level in help_text_of_newest_capture

def test_disclosures_name_no_kimi_mechanism():
    for text in (contract.CARRIERS, contract.EGRESS, contract.READ_ONLY_HONESTY):
        assert "handshake" not in text and "sandbox" not in text.replace("no OS sandbox", "")
```

Also port `tests/test_kimi_contract.py`'s pattern tests for the five predicates, with inputs taken from the probe: `"Connection error."` matches none of them; `"401 Unauthorized"` is auth; `"429 Too Many Requests"` is rate-limited; `'Warning: Model "nope" not found for provider "fake". Using custom model id.'` is an invalid model.

- [ ] **Step 3: Run them and see them fail** — `uv run pytest tests/test_pi_contract.py -q`; expected: import error for `amicus.backends.pi.contract`.

- [ ] **Step 4: Implement `contract.py`** so every test passes.

- [ ] **Step 5: Run the tests**, then perturb one capture (delete `--no-session` from a copy under `tmp_path` via a parametrized test of the checker) and confirm the flag test fails on it; run the gate.

- [ ] **Step 6: Commit** — `feat(backends): add the pi CLI contract and its 1.5.0 captures`.

### Task 2: Configuration, binary and options

**Files:**
- Create: `src/amicus/backends/pi/config.py`, `src/amicus/backends/pi/binary.py`, `src/amicus/backends/pi/options.py`
- Test: `tests/test_pi_config.py`, `tests/test_pi_binary.py`

**Interfaces:**
- Consumes: `contract.SUPPORTED_VERSIONS`, `contract.PI_BIN`.
- Produces: `ENV: EnvNamespace` with `AMICUS_PI_BIN`, `AMICUS_PI_MODEL`, `AMICUS_PI_REASONING_EFFORT`, `AMICUS_PI_SUPPORTED_VERSIONS` (no `removed=` tombstones); `PiConfig(bin_override, model, reasoning_effort, supported_versions, state_dir, warnings, errors)`; `load_config(environ) -> PiConfig`; `parse_version(str | None) -> tuple[int, int] | None`; `version_supported(str | None, PiConfig) -> bool | None`; `provider_of(model: str | None) -> str | None` (the text before the first `/`, or None when there is no `/`); `PiBinary(config)` with `resolve() -> str | None` and `override_error() -> str | None`, and `BinaryNotFoundError`; `options_for(config) -> tuple[OptionSpec, ...]` with only `model` and `reasoning_effort` entries for `{"consult", "review_changes", "delegate"}`.

- [ ] **Step 1: Write the failing tests**, porting `tests/test_kimi_config.py` and `tests/test_kimi_binary.py` with these added:

```python
def test_model_without_a_provider_prefix_warns():
    cfg = load_config({"AMICUS_PI_MODEL": "kimi-k3"})
    assert any("provider/id" in w for w in cfg.warnings)

def test_provider_of():
    assert provider_of("openrouter/moonshotai/kimi-k3") == "openrouter"
    assert provider_of("kimi-k3") is None and provider_of(None) is None

def test_no_isolation_option():
    assert {o.name for o in options_for(load_config({}))} == {"model", "reasoning_effort"}
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the three modules**, keeping kimi's precedence, never-raise and value-free-message rules.
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): add pi configuration and binary resolution`.

### Task 3: The model catalog

**Files:**
- Create: `src/amicus/backends/pi/models.py`
- Test: `tests/test_pi_models.py`

**Interfaces:**
- Consumes: `PiConfig`, `PiBinary`, `contract.LIST_MODELS_FLAG`.
- Produces: `parse_table(stdout: str) -> ModelListing | None` (header row `provider model context max-out thinking images`; each row becomes `ModelEntry(slug=f"{provider}/{model}", supported_reasoning_efforts=EFFORTS if thinking == "yes" else ("off",))`; `None` when the header is missing); `PiModels(config, binary)` with `read(force=False) -> ModelListing` (full listing, `--offline`, cached `HELP_CACHE_TTL_SECONDS`, capped at 1024 entries with `truncated`) and `lookup(slug: str) -> ModelEntry | None | Literal["unreadable"]`, which runs `pi --list-models <id-part> --offline` and returns the row whose slug equals `slug` exactly, `None` when the listing was read and has no exact row, and `"unreadable"` when the probe failed.

- [ ] **Step 1: Write the failing tests** against the captured `docs/pi-help/1.5.0/list-models-shape.txt`:

```python
def test_parse_captured_table():
    listing = parse_table(CAPTURE.read_text())
    assert "openrouter/moonshotai/kimi-k3" in [m.slug for m in listing.models]

def test_lookup_is_exact_not_fuzzy(fake_listing):  # rows for openrouter/moonshotai/kimi-k3 and ...:batch
    assert lookup("moonshotai/kimi-k3") is None
    assert lookup("openrouter/moonshotai/kimi-k3").slug == "openrouter/moonshotai/kimi-k3"

def test_lookup_unreadable_when_probe_fails():
    assert lookup_with_exit_code(1) == "unreadable"

def test_no_thinking_model_accepts_only_off():
    assert parse_table(ROW_WITH_THINKING_NO).models[0].supported_reasoning_efforts == ("off",)

def test_no_matches_message_is_an_empty_listing():
    assert parse_table('No models matching "x"\n') is None
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `models.py`** with `runtime.run_sync_capture` as kimi does.
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): read pi's model catalog`.

### Task 4: Reading the event stream

**Files:**
- Create: `src/amicus/backends/pi/normalize.py`
- Test: `tests/test_pi_normalize.py`, with stream fixtures written inline from synthetic literals in the shape of the #423 probe's `--mode json` output.

**Interfaces:**
- Produces: `final_assistant(events: str) -> dict | None` (the last `message_end` event's `message` with `role == "assistant"`); `extract_final_message(events) -> str | None` (that message's `text` parts joined, or None when it has none); `final_error(events) -> str | None` (its `errorMessage` when `stopReason == "error"`); `thinking_level(events) -> str | None`; `parse_event_metadata(events) -> tuple[Usage | None, str | None]`; `lost_after_final_message(events) -> bool` (same meaning as kimi's); `parse_structured(text) -> dict | None` (kimi's, reused by import).

- [ ] **Step 1: Write the failing tests:**

```python
def test_answer_is_last_assistant_text_after_tool_turns(): ...
def test_usage_counts_each_response_once():  # two assistant message_end + their turn_end/agent_end echoes
    usage, _ = parse_event_metadata(STREAM)
    assert (usage.input_tokens, usage.output_tokens) == (123 + 200, 45 + 60)
def test_cost_only_when_from_provider():  # totalFromProvider false -> cost_usd None; true -> the total
def test_cache_tokens_map_to_cached_input_and_cache_creation(): ...
def test_error_stop_reason_exposes_message():
    assert final_error(RETRIED_ERROR_STREAM) == "Connection error."
def test_session_id_from_session_event(): ...
def test_garbage_lines_degrade_metadata_not_the_answer(): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `normalize.py`**; tolerate unknown event types and non-JSON lines.
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): parse pi's json event stream`.

### Task 5: Command, environment, probes and the failure classifier

**Files:**
- Create: `src/amicus/backends/pi/cli.py`
- Test: `tests/test_pi_cli.py`

**Interfaces:**
- Consumes: Task 1's contract, Task 4's `final_error`.
- Produces: `build_exec_command(*, pi_bin: str, read_only: bool, model: str, thinking: str | None) -> list[str]` (the spec's invocation exactly, with no prompt text); `build_run_env(base: dict[str, str]) -> dict[str, str]`; `pi_version(binary) -> str | None`; `version_display(str | None) -> str | None`; `auth_status(binary, provider: str | None) -> bool | None` (`pi auth check --provider <p> --json --no-refresh`; never passes `--credentials`); `classify_failure(run: CommandRun, *, error_message: str | None, sanitize) -> ClassifiedFailure` with kimi's order (binary missing → timeout → drift → auth → rate limit → invalid model → `nonzero_exit`) and codes `pi_not_found`, `timeout`, `cli_contract_changed`, `pi_auth_required`, `pi_rate_limited`, `invalid_model`, `nonzero_exit`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_read_only_argv():
    argv = build_exec_command(pi_bin="/PI", read_only=True, model="openrouter/m", thinking=None)
    assert argv[argv.index("--tools") + 1] == "read,grep,find,ls"
    assert argv[argv.index("--append-system-prompt") + 1] == ""
    assert "--thinking" not in argv and "--no-session" in argv and "--no-approve" in argv

def test_write_argv_has_bash_and_thinking(): ...
def test_run_env_sets_and_drops():
    env = build_run_env({"PI_CODING_AGENT_SESSION_DIR": "/x", "OPENROUTER_API_KEY": "k"})
    assert env["PI_TELEMETRY"] == "0" and "PI_CODING_AGENT_SESSION_DIR" not in env
    assert env["OPENROUTER_API_KEY"] == "k"

def test_auth_status_maps_ready_not_ready_invalid_and_garbage(): ...  # True, False, False, None
def test_auth_status_without_provider_is_unknown_and_spawns_nothing(): ...
def test_classifier_reads_the_exit_zero_error_message():
    f = classify_failure(run(exit_code=0), error_message="401 Unauthorized", sanitize=None)
    assert f.code == "pi_auth_required"
def test_generic_detail_is_sanitized_before_the_cut(): ...  # port kimi's straddle test
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `cli.py`.**
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): build pi runs and classify their failures`.

### Task 6: The adapter

**Files:**
- Create: `src/amicus/backends/pi/adapter.py`
- Test: `tests/test_pi_adapter.py`, plus `tests/support/pifixtures.py` (`make_backend(environ, catalog, version)` pinning the binary to `/PI`, like `kimifixtures.make_backend`)

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `PiBackend(config, binary, help_probe, models)` implementing the SDK lifecycle: `validate_request`, `prepare` (yields `PreparedRun` with `stdin_text` = the composed prompt, no `artifacts`, no `staging_dir`, `orphan_marker` as kimi), `finalize`, `inspect_outcome`, `classify_failure`, `list_models`, `auth_probe`, `scrub_env`.

`validate_request` order: model resolved (`request.model or config.model`) → missing is `invalid_arguments` with `details={"field": "model"}` and a repair naming `AMICUS_PI_MODEL` and `amicus_models` → `models.lookup` returning `None` or `"unreadable"` is `invalid_model` (the detail says which) → effort shape → effort in the model entry's `supported_reasoning_efforts` → access → `instructions_append`, exactly as kimi's last two checks.
`finalize` adds the warning `f"pi ran at thinking level {actual!r}, not the requested {requested!r}; the model does not support the requested level."` when they differ.
`inspect_outcome` returns `classify_failure(...)` when `final_error(events)` is set, whatever the exit code, then `empty_response` for a zero-exit run without answer text, else None.

- [ ] **Step 1: Write the failing tests:**

```python
def test_no_model_anywhere_is_refused_pre_spend(): ...
def test_fuzzy_model_is_refused_as_invalid_model(): ...
def test_unreadable_catalog_fails_closed(): ...
def test_effort_outside_model_set_is_refused(): ...  # thinking:no model + "high"
def test_prompt_rides_stdin_and_argv_carries_no_input():
    async with backend.prepare(request(question="SENTINEL-Q", instructions_append="SENTINEL-I")) as prep:
        assert "SENTINEL-Q" in prep.stdin_text and "SENTINEL-I" in prep.stdin_text
        assert not any("SENTINEL" in a for a in prep.argv)
def test_delegate_gets_write_tools_and_consult_does_not(): ...
def test_exit_zero_error_stop_reason_is_a_failure_not_a_result(): ...
def test_clamped_thinking_level_warns(): ...
def test_empty_zero_exit_run_is_empty_response(): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `adapter.py`.**
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): add the pi adapter`.

### Task 7: Status, plugin assembly and registration

**Files:**
- Create: `src/amicus/backends/pi/status.py`; fill `src/amicus/backends/pi/__init__.py` (`plugin(environ)`, `VOCABULARY` with `install_hint` naming `https://pi.dev` and `login_hint` naming `pi auth login <provider>`).
- Create: `tests/support/fake_pi.py` (stdlib-only stand-in: `--version` prints `FAKE_PI_VERSION`, default `1.5.0`; `--help` prints the 1.5.0 capture; `--list-models` prints `FAKE_PI_MODELS`, default one `openrouter/moonshotai/kimi-k3` row; `auth check` prints `FAKE_PI_AUTH`, default `{"status":"ready"}`; a `-p` run reads stdin, copies it to `FAKE_PI_STDIN_FILE` when set, writes argv to `FAKE_PI_ARGV_FILE` when set, optionally writes `FAKE_PI_WRITE` under cwd, prints `FAKE_PI_EVENTS` or a default stream answering `FAKE_PI_ANSWER`, and exits `FAKE_PI_EXIT`, default 0).
- Modify: `tests/conftest.py` (a `_never_spawn_real_pi` autouse fixture setting `AMICUS_PI_BIN=/nonexistent/amicus-test-pi`, and a `fake_pi` fixture, both modelled on kimi's; the other places that set the three `NEVER_SPAWN_*` values set the fourth); `src/amicus/backends/__init__.py` (`IN_TREE`, the effects map, `KNOWN_DISPLAY_NAMES`); `src/amicus/schemas/codes.py` (`BACKEND_IDS`, `BackendId`, `DelegateBackendId`); `src/amicus/schemas/params.py` and `src/amicus/schemas/options.py` (descriptions naming `pi`); `src/amicus/config/__init__.py` (the names list in the `AMICUS_BACKENDS` error); `src/amicus/orchestration/prompts.py` (host name `"pi": "Pi"`); `src/amicus/tools/discovery.py` (pi lists `empty_response` wherever kimi does).
- Test: `tests/test_pi_status.py`, `tests/test_pi_plugin.py`, and the existing `tests/test_codes.py` and `tests/test_conftest_guards.py`.

**Interfaces:**
- Produces: `PiStatus(config, binary, help_probe).probe() -> StatusReport`; `plugin(environ) -> BackendPlugin`.

- [ ] **Step 1: Write the failing tests:** the plugin passes the SDK conformance kit as `test_kimi_plugin.py` does; status reports `installed`, `version`, `authenticated` from the fake; status without `AMICUS_PI_MODEL` reports `authenticated: None` and a warning containing `AMICUS_PI_MODEL`; the conftest guard test asserts a pi run without `fake_pi` is `backend_not_found`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement and register**; let the gate's snapshot tests fail only on the fingerprint (Task 9 regenerates).
- [ ] **Step 4: Run the gate**, confirming the only failures are fingerprint/snapshot pins.
- [ ] **Step 5: Commit** — `feat(backends): register the pi backend`.

### Task 8: End to end through the tools

**Files:**
- Test: `tests/test_pi_sync_tools.py` (modelled on `tests/test_kimi_sync_tools.py`, driving `fake_pi`).

- [ ] **Step 1: Write the tests:** consult returns the fake's answer with usage and `meta.backend == "pi"`; review_changes on a one-commit repo returns structured findings; delegate returns a diff of `FAKE_PI_WRITE`; the stdin copy holds the question and the argv file holds no prompt input; a no-model call is refused with zero spawns (the argv file stays absent); an exit-0 stream ending in `stopReason: "error"` with `401` yields `ok: false`, `error.code == "backend_auth_required"`, `error.backend == "pi"`; an unauthenticated provider is reported by `amicus_backends`.
- [ ] **Step 2: Run them**; each must pass without code changes, or the failure names a gap in Tasks 1–7 to fix in that task's module.
- [ ] **Step 3: Commit** — `test(backends): drive pi end to end through the tools`.

### Task 9: Fingerprint and pins

**Files:**
- Modify: `src/amicus/schemas/fingerprint.py` (`FINGERPRINT` → the next `schema-N`), `tests/fixtures/fingerprint_pins.json`, `tests/fixtures/manifest_snapshot.*.json`, `tests/fixtures/wire_shape_snapshot.json`, and any other pin the gate names.

- [ ] **Step 1: Bump `FINGERPRINT` and regenerate the pins** with the regeneration commands the failing tests print.
- [ ] **Step 2: Read the regenerated diff** and confirm every changed line is `pi` joining an enum, a description naming it, or a digest.
- [ ] **Step 3: Run the gate.**
- [ ] **Step 4: Commit alone** (rule 10) — `feat(schemas): add pi to the backend enums`.

### Task 10: Live suite and release tooling

**Files:**
- Create: `tests/test_pi_live.py` (modelled on `tests/test_kimi_live.py`: consult, review, delegate, each asserting `ok`, non-empty answer, `meta.backend == "pi"` and non-null usage; `AMICUS_REQUIRE_LIVE=1` makes a missing pi, an unset `AMICUS_PI_MODEL` or a not-ready provider a failure).
- Modify: `scripts/record_live_gate_evidence.py` (`BACKENDS` gains `"pi"` with `AMICUS_PI_BIN`), `scripts/check_release_state.py` (four suites), `scripts/check_backend_compat.py` (`pi` with npm package `@earendil-works/pi-coding-agent`, contract from `amicus.backends.pi.contract`), `tests/support/livegate.py` if it enumerates suites.
- Test: the existing tests for those scripts, extended so a record missing the pi suite is refused.

- [ ] **Step 1: Write the failing script tests** (a three-suite record is now refused; a four-suite record passes).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**; never invoke `record_live_gate_evidence.py` to inspect it, because it runs paid suites.
- [ ] **Step 4: Run the gate**, which skips the live suite.
- [ ] **Step 5: Commit** — `feat(release): require the pi live gate`.

### Task 11: Documentation

**Files:**
- Modify: `docs/CONFIGURATION.md` (the four `AMICUS_PI_*` sections; `tests/test_configuration_doc.py` holds them to `ENV`), `README.md` (backend list, "Where things are" row for `docs/pi-help/`), `docs/RELEASING.md` (four suites, `AMICUS_PI_MODEL` required for the evidence run), `skills/collaborating-with-amicus/SKILL.md` and `references/choosing-a-backend.md` (pi's row: carriers, read-only honesty, exact model), `commands/amicus/*.md` that enumerate backends, `CHANGELOG.md` `## [Unreleased]`, `docs/superpowers/specs/2026-09-04-amicus-design.md` (an M9 row in the Milestones table).
- Create: `docs/adr/0047-pi-backend-validates-an-exact-model-and-fails-closed.md` (why the model check fails closed here when kimi's fails open, and why `pi` has no `isolation` option).

- [ ] **Step 1: Write the docs**, one sentence per line under `docs/`.
- [ ] **Step 2: Find every other listing of the backends** with `grep -rn -i "codex.*kimi\|kimi.*claude" --include=*.md .` and update or justify each hit.
- [ ] **Step 3: Run the gate.**
- [ ] **Step 4: Commit** — `docs: document the pi backend`.

### Task 12: Verification and the PR

- [ ] **Step 1:** Run the full gate on the branch head and record each step's exit status separately.
- [ ] **Step 2:** Ask the maintainer to authorize the live suites; on approval run `AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_pi_live.py` with `AMICUS_PI_MODEL=openrouter/moonshotai/kimi-k3`, and report the outcome as run.
- [ ] **Step 3:** Request a Codex review of the branch through `amicus_review_changes` and verify each finding before acting on it.
- [ ] **Step 4:** Open the draft PR (`feat(backends): add the pi backend`, body linking #423 with "Part of #423"), and open the governance PR for rules 18 and 20 alongside it.
