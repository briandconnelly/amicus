# Upgrading the supported `codex` version

This is the procedure for adding a new OpenAI `codex` CLI minor to amicus's codex contract.
It pairs the mechanical check (`scripts/check_backend_compat.py`, no prompt sent, no spend) with the judgment checks a script cannot make: `--help` proves a flag exists, never that its meaning still holds.
It was ported from codex-in-claude's `docs/UPGRADING-CODEX.md` and adapted to what amicus actually ports, pins and records.

Every assumption amicus makes about the CLI lives in `src/amicus/backends/codex/contract.py`, so most steps come down to this: probe the new CLI, confirm or update that one file, and prove it with tests.
Its docstring records which checks each supported minor received, and a support PR extends that record rather than rewriting it.

This is not a release.
Cutting a release is `docs/RELEASING.md`, whose precondition "The backend CLIs are current and checked" runs the same mechanical check again, and a supported-version change is its own PR there, ahead of any release.

You usually do not have to notice a new minor yourself.
A scheduled Claude Code routine checks npm's `latest` dist-tag for `@openai/codex` and, for each new minor, opens a draft PR titled `chore(backends): support codex-cli <major>.<minor>` that does the zero-spend steps below and holds an evaluation of the release notes.
It skips a minor that already has such a PR in any state, or a closed `codex-upgrade` issue titled `chore(backends): track codex <major>.<minor>`, and names an open one in the PR body with `Closes`.
Issues opened before that title existed are titled `chore(cli-contract): track codex <major>.<minor>`.
The other backend CLIs and the capped `fastmcp` and `mcp` packages are watched by `check_backend_compat.py watch` instead, described in `docs/WATCHING.md`.
That evaluation is read from the notes alone; nothing in it was run against a binary, so everything below still runs locally, where an authenticated `codex` is installed.
A patch release within a supported minor needs no change to the set, though the steps below can still be run to refresh a capture.

## 0. Prerequisites

- The new `codex` is installed with `npm install -g @openai/codex@<version>` and authenticated with `codex login`.
  Everything below verifies this installed binary; the scratch binaries in step 2 exist only as a comparison baseline.
- `npm` is available, for step 2's comparison against the previous version.
- You are on a clean branch named `chore/codex-<major>-<minor>`, such as `chore/codex-0-164`, which is what the earlier support PRs used.
- `AMICUS_CODEX_BIN` is exported as the absolute path of that installed binary, such as `export AMICUS_CODEX_BIN="$(npm prefix -g)/bin/codex"`, and `"$AMICUS_CODEX_BIN" --version` reports the new version.
  The mechanical check and `--write` find codex the way the server does: `AMICUS_CODEX_BIN` first, then under WSL2 the native install paths before `PATH`, so without the pin they can inspect a different binary than the one step 2 probes.
- No `AMICUS_CODEX_SUPPORTED_VERSIONS` override is set, so you test the shipped set rather than your environment.
- Your `codex login status` output stays out of commits, issues and PRs, because it can carry account-identifying detail.

## 1. Run the mechanical check (no spend)

```sh
uv run python scripts/check_backend_compat.py
```

It runs `--version`, `exec --help` and the free login probe for every backend, and reports for codex:

- a `FAIL` line for an installed version outside the shipped `SUPPORTED_VERSIONS`, which is expected for a new minor until step 4 adds it;
- a `FAIL` line for a flag in `ALWAYS_SEND_FLAGS` that `exec --help` no longer declares, which is a real contract break that must be resolved before anything ships;
- `same flags and words`, `same flags` with changed wording, or `FLAGS DIFFER` against the newest capture under `docs/codex-help/`.

`FLAGS DIFFER` is not by itself a failure, since upstream adds flags constantly, but every removed flag must be looked up in `contract.py` before going on.
An added flag is a candidate for step 3's adoption review.
The script's docstring and `docs/RELEASING.md` describe every other line it can print.

This is the mechanical half only: for codex it reads `exec --help` alone, against the newest capture rather than the previous binary.
Step 2's `compare` subcommand gathers the rest of the evidence from the old and new binaries side by side, and step 3 reads it.

## 2. Gather old and new evidence

The judgment checks are only as good as what they compare against, so compare the new binary with the previous minor's.
`codex` ships on npm, so any earlier version installs side by side without touching the global install.
Drive both binaries by absolute path, so a difference is attributable to the version and not to whichever binary was first on `PATH`.
`$NEW` is the binary `AMICUS_CODEX_BIN` names, because it is the one the contract check and the live gate verify; only `$OLD` comes from npm.

```sh
SCRATCH=$(mktemp -d)
npm install --prefix "$SCRATCH/old" @openai/codex@<old-version> >/dev/null
OLD="$SCRATCH/old/node_modules/.bin/codex"
NEW="$AMICUS_CODEX_BIN"
uv run python scripts/check_backend_compat.py compare --backend codex --old-bin "$OLD" --new-bin "$NEW"
```

Keep that shell for the rest of this procedure, and run every probe in step 3 as `"$NEW"` rather than a bare `codex`.

If the new binary was installed some other way than npm, also install the new version from npm and confirm its `--help` matches the installed one's, so a difference cannot be the distribution channel rather than the version.

`compare` runs every command of either binary in a fresh scratch `HOME` and `CODEX_HOME` with no credentials, under an environment that keeps your `PATH` and nothing else, so no `OPENAI_API_KEY`, `CODEX_API_KEY` or `CODEX_ACCESS_TOKEN` reaches it.
It prints what it checked, what differed and what it did not run, then a `FAIL` line for each problem.
It exits 0 when nothing failed, 1 when something did, and 2 when it stopped before comparing; the script's docstring defines each.
A difference is evidence for step 3 to read, not by itself a failure.

### Help surfaces

`compare` collects `--help`, `exec --help`, `exec review --help`, `login --help` and `features list` from both binaries and compares each one.
For a difference it lists the flags, subcommands and features added, removed or changed, then the text diff.
The committed capture holds `codex exec --help` only, which is why the other surfaces are compared binary to binary.

Before comparing anything, it authenticates the retrieved old binary: its `exec --help` must match `docs/codex-help/<old-version>/codex-help.txt`, and a mismatch stops the comparison until it is reconciled.
The match ignores trailing whitespace on each line and blank lines at the end, because the trailing-whitespace and end-of-file hooks strip both from a capture as it is committed; any other difference is a mismatch.
Matching help is good evidence the retrieved build is the one checked last time, and no evidence about its behavior, so treat any difference below as associated with the version and reconcile it against the release notes before recording it.
If the previous minor has no capture, `compare` fails on that, still compares everything else, and names the newest capture that exists; compare against that one by hand and say so in the PR.
If npm is unreachable, the committed captures are the only baseline, and every other comparison below has no offline substitute.

### Feature flags

`compare` reads `features list` in its scratch home, so your own config cannot move a default, and lists each feature whose stage or default moved, appeared or went away.
For each row whose stage or default moved, read the feature at the release tag in `openai/codex` (the `codex-rs` sources at `rust-v<version>`) to decide whether it can reach a `codex exec` run amicus makes, and record that in the PR, as #294 and #353 did.
A feature read only under `tui/` cannot.

### The model-facing tool catalog

`--help` and `features list` stop at what the CLI accepts; neither shows the tool list codex sends the model.
This check exists because codex 0.152.0 dropped `update_plan` from the default tool set and added a gated `clock.sleep` while every `--help` surface was byte-identical.
It was compared for 0.154 through 0.160 with codex-in-claude's `scripts/capture_wire_tools.py` (#194, #294) and skipped for 0.161 through 0.164, because amicus had no instrument of its own until #380.

```sh
uv run python scripts/capture_codex_wire_tools.py --old-bin "$OLD" --new-bin "$NEW" --out "$SCRATCH/wire-tools.json"
```

It spends nothing.
Every run points codex at a fake Responses server on `127.0.0.1` through a `model_providers` entry passed as `-c` overrides, with no `env_key` and no credential anywhere in a scratch home that `login status` must first report as logged out.
The fake answers the first request with a completed one-word turn, so codex exits promptly and no model turn leaves the machine.
The same server is each run's HTTP(S) proxy, so whatever codex tries to reach beyond loopback is refused and its host listed under `OUTBOUND`; 0.163.0 and 0.164.0 try `chatgpt.com`, `ab.chatgpt.com`, `github.com` and `api.github.com`, and an attempt on `api.openai.com` is a `FAIL`.
A client that ignored the proxy settings would not show up there, so `OUTBOUND` is what codex tried through the proxy, not proof that it tried nothing else.
The only prompt is a literal of the script, over stdin, and it keeps only each tool's qualified name and a short hash of its definition (a namespace's own description gets an entry of its own), never a raw request, a header or instructions text.

It captures each model in `KNOWN_MODEL_SLUGS` on both binaries through the argv amicus builds for a read-only run, once with amicus's `MODEL_RUN_DISABLED_FEATURES` disabled and once without, and diffs the two binaries.
A disable that the binary's `features list` does not list is reported as unsupported on that binary and not sent, because codex rejects an unknown `--disable` at startup, and a run that fails at startup or sends no tools is a `FAIL`, never an empty catalog, as is one that does not exit 0 after exactly one request.

Which tools codex offers depends on the model's metadata, which a logged-in codex reads from the served catalog.
A scratch home has no login, so by default both binaries get the new binary's bundled catalog (`codex debug models --bundled`) through `-c model_catalog_json`, which holds the metadata constant so that a difference is the binary's.
`--catalog own` lets each binary use its own bundled catalog, and `--catalog-bin PATH` takes the shared one from a third binary.
A model missing from the catalog in use runs on codex's fallback metadata, and the report says which.

The disables are the positive control, checked tool by tool: `clock.sleep`, and each of `create_goal`, `get_goal` and `update_goal`, must appear in some model's baseline on an authoritative carrier (the top-level `tools` or an `additional_tools` item) and be gone from that model's disabled run, or the probe is blind and the diff proves nothing.
A name read only from a code-mode `exec` description does not count as a baseline, because it may be missing merely because it was deferred, but one still declared after its disable fails the control.
A control with any tool lacking an authoritative baseline is reported as unobserved, and then the script does not declare the probe validated.
`--omit-disables` is the negative control for the control itself: the disabled runs then send no `--disable`, and every applicable control must fail.
It exits 0 when validated, 1 on any `FAIL`, 2 when it stopped before capturing and 3 when nothing failed but a control was unobserved; the script's docstring defines each.

Its blind spots are reported as unobserved rather than guessed at.
A scratch home never shows the plugin-tool family, so the `remote_plugin` disable has no control.
A `code_mode_only` model offers its tools nested inside a code-mode `exec` tool, and their names are read from that tool's description, which codex says may omit deferred tools, so a nested name that disappears is not proof of a removal; a change to any nested declaration still moves `exec`'s own hash.
The served catalog is never read.

Replayed against 0.164.0's bundled catalog, 0.151.0 to 0.152.0 shows `clock.sleep` added and `update_plan` removed, and with `--omit-disables` the `sleep_tool` control fails on 0.152.0 (#380).
Read each difference against the release notes, as for any other surface.

### The served model catalog

`codex debug models` prints the catalog the backend serves to a client version.
It needs an account, so `compare` lists it as not run unless you pass `--debug-models`, which runs it on both binaries under your own environment and login and diffs the two.
That is the catalog served to your account today, never a replay of the one an earlier support PR recorded.
Compare its slugs with `KNOWN_MODEL_SLUGS`, which is a bundled fallback in priority order.
The catalog is served per client version and per account, so it can change with no CLI upgrade at all, which is why `KNOWN_MODEL_SLUGS`'s comment records the client versions and dates each slug was seen on.
While there, confirm `default_reasoning_level` is still a string and `supported_reasoning_levels` is still a list of `{effort, …}` objects; the parser degrades to `None` on drift, silently for agents, so a shape change belongs in `CHANGELOG.md`.

## 3. Review what changed (judgment)

The script confirms shapes; you confirm meaning.
Work from step 2's evidence and the release notes for every release between the two versions, and record each check you ran, and each you did not, in the PR.

### Zero-spend checks

Step 2's `compare` runs each of these on both binaries except the logged-in `login status` forms, and reports each under `CHECKED` or as a `FAIL`; the list below is what each of its probes asserts.
Every probe gets its own empty scratch `CODEX_HOME`, `login status` there must report logged out before the probe starts, and no API key or access token is passed, so a run that gets past config loading stops at the unauthenticated 401 instead of spending.
That stopping point is the expected result, and an exported key would turn it into a real turn, which is why a probe run by hand must unset `OPENAI_API_KEY`, `CODEX_API_KEY` and `CODEX_ACCESS_TOKEN` too.

- **Pins and disables.**
  The four `PLUGIN_OWNED_CONFIG_KEYS` pins and every `--disable` in `MODEL_RUN_DISABLED_FEATURES`, sent together under `--strict-config`, must get past config loading on both binaries.
  `--strict-config` turns a renamed or removed key into a startup failure, and an unknown `--disable` name fails as `Error: Unknown feature flag`, which amicus classifies as `cli_contract_changed`.
- **Strict-config grammar.**
  An unknown key in a `-c` override and an unknown key in the scratch `config.toml` must each still produce `STRICT_CONFIG_ERROR_PREFIX` and the unknown-field phrase, and the override form must still name `STRICT_CONFIG_OVERRIDE_ORIGIN_PHRASE`; `parse_strict_config_rejection` must parse both.
  As a positive control, `--strict-config --ignore-user-config` beside that same bad file must get past config loading.
  If the wording moves, a pin drift degrades from `cli_contract_changed` to a generic `nonzero_exit`: the run still fails, but the diagnosis is lost.
- **Invalid-value and retired-setting grammars.**
  An invalid value, such as `-c 'sandbox_mode="yolo"'`, must still parse with `parse_invalid_config_value`, and a retired setting, such as `-c 'approval_policy="untrusted"'`, must still parse with `parse_unsupported_config_setting`.
- **Contract-drift grammar.**
  An unknown flag and an invalid `--sandbox` value must still match `CONTRACT_DRIFT_STDERR_PATTERNS`, so `is_contract_drift` classifies them.
- **Login status.**
  Logged-out `codex login status` must be unchanged, and if you can observe the logged-in forms without pasting them anywhere, they must still carry `LOGIN_METHOD_CHATGPT` or `LOGIN_METHOD_API_KEY`.

Encode only phrasings seen in real output, and never a guessed one.

### Checks that read the notes and the source

- **Flag meaning.**
  A flag `--help` still lists may have changed behavior, and a change in meaning is a guarantee change even though the name held, so treat it like a removal.
  Read the notes for anything touching the flags in `ALWAYS_SEND_FLAGS`: `--sandbox`, `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, `--output-last-message` and `--output-schema` carry the guarantees.
- **Sandbox values.**
  `VALID_SANDBOXES` must still exist with the same boundaries, and no default path may emit `danger-full-access` or any `--dangerously-bypass-*` (`FORBIDDEN_SURFACE_PHRASES`).
  If the notes touch the sandbox, re-read `WORKSPACE_WRITE_SCOPE_FACT` and `READ_SCOPE_FACT` against them.
  `READ_SCOPE_FACT` is a ceiling claim, so if a release did confine reads the disclosure would be over-broad rather than unsafe, and the response is to re-probe before narrowing anything.
  Also diff upstream's complete `SandboxWorkspaceWrite` struct (`codex-rs` `config/src/types.rs`) between the previous checked release tag and the new one.
  At `rust-v0.165.0`, as at `rust-v0.164.0` and `rust-v0.163.0`, it has four fields: `writable_roots` and `network_access`, which amicus pins, and `exclude_tmpdir_env_var` and `exclude_slash_tmp`, which amicus leaves alone because they only narrow the writable scope.
  An added field, or a changed type or default on any of the four, is a finding to read for widening behavior, because a new widening key would arrive unpinned.
- **Implicit context.**
  `SKILLS_DISCOVERY_FACT` and `SKILL_BODY_FACT` describe what codex loads with no flag at all: `AGENTS.md` files and discovered skills.
  `--help` cannot see this surface, so read the notes for any change to instruction-file or skill loading, and re-check the disclosure where one appears.
- **Structured output.**
  amicus sends `--output-schema` on `codex exec`; confirm the notes do not change how the final message is held to it.
- **Event and result surface.**
  `USAGE_EVENT_MARKERS` and the result extraction in `src/amicus/backends/codex/normalize.py` read the `--json` stream tolerantly, so a renamed usage or session field degrades metadata silently instead of failing.
  If the notes touch the JSONL events, inspect a real stream, and record a lost field in `CHANGELOG.md` as a conscious call.
- **Failure classification.**
  Reconcile any new auth, capacity or rate-limit wording the notes mention against `AUTH_FAILURE_PATTERNS`, `MODEL_AT_CAPACITY_PATTERN` and `RATE_LIMIT_PATTERNS`, using observed output only.
- **New capabilities.**
  Scan the `Commands:` section of `codex --help` for new subcommands, `exec --help` for new flags, and `features list` for new features.
  A release's most relevant new surface is often there rather than in a flag the contract already sends.
  Adopting one is a separate, deliberate change, never part of a version bump.
- **Carriers.**
  AGENTS.md rule 18 exempts Codex's `-c developer_instructions` argv token only while no other channel for developer instructions is known.
  The formal re-check happens before every release (`docs/RELEASING.md`), but if these notes add such a channel, say so in the PR and open an issue, because the exemption no longer holds.

### Checks that spend

Each run below spends a trivial request, so run them when the notes touch the sandbox, config precedence or reasoning effort, and say in the PR when they were not run.
They guard the case `--strict-config` cannot see: a key that keeps its name while its meaning, default or accepted values change.

- **Reasoning effort.**
  Effort rides `-c model_reasoning_effort=…` (`MODEL_REASONING_EFFORT_CONFIG_KEY`), TOML-string-encoded, because `codex exec` has no effort flag.
  With a valid model and a bogus effort, the run must fail with both `REASONING_EFFORT_REJECTION_MARKERS` in bracketed form, which proves the key is still read.
  Also look in `exec --help` for a dedicated effort flag worth adopting.
- **Workspace-write network pin.**
  `-c sandbox_workspace_write.network_access=false` (`WORKSPACE_WRITE_NETWORK_ACCESS_CONFIG_KEY`) closes egress against a user config file or profile that opens it.
  In a subshell with a scratch `CODEX_HOME` holding a copy of `auth.json`, removed by an `EXIT` trap, set `network_access = true` in both `config.toml` and a profile, then ask codex to run `curl` against a public URL three times: with no pin, which must reach the network (the positive control), with the pin, and with the pin and the profile, which must both be blocked.
  Judge each run by the `command_execution` item's `exit_code` in the `--json` stream, never the model's prose.
- **Workspace-write writable-roots pin.**
  `-c 'sandbox_workspace_write.writable_roots=[]'` (`WORKSPACE_WRITE_WRITABLE_ROOTS_CONFIG_KEY`) gets the same three runs, with the config naming a writable root under `$HOME`, a separate pre-absent target file per run, and the target directory removed in the same `EXIT` trap.
  The target must sit outside the workspace and both temp roots, because `workspace-write` already permits `/tmp` and `$TMPDIR`, and a target there passes every run vacuously.
  Judge each run by whether the file exists afterward, never by what the model or the command reported.

## 4. Update the contract and the files around it

Add the new minor to `SUPPORTED_VERSIONS`.
amicus keeps every minor it has checked, and the set is advisory: a version outside it warns on `amicus_backends` and never blocks.
Remove an older minor only as a deliberate decision of its own, never as part of adding one.

Start by searching the whole tree for the previous minor, such as `grep -rFn 0.163 src tests docs CHANGELOG.md`, and reconcile every hit; `-F` keeps the dot literal.
The usual places are:

| File | What changes |
|------|--------------|
| `src/amicus/backends/codex/contract.py` | `SUPPORTED_VERSIONS`; the docstring's record of what this minor was checked against; the version list in the `MODEL_RUN_DISABLED_FEATURES` comment; the `KNOWN_MODEL_SLUGS` tuple and its provenance comment; any flag, sandbox, grammar or event drift step 3 found |
| `tests/test_codex_contract.py`, `tests/test_codex_config.py` | the literals that stand for the supported set or the current version |
| `docs/codex-help/<new-version>/` | the capture, written by `uv run python scripts/check_backend_compat.py --write` or by step 2's `compare --write` from the binary you verified, so the next upgrade can authenticate its baseline against it |
| `CHANGELOG.md` | an entry under `## [Unreleased]` |

Leave the release version literals alone; AGENTS.md rule 19 moves them only in a `chore(release):` PR.

## 5. `FINGERPRINT` and breaking changes

A codex upgrade usually changes nothing an MCP client can observe.
Adding a minor, refreshing a warning, adding a signature for an existing error code and updating tests or docs all leave the discovery surface unchanged, so `FINGERPRINT` stays.

A codex change moves it only when you carry the change into amicus's surface, touching a category in `FINGERPRINT_COVERS` (`src/amicus/schemas/fingerprint.py`).
Then AGENTS.md rule 10 applies: bump `FINGERPRINT` and regenerate the pins under `tests/fixtures/` in their own commit.
After the bump, `uv run python scripts/regenerate_fingerprint_pins.py` writes every pin it moves (each profile's manifest snapshot, `tests/fixtures/fingerprint_pins.json` and, when its output changed, the wire-shape snapshot) and prints the diff to review before you commit.
It refuses unless `FINGERPRINT` has advanced past its value at the merge-base with `origin/main`, and `--check` only reports stale pins without writing.
It does not move `RESULT_FORMAT`, the result-format snapshot or the discovery-cost budget: it reports their drift, and each stays a deliberate decision of its own.
Whether that change is also breaking is a separate question, and `CHANGELOG.md`'s lead defines the **Breaking** and **Surface** labels.

## 6. Verify and open the PR

```sh
uv run python scripts/check_backend_compat.py   # codex now passes the version check
```

Then run the gate, which AGENTS.md rule 2 defines.
The live gate, `tests/test_codex_live.py`, is the end-to-end proof against the new binary, but it spends quota, so it runs only under AGENTS.md rule 5, when the maintainer asks; a support PR that did not run it says so.

Title the PR `chore(backends): support codex-cli <major>.<minor>` and close the tracking issue from it.
Its body says what was checked and against which version, what was not checked, and the gate's result, as #294 and #353 do.

## Gotchas this procedure guards against

- A flag stays in `--help` while its meaning changes, which only step 3 can catch.
- A guarantee-bearing flag disappears and someone moves it to `HELP_GATED_FLAGS` to quiet the failure, which silently drops the guarantee; an `ALWAYS_SEND_FLAGS` failure fails loud by design.
- A help formatting change produces a false parser result, so confirm a `FAIL` or `FLAGS DIFFER` against the raw `--help` text before acting on it.
- A stderr wording change makes a genuine contract break classify as `nonzero_exit`, or a broad pattern such as `429` masks a more specific cause.
- A JSONL change moves error text or usage keys, and tolerant parsing degrades the metadata without failing.
- A surface nobody captured reads as unchanged because nobody looked; the comparison against the previous binary is what lets you ask a question the captures do not already answer.
- A long-lived amicus server caches `codex exec --help` for `HELP_CACHE_TTL_SECONDS`, so after an in-place upgrade it re-probes only once that lapses; restart it when validating.
