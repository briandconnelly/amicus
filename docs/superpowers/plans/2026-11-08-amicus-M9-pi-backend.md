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
- The gate is rule 2 of `AGENTS.md`; a task is done only when it passes at the task's last commit.
- Never change `AGENTS.md`, `CLAUDE.md` or `.github/**` here (rule 9): rule 18's and rule 20's text, and `.github/workflows/upstream-watch.yml`'s stream description, change in a separate governance PR merged immediately after this one, with no release between.
- No prompt input reaches argv, disk or a log (rule 18); the only argv text is the literal `PI_SYSTEM_PROMPT`.
- Never touch a release version literal (rule 19), including `.mcp.json`'s `--from` pin; its `env_vars` list is not one.
- Commit scope for backend code is `backends`; for docs, `docs`; for the release scripts, `release`; for the fingerprint, `schemas`.
- Never run `-m integration` without the maintainer's go-ahead in the session (rule 5).
- Supported pi versions: `{(1, 5)}`.
- Reasoning-effort vocabulary: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
- Read-only tools: `read,grep,find,ls`; write tools: `read,bash,edit,write,grep,find,ls`.
- Resource-suppression flags, sent on every run and every resource-loading probe: `--no-context-files --no-skills --no-extensions --no-mcp --no-prompt-templates --no-themes --no-approve --offline`.
- Child environment: set `PI_TELEMETRY=0` and `PI_SKIP_VERSION_CHECK=1`; drop `PI_CODING_AGENT_SESSION_DIR`.

## Review Focus

- A configured model whose provider has no credentials: `pi --list-models` hides it, so the pre-spend check must report `backend_auth_required` from `pi auth check --model`, never `invalid_model` (Task 6, Task 8).
- A model id that is a fuzzy match but not an exact row (`moonshotai/kimi-k3` without its `openrouter/` prefix): refused pre-spend as `invalid_model`, never passed through (Task 3, Task 6).
- A provider failure after pi's own three retries: the result must be a classified failure, never `ok: true` with an empty answer, even though pi exits 0 (Task 4, Task 6).
- A provider id that contains `/`: the exact-row match joins the table's provider and model columns, so no split of the model string decides anything (Task 3).
- An unresolvable binary with an unreadable catalog: the result is `backend_not_found`, not a model error (Task 6, Task 7).

---

### Task 1: Captured evidence and the contract module

**Files:**
- Create: `docs/pi-help/1.5.0/pi-version.txt`, `docs/pi-help/1.5.0/pi-help.txt`, `docs/pi-help/1.5.0/list-models-shape.txt`, `docs/pi-help/1.5.0/FINDINGS.md`
- Create: `src/amicus/backends/pi/__init__.py` (docstring only for now), `src/amicus/backends/pi/contract.py`
- Test: `tests/test_pi_contract.py`

**Interfaces:**
- Produces in `contract.py`: `PI_BIN = "pi"`; `PI_SYSTEM_PROMPT: str`; `READ_ONLY_TOOLS`, `WRITE_TOOLS` (the Global Constraints sets, as tuples); `SUPPRESSION_FLAGS: tuple[str, ...]` (the Global Constraints list, in order); `RUN_FLAGS: tuple[str, ...]` (`-p`, `--mode`, `json`, `--no-session`, then `SUPPRESSION_FLAGS`); `ALWAYS_SEND_FLAGS: tuple[str, ...]` (every long flag a run sends, for the help probe); `THINKING_FLAG = "--thinking"`; `EFFORTS: tuple[str, ...]`; `VERSION_ARGS = ("--version",)`; `HELP_ARGS = ("--help", *SUPPRESSION_FLAGS)`; `LIST_MODELS_ARGS = ("--list-models",)` (callers append the id and `SUPPRESSION_FLAGS`); `AUTH_CHECK_ARGS = ("auth", "check", "--json", "--no-refresh")`; `SUPPORTED_VERSIONS = frozenset({(1, 5)})`; `SANDBOX_READ_ONLY`, `SANDBOX_WORKSPACE_WRITE` (kimi's labels); `RUN_ENV_SET: dict[str, str]`; `RUN_ENV_DROP: tuple[str, ...]`; `LOGIN_HINT: str`; the predicates `is_auth_failure`, `is_rate_limited`, `parse_retry_after_ms`, `is_invalid_model`, `is_contract_drift` (kimi's signatures); the disclosures `READ_ONLY_HONESTY`, `IMPLICIT_CONTEXT_DISCLOSURE`, `EGRESS`, `CARRIERS` (the spec's Disclosures section); and `CONTRACT: BackendContract` with `backend_id="pi"`, `display_name="Pi"`, `bin_name="pi"`, `env_prefix="AMICUS_PI_"`, `supported_features={"delegate", "model_validation", "empty_response_detection"}`, `structured_output="prompt_append"`, `isolation_policy=WORKTREE_ALL_TIERS`, `needs_orphan_sweep=True`, `effort_silently_ignored_upstream=True`, `effort_validation="token_floor_plus_catalog"`, and `ModelCatalog(strategy="live_probe", model_identifier_authority="authoritative", effort_metadata_authority="advisory")`.

- [ ] **Step 1: Capture the evidence (zero spend).**
From a scratch directory, with a `find ~/.pi -newer <marker>` before and after, run `pi --version`, `pi --help <SUPPRESSION_FLAGS>` and `pi --list-models kimi-k3 <SUPPRESSION_FLAGS> | head -4` into the three capture files.
Confirm none of them holds a credential, a home path or a provider URL.
Write `FINDINGS.md` in the format of `docs/kimi-help/0.43.1/FINDINGS.md`: the #423 probe, what each capture shows, what the `find` comparison showed, and what was not tested, one sentence per line.

- [ ] **Step 2: Write the failing tests:**

```python
def test_every_sent_flag_is_in_every_capture():  # parametrized over docs/pi-help/*/pi-help.txt
    assert "--definitely-not-a-pi-flag" not in help_text  # negative control first
    for flag in (*contract.ALWAYS_SEND_FLAGS, contract.THINKING_FLAG):
        assert flag in help_text

def test_system_prompt_can_never_name_a_path(tmp_path):
    raw = contract.PI_SYSTEM_PROMPT
    assert "/" not in raw and len(raw.encode()) > 255
    with pytest.raises(OSError):  # ENAMETOOLONG: no file by that name can be created
        (tmp_path / raw).write_text("x")

def test_read_only_tools_cannot_write_or_run():
    assert not {"bash", "edit", "write"} & set(contract.READ_ONLY_TOOLS)

def test_every_effort_is_in_the_captured_help(): ...
def test_probes_carry_the_suppression_flags():
    assert set(contract.SUPPRESSION_FLAGS) <= set(contract.HELP_ARGS)
def test_login_hint_names_no_auth_login():
    assert "auth login" not in contract.LOGIN_HINT and "/login" in contract.LOGIN_HINT
```

Port `tests/test_kimi_contract.py`'s predicate tests with the probe's texts: `"Connection error."` matches none; `"401 Unauthorized"` is auth; `"429 Too Many Requests"` is rate-limited; `'Warning: Model "nope" not found for provider "fake". Using custom model id.'` is an invalid model.

- [ ] **Step 3: Run them and see them fail** — `uv run pytest tests/test_pi_contract.py -q`; expected: an import error for `amicus.backends.pi.contract`.
- [ ] **Step 4: Implement `contract.py`.**
- [ ] **Step 5: Run the tests**, add a parametrized case that deletes `--no-session` from a copy of the capture under `tmp_path` and expects the flag check to fail, then run the gate.
- [ ] **Step 6: Commit** — `feat(backends): add the pi CLI contract and its 1.5.0 captures`.

### Task 2: Configuration, binary and options

**Files:**
- Create: `src/amicus/backends/pi/config.py`, `src/amicus/backends/pi/binary.py`, `src/amicus/backends/pi/options.py`
- Test: `tests/test_pi_config.py`, `tests/test_pi_binary.py`

**Interfaces:**
- Consumes: `contract.SUPPORTED_VERSIONS`, `contract.PI_BIN`.
- Produces: `ENV: EnvNamespace` with `AMICUS_PI_BIN`, `AMICUS_PI_MODEL`, `AMICUS_PI_REASONING_EFFORT`, `AMICUS_PI_SUPPORTED_VERSIONS` and no tombstones; `PiConfig(bin_override, model, reasoning_effort, supported_versions, state_dir, warnings, errors)`; `load_config(environ) -> PiConfig`; `parse_version`, `version_supported` (kimi's signatures); `PiBinary(config)` with `resolve() -> str | None` and `override_error() -> str | None`; `BinaryNotFoundError`; `options_for(config) -> tuple[OptionSpec, ...]` with only `model` and `reasoning_effort` for `{"consult", "review_changes", "delegate"}`.

- [ ] **Step 1: Write the failing tests**, porting `tests/test_kimi_config.py` and `tests/test_kimi_binary.py`, plus:

```python
def test_model_without_a_slash_warns():
    assert any("provider/id" in w for w in load_config({"AMICUS_PI_MODEL": "kimi-k3"}).warnings)

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
- Consumes: `PiConfig`, `PiBinary`, `contract.LIST_MODELS_ARGS`, `contract.SUPPRESSION_FLAGS`.
- Produces: `parse_table(stdout: str) -> ModelListing | None` (header `provider model context max-out thinking images`; each row becomes `ModelEntry(slug=f"{provider}/{model}", supported_reasoning_efforts=EFFORTS if thinking == "yes" else ("off",))`; None without the header); `PiModels(config, binary)` with `read(force=False) -> ModelListing` (the full listing, cached `HELP_CACHE_TTL_SECONDS`, capped at 1024 entries with `truncated`) and `lookup(model: str) -> ModelEntry | None | Literal["unreadable"]`, which runs `pi --list-models <model> <SUPPRESSION_FLAGS>` and returns the row whose joined slug equals `model` exactly, None when the listing was read and has no exact row, and `"unreadable"` when the probe failed.

- [ ] **Step 1: Write the failing tests** against `docs/pi-help/1.5.0/list-models-shape.txt` and inline tables:

```python
def test_parse_captured_table():
    assert "openrouter/moonshotai/kimi-k3" in [m.slug for m in parse_table(CAPTURE.read_text()).models]

def test_lookup_is_exact_not_fuzzy(): ...  # rows kimi-k3 and kimi-k3:batch; "moonshotai/kimi-k3" -> None
def test_slash_in_provider_joins_columns():
    table = HEADER + "gateway/team  m  128K  16K  no  no\n"
    assert parse_table(table).models[0].slug == "gateway/team/m"
def test_lookup_unreadable_when_probe_fails(): ...
def test_no_thinking_model_accepts_only_off(): ...
def test_no_matches_message_is_none():
    assert parse_table('No models matching "x"\n') is None
def test_probe_argv_carries_suppression_flags(): ...  # via a recorded run_sync_capture
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `models.py`** with `runtime.run_sync_capture`, as kimi does.
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): read pi's model catalog`.

### Task 4: Reading the event stream

**Files:**
- Create: `src/amicus/backends/pi/normalize.py`
- Test: `tests/test_pi_normalize.py`, with streams written inline from synthetic literals in the shape of the #423 probe's output.

**Interfaces:**
- Produces: `final_assistant(events: str) -> dict | None` (the `message` of the last `message_end` event with `role == "assistant"`); `extract_final_message(events) -> str | None` (its `text` parts joined); `final_error(events) -> str | None` (its `errorMessage` when `stopReason == "error"`); `thinking_level(events) -> str | None`; `parse_event_metadata(events) -> tuple[Usage | None, str | None]`; `lost_after_final_message(events) -> bool` (kimi's meaning); `parse_structured` re-exported from kimi's normalize.

- [ ] **Step 1: Write the failing tests:**

```python
def test_answer_is_last_assistant_text_after_tool_turns(): ...
def test_usage_counts_each_response_once():  # two assistant message_end plus their turn_end/agent_end echoes
    usage, _ = parse_event_metadata(STREAM)
    assert (usage.input_tokens, usage.output_tokens) == (123 + 200, 45 + 60)
def test_cost_only_when_from_provider(): ...  # totalFromProvider false -> None; true -> the total
def test_cache_tokens_map_to_cached_input_and_cache_creation(): ...
def test_error_stop_reason_exposes_message():
    assert final_error(RETRIED_ERROR_STREAM) == "Connection error."
def test_session_id_from_session_event(): ...
def test_garbage_lines_degrade_metadata_not_the_answer(): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `normalize.py`**, tolerating unknown event types and non-JSON lines.
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): parse pi's json event stream`.

### Task 5: Command, environment, probes and the failure classifier

**Files:**
- Create: `src/amicus/backends/pi/cli.py`
- Test: `tests/test_pi_cli.py`

**Interfaces:**
- Consumes: Task 1's contract.
- Produces: `build_exec_command(*, pi_bin: str, read_only: bool, model: str, thinking: str | None) -> list[str]` (`RUN_FLAGS`, `--system-prompt PI_SYSTEM_PROMPT`, `--append-system-prompt ""`, `--tools`, `--model`, optional `--thinking`; no prompt text); `build_run_env(base: dict[str, str]) -> dict[str, str]`; `pi_version(binary) -> str | None`; `version_display(str | None) -> str | None`; `auth_status(binary, model: str | None) -> Literal["ready", "not_ready", "unresolved", "unknown"]` (`pi auth check --model <model> --json --no-refresh`; `invalid` maps to `not_ready`, a resolution error to `unresolved`, anything else to `unknown`; no model spawns nothing and is `unknown`; never passes `--credentials`); `classify_failure(run: CommandRun, *, error_message: str | None, sanitize) -> ClassifiedFailure`, in kimi's order (binary missing → timeout → drift → auth → rate limit → invalid model → `nonzero_exit`) with codes `pi_not_found`, `timeout`, `cli_contract_changed`, `pi_auth_required`, `pi_rate_limited`, `invalid_model`, `nonzero_exit`.

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

def test_auth_status_maps_every_outcome(): ...  # ready, not_ready, invalid, resolution error, garbage
def test_auth_status_without_model_spawns_nothing(): ...
def test_classifier_reads_the_exit_zero_error_message():
    assert classify_failure(run(exit_code=0), error_message="401 Unauthorized", sanitize=None).code == "pi_auth_required"
def test_generic_detail_is_sanitized_before_the_cut(): ...  # port kimi's straddle test
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `cli.py`.**
- [ ] **Step 4: Run the tests and the gate.**
- [ ] **Step 5: Commit** — `feat(backends): build pi runs and classify their failures`.

### Task 6: The adapter

**Files:**
- Create: `src/amicus/backends/pi/adapter.py`, `tests/support/pifixtures.py` (`make_backend(environ, catalog, auth, version)` pinning the binary to `/PI`, like `kimifixtures.make_backend`)
- Test: `tests/test_pi_adapter.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `PiBackend(config, binary, help_probe, models)` with the SDK lifecycle methods kimi's adapter has; `prepare` yields `PreparedRun` with `stdin_text` set to the composed prompt, no `artifacts`, no `staging_dir`, and kimi's `orphan_marker` rule.

`validate_request` order: the model (`request.model or config.model`) missing is `invalid_arguments`, `details={"field": "model"}`, with a repair naming `AMICUS_PI_MODEL` and `amicus_models` → when `binary.resolve()` is None, return None so the orchestration reports `backend_not_found` → `auth_status` `unresolved` is `invalid_model`, `not_ready` is `pi_auth_required` → `models.lookup` returning None or `"unreadable"` is `invalid_model`, with a detail saying which → effort shape → effort in the entry's `supported_reasoning_efforts` → kimi's `access` and `instructions_append` checks.
`finalize` warns `f"pi ran at thinking level {actual!r}, not the requested {requested!r}; the model does not support the requested level."` when the two differ.
`inspect_outcome` returns `classify_failure(...)` when `final_error(events)` is set, whatever the exit code; then `empty_response` for a zero-exit run with no answer text; else None.

- [ ] **Step 1: Write the failing tests:**

```python
def test_no_model_anywhere_is_refused_pre_spend(): ...
def test_unauthenticated_provider_is_auth_required_not_invalid_model(): ...
def test_fuzzy_model_is_refused_as_invalid_model(): ...
def test_unreadable_catalog_fails_closed(): ...
def test_unresolvable_binary_skips_the_probes(): ...  # validate_request returns None, no spawn recorded
def test_effort_outside_model_set_is_refused(): ...  # thinking:no model with "high"
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

### Task 7: Registration, mirrors and the fingerprint

This task leaves the gate green only at its second commit, which rule 10 requires to hold the fingerprint and pins alone.

**Files:**
- Create: `src/amicus/backends/pi/status.py`; fill `src/amicus/backends/pi/__init__.py` (`plugin(environ)`, `VOCABULARY` with `install_hint` naming `https://pi.dev` and `login_hint=contract.LOGIN_HINT`, `EGRESS`, `CARRIERS`).
- Create: `tests/support/fake_pi.py` (stdlib only: `--version` prints `FAKE_PI_VERSION`, default `1.5.0`; `--help` prints the 1.5.0 capture; `--list-models` prints `FAKE_PI_MODELS`, default one `openrouter moonshotai/kimi-k3` row; `auth check` prints `FAKE_PI_AUTH`, default `{"status":"ready","provider":"openrouter"}`, exiting 0 for ready, 1 for not_ready, 2 otherwise; a `-p` run reads stdin, copies it to `FAKE_PI_STDIN_FILE` and argv to `FAKE_PI_ARGV_FILE` when set, writes `FAKE_PI_WRITE` under cwd when set, prints `FAKE_PI_EVENTS` or a default stream answering `FAKE_PI_ANSWER`, and exits `FAKE_PI_EXIT`, default 0).
- Create: `tests/test_pi_status.py`, `tests/test_pi_plugin.py`.
- Modify, registration: `src/amicus/backends/__init__.py` (`IN_TREE`, effects, `KNOWN_DISPLAY_NAMES`); `src/amicus/schemas/codes.py` (`BACKEND_IDS`, `BackendId`, `DelegateBackendId`); `src/amicus/schemas/params.py`, `src/amicus/schemas/options.py`, `src/amicus/server.py` (the instructions' backend list and delegate restriction), `src/amicus/tools/delegate.py`, `src/amicus/tools/discovery.py` (pi lists `empty_response` wherever kimi does, and the scope text), `src/amicus/config/__init__.py` (the `AMICUS_BACKENDS` error's names), `src/amicus/orchestration/prompts.py` (`"pi": "Pi"`).
- Modify, mirrors: `.mcp.json` `env_vars` (the four `AMICUS_PI_*` names, `--from` untouched), `tests/test_packaging.py` `EXPECTED_ENV_VARS`, `docs/MIGRATION.md` (the four variables, no former names), `scripts/render_configuration_doc.py` (`("AMICUS_PI_", "Pi")` in `_GROUPS` and a Pi section in `render()`), then regenerate `docs/CONFIGURATION.md` with it, never by hand.
- Modify, guard and regression tests: `tests/conftest.py` (`NEVER_SPAWN_PI`, a `_never_spawn_real_pi` autouse fixture and a `fake_pi` fixture, modelled on kimi's, and every place the other `NEVER_SPAWN_*` values are set), `tests/test_codes.py`, `tests/test_registry.py`, `tests/test_config.py`, `tests/test_server.py`, `tests/test_paid_tools.py`, `tests/test_discovery.py`, `tests/test_resources.py`, `tests/test_prompts.py`, `tests/test_relative_config_paths.py`, `tests/test_skill_contract.py`, `tests/test_conftest_guards.py`: each hardcoded three-backend default, list or two-backend delegate enum gains `pi`.
- Modify, second commit: `src/amicus/schemas/fingerprint.py` (`FINGERPRINT` to the next `schema-N`), the pins `scripts/regenerate_fingerprint_pins.py` writes, and `tests/test_discovery_cost.py` `MEASURED` and `BUDGET` for every profile, with the growth explained in its comment block as earlier raises are.

**Interfaces:**
- Produces: `PiStatus(config, binary, help_probe).probe() -> StatusReport`; `plugin(environ) -> BackendPlugin`.

- [ ] **Step 1: Write the failing tests:** the plugin passes the SDK conformance kit as `tests/test_kimi_plugin.py` does; status reports `installed`, `version` and `authenticated` from `fake_pi`; status without `AMICUS_PI_MODEL` reports `authenticated: None` and a warning containing `AMICUS_PI_MODEL`; the status help probe's argv carries `SUPPRESSION_FLAGS`; the conftest guard test asserts a pi call without `fake_pi` is `backend_not_found`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement status and the plugin, and make every registration and mirror change above.**
- [ ] **Step 4: Run the gate** and confirm the only failures are fingerprint, snapshot and discovery-cost pins.
- [ ] **Step 5: Commit** — `feat(backends): register the pi backend`.
- [ ] **Step 6: Bump `FINGERPRINT`, regenerate the pins, remeasure discovery cost**, and read the diff: every changed line must be `pi` joining an enum, a description naming it, a digest, or a measured size.
- [ ] **Step 7: Run the gate**; it must pass.
- [ ] **Step 8: Commit alone** — `feat(schemas): add pi to the backend enums`.

### Task 8: End to end through the tools

**Files:**
- Test: `tests/test_pi_sync_tools.py`, modelled on `tests/test_kimi_sync_tools.py` and driving `fake_pi`.

- [ ] **Step 1: Write the tests:** consult returns the fake's answer with usage and `meta.backend == "pi"`; review_changes on a one-commit repo returns structured findings; delegate returns a diff of `FAKE_PI_WRITE`; the stdin copy holds the question and the argv file holds no prompt input; a no-model call is refused with no `-p` spawn recorded; an exit-0 stream ending in `stopReason: "error"` with `401` is `ok: false` with `error.code == "backend_auth_required"` and `error.backend == "pi"`; `FAKE_PI_AUTH` `not_ready` refuses before any `-p` spawn with `backend_auth_required`, and `amicus_backends` reports `authenticated: false`.
- [ ] **Step 2: Run them**; each must pass without code changes, or the failure names a gap to fix in the owning task's module.
- [ ] **Step 3: Run the gate and commit** — `test(backends): drive pi end to end through the tools`.

### Task 9: Live suite and release tooling

**Files:**
- Create: `tests/test_pi_live.py`, modelled on `tests/test_kimi_live.py`: consult, review and delegate, each asserting `ok`, a non-empty answer, `meta.backend == "pi"` and non-null usage; under `AMICUS_REQUIRE_LIVE=1`, a missing pi, an unset `AMICUS_PI_MODEL` or a not-ready provider fails.
- Modify: `scripts/record_live_gate_evidence.py` (`BACKENDS` gains `"pi"` with `AMICUS_PI_BIN`), `scripts/check_release_state.py` (four suites), `scripts/release.py` (the spend notice names four backends), `scripts/check_backend_compat.py` (`pi` in `BACKENDS`, npm package `@earendil-works/pi-coding-agent`, contract from `amicus.backends.pi.contract`, and a `pi` stream in `WATCH_STREAMS`, `WATCH_LABELS` and the watch reader map), `docs/WATCHING.md`, and `tests/support/livegate.py` if it enumerates suites.
- Test: the existing tests of those scripts, including `tests/test_check_backend_compat_watch.py`, extended so a three-suite record is refused and the pi stream is watched.

- [ ] **Step 1: Write the failing script tests.**
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**; never invoke `record_live_gate_evidence.py` to inspect it, because it runs paid suites.
- [ ] **Step 4: Run the gate**, which skips the live suite.
- [ ] **Step 5: Commit** — `feat(release): require the pi live gate`.

### Task 10: Documentation and metadata

**Files:**
- Modify: `README.md` (backend list, a "Where things are" row for `docs/pi-help/`), `docs/RELEASING.md` (four suites, `AMICUS_PI_MODEL` required for the evidence run), `CHANGELOG.md` `## [Unreleased]`, `docs/superpowers/specs/2026-09-04-amicus-design.md` (an M9 row in the Milestones table), `pyproject.toml` `keywords`, `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` (`keywords` and `interface.shortDescription` only, never `version`), `commands/amicus/*.md` that enumerate backends.
- Modify, skill: `skills/collaborating-with-amicus/SKILL.md`, `references/choosing-a-backend.md` (pi's row: carriers, read-only honesty, exact model), `references/reviewing-a-returned-diff.md` (delegation is codex, kimi or pi; pi's confinement row), `references/reading-results.md` (pi's `empty_response` and stream-only answer), `references/server-down-fallback.md`, `tests/scenarios.md`.
- Create: `docs/adr/0047-pi-backend-validates-an-exact-model-and-fails-closed.md` (why pi's model check fails closed when kimi's fails open, why it asks `pi auth check` first, and why `pi` has no `isolation` option).

- [ ] **Step 1: Write the docs**, one sentence per line under `docs/`.
- [ ] **Step 2: Find every other listing of the backends**, across lines as well as within them: `grep -rln -i "kimi" --exclude-dir=.git --exclude-dir=kimi-help --exclude-dir=host-captures --exclude-dir=tests . | sort`, then read each hit and update it or note why it stays kimi-only.
- [ ] **Step 3: Run the gate.**
- [ ] **Step 4: Commit** — `docs: document the pi backend`.

### Task 11: Verification and the PRs

- [ ] **Step 1:** Run the full gate on the branch head, recording each step's exit status separately.
- [ ] **Step 2:** Ask the maintainer to authorize the pi live suite; on approval run `AMICUS_REQUIRE_LIVE=1 AMICUS_PI_MODEL=openrouter/moonshotai/kimi-k3 uv run pytest -m integration --no-cov tests/test_pi_live.py` and report the outcome as run.
- [ ] **Step 3:** Request a Codex review of the branch through `amicus_review_changes` and verify each finding before acting on it.
- [ ] **Step 4:** Open the draft PR `feat(backends): add the pi backend`, its body saying "Part of #423" and that the governance PR merges immediately after it with no release between.
- [ ] **Step 5:** Open the governance PR: rule 18 (no pi exemption), rule 20 (`tests/test_pi_live.py` as a fourth suite) and the `upstream-watch.yml` stream description, run `scripts/check_github_actions_pinning.py` if the workflow changed (rule 3), and link it from the milestone PR.
