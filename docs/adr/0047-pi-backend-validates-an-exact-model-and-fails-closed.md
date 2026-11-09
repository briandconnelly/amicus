# ADR 0047: the pi backend validates an exact model and fails closed

**Status:** Accepted (2026-11-08)

Departs from the kimi model and effort checks of [ADR 0009](0009-m3-kimi-port-decisions.md) because pi's CLI does not reject an unknown model, and keeps the closed `backend_options` set of [ADR 0002](0002-backend-options-is-a-closed-superset.md) for a backend with nothing to isolate.

## Context

M9 adds `pi` (issue #423), the pi coding-agent CLI, beside `codex`, `kimi` and `claude`.
Every paid call spends the provider's quota, so a model check that is wrong in either direction costs something: a mistaken refusal blocks a good call, and a mistaken pass spends on a model that cannot answer.
Three properties of pi 1.5.0 decide how the check is built.
Pi has no default model of its own that amicus can rely on, because its default comes from ambient settings and fuzzy matching.
Pi sends an unknown model id to the provider anyway, so nothing in the CLI stops the spend.
And `pi --list-models` lists only models of providers that have credentials, so a model missing from that listing may be unknown or may belong to a provider that is not logged in.

## Decision

**A model is an exact `provider/id`, and a call with none is refused before it spends.**
`AMICUS_PI_MODEL` is the default and a call's `model` overrides it.
With neither set the call is `invalid_arguments` on field `model`.
Pi's own default is not used, because it would make the model, and so the provider that receives the prompt, depend on settings amicus cannot see.

**The check asks `pi auth check` first.**
`pi auth check --model <model> --json --no-refresh` resolves the provider, including a provider id that itself contains `/`, so it is the only step that can tell an unresolvable model from an unauthenticated provider.
An unresolvable model is `invalid_model`, and `not_ready` or `invalid` is `pi_auth_required`.
Only with the provider ready does the second step run: `pi --list-models <id>` must hold a row whose provider and model columns join to exactly the requested model.
Asking the listing first would report a logged-out provider's model as unknown, which names the wrong repair.
`--no-refresh` keeps discovery from refreshing, and so writing, OAuth credentials.

**The check fails closed.**
No exact row, or a listing that could not be read, is `invalid_model`.
Kimi's path differs on purpose: the kimi CLI rejects an unknown alias itself, so amicus has no spend to prevent and lets the catalog's silence pass to the CLI, and its pre-spend verdict is about reasoning effort.
Pi would send the unknown id, so the same silence would be a paid call.
The cost of failing closed is that a catalog amicus cannot read blocks a call that might have worked; the repair names `amicus_models`, and the price of the opposite error is real quota.
When the binary cannot be resolved, validation skips both probes, so the run reports `backend_not_found` rather than a model error.

**Reasoning effort is advisory.**
Pi clamps an effort the model does not support, so only the token vocabulary and `off` for a model whose catalog row says `thinking: no` are refused, and a run whose reported `thinkingLevel` differs from the request carries a warning naming both.

**`pi` has no `isolation` option.**
Kimi's `isolation` decides whether the user's skills load.
Pi runs every call with all resource loading suppressed (`--no-context-files --no-skills --no-extensions --no-mcp --no-prompt-templates --no-themes --no-approve --offline`) and `--no-session`, so there is no inherited context for an option to switch, and offering one would suggest a choice that does not exist.
The `backend_options` set stays closed, and `isolation` for `pi` is rejected pre-spend as `invalid_arguments` like any option a backend does not accept.

## Consequences

- A `pi` call needs a model that its provider has credentials for; `amicus_backends` reports authentication as unknown, and says that calls must pass `model`, while `AMICUS_PI_MODEL` is unset.
- Credentials saved by pi's interactive `/login` need nothing more.
  A provider API key in the environment reaches pi only if the host forwards it to the amicus server, because the plugin's `.mcp.json` lists amicus's own variables and not provider keys.
- Each call spends two free probes, cached per model for the help-cache TTL, so a credential revoked within that window is reported ready until it expires and the run then fails as `pi_auth_required`.
- Pi carries the prompt on stdin and writes no session file under `--no-session`, so it adds no rule-18 carrier exemption.
- A shell command that pi starts during a delegate, such as a hung or backgrounded process, can outlive the run, because amicus cannot yet find and stop it.
  Pi's bash tool starts its shell detached, with the worktree as a spawn option rather than an argument, so amicus's orphan sweep, which matches the worktree path in a process's argv, does not see it; and amicus ends a timed-out or cancelled run with SIGKILL, so pi's own cleanup of its shells never runs.
