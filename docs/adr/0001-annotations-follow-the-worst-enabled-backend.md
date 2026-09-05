# ADR 0001: Tool annotations follow the worst enabled backend

**Status:** Accepted (2026-09-04, M0)

## Context

One tool serves several backends whose observable effects differ.
Claude's config modes may run workspace hooks, so claude-in-codex marks paid tools `destructiveHint: true`.
Codex and Kimi confine writes to a throwaway worktree, so their bridges mark paid tools `destructiveHint: false`.
An annotation set is static per tool, but the backend is a per-call parameter.

## Decision

Annotate each tool for its worst enabled backend, per `[3.ap-mode-annotations]`.
The enabled set comes from `AMICUS_BACKENDS` (default: every in-tree backend), so a profile that enables Claude advertises paid tools as `destructiveHint: true`, and a codex/kimi-only profile advertises `false`.
Each backend's own `AnnotationEffects` is published on `amicus_backends` so an agent can read the per-backend truth.
Job reads (`amicus_job_status`, `amicus_job_result`, `amicus_job_list`) advertise `readOnlyHint: true` under the observable-scope reading (`[3.mutation-scope]`), documented on `amicus_capabilities.annotations_reading`.

## Consequences

- A user who enables Claude pays mutation-grade approval friction on codex-only calls; this is a deliberate UX regression, disclosed on `amicus_capabilities`.
- The manifest snapshot and discovery-cost ratchet are measured per profile, because the annotations differ per profile.
- Host approval behaviour is captured in M6 (`docs/superpowers/specs` → "Annotations").
