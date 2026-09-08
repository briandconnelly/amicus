# Codex CLI 0.153.4 — scrubbed probe summary

This file is a scrubbed summary, not a transcript.
Under AGENTS.md rule 18 the prompt inputs never reach disk, so the raw host output was read only in the terminal.
What follows is the allowlist: tool name, negotiated protocol facts, selected backend, `AMICUS_BACKENDS` for the run, `ok` / `error.code` / the `repair` object's shape, and the assertion verdict.
Cost and token telemetry is stripped.

## S1 — cold start (paid, 3 calls)

Mode: baseline; no amicus skill was staged for this host, so the runs had only the MCP tool catalog to work from.
Harness: `codex exec --json --approve-for-me` under the scoped `CODEX_HOME`, fresh thread per run.

| Run | `AMICUS_BACKENDS` | Ordered amicus calls | `backend` on the paid call | `ok` | Verdict |
| --- | --- | --- | --- | --- | --- |
| 4 | `codex` | `amicus_capabilities`, `amicus_backends`, then `amicus_consult` | `codex` | `true` | pass |
| 5 | `kimi` | `amicus_capabilities`, `amicus_backends`, then `amicus_consult` | `kimi` | `true` | pass |
| 6 | `claude` | `amicus_backends`, then `amicus_consult` | `claude` | `true` | pass |

All three took S1's first branch, a tool call is made.
The paid call that followed the free discovery was `amicus_consult` in every run.

Runs 4 and 5 pass on intent with a literal deviation that is named rather than smoothed over.
Branch A names only `amicus_backends` as the free discovery call that may precede the paid call, and those two runs opened with `amicus_capabilities` instead.
That is free discovery of the same kind, and neither leading call is a paid verb, but it is not the call the branch lists.
`scenarios.md` records a proposed widening of branch A to "a free discovery call (`amicus_backends` or `amicus_capabilities`)" for future runs, explicitly marked as postdating these six runs and not applied to them, so that no later reader mistakes an amendment for a grading rule these runs were held to.
Run 6 opened with `amicus_backends` and is a clean branch-A pass.
No run reached for a review, delegate or adversarial verb, and no run omitted the required `backend` argument.
The `backend` argument equalled the single enabled backend in all three runs.
Run 6 also passed `backend_options` `{"access": "toolless", "config_mode": "safe"}` with no skill loaded, so that hygiene came from the tool's own schema and description rather than from SKILL.md.

The answers themselves are withheld under rule 18, deliberately and at no cost to the record: every S1 assertion is a call-shape assertion, and all of them are recorded per run in the table above.

Baseline is the interesting part of this result.
With no amicus skill installed, this host still reached a correct first paid call in all three runs, and it read `amicus_capabilities` or `amicus_backends` first in all three.
Under `review-workflow.md` step 1 that is positive cold-start evidence, not merely an absence of failure.

Two earlier S1 attempts on this host are recorded because they made no amicus call and spent nothing.

- The first ran with the maintainer's own MCP fleet still loaded, and the host called a rival second-opinion server's status and consult tools instead of amicus.
  Its consult was itself refused by the approval policy, so nothing was spent there either.
- The second ran isolated but under `approval_policy = "never"` with `-s read-only`, and the host refused `amicus_consult` with `MCP tool call requires approval, but approval policy is never`.

## S2 — first repair

The scenario's own S2 run is recorded on the Claude Code host, where the repaired call could be made spend-free against a stub backend.
This host contributed a second, independent repair observation, free and unplanned.

A call to `amicus_job_consume_result` with no `workspace_root` returned:

```
error.code = invalid_workspace_root
message    = "no workspace_root was given and the client advertised no file roots;
              pass workspace_root (an absolute directory) on every call from a sessionless ..."
```

The model read the code and reported it back correctly.
That is the same property S2 tests, on a different error code, and it confirms the repair surface is legible to this host too.

## S7 — annotation friction (free)

`AMICUS_BACKENDS=claude,codex` with `AMICUS_CLAUDE_ACCESS=write`, under `approval_policy = "never"`.

The run called `amicus_backends` first, which the host auto-approved, then `amicus_delegate_async` with `backend="codex"`, which the host refused:

```
MCP tool call requires approval, but approval policy is never
```

Both calls happened in the same run under the same policy, and the only thing that separated them is the annotation: `amicus_backends` declares `read_only_hint: true`, `amicus_delegate_async` does not.
That is the direct evidence the Claude host's `-p` refusal could not supply.

Verdict: fail, on the third assertion only.

- Assertion 1, a delegate verb with `backend="codex"`: pass.
  The model chose the `_async` twin, which the scenario allows.
- Assertion 2, the host surfaces a mutation-grade approval prompt: pass, and here it is demonstrably annotation-driven.
- Assertion 3, the model explains that the friction tracks the worst enabled backend: fail.
  It reported that approval was required and that `client.py` was unchanged, and it never connected the approval to `claude` being enabled.
- Assertion 4, no silent retry, no backend switch, no request to disable Claude: pass.

Across both hosts the pattern is the same: the friction ADR 0001 predicted arrives exactly as predicted, and the explanation that is supposed to accompany it does not.
That is a finding about the skill's text, not about the server.

## Other probes

- **Discovery cost**: the same live measurement as the Claude capture applies, since it is the same server and the same wheel.
  The serialized `tools/list` response is 92202 bytes for the `all` profile, 92210 for `codex-kimi` and 92202 for `claude`, all 18 tools, against the 93000-byte budget.
  Those live numbers sit about 120 bytes above the `MEASURED` values in `tests/test_discovery_cost.py`, which is a measurement difference rather than drift: `MEASURED` serializes the app's tool models in process, while these re-serialize what a real client received over stdio after the dialect-stamping middleware ran.
  Unlike the Claude host, this host had the tools available without a deferred lookup, so the ratchet's preloading-client assumption is the right one here.
- **Annotation honesty**: strongly confirmed on this host, because the host acts on the hints.
  Every tool the host auto-approved declares `read_only_hint: true`, and every tool it refused does not.
  No tool was approved that should have been gated.
- **Cross-version**: `amicus_capabilities` reported `fingerprint: amicus/0.1/schema-6` and `surface_digest: f4d9a501c65d62bf2792fe2f5a0ab3abab1fe84f1f4918b6ab41f39cba19cf2b`, byte-identical to the Claude host's, so the fingerprint is a stable cross-host cache key.
- **Capability gating**: the tasks extension was not declared on any call, so every call took the plain path.
- **Cold-start legibility**: two of the three paid runs opened with `amicus_capabilities`, unprompted and with no skill loaded, which is the capability summary being used the way it is meant to be used.

## Probes not run here, with reasons

- **Command discovery**: inapplicable.
  Codex CLI has no slash-command surface, and `.codex-plugin/plugin.json` declares no `commands` key, so there is nothing to enumerate.
- **Long-running operation**: not exercised.
  The async job surface needs a real paid `_async` call plus polling, and the six-call budget was fully committed to S1.
- **Resource freshness**: not exercised.
  No resource was held across turns in these runs.
- **Security boundary**: partially exercised.
  The egress and implicit-context disclosures were read off `amicus_backends`, and the approval gate above is the confirmation boundary working, but no redaction was traced end to end.
