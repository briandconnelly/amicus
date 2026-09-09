# Choosing a backend

`backend` is required on every paid amicus tool and has no default — pick it deliberately for each
call. Two questions decide it: **is this backend eligible**, and **can it actually see the
evidence the task needs**.

## Rules

- **Call `amicus_backends` (free) before choosing**, and pick only among backends it reports
  `enabled: true`, `status.installed: true`, and `status.authenticated: true`.
- **Confirm the verb appears in that backend's `features` list.**
- **Treat the live `amicus_backends` report as authoritative** wherever it disagrees with this
  file.
- **Re-read it rather than reusing an assumption** from earlier in the session.
- **Decide what evidence the call needs before choosing `access`**, and supply that evidence in
  the request rather than widening a backend's permissions to compensate.
- **Never spend a paid call to break a tie** between backends that are equally suitable.
- **Never claim two backends are different model families** unless you have evidence of the
  underlying models.

## What `amicus_backends` reports

Per backend: `enabled` (turned on for this deployment), `available` (the plugin loaded),
`status.installed`, `status.authenticated`, `status.warnings`, `features` (the verbs it supports),
`effects` (`paid_calls_destructive`, `job_reads_read_only`), `options` (backend-specific knobs and
their allowed values), `egress`/`carriers` (how prompt inputs travel), `readonly_honesty` (what
this backend's read-only tier does and does not bound), and `implicit_context` (what the CLI
auto-loads regardless of your prompt).

`AMICUS_BACKENDS` decides which backends exist in this deployment; it does not decide which to
prefer.

## Feature gates in v1

- `amicus_consult` / `amicus_review_changes`: `codex`, `kimi`, `claude`.
- `amicus_delegate`: `codex`, `kimi` only. Claude stays review-only — a delegate call routed to
  `claude` fails the feature gate.
- `amicus_adversarial_review`: `claude` only.

## What each backend can inspect

A backend answers from what it can read. These differ enough to change which one is right for a
task, and one default surprises people:

| | Reads the repo during a call? | Default |
| --- | --- | --- |
| `codex` | Yes — under codex's `--sandbox read-only` OS sandbox | read-only sandbox |
| `kimi` | Yes — a generated agent profile grants `Read`, `Glob`, `Grep` and no shell or write tool | read-only profile |
| `claude` | **Only if you ask.** `access="toolless"` is the default and grants **no tools at all** | `access="toolless"`, `config_mode="inherit"` |

**A `claude` consult told to "look at the file and tell me what's wrong" has, by default, no way
to look at anything.** It answers from your prompt alone. Either supply the evidence inline
(`question`, `extra_context`) or pass `backend_options: {"access": "readonly"}` deliberately —
which grants `Read`, `Grep`, `Glob`.

Read-only bounds *modification*, never *reach*, on any of the three. Codex's sandbox bounds
writes, not reads; kimi's `Read` accepts absolute paths; Claude's `readonly` accepts absolute
paths too and, having read a file itself, bypasses the diff redaction entirely. The workspace
selects where a backend works, not what it can read — `readonly_honesty` on `amicus_backends` is
each backend's own statement of that limit.

## How your text reaches each backend

Amicus's own transport is the same for all three: free-text fields never touch its logs, and for
an async job they reach the worker over stdin. How a field reaches the *backend CLI* is the
backend's own choice, and `carriers` on `amicus_backends` is authoritative. Today:

| | Prompt carrier | `instructions_append` | Exposure to note |
| --- | --- | --- | --- |
| `codex` | stdin | **argv**, as the `-c developer_instructions` override | Visible to any local process listing for the run's duration — never put a secret here |
| `claude` | stdin | stdin | argv carries only fixed text and flags |
| `kimi` | a file in a private temp dir outside the workspace; argv carries only its path | same file | Nothing you type rides argv, but the text is briefly on local disk; amicus removes the directory when the run ends |

Each backend also loads context you did not supply — `AGENTS.md`, skills, and on `claude` under
`inherit`/`scoped`, workspace hooks that run outside the tool allowlist. `implicit_context` on
`amicus_backends` is the authoritative per-backend statement.

## Judgment call: which backend for a consult or review

Beyond the feature gate and the evidence question, amicus does not rank backends. Weigh:

- **Model diversity, carefully.** Different backend IDs do **not** establish different model
  families. Kimi routes to whatever OpenAI-compatible provider its `config.toml` names, and its
  `model` argument is a configuration alias — `amicus_models` exposes aliases and display labels,
  never verified provider identity. When you have reliable, non-sensitive information about the
  underlying models, weigh family diversity alongside task fit; when you do not, record the
  diversity as **unverified** rather than assuming it. Do not go inspecting a user's provider
  configuration to strengthen the claim. Separate attempts and complementary review scopes are
  still useful without it — they just do not establish independence or correctness on their own.
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
