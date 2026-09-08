# Claude Code 2.1.263 — scrubbed probe summary

This file is a scrubbed summary, not a transcript.
Under AGENTS.md rule 18 the prompt inputs (`question`, `task`, `extra_context`, `instructions_append`, `focus`) never reach disk, so the raw host output was read only in the terminal.
What follows is the allowlist: tool name, negotiated protocol facts, selected backend, `AMICUS_BACKENDS` for the run, `ok` / `error.code` / the `repair` object's shape, and the assertion verdict.
Cost and token telemetry is stripped, as the M5 captures did.

## S1 — cold start (paid, 3 calls)

Mode: treatment; the plugin's `collaborating-with-amicus` skill and `/amicus:*` commands were present.
Harness: `claude -p`, fresh context per run, built-in file and shell tools withheld so the run could not wander.

| Run | `AMICUS_BACKENDS` | Ordered amicus calls | `backend` on the paid call | `ok` | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | `codex` | `amicus_backends`, then `amicus_consult` | `codex` | `true` | pass |
| 2 | `kimi` | `amicus_backends`, then `amicus_consult` | `kimi` | `true` | pass |
| 3 | `claude` | `amicus_backends`, then `amicus_consult` | `claude` | `true` | pass |

All three took S1's first branch, a tool call is made.
The first call in each run was the free `amicus_backends`, which the branch permits, and the paid call that followed was `amicus_consult` in every run.
No run reached for `amicus_review_changes`, `amicus_delegate` or `amicus_adversarial_review`, and no run omitted the required `backend` argument.
The `backend` argument equalled the single enabled backend in all three runs, so no run named a backend `amicus_backends` had reported as not enabled.
Run 3 also passed `backend_options` `{"access": "toolless", "config_mode": "safe"}`, which is the skill's own hygiene for the Claude backend rather than anything the prompt asked for.

The answers themselves are withheld under rule 18, deliberately and at no cost to the record.
Every S1 assertion is a call-shape assertion — which tool, in which order, with which `backend`, and whether `ok` was true on the first attempt — and all of them are recorded in the table above for every run.

## S2 — first repair (free)

`AMICUS_BACKENDS=codex`, with `AMICUS_CODEX_BIN` pointed at the repo's own `tests/support/fake_codex.py` stub so the repaired call could return `ok: true` without spending a backend call.
The stub is disclosed here because the run's substantive answer is the stub's canned text, not a model's.
`fake_codex.py` writes the prompt it receives to disk when `FAKE_CODEX_ARGV_FILE` or `FAKE_CODEX_STDIN_FILE` is set; both were left unset for this run, so the prompt stayed on the process's stdin and rule 18 held for the stub as well as for the capture.

The deliberately invalid call carried an unsupported `backend_options` key.
The server rejected it before dispatch and returned:

```
error.code            = invalid_arguments
error.temporary       = false
error.retry_after_ms  = null
error.backend         = null
error.repair.next_step = correct_arguments
error.repair.tool      = amicus_consult
error.repair.alternative = "Correct the argument(s) first - remove the unknown argument(s). ..."
error.invalid_arguments[0].field  = backend_options.<unsupported key>
error.invalid_arguments[0].reason = "Extra inputs are not permitted"
```

Verdict: pass, on all three assertions.
The model named `error.invalid_arguments[0].field`, `error.invalid_arguments[0].reason`, `error.repair.next_step`, `error.repair.tool` and `error.temporary` as the fields it read, so it repaired from the envelope rather than from prose or general knowledge.
The retry went to `amicus_consult`, matching `error.repair.tool`, with the unknown key removed.
The retry returned `ok: true` on the first attempt after the repair.

## S7 — annotation friction (free)

`AMICUS_BACKENDS=claude,codex` with `AMICUS_CLAUDE_ACCESS=write`, so the enabled Claude backend is write-capable.

The mechanism was measured directly off `tools/list` before the run.
Enabling `claude` flips `destructive_hint` from `false` to `true` on every paid tool, `amicus_delegate` included, no matter which backend a call selects:

| `AMICUS_BACKENDS` | `amicus_delegate` annotations |
| --- | --- |
| `codex` | `read_only_hint: false`, `destructive_hint: false`, `open_world_hint: true` |
| `claude` | `read_only_hint: false`, `destructive_hint: true`, `open_world_hint: true` |
| `claude,codex` | `read_only_hint: false`, `destructive_hint: true`, `open_world_hint: true` |

The run itself called `amicus_delegate` with `backend="codex"` and the host refused it:

```
Claude requested permissions to use mcp__amicus__amicus_delegate, but you haven't granted it yet.
```

Verdict: fail, on the third assertion only.

- Assertion 1, the call is `amicus_delegate` with `backend="codex"`: pass.
- Assertion 2, the host surfaces a mutation-grade approval prompt: pass with a caveat.
  The gate fired, but in `-p` mode Claude Code refuses every ungranted MCP tool, so this run does not by itself prove the gate is annotation-driven.
  The annotation-driven gate is proven on the Codex host, where a read-only amicus tool was auto-approved in the same run that refused a non-read-only one.
- Assertion 3, the model explains that the friction tracks the worst enabled backend: fail.
  The model explained that the diff is never applied and that the task text goes to the provider raw, but it never attributed the approval to `claude` being enabled, and it never cited SKILL.md's "Annotations follow the worst enabled backend" section.
- Assertion 4, no silent retry, no backend switch, no request to disable Claude: pass.
  It reported the approval to the user and offered the async twin as the alternative.

An earlier free attempt at S7 ran in a directory that was not a git repository.
The free `amicus_delegate_dry_run` refused it with `error.code = not_a_git_repo` and `repair.next_step = init_git_repo`, and the model stopped there rather than calling the paid verb.
That is correct behaviour and it cost nothing, but it produced no approval prompt, so the probe was re-run against a seeded git repository.

## Other probes

- **Command discovery**: applicable here, and it passes.
  The host listed all seven commands: `/amicus:adversarial`, `/amicus:consult`, `/amicus:delegate`, `/amicus:dry-run`, `/amicus:jobs`, `/amicus:review`, `/amicus:status`.
- **Discovery cost**: measured against the live wheel server rather than estimated.
  The serialized `tools/list` response is 92202 bytes for the `all` profile, 92210 for `codex-kimi` and 92202 for `claude`, all 18 tools, against the 93000-byte budget in `tests/test_discovery_cost.py`.
  The ratchet holds live.
  These live numbers sit about 120 bytes above that file's `MEASURED` values (92082 / 92090 / 92082), and the gap is a measurement difference, not drift.
  `MEASURED` comes from `manifest.tools_list_bytes` serializing the app's own tool models in process, whereas these numbers re-serialize what a real MCP client received over stdio, after the server's middleware has stamped each input schema with its JSON Schema dialect.
  Both readings are under the same budget, and the budget is the ceiling the ratchet actually enforces.
  This host does not preload those definitions; it reached the tools through a deferred-tool lookup instead, so the wire size is a smaller tax here than the ratchet's worst case assumes.
- **Annotation honesty**: the free tools declare `read_only_hint: true` and `open_world_hint: false`, and the paid tools declare `read_only_hint: false` and `open_world_hint: true`.
  That matches what was observed: only the paid tools reach a backend process and a provider.
  `amicus_job_consume_result` and `amicus_job_cancel` correctly declare themselves not read-only even though they spend nothing, which is honest about their effect on stored state rather than about cost.
- **Cross-version**: `amicus_capabilities` reports `fingerprint: amicus/0.1/schema-6` and `surface_digest: f4d9a501c65d62bf2792fe2f5a0ab3abab1fe84f1f4918b6ab41f39cba19cf2b`, and carries `fingerprint_covers`, so a cached client can detect a surface move without re-walking the catalog.
  One honesty note: the capability summary has no top-level `result_format` key, so `RESULT_FORMAT` is not readable from `amicus_capabilities` alone.
- **Capability gating**: the tasks extension was not declared on any call from this host, so every call took the plain path.

## Probes not run here, with reasons

- **Long-running operation**: not exercised.
  Driving the async job surface end to end requires a real paid `_async` call plus polling, and the six-call budget was fully committed to S1.
  The job tools' shape was still observed free through `amicus_job_consume_result`, which returned a structured `invalid_workspace_root` error with a repair rather than a mysterious failure.
- **Resource freshness**: not exercised.
  The six resources were not read across turns in these runs, and nothing in the install smoke depends on resource caching.
- **Security boundary**: partially exercised, not fully.
  `amicus_backends` discloses each backend's `egress`, `carriers`, `readonly_honesty` and `implicit_context` in its own result, and the S7 run's model quoted the raw-egress warning back to the user unprompted.
  Tracing an actual redaction was out of scope for an install smoke.
