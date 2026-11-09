# Choosing a backend

`backend` is required on every paid amicus tool and has no default — pick it deliberately for each
call. Two questions decide it: **is this backend eligible**, and **can it actually see the
evidence the task needs**.

## Rules

Eligibility, freshness and authority are governed by SKILL.md → Binding rules → Discovery, the
`access` and `config_mode` decision by SKILL.md → Binding rules → Scope and inputs, and what
may be sent to `kimi` by SKILL.md → Binding rules → Data exposure; they are not restated here.
These are this file's own:

- **Never spend a paid call to break a tie** between backends that are equally suitable.
- **Never claim two backends are different model families** unless you have evidence of the
  underlying models.
- **Never inspect a user's provider configuration to establish model identity.** Report the
  diversity as unverified instead.

## What `amicus_backends` reports

Per backend: `enabled` (turned on for this deployment), `available` (the plugin loaded),
`status.installed`, `status.authenticated`, `status.warnings`, `features` (the gated verbs it
supports plus its extra capabilities — see below), `effects` (`paid_calls_destructive`,
`job_reads_read_only`), `options` (backend-specific knobs and their allowed values),
`egress`/`carriers` (how prompt inputs travel), `readonly_honesty` (what this backend's read-only
tier does and does not bound), and `implicit_context` (what the CLI auto-loads regardless of your
prompt). The last four are on `detail="full"` only: the default `summary` leaves those keys out of
every entry and lists them in the top-level `omitted_fields`, so an absent key means "not
requested", while a `null` on `full` means no loaded plugin declares one (the backend declares
none, or its plugin did not load). `summary` is enough for a readiness re-check once the full
report has been read.

`AMICUS_BACKENDS` decides which backends exist in this deployment; it does not decide which to
prefer.

## What `features` contains

`features` is not the list of verbs a backend answers. It names the gated verbs the backend
declares, plus capabilities that are not verbs at all:

- `delegate` and `adversarial_review` — the gated verbs. A call routing one to a backend outside
  the tool's `backend` enum, in-tree or not, is rejected pre-spend as `invalid_arguments` with
  `details.allowed_values` (the enum is the accepted set); `feature_unsupported` is only a
  defensive check, returned if the named backend's declared features lack the verb, which no
  backend a tool's enum accepts does today.
- `usage_accounting` — the backend's CLI reports token usage, carried as `meta.usage`.
- `model_validation` and `empty_response_detection` — the backend can refuse an unknown `model`
  (`invalid_model`) and report a reply with no content (`empty_response`).

`consult` and `review_changes` are baseline on every backend and never appear in `features`. A
host that looks for them there concludes, wrongly, that no backend supports them (issue #84).

The gates:

- `amicus_consult` / `amicus_review_changes`: `codex`, `kimi`, `claude`, `pi`; never gated.
- `amicus_delegate`: `codex`, `kimi`, `pi` only. Claude is outside the tool's `backend` enum, so a
  delegate routed to it is rejected as `invalid_arguments`, never `feature_unsupported`.
- `amicus_adversarial_review`: `claude` only.

## What each backend can inspect

A backend answers from what it can read. These differ enough to change which one is right for a
task, and one default surprises people:

| | Reads the repo during a call? | Default |
| --- | --- | --- |
| `codex` | Yes — under codex's `--sandbox read-only` OS sandbox | read-only sandbox |
| `kimi` | Yes — a generated agent profile grants `Read`, `Glob`, `Grep` and no shell or write tool | read-only profile |
| `pi` | Yes — `--tools read,grep,find,ls`, so no shell, edit or write tool; pi has no OS sandbox | read-only tool allowlist; needs an exact `provider/id` model |
| `claude` | **Reviews only, by default.** `amicus_review_changes` defaults to `access="readonly"` (`Read`, `Grep`, `Glob`); consult and adversarial review default to `access="toolless"`, which grants **no tools at all** | `access="readonly"` for reviews and `"toolless"` otherwise, `config_mode="inherit"` |

**A `claude` consult told to "look at the file and tell me what's wrong" has, by default, no
tool with which to look.** Either supply the evidence inline (`question`, `extra_context`) or pass
`backend_options: {"access": "readonly"}` deliberately — which grants `Read`, `Grep`, `Glob`.

An operator who sets `AMICUS_CLAUDE_ACCESS` sets the default for every verb, reviews included,
so read the resolved value on `amicus_backends` (`default` or `default_by_verb`) rather than
assuming a review can read the repository.

`toolless` is not isolation. It removes the model's tools; it does not stop the CLI loading
context on its own. Under the default `config_mode="inherit"` (and under `scoped`) claude still
reads the workspace's `CLAUDE.md` and `.claude/settings*.json`, hooks included — and hooks run
outside the tool allowlist. What the backend receives is therefore your prompt *plus* whatever
that mode loads, which `implicit_context` states per backend.

Read-only bounds *modification*, never *reach*, on any of the four. Codex's sandbox bounds
writes, not reads; kimi's `Read` accepts absolute paths; pi can read files outside the workspace; Claude's `readonly` accepts absolute
paths too and, having read a file itself, bypasses the diff redaction entirely. The workspace
selects where a backend works, not what it can read — `readonly_honesty` on `amicus_backends(detail="full")` is
each backend's own statement of that limit.

## How your text reaches each backend

Amicus's own transport is the same for all four: free-text fields never touch its logs, and for
an async job they reach the worker over stdin. How a field reaches the *backend CLI* is the
backend's own choice, and `carriers` on `amicus_backends(detail="full")` is authoritative. Today:

| | Prompt carrier | `instructions_append` | Exposure to note |
| --- | --- | --- | --- |
| `codex` | stdin | **argv**, as the `-c developer_instructions` override | Visible to any local process listing for the run's duration — never put a secret here |
| `claude` | stdin | stdin | argv carries only fixed text and flags |
| `pi` | stdin | stdin | argv carries only a fixed system prompt, the model, the effort and flags. With `--no-session` pi wrote no session file on 1.5.0, so there is no store of its own to disclose |
| `kimi` | a file in a private temp dir outside the workspace; argv carries only its path | same file | Nothing you type rides argv. amicus removes its temp directory when the run ends, but the kimi CLI also writes its own session store (observed under `~/.kimi-code/sessions`), which can hold the whole prompt and any answer produced; amicus does not delete it, and job expiry, the per-workspace cap and `amicus_job_consume_result` never touch it |

Each backend also loads context you did not supply — `AGENTS.md`, skills, and on `claude` under
`inherit`/`scoped`, workspace hooks that run outside the tool allowlist. `implicit_context` on
`amicus_backends(detail="full")` is the authoritative per-backend statement.

## Judgment call: which backend for a consult or review

Beyond the feature gate and the evidence question, amicus does not rank backends. Weigh:

- **Model diversity, carefully.** Different backend IDs do **not** establish different model
  families. Kimi routes to whatever OpenAI-compatible provider its `config.toml` names, and its
  `model` argument is a configuration alias — `amicus_models` exposes aliases and display labels,
  never verified provider identity. When you have reliable, non-sensitive information about the
  underlying models, weigh family diversity alongside task fit; when you do not, record the
  diversity as **unverified** rather than assuming it. Separate attempts and complementary review
  scopes are still useful without it — they just do not establish independence or correctness on
  their own.
- **Pi's model is yours to name.** `pi` has no default model: it uses `AMICUS_PI_MODEL` or the
  call's `model`, an exact `provider/id`, and refuses the call before it spends when neither is
  set. Until `AMICUS_PI_MODEL` is set, `status.authenticated` is unknown rather than false. The
  model's provider prefix decides where the prompt goes, and `amicus_models` lists only models of
  providers pi holds credentials for. An unknown id is `invalid_model`, refused pre-spend because pi
  would send it anyway, where `kimi` rejects an unknown alias itself. A provider API key reaches pi only if
  the host forwards it to the amicus server; credentials saved by pi's `/login` need nothing.
- **Task shape.** A broad architectural question benefits from strong general reasoning; a narrow
  mechanical review benefits more from speed and cost. `amicus_models` lists each backend's
  advertised models and reasoning-effort sets.
- **What is usable right now.** A backend that is enabled but unauthenticated, rate limited, or
  reporting `status.warnings` is not a good choice however well suited it looks.
- **Effects.** Approval friction follows the worst *enabled* backend, not the one you pick for
  this call (SKILL.md → Annotations follow the worst enabled backend). Picking a different
  `backend` does not change it, and `effects` is a static per-backend declaration rather than a
  statement about your call.

When none of these distinguishes the eligible backends, pick any ready, eligible one.
