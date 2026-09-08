---
description: Run a fixed adversarial critic (via amicus) against a plan, claim, or decision
argument-hint: "<backend> [working_tree|branch <base>|commit <sha>]"
---

Use the `amicus_adversarial_review` MCP tool from the amicus server to have a fixed
adversarial critic attack a plan, claim, or decision before you commit to it.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. `amicus_adversarial_review`
supports `claude` only in v1 — do not route an adversarial-review request to `codex`
or `kimi`. If the request does not confirm `claude` is enabled, call
`amicus_backends` first and check `enabled: true` and `status.authenticated: true`
for `claude`.

State the plan, claim, or decision under attack in `target`. It is required, and it is
the only carrier for the subject of the critique: this tool takes no question argument.
Supporting material is optional — put the case for the target in `evidence`, and any
surrounding background in `extra_context`. Pass the absolute repo path as
`workspace_root`.

`scope` is optional, exactly as it is on `amicus_review_changes` (both default to
`working_tree`); what differs is that an adversarial review needs no diff at all. Pass
it the same way (`working_tree` default, `branch`/`base`, or `commit`/`commit`) when
there is a concrete diff to attack, or omit it to critique a `target` described in
`evidence`/`extra_context` alone.

Treat the returned `verdict` and `confidence` as claims to verify, not settled fact
— run this project's own checks before acting on a finding.

For a review that can exceed the synchronous deadline, use
`amicus_adversarial_review_async` instead and poll `amicus_job_status` for the
result — a sync call whose deadline expires still spends the paid run.
