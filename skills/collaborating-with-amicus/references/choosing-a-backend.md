# Choosing a backend

`backend` is required on every paid amicus tool and has no default — pick it deliberately for each
call. It names a **harness**, the CLI that runs the call, not a model: `codex` runs OpenAI models,
`claude` runs Anthropic models, and `pi` runs any provider's model it lists by exact `provider/id`. Three questions decide a
call: **which harness and model the request means**, **is that route eligible**, and **can it
actually see the evidence the task needs**.

## Rules

SKILL.md → Binding rules → Required reading sends you here before a paid call routed to `pi`, before choosing among several routes, and before a call that needs the backend to read
files or sets `backend_options`. Eligibility, the routing procedure and model-diversity claims
are governed by SKILL.md → Binding rules → Discovery, Routing and Composed workflows, the
`access` and `config_mode` decision by Scope and inputs, and data exposure by Data
exposure; they are not restated here. These are this file's own:

- **Never spend a paid call to break a tie** between backends, or between models on one
  backend, that are equally suitable.
- **For `pi`, pass `model` as an exact `provider/id` that `amicus_models(backend="pi")` lists,
  or, when that listing is `truncated`, one past its cut that you know exactly, unless
  `AMICUS_PI_MODEL` is set and is the model you mean.** pi checks the exact model and its
  `reasoning_effort` pre-spend either way, and refuses one it cannot resolve.
- **For a `pi` model whose row lists only `off`, pass `reasoning_effort: "off"` explicitly.**
  It is a non-thinking model: amicus refuses any other value pre-spend, and omitting it inherits
  `AMICUS_PI_REASONING_EFFORT`.
- **Put the project's constraints in a `pi` brief yourself.** pi runs with
  `--no-context-files`, so it loads no `AGENTS.md`.
- **Never trial a candidate `pi` model outside amicus**, through a provider's inference API
  or any other tool that runs a model.
- **Never put the user's text into a provider's catalog or search tool.**
- **Take a candidate's price and terms from its provider's catalog as read in this session,
  never from memory**, and say which facts you could not establish rather than supplying them.
- **Read `context_tokens` and `max_output_tokens` as a screen with headroom, never as proof a
  call fits, and never read a `null` as evidence that it does.**

## Worked routes

SKILL.md → Binding rules → Routing is the procedure; this table only applies it.
Worked examples, each after `amicus_backends(detail="full")`:

| Request | Route |
| --- | --- |
| "collaborate with codex" | `codex`; its default model unless one is named |
| "ask kimi" | the removed `kimi` harness; explain its removal and offer `pi` with an exact listed model, proceeding only when the user chooses it |
| "get GPT's opinion" | `codex` when it is ready; otherwise `pi` with a listed OpenAI `provider/id`, named before the call |
| "collaborate with codex" while `codex` is not ready | say so and offer `pi` with a listed OpenAI `provider/id`, proceeding only on the user's choice |
| "use Opus" | `claude` when it is ready and supports the verb, deciding `access` up front, because a `claude` consult defaults to `toolless` and cannot read the repository; otherwise `pi` with a listed Anthropic `provider/id`, named before the call. A delegate is not on `claude`, so it goes to `pi` the same way |
| "have Claude adversarially review this" while `claude` is not ready | no eligible route: only `claude` has `adversarial_review`, so say so rather than switching harness or verb |
| "use `<provider>/<id>`" (an exact `provider/id`) | `pi` with that `model`, once `amicus_models(backend="pi")` lists it; its egress is the provider the prefix names, which may be a router rather than the model's vendor, or the endpoint pi's `models.json` sets for it |
| "ask pi to use `<provider>/<id>`" | `pi`, the named harness, with that `model`: the two selectors agree |
| "ask codex to use `<provider>/<id>`", `codex` is ready and supports the verb, and `amicus_models(backend="codex")` lists that exact id | `codex`, as the named harness, with that `model` |
| "ask codex to use `<provider>/<id>`", and that listing does not show the id | no call yet: say the `codex` listing does not confirm the pair; where `amicus_models(backend="pi")` lists that exact id and `pi` supports the verb, offer `pi` with it, naming its provider and containment, and proceed only on the user's choice; where it does not, report that no confirmed route exists |
| "use Kimi K3" | `pi` with a listed `provider/id` for that model, named before the call |

## Choosing among pi's listed models

`amicus_models(backend="pi")` can list several hundred rows, and amicus does not rank them. When
the user named a model, SKILL.md → Binding rules → Routing has already chosen; this section is
for the request that names none ("a cheap second opinion", "something that is not you").

What the listing establishes, and what it does not:

| Question | Source |
| --- | --- |
| Which exact `provider/id` pi can call, and its effort vocabulary | the row's `slug` and `supported_reasoning_efforts` |
| Roughly how much the model accepts and can return | the row's `context_tokens` and `max_output_tokens` |
| Where the prompt goes | the `provider/` prefix, which may be a router rather than the model's vendor, unless pi's `models.json` overrides that provider's `baseUrl` |
| Price, rate limits, retention terms, how good the model is at the task | the provider's own catalog; amicus carries none of it |

- **Token limits are approximate on `pi`.** pi prints them rounded, so a value in the
  thousands is within about 50 tokens of pi's own figure and one in the millions within about
  50,000. What a call sends is more than the text supplied: amicus's framing, the gathered
  diff, files pi reads for itself, and the answer all count against the same limits.
  `amicus_review_changes_dry_run` reports a review's `prompt_bytes` for free, in bytes rather
  than tokens. `null` is unknown, neither zero nor unlimited, and other backends report `null`
  today.
- **An effort a row lists is advertised, not guaranteed.** A thinking model's row lists pi's
  whole vocabulary; where the model lacks the level passed, pi runs another and the result
  says so on `meta.security_warnings`. An omitted `reasoning_effort` inherits
  `AMICUS_PI_REASONING_EFFORT`, else pi's own default, which no amicus surface reports. An
  explicit one avoids that unreported default. It selects a level; it caps neither tokens nor
  cost.
- **A catalog describes; it does not rank.** A provider's listing gives advertised
  specifications and prices, which can separate candidates against what the task needs (a
  narrow mechanical review needs less than an architectural question). It does not establish
  how well a model does the task, and it can leave several candidates tied. Whether a paid
  call may settle a tie is the first rule above.
- **Trialling a candidate is not a free comparison.** A call to a provider's own inference
  API or tool spends outside the cap declared for the decision, and sends text to a
  destination no `amicus_backends` disclosure covers.
- **The listing does not say which ids are aliases.** A provider may list a floating alias
  that follows its newest model beside version-specific ids, and nothing in a row marks which
  kind a slug is; the provider's documentation does. A version-specific id reduces drift but
  does not guarantee the same weights or a repeatable answer.
- **Checking an id is free.** pi refuses a model it cannot resolve before spending
  (`invalid_model`), so an exact listed slug, or a dry run that names it, is the evidence the
  exact-`provider/id` rule above asks for.
- **A free-tier id is a different route.** Its rate limits and retention terms can differ
  from the paid id's, so where both remain it is a choice between routes that differ in spend
  or exposure, which SKILL.md → Binding rules → Routing puts to the user.
- **Whether a candidate is a second opinion at all** is SKILL.md → Binding rules → Composed
  workflows: by resolved model, never by vendor or backend id.

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

`model_policy` on each `amicus_backends` entry reports the operator's `AMICUS_DENY_MODELS`.
When its `state` is `active`, an explicit `model` wins and is checked against `deny_patterns`;
an omitted `model` falls back to the backend's configured `AMICUS_*_MODEL` default, which is
checked too, and a call with neither is refused, since the CLI's own default cannot be checked.
`default_denied: true` means the configured default itself is refused, so pass an explicit model
that `amicus_models` lists. `amicus_models` omits denied rows and counts
them in `hidden_by_policy`. The policy checks the selector amicus sends, not the model a CLI
or router resolves it to.

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
host that looks for them there concludes, wrongly, that no backend supports them ([#84](https://github.com/briandconnelly/amicus/issues/84)).

The gates:

- `amicus_consult` / `amicus_review_changes`: `codex`, `claude`, `pi`; never gated.
- `amicus_delegate`: `codex`, `pi` only. Claude is outside the tool's `backend` enum, so a
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
| `pi` | Yes — `--tools read,grep,find,ls`, so no shell, edit or write tool; pi has no OS sandbox, and at startup it renames a workspace's `.pi/commands/` to `.pi/prompts/` when the latter does not exist, even on a consult or review | read-only tool allowlist; needs an exact `provider/id` model |
| `claude` | **Reviews only, by default.** `amicus_review_changes` defaults to `access="readonly"` (`Read`, `Grep`, `Glob`); consult and adversarial review default to `access="toolless"`, which grants **no tools at all** | `access="readonly"` for reviews and `"toolless"` otherwise; `config_mode="inherit"` for consult and review, and `"safe"` for adversarial review (`"bare"` when the operator's mode is `bare`) |

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
writes, not reads; pi can read files outside the workspace; Claude's `readonly` accepts absolute
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
  `claude` is one family through two harnesses. `amicus_models` exposes model ids and display labels,
  never verified provider identity. When you have reliable, non-sensitive information about the
  underlying models, weigh family diversity alongside task fit; when you do not, record the
  diversity as **unverified** rather than assuming it. Separate attempts and complementary review
  scopes are still useful without it — they just do not establish independence or correctness on
  their own.
- **Pi's model is yours to name.** A call's `model`, an exact `provider/id`, wins; an omitted
  `model` uses `AMICUS_PI_MODEL`; and a call with neither is refused before it spends. amicus
  never falls back to pi's own default. Until `AMICUS_PI_MODEL` is set, `status.authenticated` is unknown (`null`) rather than
  false, and a call with a listed `model` is still eligible. The model's provider prefix, a
  router included, decides where the prompt goes, and `amicus_models` lists only models of
  providers pi holds credentials for. An unknown id is `invalid_model`, refused pre-spend because pi
  would send it anyway. A provider API key reaches pi only if
  the host forwards it to the amicus server; credentials saved by pi's `/login` need nothing.
- **Task shape.** A broad architectural question benefits from strong general reasoning; a narrow
  mechanical review benefits more from speed and cost. `amicus_models` lists each backend's
  advertised models and reasoning-effort sets, and on `pi` their approximate token limits
  (Choosing among pi's listed models, above).
- **What is usable right now.** A backend that is enabled but unauthenticated, rate limited, or
  reporting `status.warnings` is not a good choice however well suited it looks.
- **Effects.** Approval friction follows the worst *enabled* backend, not the one you pick for
  this call ([options and errors](options-and-errors.md)). Picking a different
  `backend` does not change it, and `effects` is a static per-backend declaration rather than a
  statement about your call.

When none of these distinguishes the eligible backends, pick any ready, eligible one.
