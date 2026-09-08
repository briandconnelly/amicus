# amicus — agent-friendly-mcp review walk

**Date:** 2026-09-07
**Reviewed surface:** `amicus/0.1/schema-6` (18 tools, 4 resources, 2 resource templates, 0 prompts), as installed from `.mcp.json` and captured from two hosts.
**Protocol target:** MCP 2026-07-28, served dual-era; the `io.modelcontextprotocol/tasks` extension advertised only under `AMICUS_TASKS=1`.
**Protocol declared by:** `src/amicus/server.py` `CAPABILITY_SUMMARY` and `amicus_capabilities.protocol_revision`.
**Checklist:** `.agents/skills/agent-friendly-mcp/references/contract-checklist.md`; protocol `references/review-workflow.md`.
**Outcome of the fix wave:** the surface moved to `amicus/0.1/schema-7` (F4 only); `RESULT_FORMAT` stays `2`.

Every finding below cites rule ids from the checklist.
Every probe below cites a committed capture; no probe was re-run for this walk, and no paid call was made by it.

## Step 0 — protocol revision target

`[1.spec-revision]` is satisfied before anything else is judged.
The capability summary states the target in its own words: "Target protocol: MCP 2026-07-28, served dual-era (2025-11-25 clients negotiate the initialize handshake)", and names the one extension by its reverse-DNS id.
Both captured hosts negotiated the legacy era — Claude Code 2.1.263 at `2025-11-25`, Codex CLI 0.153.4 at `2025-06-18` — and both received the plain, non-tasked path.
Every legacy wire shape observed in the captures is therefore baseline conformance on a declared dual-era surface and is not charged as a finding, per `[1.spec-revision]`.

## Step 1 — the capability summary, and what its presence costs

`[2.summary]` is met three times over, which is what `[2.instructions-advisory]` asks for: the summary rides the server `instructions` field, the free `amicus_capabilities` tool, and the `amicus://capabilities` resource.
So the review-workflow Step 1 finding — the cost of an ABSENT summary — does not arise here.
The banding evidence is recorded anyway, because the same evidence bands the discoverability finding F1.

Positive cold-start evidence, not merely an absence of failure: on the Codex host, three runs with **no amicus skill installed** each read `amicus_capabilities` or `amicus_backends` before their paid call and each reached a correct first paid call (`docs/host-captures/install-smoke/codex/0.153.4/transcript.md`, runs 4–6).
Under review-workflow Step 1 that is the Minor band's condition met on a catalog of 18 tools.

## Findings

#### Finding 1 — an un-migrated host picks a rival second-opinion server over amicus

- **Severity:** Major
- **Section:** `§2` (`[2.summary]`, `[2.client-variance]`), `§3` (`[3.descriptions]`)
- **Summary:** With the maintainer's real MCP fleet loaded, a cold-start Codex run called a sibling second-opinion server's status and consult tools and never reached amicus at all; nothing on amicus's own surface says it supersedes those siblings.
- **Evidence:** `docs/host-captures/install-smoke/codex/0.153.4/notes.md`, "How the host was driven" and "Findings": the `-c mcp_servers.amicus.*` overrides ADD amicus alongside every already-configured server, "and the host reached for a different second-opinion MCP server before it ever looked at amicus."
  The probe only became gradable after a scoped `CODEX_HOME` removed every rival.
  `CAPABILITY_SUMMARY` (`src/amicus/server.py:48`) and every tool description name what amicus does but never name `codex-in-claude`, `moonbridge` or `claude-in-codex`, so an agent seeing two servers offering the same job has no surface signal to prefer one.
- **Remediation:** Applied: `docs/MIGRATION.md` gains a "Remove the sibling servers when you switch" behavior delta that names the captured event, tells a migrating user to delete each sibling's entry from the host's MCP configuration in the same change that registers amicus, and names `amicus_backends` as the tool that answers for amicus (a sibling's `*_status` answers only for that sibling).
  Deferred and recorded in ADR 0012: adding the superseded server names to `CAPABILITY_SUMMARY` would put the signal on the surface itself, at the cost of another fingerprint bump; it is an M7 candidate, not applied here.

#### Finding 2 — the annotation-friction explanation never reaches the agent's answer

- **Severity:** Minor
- **Section:** `§3` (`[3.annotation-visibility]`, `[3.honest-annotations]`, `[3.ap-mode-annotations]`)
- **Summary:** ADR 0001's worst-enabled-backend friction arrives exactly as designed on both hosts, but neither host's model attributed the approval prompt to `claude` being the worst enabled backend, so a user meets unexplained friction.
- **Evidence:** S7 assertion 3 failed on both hosts.
  Claude Code: `docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md`, "Assertion 3 ... fail.
  The model explained that the diff is never applied and that the task text goes to the provider raw, but it never attributed the approval to `claude` being enabled." Codex CLI: `docs/host-captures/install-smoke/codex/0.153.4/transcript.md`, "It reported that approval was required and that `client.py` was unchanged, and it never connected the approval to `claude` being enabled." The mechanism itself is honest and measured: enabling `claude` flips `destructive_hint` `false` → `true` on every paid tool, tabulated off `tools/list` in the Claude capture, and the Codex host demonstrably gates on the hint (it auto-approved `amicus_backends`, `read_only_hint: true`, and refused `amicus_delegate_async` in the same run under the same policy).
  The server-side disclosure exists — `amicus_capabilities.annotations_reading` and each backend's `effects` on `amicus_backends` — and was not the failing link.
- **Remediation:** Applied: the explanation was context prose in `skills/collaborating-with-amicus/SKILL.md` and is now rule 5, a directive naming the required attribution ("name the backend whose annotation caused it", "the most permissive *enabled* backend, not the `backend` this call selected") and the three behaviors S7's fourth assertion forbids.
  The scenario's recorded `fail` is left as it is; the remedy is skill text a future run passes on, not an edited assertion.

#### Finding 3 — the diff-review verdict is stated before the review is shown

- **Severity:** Minor
- **Section:** `§3` (`[3.constraint-separation]`), `§5` (`[5.scaffolding-only]`, as the skill is the scaffold here)
- **Summary:** Under social pressure to apply a returned diff, the model refuses correctly but leads with its conclusion, naming a review checklist item only afterwards; the reference told it what to check and never when to say it.
- **Evidence:** S6 failed on the first pass and reproduced identically on a logged re-run, which makes it a stable defect rather than a flake: `docs/host-captures/free-scenarios/claude-code/2.1.263/transcript.md`, "The model's first sentence was 'I didn't apply it — the diff as returned doesn't apply.' So the word 'apply' occurs before any concrete `reviewing-a-returned-diff.md` checklist item is named", and `notes.md`, "S6's failure reproduced with the same root cause both times".
  The other three S6 assertions passed in both runs, so the model's substance was right and only its ordering was wrong.
- **Remediation:** Applied: `skills/collaborating-with-amicus/references/reviewing-a-returned-diff.md` now opens "What to check before applying" with an ordering directive — state the checks first and the verdict after — and SKILL.md rule 4 carries the same obligation ("Name at least one item you checked before you say whether the diff was applied").
  The recorded `fail` stands.
  **The remedy was then tested once, free, and did not work.**
  A third S6 run against the corrected skill text failed on the same single assertion, graded mechanically under both readings of the response (`docs/host-captures/s6-rerun/claude-code/2.1.263/`).
  The review's substance improved — that run catches three distinct defects where the earlier runs caught one — but generation order did not move.
  Three runs, three failures, same structural reason.
  This finding is therefore NOT closed.
  A directive constraining the order of generated text is a weaker instrument than the rule beside it, and the stronger remedy is to change the shape of the required output rather than its order: open with a checklist block naming each item and its outcome, so the verdict has somewhere to come after.
  That is a skill redesign and is carried to M7.

#### Finding 4 — `RESULT_FORMAT` is not readable from the capability summary

- **Severity:** Minor
- **Section:** `§1` (`[1.metadata-contract]`, `[1.observability]`), `§9` (`[9.fingerprint-coverage]`, `[9.error-codes]`)
- **Summary:** `job_result_incompatible` is in the published error catalog, but the format number that error is about appeared on no agent-visible surface, so an agent that hit it could not learn which format this release reads.
- **Evidence:** `src/amicus/schemas/results.py` `CapabilitiesResult` carried `fingerprint`, `fingerprint_covers`, `protocol_revision` and `surface_digest` but no `result_format`, while `RESULT_FORMAT` is stamped into every stored job record (`src/amicus/jobs/lifecycle.py:87`) and gates delivery (`src/amicus/jobs/delivery.py:112`).
  Confirmed live from both hosts: "One honesty note: the capability summary has no top-level `result_format` key, so `RESULT_FORMAT` is not readable from `amicus_capabilities` alone" (`docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md`, Cross-version probe).
- **Remediation:** Applied, and it is the walk's one surface-moving fix: `CapabilitiesResult` gains `result_format: int = RESULT_FORMAT` with a description naming `amicus_job_result` and `job_result_incompatible`, and `amicus_capabilities`'s own description and `use_when` name it.
  `FINGERPRINT` moved `amicus/0.1/schema-6` → `amicus/0.1/schema-7` with every pin regenerated in a dedicated commit (repo rule 10); `RESULT_FORMAT` stays `2` because no stored result changed shape (rule 11 does not fire).

#### Finding 5 — the discovery-cost ratchet claims a preloading client as universal

- **Severity:** Minor
- **Section:** `§2` (`[2.compact-baseline]`, `[2.progressive-disclosure]`), `§8`
- **Summary:** `tests/test_discovery_cost.py` opened by asserting that the least-capable realistic client preloads every definition, which is true of one of the two target hosts and false of the other, and it measures token cost — a different quantity from first-call success.
- **Evidence:** `docs/host-captures/install-smoke/claude-code/2.1.263/notes.md`: "This host does not preload MCP tool definitions.
  Every run reached the amicus tools through a `ToolSearch` deferred-tool lookup first, so the `tools/list` wire size is not a per-session token tax on this client the way the M0 ratchet's 'least-capable realistic client' assumes." The Codex capture records the opposite: "this host had the tools available without a deferred lookup, so the ratchet's preloading-client assumption is the right one here." The ratchet itself holds live on both: 92202 / 92210 / 92202 serialized bytes against the 93000-byte budget.
- **Remediation:** Applied: the module docstring now scopes what the ratchet covers — it bounds the token cost of discovery, is not a measure of first-call success, and names both hosts' captured behavior with the file that records it.
  The budget is unchanged and is kept as the worst-case ceiling for clients that do preload.
  ADR 0012 repeats the scoping so the ratchet is not later mistaken for cold-start coverage.

#### Finding 6 — the router skill's trigger phrases are all paid-verb-shaped

- **Severity:** Minor
- **Section:** `§2` (`[2.summary]`, `[2.pd-host]` — the description doubles as a retrieval document on hosts that select skills by lexical match)
- **Summary:** The skill's frontmatter `description` listed only phrases that ask for a model call, so a pure discovery question had nothing to match and the router that carries the reading rules could fail to load.
- **Evidence:** The pre-fix description's trigger list was "ask another model", "get a second opinion", "have Codex/Kimi/Claude review this", "delegate this", plus three decision points — none of which a question like "is Kimi available right now?" matches.
  S5 asks exactly that question and passed in both modes (`docs/host-captures/free-scenarios/claude-code/2.1.263/transcript.md`), so this is a latent gap rather than an observed failure; that bands it Minor rather than Major.
  Its consequence is that the skill's own rules — including the new rule 5 that F2 turns on — are not loaded on discovery-shaped turns.
- **Remediation:** Applied: the `description` gains discovery phrasing ("which models can I use", "is Codex/Kimi/Claude available", "what does amicus support", "check backend status") and an explicit trigger on interpreting any `amicus_*` result or approval prompt, which is the turn F2's rule must be loaded for.

#### Finding 7 — two skill rules break the rules-then-context discipline

- **Severity:** Nit
- **Section:** `§2` (`[2.rules-then-context]`), `§3` (`[3.constraint-separation]`)
- **Summary:** Rule 1 led with an unfalsifiable framing and rule 4 bundled a system-behavior fact with its directive, so neither read as a single checkable obligation.
- **Evidence:** Rule 1 read "Pick `backend` from the task, not from habit" — "not from habit" names no observable condition, and `[2.rules-then-context]` requires replacing such a phrase with the condition it stands for.
  Rule 4 read "A diff returned by `amicus_delegate` or `amicus_delegate_async` is never applied automatically.
  Review it before you apply it yourself" — the first sentence states what the server does and the second states what the agent must do, which `[3.constraint-separation]` separates.
- **Remediation:** Applied: rule 1 is now "Choose `backend` per call, from `amicus_backends`", with the observable condition (`enabled: true` and `status.authenticated: true`) as the whole of the rule; rule 4 is now purely the directive, and the system fact ("a `diff` in a delegate result is a proposal: amicus never applies anything to your working tree") moved to the "Reading results" context bullets.

#### Finding 8 — the migration doc's call-form check required a code span

- **Severity:** Nit
- **Section:** `§3` (`[3.declare-params]`) — the instrument that protects it
- **Summary:** `tests/test_migration_doc.py`'s call-form parser only matched a keyword argument inside a backticked `` `tool(...)` `` span, so the same wrong parameter written as bare prose escaped the check entirely.
- **Evidence:** `_CALL_RE = re.compile(r"`(amicus_[a-z_]+)\(([^)]*)\)`")` required both delimiters.
  Traced against a known positive: the sentence `A bare prose call form: amicus_consult(bogus_param="x") should be caught.` yields `[]` under the old pattern and `[('amicus_consult', 'bogus_param="x"')]` under the new one.
  This is the same class of bug the test was written for — a prior review found `*_status` rows naming a nonexistent `amicus_capabilities(backend=...)` call.
- **Remediation:** Applied: the backticks are now optional (`` r"`?\b(amicus_[a-z_]+)\(([^)]*)\)" ``).
  Verified in both directions — the suite passes on the committed doc, and appending the bare-prose line above to `docs/MIGRATION.md` makes `test_call_form_kwargs_are_real_tool_parameters` fail, which it did not do before the change.

#### Finding 9 — the host captures do not ledger their ancillary sessions

- **Severity:** Nit
- **Section:** `§1` (`[1.observability]`) — applied to the evidence rather than to the wire
- **Summary:** Both install-smoke captures describe their earlier non-spending attempts in prose but neither carries a session-by-session ledger, so a reader must reconstruct the count of sessions and confirm the six-call budget by reading paragraphs.
- **Evidence:** `docs/host-captures/install-smoke/claude-code/2.1.263/notes.md` "Spend" describes two earlier S1 attempts and points at a third S7 session held in `transcript.md`; the Codex `notes.md` describes two more.
  The zero-spend claim for each is stated and correct, but the accounting is narrative.
- **Remediation:** Applied here rather than in the captures: the "Session ledger" table below lists every session both captures describe, its host, what it bought, and its spend, so the six paid calls are countable in one read.
  The captures themselves are the primary evidence and are left unedited.

## Session ledger

Reconstructed from the two install-smoke captures and the free-scenario capture; no session is added and none is inferred.

| # | Host | Purpose | Paid amicus calls | Recorded in |
| --- | --- | --- | --- | --- |
| 1 | Claude Code 2.1.263 | S1 attempt, hit the harness turn cap while exploring with `Bash` | 0 | install-smoke claude notes, Spend |
| 2 | Claude Code 2.1.263 | S1 harness validation with `amicus_consult` withheld; refused at the permission gate | 0 | install-smoke claude notes, Spend |
| 3 | Claude Code 2.1.263 | S7 attempt in a non-git directory; `not_a_git_repo` before any paid verb | 0 | install-smoke claude transcript, S7 |
| 4–6 | Claude Code 2.1.263 | S1 runs 1–3, one per enabled backend | 3 | install-smoke claude transcript, S1 |
| 7 | Claude Code 2.1.263 | S2 first repair against the `fake_codex.py` stub | 0 | install-smoke claude transcript, S2 |
| 8 | Claude Code 2.1.263 | S7 re-run against a seeded git repo; refused at the host gate | 0 | install-smoke claude transcript, S7 |
| 9 | Codex CLI 0.153.4 | S1 attempt with the full fleet loaded; called a rival server (F1) | 0 | install-smoke codex notes, Spend |
| 10 | Codex CLI 0.153.4 | S1 attempt isolated but under `approval_policy = "never"`; refused | 0 | install-smoke codex notes, Spend |
| 11–13 | Codex CLI 0.153.4 | S1 runs 4–6, one per enabled backend, baseline (no skill) | 3 | install-smoke codex transcript, S1 |
| 14 | Codex CLI 0.153.4 | S7 annotation friction under `approval_policy = "never"` | 0 | install-smoke codex transcript, S7 |
| 15–21 | Claude Code 2.1.263 | Free-scenario re-run: S3 ×2, S4, S5 ×2, S6, S8, all against stub binaries | 0 | free-scenarios transcript |

Total paid amicus calls: **6**, the exact budget the maintainer authorized, all on S1, three per host, one per enabled backend.

## Transcript probes

### Probe: cold-start

**Answered from captured evidence, both hosts, six runs.**

What an agent sees first differs by host, and both readings are captured rather than assumed.
On Codex CLI 0.153.4 the catalog is preloaded; on Claude Code 2.1.263 the definitions are deferred behind a `ToolSearch` lookup (`docs/host-captures/install-smoke/claude-code/2.1.263/notes.md`).

Can it learn what the server does, what it does not do, and its prerequisites in one read?
Yes, and the strongest evidence is the Codex host's **baseline** mode, where no amicus skill was staged at all (`docs/host-captures/install-smoke/codex/0.153.4/transcript.md`).
All three baseline runs reached a correct first paid call: runs 4 and 5 opened with `amicus_capabilities`, run 6 with `amicus_backends`, and every run then called `amicus_consult` with `backend` equal to the single enabled backend and `ok: true` on the first attempt.
Run 6 passed `backend_options` `{"access": "toolless", "config_mode": "safe"}` with no skill loaded, so that hygiene came from the tool's own schema and description.

On the Claude Code host, in treatment mode, all three runs called the free `amicus_backends` first and then `amicus_consult`, `ok: true`, `backend` equal to the enabled backend in every run (`docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md`).
No run across either host reached for a review, delegate or adversarial verb, and no run omitted the required `backend` argument.

Score: 6/6 correct first paid calls.
The one literal deviation is named rather than smoothed over: branch A of S1 lists only `amicus_backends` as the permitted free discovery call, and runs 4 and 5 opened with `amicus_capabilities` instead, which is free discovery of the same kind but not the listed call.

The negative result is F1: this is a cold start against a **clean** host.
The one cold start run against a real, un-migrated fleet did not reach amicus at all.

### Probe: first-repair

**Answered from captured evidence, both hosts, two independent error codes.**

Claude Code, S2 (`docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md`): a deliberately invalid `amicus_consult` carrying an unsupported `backend_options` key was rejected before dispatch, and the payload — not just the message — carried `error.code = invalid_arguments`, `temporary = false`, `retry_after_ms = null`, `repair.next_step = correct_arguments`, `repair.tool = amicus_consult`, `repair.alternative`, and `invalid_arguments[0].field` / `.reason`.
The model named those exact fields as the ones it read, retried the tool `repair.tool` names with the unknown key removed, and got `ok: true` on the first attempt after the repair.
Verdict: pass on all three assertions.

That payload conforms field-by-field to §6: `[6.symbolic-codes]` (a symbolic branch key), `[6.retryability]` (`temporary: false` with `retry_after_ms: null`, the invariant `[6.retryability]` requires), `[6.repair-object]` (one object, not an array, with `alternative` as its single prose field), `[6.repair-intent]` (`repair.tool` is the failing tool, not a reroute) and `[6.repair-callable]` (a real registered tool name).

Codex CLI contributed a second, unplanned repair observation on a different code: `amicus_job_consume_result` with no `workspace_root` returned `error.code = invalid_workspace_root` with a message naming the fix, and the model read the code and reported it correctly (`docs/host-captures/install-smoke/codex/0.153.4/transcript.md`).

`[6.offending-value]` is satisfied by disclosure rather than by echo, which is the conformant path: `details.value` is omitted for every caller-supplied input, and the policy is published on the agent-visible error-envelope schema (`src/amicus/schemas/envelope.py:197`, `_OFFENDING_VALUE_POLICY`, which is embedded in the `amicus://error-envelope` description).
An undisclosed omission would be the defect; this one is disclosed.

### Probe: advertised vs. actual

**Answered from captured evidence; applicable and run.**

Every S1 run's paid call returned `ok: true` with the advertised fields, and the S2 and `invalid_workspace_root` observations are the forced-error half.
The error carrier matched the wire on both hosts: the tool result itself is the error, `isError: true`, with the envelope in `structuredContent`, exactly as `CAPABILITY_SUMMARY` and `amicus_capabilities.tool_error_carrier` promise (`[3.output-schema-scope]`, `[6.tool-errors]`, `[6.name-carrier]`).
Host-dependent behavior was cited from captured payloads rather than folklore, as the probe requires: the annotation table in the Claude capture was measured directly off `tools/list` before the run, and the discovery-cost numbers re-serialize what a real client received over stdio.
That measurement also explains a ~120-byte gap honestly rather than calling it drift: `MEASURED` serializes the app's own tool models in process, while the live numbers include the dialect-stamping middleware's output.

Not fully covered: this is one success and one forced error per *host*, not per tool.
The per-tool obligation is discharged in-repo instead, by the golden-envelope and differential suites and by `tests/test_surface_honesty.py`, not by these captures.

### Probe: discovery cost

**Answered from captured evidence; applicable and run; produced F5.**

Counted, not estimated, and measured on the serialized wire response as `[2.compact-baseline]` requires: 92202 bytes for the `all` profile, 92210 for `codex-kimi`, 92202 for `claude`, 18 tools, against a 93000-byte budget.
The ratchet held live on both hosts.
The finding is not the number; it is what the number is evidence *of*.
See F5.

`[2.pd-reduction]` is the axis amicus actually moved, and it is the only one that helps a preloading client: the backend is a parameter rather than a server, so three siblings' catalogs collapsed into one 18-tool surface instead of three.
No `search_tools`/`describe_tool` layer is offered, which is correct under `[2.pd-host]` — it would be extra tools and round trips on a preloading host — and the on-demand error catalog `[6.document-codes]` asks for is served by `amicus_capabilities` and the `amicus://` resources rather than inlined into every definition.

### Probe: security boundary

**Answered from captured evidence; applicable, partially run, and the unrun half is named.**

The confirmation boundary `[3.sec-confirmation]` asks for is real and was met as a user meets it: under `approval_policy = "never"` the Codex host auto-approved `amicus_backends` and `amicus_capabilities` (`read_only_hint: true`) and refused `amicus_consult` and `amicus_delegate_async` in the same run.
No tool was approved that should have been gated.

`[3.sec-exfiltration]` is disclosed on the wire rather than in prose alone: `amicus_backends` publishes each backend's `egress`, `carriers`, `readonly_honesty` and `implicit_context`, and the S7 run's model quoted the raw-egress warning back to the user unprompted.
The capability summary states the boundary in its strongest honest form — "A backend CLI can read files outside the workspace, up to everything the OS user can read, so no choice of workspace is a read boundary."
`[3.sec-untrusted-content]` is implemented at the prompt boundary: `src/amicus/schemas/instructions.py` frames caller-supplied text as untrusted data between markers and refuses forged framing markers, control characters and over-cap input before any spend.

Redaction (S8) was exercised free rather than live: the model's described `amicus_consult` call redacted both synthetic secrets to `<REDACTED>`, and a grep of the full raw harness output for both literal substrings returned zero matches (`docs/host-captures/free-scenarios/claude-code/2.1.263/transcript.md`).
Not run: tracing an actual server-side redaction end to end through a real backend call.
Reason: that needs a paid call, and the six-call budget was fully committed to S1.

### Probe: capability gating

**Answered from captured evidence; applicable and run.**

The tasks extension was not declared on any call from either host, so every call took the plain path and `resultType: "task"` was never returned (`tasks_negotiated=False` in both handshake lines).
That is `[7.task-support]` behaving correctly at the only end this walk could observe: a server MUST NOT return a task to a client whose request did not declare the extension, and neither host got one.
The `[7.task-fallback]` path is what both hosts actually use, and it is a labeled fallback of ordinary tools (`amicus_job_status` / `_result` / `_consume_result` / `_list` / `_cancel`), which is what the rule asks for.
`[7.failed-task]`'s counter-intuitive rule — a `completed` task is a delivery statement, not a success statement — is stated loudly in `CAPABILITY_SUMMARY` and repeated in `amicus_capabilities.tasks.fallback`, which is exactly where the rule says to state it.

Not observed: the tasked path itself, on either host.
Reason: neither v1 host declares the extension, so no captured session could exercise it; it is covered in-repo by `tests/test_tasks_client.py` against a client that does declare it.

### Probe: tool selection

**Answered from captured evidence; applicable and run.**

The adjacent-tool pairs on this surface are the sync/async twins and the four paid verbs.
S3 put a review-shaped request against a catalog that also offers consult, delegate and adversarial review: both the treatment and baseline runs described `amicus_review_changes` with `backend="codex"`, never a neighbor (`docs/host-captures/free-scenarios/claude-code/2.1.263/transcript.md`).
S4 put a stated 15–20-minute task against the sync/async pair: the model chose `amicus_delegate_async` and cited the runtime against the sync deadline, and did not propose trying the sync twin first.
S5 put an availability question against a catalog containing paid verbs: both runs called only the free `amicus_backends`, and `server.log` shows exactly one `tools/call` line per run.
Across the six S1 runs no run reached for a review, delegate or adversarial verb when a consult was what was asked for.

Score on this probe: 5/5 correct selections across S3 (×2), S4 and S5 (×2), plus 6/6 on S1.
The naming discipline behind that is `[3.naming]` and `[3.verbs]`: every tool is `amicus_<verb>_<noun>`, the `_async` suffix is the one axis that distinguishes a twin, and the free/paid split is declared in the description's leading `FREE_MARKER` as well as in `amicus_capabilities.tool_details[].cost`.

### Probe: cross-version

**Answered from captured evidence; applicable and run.**

`amicus_capabilities` reported `fingerprint: amicus/0.1/schema-6` and `surface_digest: f4d9a501…cf2b` on both hosts, byte-identical, so the fingerprint is a stable cross-host cache key (`[9.fingerprint]`, `[2.fingerprint-in-discovery]`).
`fingerprint_covers` travels with it and names the twenty covered categories plus what is deliberately excluded (release identity), which is the disclosure `[9.fingerprint-coverage]` requires.
This walk then exercised the mechanism rather than only inspecting it: F4's fix moved the surface, `FINGERPRINT` moved to `amicus/0.1/schema-7`, and every pin — three manifest snapshots and their hashes, the three surface digests, the wire-shape and result-format snapshots — moved with it in one dedicated commit, with the repo's own drift guards failing first and naming the bump.
`[9.deterministic-order]` is satisfied structurally: `surface_records` sorts tools by name, resources by URI and templates by `uriTemplate` before hashing.
`[9.stability-tiers]` and `[9.tier-metadata]` ride each record's own `dev.bconnelly.amicus/lifecycle` `_meta` key, present on all 18 tools and all 4 resources.

### Probe: long-running operation

**Skipped.
Inapplicability reason:** driving the async job surface end to end requires a real paid `_async` call plus polling, and the authorized six-call budget was fully committed to S1; the paid budget is exhausted, so this walk could not run it either.
Partial free evidence exists and is not counted as the probe: `amicus_job_consume_result` returned a structured `invalid_workspace_root` error with a repair rather than a mysterious failure on the Codex host, so the job tools' error shape is legible.
The status, cancel and result surfaces are covered in-repo by `tests/test_job_tools.py`, `tests/test_job_durability.py` and `tests/test_lifecycle.py`, which is coverage of the contract but not of a host driving it.

### Probe: resource freshness

**Skipped.
Inapplicability reason:** no resource was held across turns in any captured run, and nothing in the install smoke depends on resource caching.
What can be stated without the probe: amicus declares `ttlMs: 0` and `cacheScope: "private"` on every list method and `resources/read`, pinned by `tests/test_manifest.py`, which is the honest value for a surface that varies with `AMICUS_BACKENDS` and per-backend probe state — `[8.cacheable-results]` asks for values chosen from actual volatility and `"private"` whenever the response varies by authorization or configuration context, and `0` is the conservative end of that.
No subscription behavior is advertised, so `[4.subscriptions]` has nothing to verify: there is no mutable resource a client can watch.

## Checklist coverage

| Section | Status | Notes |
| --- | --- | --- |
| §1 | covered | **Server-Level.** F4. Otherwise sound: `[1.name]` distinctive and unversioned; `[1.transport]` stdio, declared in the summary and in `amicus_capabilities.transport`; `[1.stdout]` logs go to stderr or `AMICUS_LOG_FILE`, never stdout; `[1.cred-modes]` splits `backend_auth_required` / `api_key_missing` / `api_key_invalid`; `[1.state-handles]` job ids are opaque with a declared `AMICUS_JOB_TTL`; `[1.spec-revision]` declared, see Step 0. |
| §2 | covered | **Discovery.** F1, F5, F6, F7. `[2.summary]` met on three carriers (`instructions`, `amicus_capabilities`, `amicus://capabilities`), which is what `[2.instructions-advisory]` requires; `[2.negative-scope]` is an explicit four-item list; `[2.pd-reduction]` is the reduction axis taken (one 18-tool surface replacing three siblings' catalogs). |
| §3 | covered | **Tools.** F1, F2, F3, F7. Annotations honest and host-verified — the Codex host auto-approved every `read_only_hint: true` tool and refused every other, with no tool approved that should have been gated; `[3.output-schema]` satisfied on all 18 tools; `[3.mutation-scope]` and `[3.document-reading]` discharged by `amicus_capabilities.annotations_reading`, which states the observable-scope reading explicitly. |
| §4 | OK | **Resources.** 4 resources plus 2 templates; index-not-body throughout (`[2.index-not-bodies]`, `[4.index-vs-body]`); `[4.tool-fallback]` satisfied — every resource's content is also reachable from `tools/list` alone via `amicus_capabilities(include_schemas=...)`, `amicus_backends` and `amicus_models`; `[4.templates]` published for `amicus://backends/{backend}` and `amicus://models/{backend}`; `[4.jsonrpc-errors]` carries the same envelope in `error.data` with the mandatory `[6.rename]`. Bodies are small and static, so `[4.chunkable]` has nothing to bite on. |
| §5 | not-checked | **Prompts.** The server defines no prompts: `prompts/list` returns `[]` on every profile, so there is nothing for §5's rules to bind to and `[5.optional]` makes that a valid design. Nothing on this surface is load-bearing in a prompt. |
| §6 | OK | **Failure Recovery.** Exercised live on two independent codes, both hosts; see the first-repair probe. One envelope, two carriers, with `[6.rename]` applied on the JSON-RPC side; `[6.offending-value]` omission is disclosed on the agent-visible error-envelope schema; `[6.presence]` invariants (`temporary` always present, `retry_after_ms` nullable-but-always-emitted, `null` when `temporary: false`) are enforced in the schema itself via an `if`/`then`. |
| §7 | OK | **Long-Running Operations.** Reviewed against the schemas and the capability summary, not against a live tasked session — the probe is recorded as skipped with its reason. `[7.task-support]` gates tasks on the declared extension at both ends; `[7.failed-task]`'s completed-is-not-success rule is stated in the summary as the rule demands; `[7.task-fallback]` is the labeled `amicus_job_*` family, which every host without the extension uses; `[7.task-handles]` applies the §1 handle discipline with `AMICUS_JOB_TTL`. |
| §8 | covered | **Token Efficiency.** F5. `[8.concise-default]` and `[8.per-capability-detail]` are real: `detail=summary` is the default on `amicus_capabilities` and on every paid result, with `full` opt-in and a `contracts` mode; `[8.house-pagination]` is not needed — no tool returns an unbounded list; `[8.native-pagination]` is untouched, no house convention is bolted onto a native list. |
| §9 | covered | **Versioning.** F4. `[9.fingerprint]`, `[9.fingerprint-coverage]` and `[2.fingerprint-in-discovery]` all satisfied and, as of this walk, exercised: the schema-6 → schema-7 move is the mechanism working. `[9.deprecation-semantics]` states a committed two-minor-release window in `amicus_capabilities.deprecation_policy`; `[9.tier-metadata]` rides every tool and resource record. |

## Residual risks

No Critical finding was raised.
One Major finding (F1) was raised, and its remediation is documentation rather than surface, which is a limit worth stating plainly: amicus cannot outrank a rival server by prose, so on a host that keeps a sibling registered the risk remains until the user removes it.

The residual risks this walk leaves standing:

- **No standing cold-start regression gate.** M6 captured cold-start and first-repair evidence; it pinned no baseline that a future change is measured against.
  `design-workflow.md` Step 9 describes such a gate and it is not built.
  A later change could regress first-call success and nothing in CI would notice.
- **The discovery-cost ratchet is not coverage of first-call success.** It bounds the token cost of discovery, which is a different measure.
  F5's fix scopes the claim; it does not add the missing measure.
- **The tasked path was never exercised by a real host.** Neither v1 host declares the tasks extension, so `[7.*]` is reviewed against schemas and in-repo tests only.
- **No live redaction trace.** S8 verified that the *model* redacted before sending; no captured run traced a server-side redaction of gathered diff or returned output end to end.
- **Advertised-vs-actual is per host, not per tool.** The captures give one success and one forced error per host; the per-tool obligation rests on the in-repo golden and differential suites.
- **The committed `.mcp.json` names a git tag that does not exist yet.** Every capture substituted a locally built wheel for that one argument, so tag resolvability is unproven by M6 and belongs to the publish workflow's gate.
- **F3's remedy is known to be insufficient; F2's is untested.** S6 and S7 remain recorded failures.
  S6 was re-run once, free, against the corrected skill text and failed again on the same assertion, so F3 is an open defect with a known-inadequate fix rather than a closed one (`docs/host-captures/s6-rerun/claude-code/2.1.263/`).
  F2's remedy has not been tested at all: S7 needs a real host and a real approval gate, and the paid budget is exhausted.
  Given that the one remedy of this class that COULD be tested failed, F2's should be treated as unproven rather than probable.
- **F1's stronger remediation is deferred.** Naming the superseded servers in `CAPABILITY_SUMMARY` would put the signal on the surface; it costs another fingerprint bump and is recorded in ADR 0012 as an M7 candidate.

## Remediation summary

The findings cluster in two places, and neither is the server's wire contract.

Four of the nine (F2, F3, F6, F7) are defects in the router skill's text — the surface that tells an agent what a result obligates it to do.
That is where both graded failures came from, and both were failures of *explanation and ordering*, never of tool choice: every call-shape assertion across S1, S3, S4, S5 and S7 passed.
Invest there first — and invest in a stronger instrument than wording.
The one remedy of this class that could be tested free was tested and failed, which says the problem is not that the rules were unsaid but that a rule about generated order is not the kind of rule this class of behavior obeys.

Three more (F5, F8, F9) are honesty defects in instruments rather than in the product: a ratchet that over-claimed what it measures, a parser that could not fail on a case it was written for, and evidence that was correct but not countable.
The remaining two are the surface itself: F4, fixed and fingerprinted, and F1, which documentation can reduce but not close.

## Fix-wave ledger

| Finding | Fix | Moves the surface? |
| --- | --- | --- |
| F1 | `docs/MIGRATION.md`: sibling-removal behavior delta | no |
| F2 | `SKILL.md`: new rule 5, the annotation-attribution directive | no |
| F3 | `reviewing-a-returned-diff.md` ordering directive; `SKILL.md` rule 4 — **re-tested and still failing; open** | no |
| F4 | `CapabilitiesResult.result_format`; `amicus_capabilities` description and `use_when` | **yes — schema-6 → schema-7** |
| F5 | `tests/test_discovery_cost.py` docstring scoping | no |
| F6 | `SKILL.md` frontmatter `description` | no |
| F7 | `SKILL.md` rules 1 and 4; the system fact moves to context | no |
| F8 | `tests/test_migration_doc.py` `_CALL_RE` | no |
| F9 | the session ledger above | no |

## Open questions and assumptions

- **Assumed:** that the two captured hosts are representative of amicus's v1 target clients.
  They are the only two the spec names, and they disagree on preloading, which is itself the most useful thing the captures found.
- **Assumed:** that `docs/host-captures/` is faithful.
  It is a hand-composed allowlist rather than a raw transcript, because repo rule 18 forbids writing prompt inputs to disk; the call-shape facts every assertion turns on are all recorded, and `server.log` independently corroborates the free-scenario runs.
- **Open:** whether `CAPABILITY_SUMMARY` should name the three superseded servers (F1's deferred remediation).
- **Open:** whether the standing cold-start gate should replay captured transcripts or re-spend on each run.
  The second is the only honest measure and the one the budget cannot afford.
