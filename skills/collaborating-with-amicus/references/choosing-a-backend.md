# Choosing a backend

`backend` is required on every paid amicus tool and has no default — pick it deliberately for each
call. It names a **harness**, the CLI that runs the call, not a model: `codex` runs OpenAI models,
`claude` runs Anthropic models, `pi` runs any provider's model it lists by exact `provider/id`,
and the deprecated `kimi` runs whatever its own configuration names. Three questions decide a
call: **which harness and model the request means**, **is that route eligible**, and **can it
actually see the evidence the task needs**.

## Rules

Eligibility, freshness and authority are governed by SKILL.md → Binding rules → Discovery, the
`access` and `config_mode` decision by SKILL.md → Binding rules → Scope and inputs, and what
may be sent to `kimi` by SKILL.md → Binding rules → Data exposure; they are not restated here.
These are this file's own:

- **Resolve the harness and the model by the routing procedure below before choosing the verb.**
- **Never spend a paid call to break a tie** between backends that are equally suitable.
- **Compare resolved models, never backend ids, when you claim diversity.** Two calls are
  different models only when their resolved `provider/id` (or, off `pi`, the model each harness
  reports running) differ; never claim two different model families without evidence of the
  underlying models.
- **Never inspect a user's provider configuration to establish model identity or what `pi` can
  reach.** Report the diversity as unverified instead, and read `pi`'s reach from
  `amicus_models(backend="pi")`.
- **For `pi`, pass `model` as an exact `provider/id` that `amicus_models(backend="pi")` lists,
  unless `AMICUS_PI_MODEL` is set and is the model you mean.**
- **Put the project's constraints in a `pi` brief yourself.** pi runs with
  `--no-context-files`, so it loads no `AGENTS.md`.

### Routing procedure

Binding: SKILL.md → Binding rules → Routing states it in short; this is the full procedure.
Run it after the free discovery calls and before choosing the verb.

1. **A named harness wins.** A backend id or CLI name — `codex`, `claude` or Claude Code, `pi`,
   and bare `kimi`, which still means the deprecated kimi harness — selects that harness.
   Capitalization changes nothing. A model named alongside it is passed as that harness's
   `model`. An exact `provider/id` is pi's own model syntax, so it selects `pi` the same way.
2. **A model-only request** — GPT, Opus, Sonnet, Kimi K3 — goes to the native harness for that
   family when it is ready and supports the verb: `codex` for OpenAI models, `claude` for
   Anthropic models. A family with neither, or a request whose native harness is not ready or
   lacks the verb, goes to `pi` with an exact model `amicus_models(backend="pi")` lists. That is
   routing, not substitution: no confirmation is needed, but name the harness, the model and
   the provider before the paid call.
3. **Never substitute for a named harness silently.** When the harness the user named is not
   ready or lacks the verb, say so and offer the alternative route — `pi` plus an exact listed
   model — naming its provider (the `provider/id` prefix, which may be a router) and its
   containment (pi has no OS sandbox, and a pi delegate has no network block). Proceed only
   when the user chooses it. Every route offered or taken must support the requested verb: when
   none does, as for an adversarial review with `claude` not ready, report that no eligible
   route exists; changing the verb is a separate choice for the user.
4. **Learn what `pi` can reach from `amicus_models(backend="pi")`**, never from provider
   configuration. A missing or truncated listing does not prove a model unreachable; it means
   you cannot vouch for it, so say that rather than calling it unavailable.
5. **Ask once, before spending,** only when the routes that still match after free discovery
   differ in spend, exposure, containment or verb. Otherwise take the one route left.

Worked examples, each after `amicus_backends(detail="full")`:

| Request | Route |
| --- | --- |
| "collaborate with codex" | `codex`; its default model unless one is named |
| "ask kimi" | the `kimi` harness, disclosing its deprecation and that `pi` is the replacement; not a Kimi model through `pi` |
| "get GPT's opinion" | `codex` when it is ready; otherwise `pi` with a listed OpenAI `provider/id`, named before the call |
| "collaborate with codex" while `codex` is not ready | say so and offer `pi` with a listed OpenAI `provider/id`, proceeding only on the user's choice |
| "use Opus" | `claude` when it is ready and supports the verb, deciding `access` up front, because a `claude` consult defaults to `toolless` and cannot read the repository; otherwise `pi` with a listed Anthropic `provider/id`, named before the call. A delegate is not on `claude`, so it goes to `pi` the same way |
| "have Claude adversarially review this" while `claude` is not ready | no eligible route: only `claude` has `adversarial_review`, so say so rather than switching harness or verb |
| "use `<provider>/<id>`" (an exact `provider/id`) | `pi`, as a named harness, with that `model`, once `amicus_models(backend="pi")` lists it; its egress is the provider the prefix names, which may be a router rather than the model's vendor |
| "use Kimi K3" | a model-only request with no native harness among `codex` and `claude`, so `pi` with a listed `provider/id` for it; the `kimi` harness only when the user names `kimi` |

## `kimi` is deprecated

`kimi` is deprecated in favour of `pi`, since 0.13.0, and is removed in 0.15.0 or later. It still
works, so a call already routed to it need not fail, but prefer `pi` for new work: it serves the
same verbs (`consult`, `review_changes`, `delegate`) and can run the same model when
`AMICUS_PI_MODEL` names it as an exact `provider/id`. The `deprecation` marker on kimi's
`amicus_backends` entry, and `meta.deprecation` on every kimi result, carry the window and the
migration text; treat that marker, not this file, as authoritative.

## What `amicus_backends` reports

Per backend: `enabled` (turned on for this deployment), `available` (the plugin loaded),
`status.installed`, `status.authenticated`, `status.warnings`, `features` (the gated verbs it
supports plus its extra capabilities — see below), `effects` (`paid_calls_destructive`,
`job_reads_read_only`), `options` (backend-specific knobs and their allowed values),
`egress`/`carriers` (how prompt inputs travel), `readonly_honesty` (what this backend's read-only
tier does and does not bound), `implicit_context` (what the CLI auto-loads regardless of your
prompt), and `deprecation` (a marker on a deprecated backend, `null` otherwise, at every detail).
The four before `deprecation` are on `detail="full"` only: the default `summary` leaves those keys out of
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

These gates belong to harnesses, not models: an Anthropic model run through `pi` can delegate and
still has no `adversarial_review`.

## What each backend can inspect

A backend answers from what it can read. These differ enough to change which one is right for a
task, and one default surprises people:

| | Reads the repo during a call? | Default |
| --- | --- | --- |
| `codex` | Yes — under codex's `--sandbox read-only` OS sandbox | read-only sandbox |
| `kimi` | Yes — a generated agent profile grants `Read`, `Glob`, `Grep` and no shell or write tool | read-only profile |
| `pi` | Yes — `--tools read,grep,find,ls`, so no shell, edit or write tool; pi has no OS sandbox, and at startup it renames a workspace's `.pi/commands/` to `.pi/prompts/` when the latter does not exist, even on a consult or review | read-only tool allowlist; needs an exact `provider/id` model |
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

Most backends also load context you did not supply — `AGENTS.md`, skills, and on `claude` under
`inherit`/`scoped`, workspace hooks that run outside the tool allowlist. `pi` is the exception
for project context: it runs with `--no-context-files --no-skills --no-extensions --no-mcp`, so
it loads no `AGENTS.md`, while its user-level settings, its `models.json` (whose `!command`
values pi runs) and its credentials still load; put the project's constraints in the brief.
`implicit_context` on `amicus_backends(detail="full")` is the authoritative per-backend
statement.

## Judgment call: which backend for a consult or review

Beyond the feature gate and the evidence question, amicus does not rank backends. Weigh:

- **Model diversity, carefully.** Different backend IDs do **not** establish different model
  families, and the same backend id can run different models: compare the resolved `provider/id`
  on `pi`, and the model each harness reports otherwise. `pi` running an Anthropic model beside
  `claude` is one family through two harnesses. Kimi routes to whatever OpenAI-compatible provider its `config.toml` names, and its
  `model` argument is a configuration alias — `amicus_models` exposes aliases and display labels,
  never verified provider identity. When you have reliable, non-sensitive information about the
  underlying models, weigh family diversity alongside task fit; when you do not, record the
  diversity as **unverified** rather than assuming it. Separate attempts and complementary review
  scopes are still useful without it — they just do not establish independence or correctness on
  their own.
- **Pi's model is yours to name.** `pi` has no default model: it uses `AMICUS_PI_MODEL` or the
  call's `model`, an exact `provider/id`, and refuses the call before it spends when neither is
  set. Until `AMICUS_PI_MODEL` is set, `status.authenticated` is unknown (`null`) rather than
  false, and a call with a listed `model` is still eligible. The model's provider prefix, a
  router included, decides where the prompt goes, and `amicus_models` lists only models of
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
