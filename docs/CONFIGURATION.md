# Configuration reference

Every environment variable amicus reads, rendered from its declaration in the code by `scripts/render_configuration_doc.py`; edit the declaration, not this file.
A value is read once at startup.
`AMICUS_BACKENDS` is the one most installs set; see the README for where a client sets environment variables.
Former sibling names are listed in `docs/MIGRATION.md` and are not read.

## Server

### `AMICUS_BACKENDS`

Comma-separated enabled backends; unset, every in-tree backend is enabled.
Unset by default.

### `AMICUS_TIMEOUT_SECONDS`

Default sync deadline (10-600).
Default: `300`.
Former names, no longer read: `CODEX_IN_CLAUDE_TIMEOUT_SECONDS`, `MOONBRIDGE_TIMEOUT_SECONDS`, `CLAUDE_IN_CODEX_TIMEOUT_SECONDS`.

### `AMICUS_MAX_INPUT_BYTES`

Byte budget applied independently to the caller-input sum and to the gathered diff (the diff is truncated on excess, not rejected).
Default: `200000`.
Former names, no longer read: `CODEX_IN_CLAUDE_MAX_INPUT_BYTES`, `MOONBRIDGE_MAX_INPUT_BYTES`, `CLAUDE_IN_CODEX_MAX_INPUT_BYTES`.

### `AMICUS_JOB_TTL`

Seconds a terminal job record is retained.
Default: `86400`.
Former names, no longer read: `CODEX_IN_CLAUDE_JOB_TTL`, `MOONBRIDGE_JOB_TTL`, `CLAUDE_IN_CODEX_JOB_TTL`.

### `AMICUS_JOB_MAX_SECONDS`

Background job wall-clock cap (60-7200).
Default: `1800`.
Former names, no longer read: `CODEX_IN_CLAUDE_JOB_MAX_SECONDS`, `MOONBRIDGE_JOB_MAX_SECONDS`, `CLAUDE_IN_CODEX_JOB_MAX_SECONDS`.

### `AMICUS_JOB_MAX_COUNT`

Retained job records per workspace (1-1000).
Default: `50`.
Former names, no longer read: `CODEX_IN_CLAUDE_JOB_MAX_COUNT`, `MOONBRIDGE_JOB_MAX_COUNT`, `CLAUDE_IN_CODEX_JOB_MAX_COUNT`.

### `AMICUS_MAX_OUTPUT_BYTES`

Byte ceiling for a backend process's captured stdout+stderr (head+tail kept).
Default: `10485760`.
Former names, no longer read: `CODEX_IN_CLAUDE_MAX_OUTPUT_BYTES`, `MOONBRIDGE_MAX_OUTPUT_BYTES`, `CLAUDE_IN_CODEX_MAX_OUTPUT_BYTES`.

### `AMICUS_MAX_DELEGATE_DIFF_BYTES`

Byte cap for the diff a delegate returns inline (diffstat stays whole).
Default: `200000`.
Former names, no longer read: `CODEX_IN_CLAUDE_MAX_DELEGATE_DIFF_BYTES`, `MOONBRIDGE_MAX_DELEGATE_DIFF_BYTES`, `CLAUDE_IN_CODEX_MAX_DELEGATE_DIFF_BYTES`.

### `AMICUS_GIT_TIMEOUT_SECONDS`

Per-git-command timeout for diff gathering and worktrees (1-3600).
Default: `60`.
Former names, no longer read: `CODEX_IN_CLAUDE_GIT_TIMEOUT_SECONDS`, `MOONBRIDGE_GIT_TIMEOUT_SECONDS`, `CLAUDE_IN_CODEX_GIT_TIMEOUT_SECONDS`.

### `AMICUS_STATE_DIR`

Absolute directory for job records; unset, it is `$XDG_CACHE_HOME/amicus/jobs`, or `~/.cache/amicus/jobs` when `XDG_CACHE_HOME` is not an absolute path.
Unset by default.

### `AMICUS_LOG_LEVEL`

Diagnostic log level (stderr).
Default: `WARNING`.
Former names, no longer read: `CODEX_IN_CLAUDE_LOG_LEVEL`, `MOONBRIDGE_LOG_LEVEL`.

### `AMICUS_LOG_FILE`

Optional file mirroring the stderr log.
Unset by default.
Former names, no longer read: `CODEX_IN_CLAUDE_LOG_FILE`, `MOONBRIDGE_LOG_FILE`.

### `AMICUS_TASKS`

`1` to register the paid sync tools with the tasks extension.
Default: `0`.

### `AMICUS_TASKS_BACKEND_URL`

Docket backend for the tasks extension (memory:// or redis://).
Default: `memory://`.

### `AMICUS_HOST_NAME`

Override the host name used in prompt framing.
Unset by default.

### `AMICUS_ALLOW_CWD_WORKSPACE`

`1` to allow falling back to the server cwd (disclosed).
Default: `0`.

## Codex

### `AMICUS_CODEX_BIN`

Absolute path to the codex executable; used exactly as given.
Unset by default.
Former names, no longer read: `CODEX_IN_CLAUDE_CODEX_BIN`.

### `AMICUS_CODEX_EXTRA_ARGS`

Operator-only extra global codex options (-c/--config, -p/--profile, --enable/--disable) added to every paid run; allowlisted, never echoed.
Unset by default.
Former names, no longer read: `CODEX_IN_CLAUDE_EXTRA_ARGS`.

### `AMICUS_CODEX_MODEL`

Default model slug when a call omits `model`.
Unset by default.
Former names, no longer read: `CODEX_IN_CLAUDE_MODEL`.

### `AMICUS_CODEX_REASONING_EFFORT`

Default reasoning effort when a call omits `reasoning_effort`.
Unset by default.
Former names, no longer read: `CODEX_IN_CLAUDE_REASONING_EFFORT`.

### `AMICUS_CODEX_ISOLATION`

Default backend_options.isolation: inherit | ignore-config | ignore-rules.
Default: `inherit`.
Former names, no longer read: `CODEX_IN_CLAUDE_ISOLATION`.

### `AMICUS_CODEX_SUPPORTED_VERSIONS`

Comma-separated codex major.minor versions treated as supported (advisory).
Unset by default.
Former names, no longer read: `CODEX_IN_CLAUDE_SUPPORTED_VERSIONS`.

## Kimi

### `AMICUS_KIMI_BIN`

Absolute path to the kimi executable; used exactly as given.
Unset by default.

### `AMICUS_KIMI_EXTRA_ARGS`

Operator passthrough of extra kimi options; kimi exposes no option amicus can pass safely, so any value is refused and reported by `amicus_backends`.
Unset by default.
Former names, no longer read: `MOONBRIDGE_EXTRA_ARGS`.

### `AMICUS_KIMI_MODEL`

Default model ALIAS (from kimi's config.toml) when a call omits `model`.
Unset by default.
Former names, no longer read: `MOONBRIDGE_MODEL`.

### `AMICUS_KIMI_REASONING_EFFORT`

Default reasoning effort when a call omits `reasoning_effort`.
Unset by default.
Former names, no longer read: `MOONBRIDGE_REASONING_EFFORT`.

### `AMICUS_KIMI_ISOLATION`

Default backend_options.isolation: inherit | ignore-skills.
Default: `inherit`.
Former names, no longer read: `MOONBRIDGE_ISOLATION`.

### `AMICUS_KIMI_SUPPORTED_VERSIONS`

Comma-separated kimi major.minor versions treated as supported (advisory).
Unset by default.
Former names, no longer read: `MOONBRIDGE_SUPPORTED_VERSIONS`.

## Claude

### `AMICUS_CLAUDE_BIN`

Absolute path to the claude executable; used exactly as given.
Unset by default.

### `AMICUS_CLAUDE_CONFIG_MODE`

Default backend_options.config_mode: inherit | scoped | safe | bare.
Adversarial reviews default to safe even when inherit/scoped is configured, or bare when bare is configured.
Explicit per-call config_mode overrides apply.
Default: `inherit`.
Former names, no longer read: `CLAUDE_IN_CODEX_CLAUDE_CONFIG`.

### `AMICUS_CLAUDE_ACCESS`

Default `backend_options.access`: toolless | readonly.
Unset, `amicus_review_changes` runs readonly and every other verb runs the declared default, toolless.
Set to any value, even toolless, that value applies to every verb, including reviews.
Default: `toolless`.
Former names, no longer read: `CLAUDE_IN_CODEX_ACCESS`.

### `AMICUS_CLAUDE_MODEL`

Default model slug when a call omits `model`.
Unset by default.
Former names, no longer read: `CLAUDE_IN_CODEX_MODEL`.

### `AMICUS_CLAUDE_REASONING_EFFORT`

Default reasoning effort when a call omits `reasoning_effort`: low | medium | high | xhigh | max.
Default: `xhigh`.
Former names, no longer read: `CLAUDE_IN_CODEX_EFFORT`.

### `AMICUS_CLAUDE_MAX_BUDGET_USD`

Default backend_options.max_budget_usd (0.01-5.00), a best-effort stop threshold checked between model calls.
Default: `1.0`.
Former names, no longer read: `CLAUDE_IN_CODEX_MAX_BUDGET_USD`.

### `AMICUS_CLAUDE_SUPPORTED_MAJORS`

Comma-separated claude major versions treated as supported (advisory).
Unset by default.
Former names, no longer read: `CLAUDE_IN_CODEX_SUPPORTED_MAJORS`.
