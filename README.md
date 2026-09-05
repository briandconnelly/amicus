# amicus

One MCP server for every second-opinion model: a verb-first surface (`amicus_consult`, `amicus_review_changes`, `amicus_delegate`, …) with the backend (`codex`, `kimi`, `claude`, …) as a parameter, built on FastMCP 4.0.x and MCP 2026-07-28 on top of the [pontonier](https://github.com/briandconnelly/pontonier) backend SDK.
It replaces `codex-in-claude`, `moonbridge` and `claude-in-codex`.

**Status:** milestone M0 (scaffold and schema-only surface).
Every tool is registered with its final schema; paid tools return `not_implemented` until their backend lands (M1 Codex, M3 Kimi, M4 Claude).

## Development

```sh
uv sync
uv run prek install --prepare-hooks   # one-time local hooks
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

## Where things are

| Question | Read |
| --- | --- |
| What is being built and why | `docs/superpowers/specs/2026-09-04-amicus-design.md` |
| How milestones are executed by agents | `docs/superpowers/plans/2026-09-04-amicus-execution-model.md` |
| The first executed milestone (M-1, pontonier 0.9.0) | `docs/superpowers/plans/2026-09-04-amicus-M-1-protocol-seams.md` |
| The M0 plan (scaffold, schemas, plugin seam, tasks spike) | `docs/superpowers/plans/2026-09-04-amicus-M0-scaffold-and-surface.md` |
| Naming and scoping notes | `docs/2026-09-04-naming-and-scoping-notes.md` |
| Architecture decisions | `docs/adr/` |

## Resuming the work

1. Confirm pontonier 0.9.0 is on PyPI (`uv pip index versions pontonier` or the GitHub release) and that PR pontonier#25 was merged.
2. In a fresh agent session, from this directory, say: "Resume amicus at milestone M0 per the execution model; pontonier 0.9.0 is released."
3. The agent writes the M0 implementation plan from the spec (writing-plans format, per the execution model), then executes it with subagent-driven development.

Open items only the maintainer can settle: trademark clearance for the name before any PyPI publish; the pontonier repo-layout question (separate repo vs uv workspace) is deferred until after M1.
