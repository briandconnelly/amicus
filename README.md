# amicus

One MCP server for every second-opinion model: a verb-first surface (`amicus_consult`, `amicus_review_changes`, `amicus_delegate`, …) with the backend (`codex`, `kimi`, `claude`, …) as a parameter, built on FastMCP 4.0.x and MCP 2026-07-28 on top of the [pontonier](https://github.com/briandconnelly/pontonier) backend SDK.
It replaces `codex-in-claude`, `moonbridge` and `claude-in-codex`.

**Status:** milestone M4 (Claude Code).
`amicus_consult`, `amicus_review_changes`, their `_async` twins, both dry runs and the five `amicus_job_*` tools work for `backend="codex"`, `"kimi"` and `"claude"`; `amicus_delegate(_async)` works for Codex and Kimi (Claude is review-only, `feature_unsupported`); `amicus_adversarial_review(_async)` works for Claude (the only backend declaring `adversarial_review`).
Every paid call runs in a detached worker and records a job (`meta.job_id`), and `idempotency_key` dedups an `_async` retry.
`task=True` wiring lands in M5.

## Development

```sh
uv sync
uv run prek install --prepare-hooks   # one-time local hooks
```

The gate is defined once, in `AGENTS.md` (Rules, item 2); CI runs it on every supported Python version.

## Where things are

| Question | Read |
| --- | --- |
| What is being built and why | `docs/superpowers/specs/2026-09-04-amicus-design.md` |
| How milestones are executed by agents | `docs/superpowers/plans/2026-09-04-amicus-execution-model.md` |
| The first executed milestone (M-1, pontonier 0.9.0) | `docs/superpowers/plans/2026-09-04-amicus-M-1-protocol-seams.md` |
| The M0 plan (scaffold, schemas, plugin seam, tasks spike) | `docs/superpowers/plans/2026-09-04-amicus-M0-scaffold-and-surface.md` |
| Naming and scoping notes | `docs/2026-09-04-naming-and-scoping-notes.md` |
| Architecture decisions | `docs/adr/` |
| The M1 plan (Codex end to end) | `docs/superpowers/plans/2026-09-05-amicus-M1-codex-end-to-end.md` |
| The M2 plan (jobs surface) | `docs/superpowers/plans/2026-09-06-amicus-M2-jobs-surface.md` |
| The M3 plan (Kimi) | `docs/superpowers/plans/2026-09-06-amicus-M3-kimi.md` |
| The M4 plan (Claude Code) | `docs/superpowers/plans/2026-09-07-amicus-M4-claude.md` |
| Claude Code CLI evidence captures | `docs/claude-help/` |
| Kimi CLI evidence captures | `docs/kimi-help/` |

## Resuming the work

1. `main` carries M4.
2. In a fresh session say "Resume amicus at milestone M5 per the execution model".
3. The agent writes the M5 plan from the spec and executes it.

Open items only the maintainer can settle: trademark clearance for the name before any PyPI publish; the pontonier repo-layout question (separate repo vs uv workspace) is deferred until after M1.
