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

`scope` is optional here (unlike `amicus_review_changes`): pass it the same way
(`working_tree` default, `branch`/`base`, or `commit`/`commit`) when there is a
concrete diff to attack, or omit it to critique a claim or plan described in
`question`/`extra_context` alone. Pass the absolute repo path as `workspace_root`.

Treat the returned `verdict` and `confidence` as claims to verify, not settled fact
— run this project's own checks before acting on a finding.

For a review that can exceed the synchronous deadline, use
`amicus_adversarial_review_async` instead and poll `amicus_job_status` for the
result — a sync call whose deadline expires still spends the paid run.
