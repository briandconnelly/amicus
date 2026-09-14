# ADR 0027: every rule in the server instructions fits the prefix a host shows

**Status:** Accepted (2026-09-14)

## Context

Issue #49, an agent-friendliness audit finding graded a nit, said the server `instructions` (`CAPABILITY_SUMMARY` in `src/amicus/server.py`) led with protocol-era background before any rule and shipped as one unbroken run: 3,338 characters with no newlines when filed, 4,033 by the time it was worked.
`[2.rules-then-context]` wants scope first, then each binding rule, then background after the rules or not at all.

Working the issue turned up a stronger reason than style.
In a Claude Code session on 2026-09-14, the instructions shown to the model were cut at exactly 2,048 characters for two servers, each measured against the string the server actually serves: amicus 0.2.0, which serves 3,698 characters, and codex-in-claude 0.22.0, which serves 3,987.
On 0.2.0 the cut falls mid-sentence at "read error.backend, and", so following `error.repair`, treating findings as claims, reading a `completed` task as a delivery statement, the job-handle TTL and the `fingerprint`/`surface_digest` rule never reached the model in that host.
The order of the text decided which rules a Claude Code agent received.

`[2.instructions-advisory]` says `instructions` is advisory and never a rule's only carrier.
Whether each rule had another carrier was not re-audited here; what the cut certainly removed is the one surface that states the rules together and in priority order, which is the reason to have it.

## Decision

**The text is three blocks: scope, a list of rules, then reference.**
The scope paragraph says what amicus does, which tool serves which verb, and what it does not do.
The rules follow under a `Rules:` header, one per `- ` item, each opening on its imperative.
The reference block comes last and states facts, not rules: each has an authoritative carrier elsewhere, `amicus_capabilities` for most of them.
It is not called background, because cancellation, retention and the error carriers' secondary fields are contract, not history.

**Every rule ends before `INSTRUCTIONS_HOST_CAP`, and only reference may fall past it.**
The constant is 2,048, the measured Claude Code cut.
It names a host behaviour, not a protocol limit; if a host is measured cutting shorter, lower the constant and fit the rules to it.
`tests/test_server.py::test_summary_is_scope_then_rules_then_reference` pins the constant literally, the three blocks, each safety clause of the scope, the rule leads in order, the budget, both error-carrier paths, and that the protocol-era facts and the transport sit in reference.

**Each error carrier keeps its own path.**
A tool failure is branched on `error.code` in `structuredContent`; a resource-read failure's envelope is in JSON-RPC `error.data`, whose code is `machine_code`, because the numeric JSON-RPC `error.code` is era-bound.
One "on a failure" rule for both would send an agent to the era-bound number.

**Protocol-era mechanics leave the rules, and repository provenance leaves the text.**
The target revision and when a task may be returned move to reference, and `amicus_capabilities` carries both machine-readably as `protocol_revision` and `tasks`.
The transport is stated there too, as `[1.transport]` asks of a capability summary.
The pointer to `docs/host-captures/` is dropped: it names a path in this repository, which an agent reading the text over the wire cannot open.

## Consequences

The rules block has a fixed budget, with 44 characters of headroom at the time of this ADR.
Adding a rule means shortening one or moving a fact to reference, and the test fails an edit that forgets.

`initialize` and `server/discover` carry the changed text, so `FINGERPRINT` moves to `schema-26`; no stored result changes, so `RESULT_FORMAT` stays 6.

The cut was measured in Claude Code only.
Codex CLI and other hosts may show more or less, and nothing here claims otherwise.

Codex was consulted once on the draft, at high reasoning effort.
It confirmed the draft's factual claims against source, and that every item removed from or moved within the text is still carried by a tool schema, a tool description or `amicus_capabilities`.
It found four things, all taken: the draft's single failure rule sent a resource-read failure to the era-bound numeric code; the last block was mislabelled background; `[1.transport]` wants the transport stated; and the test pinned neither each safety clause nor the literal cap.
