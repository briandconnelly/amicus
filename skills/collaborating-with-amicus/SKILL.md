---
name: collaborating-with-amicus
description: Use when calling another model or coding-agent harness through the amicus MCP server (backends codex, claude, pi, deprecated kimi), or when reading what an amicus_* tool returned. Covers second opinions, code and adversarial reviews, delegated implementation returned as a diff, independent two-model attempts, review–revise passes and blind comparisons. Trigger on "ask another model", "get a second opinion", "collaborate with Codex", "have Codex/Pi/Kimi review this", "get GPT's opinion", "delegate this to Codex", "which models can amicus use", "is Codex available in amicus", "check amicus backend status", an amicus_* error or a host denial of an amicus call, and, as an offer only, decisions another opinion would change — a hard-to-reverse choice, two failed fixes, risky work about to be called complete.
---

# Collaborating with amicus

amicus is one MCP server that calls other models through their CLI harnesses. Every paid tool
takes a `backend` parameter naming the **harness** that runs the call (`codex`, `claude`, `pi`,
or the deprecated `kimi`), not the model: `codex` runs OpenAI models, `claude` runs Anthropic
models, and `pi` runs any provider's model it lists, by exact `provider/id`, so two harnesses
can run the same model. `kimi` is deprecated in favour of `pi` (removal at or after 0.15.0): it
still serves a request that names it or a Kimi model, with its deprecation disclosed; read the
`deprecation` marker `amicus_backends` carries for it.

You are the host. A backend is a worker you consult; it does not own the decision, the
verification, or the working tree.

## Shared workflow

The order of work. Each step is governed by the rules named beside it, which are the authoritative
statement — this list is a map, not a second copy.

1. Discover what is usable → Binding rules → Discovery.
2. Resolve the harness and model → Binding rules → Routing.
3. Choose the verb from the route table.
4. Read what that route requires → Binding rules → Required reading.
5. Preview and budget → Binding rules → Spend, Scope and inputs.
6. Call.
7. Read the result and verify before acting →
   [reading results](references/reading-results.md) → Rules.

## Route the request

| Situation | Tool or workflow | Read |
| --- | --- | --- |
| One answer, design critique, or second opinion (including on a diff you paste inline) | `amicus_consult` | [active workflows](references/active-workflows.md) |
| Review changes already represented in git | `amicus_review_changes` | [active workflows](references/active-workflows.md) |
| A fixed adversarial critic attacking a plan, claim, or decision before you commit to it (`claude` only) | `amicus_adversarial_review` | [active workflows](references/active-workflows.md) |
| A self-contained coding task implemented in a throwaway worktree, returned as a diff (`codex`, `kimi` or `pi` only) | `amicus_delegate` | [active workflows](references/active-workflows.md), [reviewing a returned diff](references/reviewing-a-returned-diff.md) |
| Any of the above when the work can exceed the sync deadline | the matching `_async` tool | that route's references, and [sync vs async](references/sync-vs-async.md) |
| Which backend to pick, and what evidence it can actually inspect | `amicus_backends` (free) | [choosing a backend](references/choosing-a-backend.md) |
| You and one backend attempt the same problem independently, then you synthesize | independent attempt | [independent attempt](references/independent-attempt.md) |
| You draft, a backend critiques, you revise | declared review–revise | [review–revise](references/review-revise.md) |
| Two or more finalized candidates, nothing cheaper tells them apart, and a backend that wrote none of them compares them | blind comparison | [blind comparison](references/blind-comparison.md) |
| Preview a review's or delegate's scope, size, and resolved options before spending | `amicus_review_changes_dry_run` / `amicus_delegate_dry_run` (free) | [active workflows](references/active-workflows.md) |
| Model slugs and reasoning-effort sets before overriding `model` or `reasoning_effort` | `amicus_models` (free) | — |
| Full tool inventory, fingerprint, and error catalog | `amicus_capabilities` (free) | — |
| Poll, fetch, list, or cancel a background job | `amicus_job_status` / `amicus_job_result` / `amicus_job_consume_result` / `amicus_job_list` / `amicus_job_cancel` (all free) | [sync vs async](references/sync-vs-async.md) |
| An optional parameter, an idempotency key, a returned error, or a host's denial of an amicus call | the tool already selected; a denial is reported, never worked around | [options and errors](references/options-and-errors.md) |
| The amicus MCP server is unreachable | limited fallback | [server-down fallback](references/server-down-fallback.md) |
| None of these, or a call would not change the decision | no call — proceed without amicus | — |

## Binding rules

Each rule is checkable against a tool call, a result, or your own output. The rules below bind
every use of this skill. A rule that binds only once a call is made, a result is read, a job is
polled or a workflow is composed lives under the `Rules` heading of the reference that owns it:
Required reading says when each of those blocks must be read, and a rule in one binds exactly as
a rule here does.

### Discovery

- **Call `amicus_backends(detail="full")` before the first paid call of a session.** Its
  per-backend report, including the disclosures the default `summary` leaves out, is what makes
  the remaining discovery rules checkable.
- **Pass only a backend reported `enabled: true` and `status.installed: true` that is ready for
  the model the call will run: `status.authenticated: true`, or, for `pi`, an exact `model` the
  same call passes that `amicus_models(backend="pi")` lists, or, past a `truncated` listing's
  cut, that you know exactly, or, for `claude`, a `config_mode` the user chose under the next
  rule.** pi checks such a model pre-spend and refuses one it cannot resolve. `enabled` alone is
  not eligibility. pi's `status.authenticated` speaks only for `AMICUS_PI_MODEL` and is `null`
  while that is unset, so it neither admits nor excludes a per-call `model`.
- **Read `claude`'s `status.authenticated` as speaking for the deployment's default
  `config_mode` only.** Where it is not `true` and `status.warnings` reports an
  `ANTHROPIC_API_KEY` that the default mode ignores, a call passing `config_mode: "bare"` can
  still run: offer that route to the user, naming the mode, instead of reporting `claude` as
  unusable, and take it only when they choose it.
- **Confirm the backend's `features` list names `delegate` or `adversarial_review` before calling
  that verb.** Those are the only gated verbs; `consult` and `review_changes` run on every
  backend and never appear in `features`, whose other members are capabilities, not verbs.
- **Treat the running deployment's `amicus_backends` report as authoritative** wherever it
  disagrees with this skill or any reference in it.
- **Re-read `amicus_backends` rather than reusing an earlier session's assumption** about what is
  ready.

### Routing

This is the one statement of the routing procedure;
[choosing a backend](references/choosing-a-backend.md) has worked examples of it.

- **Resolve the harness and the model before choosing the verb, and name both, and the provider
  the call sends to, before the first paid call.** The kind of work the request asks for is an
  input to that resolution: a harness that lacks its verb is not a route. What waits until the
  route is resolved is selecting the tool and reading its references. Where the call takes a
  harness's default model and no surface reports which model that is, name it as that harness's
  default rather than guessing a slug.
- **Let a named harness win.** `codex`, `claude` or Claude Code, `pi`, and bare `kimi` (the
  deprecated kimi harness) select that harness, whatever the capitalization, and a model named
  alongside it is passed as that harness's `model`. An exact `provider/id` is pi's model syntax,
  so it selects `pi`.
- **Send a model-only request to its native harness — `codex` for an OpenAI model, `claude` for
  an Anthropic model, `kimi` for a Kimi model while that deprecated harness remains, disclosing
  its deprecation — when that harness is ready and supports the verb; otherwise route it to
  `pi` with an exact model `amicus_models(backend="pi")` lists, and name that route before the
  call.** That is routing, not substitution, so it needs no confirmation.
- **Never substitute for a named harness silently.** When the harness the user named is not
  ready or lacks the verb, say so, offer the alternative route (`pi` plus an exact listed model)
  naming its provider (the `provider/id` prefix, which may be a router) and its containment
  (pi has no OS sandbox, and a pi delegate no network block), and proceed only when the user
  chooses it.
- **Route only to a harness that supports the verb.** When none does — an adversarial review
  with `claude` not ready — report that no eligible route exists; changing the verb is a
  separate choice for the user.
- **Learn what `pi` can reach from `amicus_models(backend="pi")`, never from provider
  configuration.** A missing or truncated listing does not prove a model unreachable: say you
  cannot vouch for it rather than calling it unavailable. Provider configuration does not
  establish which model a harness runs either; never inspect a user's to find out.
- **Take `reasoning_effort` from the chosen row's `supported_reasoning_efforts`.**
- **Ask the user once, before spending, only when the routes that still match after free
  discovery differ in spend, exposure, containment or verb.** This limits questions about
  which route to take. Consent for a call the user did not ask for is a separate question,
  under Spend, and is asked even when one route is left.

### Spend

- **Never call a paid tool to find out whether a backend is available.**
- **Ask the user before a paid call they did not ask for.** A situation this skill's
  description names — a hard-to-reverse choice, two failed fixes, risky work about to be called
  complete — is a reason to offer the call, naming the harness, the provider it sends to and
  what it would be sent. It is not consent to spend quota or to send workspace content. A
  standing instruction from the user or the project to consult without asking is that consent.
- **State the paid-call cap for the decision before the first paid call, then stay within it.**
  Count paid calls across the whole decision, not per backend or per workflow step.
- **Use the matching `_async` tool, or the sync tool with an `idempotency_key`, when you are
  unsure the work will finish inside the sync deadline.** A terminated unkeyed sync call returns
  nothing; a keyed one leaves the run going and can be repeated to reattach to it.
- **Recover an existing job before paying for the same work again** (`amicus_job_list`, or an
  `idempotency_key` replay — see [options and errors](references/options-and-errors.md)).
- **Never run the sync and `_async` forms of the same work concurrently**, and never launch the
  sync form speculatively intending to fall back to `_async`.
- **After a terminal failure, start a new attempt only as `error.repair` directs, or, where the
  envelope carries no `error.repair`, after fixing what `error.details` names; and only within the
  declared cap.** An unkeyed sync timeout's repair prescribes the `_async` twin; that is a
  new paid run, not a duplicate of the lost one. A keyed sync timeout's repair prescribes polling
  the run that is still going; starting the twin or dropping the key there pays twice.

### Scope and inputs

- **Match `scope`, `base`/`commit`, `paths`, and `untracked` to what the user asked to have
  reviewed.** Selecting the right verb does not select the right changes.
- **Run the free dry run before a paid review or delegate whose scope you cannot predict**, and
  read its reported scope before spending.
- **Pass an absolute `workspace_root` on every repo-grounded call**, including free job-lifecycle
  calls.
- **Decide `access` and `config_mode` before the call, from the evidence the task needs, and
  state that need.** Raising either in response to a result that came back short of evidence is
  the case this forbids; choosing `readonly` up front because the backend must read a named file
  is not. When a result does come back short of evidence, say so, then either resend with the
  evidence inline under the declared cap or put the wider setting to the user, who decides.

### Required reading

Each rule names a `Rules` block and the moment by which it must have been read. A block already
read in this session need not be read again.

- **Read [active workflows](references/active-workflows.md) → Rules before every paid call,
  whatever the route.** Its brief and input-placement rules bind every paid verb, the delegate and
  `_async` routes included, except where a composed workflow's reference overrides one by name.
- **Read [reading results](references/reading-results.md) → Rules before interpreting, acting
  on or reporting what any paid tool returned**, whether it came back directly or through
  `amicus_job_result`.
- **Read [options and errors](references/options-and-errors.md) → Rules before recovering from
  or reporting any amicus response with `ok: false`, any response that looks malformed or
  contradicts its own schema whatever its `ok`, any failed read of an `amicus://` resource, or
  a host's denial of an amicus call**, free tools included, and before passing an
  `idempotency_key`.
- **Read [sync vs async](references/sync-vs-async.md) → Rules before the first `_async` call,
  keyed sync call or job-lifecycle call.**
- **Read [choosing a backend](references/choosing-a-backend.md) → Rules before a paid call
  whose route is `pi` or `kimi`, before choosing among routes when more than one is left, and
  before a call that needs the backend to read files itself or that sets `backend_options`.**
- **Read [reviewing a returned diff](references/reviewing-a-returned-diff.md) → Rules before
  acting on or reporting a delegate's result.**
- **Read a composed workflow's own reference → Rules before its first paid call.**
- **Read [server-down fallback](references/server-down-fallback.md) → Rules before any call
  that goes around the amicus server.**

### Jobs

- **Never read or watch amicus's job store** (`AMICUS_STATE_DIR`, by default
  `$XDG_CACHE_HOME/amicus/jobs` or `~/.cache/amicus/jobs`) or loop on it in a shell: its files
  skip the delivery checks and their layout is not a contract. Observe a job through
  `amicus_job_status`, or reattach to a keyed sync run by repeating the same keyed call.

### Delegated diffs

- **Never apply a returned diff before reviewing it** against
  [reviewing a returned diff](references/reviewing-a-returned-diff.md), and answer in that file's
  response contract.
- **Never state or imply that amicus applied anything to the working tree.** It does not.

### Data exposure

- **Never put a secret in any free-text field you supply:** `question`, `task`, `target`,
  `evidence`, `extra_context`, `instructions_append`, `focus`.
- **Read `carriers` on `amicus_backends(detail="full")` before supplying `instructions_append`.**
- **Never treat a dry run as evidence that a paid call is safe to make.**
- **Never make a paid call from a workspace that the user or the project's instructions have
  said must not be disclosed to that backend's provider** — for `pi`, the provider the model's
  `provider/id` prefix names — **and never present a workspace as a boundary on what is read.**
  A backend can read whatever the OS user running it can, so choosing a different workspace
  does not keep other files from it.
- **Never send `kimi` text you would not leave on this machine's disk.**

### Composed workflows

- **Select an independent attempt, a review–revise pass or a blind comparison only when the user
  asked for it, or when the task declares it and the decision is hard to reverse, load-bearing,
  or security-sensitive.** A user's request is enough on its own. Otherwise make one call or
  none.
- **Judge model diversity by resolved model (`provider/id` where known), never by backend id.**
  Two harnesses can run one model, and one harness can run several; never claim two different
  model families without evidence of the underlying models.

## Semantics

Facts the rules above depend on, kept short; the references carry the detail. Nothing here is an
obligation.

### Backend names a harness

`backend` has no default, and each tool's `backend` enum is the set it accepts: any other
pairing is rejected pre-spend as `invalid_arguments`. Those restrictions belong to harnesses: an
Anthropic model run through `pi` can delegate and still has no `adversarial_review`. `pi` has no
default model, so a pi call needs an exact `provider/id`. `AMICUS_BACKENDS` says which backends
this deployment enables, not which to prefer. An unkeyed sync call past `timeout_seconds` is
terminated and its work is lost; a keyed sync call or an `_async` call keeps the result. Every
paid call is a job (`meta.job_id`).

### Data exposure

Every free-text field you supply reaches the selected backend's provider raw; amicus carries it
over stdin and never logs it, but how it then reaches the backend CLI is the backend's choice,
and `carriers` on `amicus_backends(detail="full")` is authoritative: on `codex`,
`instructions_append` rides argv, and the kimi CLI's own session store keeps what it is sent on
this machine's disk. On `pi` the provider is the one the model's `provider/id` prefix names, a
router included, so the model you pick is also the egress destination. A backend can read files
outside the workspace during a call, redaction covers only gathered diffs and returned output,
and a dry run calls no model (it runs only the backend's free pre-spend checks), so it proves
nothing about what a paid call reads or sends.
[choosing a backend](references/choosing-a-backend.md) has the per-backend table.
