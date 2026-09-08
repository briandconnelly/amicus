# Consolidating the model bridges

Notes from a naming and scoping session, 2026-09-04.

## Problem

Three separate MCP servers bridge a host coding agent to a different model:

| Repo | Model | Version |
|---|---|---|
| `claude-in-codex` | Claude Code | 0.9.0 |
| `codex-in-claude` | OpenAI Codex | 0.22.0 |
| `moonbridge` | Kimi (Moonshot) | 0.3.0 |

Two issues, and the second is the real one:

1. The names encode the *host* (`-in-codex`, `-in-claude`). These are MCP
   servers and work in any MCP host, so the names understate their reach.
2. Naming them as a family is hard, and the family is still growing. Only one
   vendor of the three supplies usable imagery (Moonshot -> moon). Anthropic
   gives you Claude Shannon at a stretch; OpenAI gives you nothing. Any scheme
   that needs a lucky coincidence per member is not a convention.

A convention has to survive Gemini, Grok, and whatever is next without a fresh
act of invention.

## Naming options considered

**Literal `<model>-bridge`** — `claude-bridge`, `codex-bridge`, `kimi-bridge`.
Scales forever, instantly understood, discoverable. Costs the `moonbridge` name,
which is the best of the three. Viable middle path: use the literal rule for
package and repo names, keep "Moonbridge" as `interface.displayName`.

**Allusive `<namesake>bridge`** — `shannonbridge` (Claude Shannon),
`moonbridge` (unchanged), and nothing workable for Codex. Rejected: three names
that happen to rhyme is not a convention.

**Merge into one multi-backend server** — dissolves the naming problem
permanently. Pursued below.

## Name availability

Checked 2026-09-04 against PyPI, the npm registry, and GitHub repo search.
Trademark registries were **not** checked.

| Name | PyPI | npm | GitHub |
|---|---|---|---|
| `peerpanel` | free | free | zero results |
| `amicus` | free | taken | top hit `nathos/amicus` (164*, dormant Middleman template); nothing in AI tooling |
| `bridgehead` | free | free | `samply/bridgehead` (14*, federated research), `ZakiPedio/BridgeHead` (83*, Active Directory) |
| `discussant` | free | free | academic slide repos only |
| `agentpanel` | free | free | `InternScience/AgentPanel` (80*), `SmockDev/agentpanel` ("steer all your coding agents") |

`agentpanel` is unregistered on both package registries — the collision is
brand-level, not a blocked name. But `SmockDev/agentpanel` is in this exact
space, which is the disqualifying find.

**Resolved 2026-09-08 by ADR 0013.** "Amicus" has commercial use in legal
practice-management software, and a real trademark search was called for here
before committing to the name. That search was not performed; the maintainer
decided deliberately to publish without clearance. See
`docs/adr/0013-proceed-without-trademark-clearance.md` for the reasoning, the
consequences accepted, and what would reopen it.

### Why `amicus`

*Amicus curiae* — "friend of the court" — is an outside party who submits an
independent brief that the decision-maker reads and is **not bound by**. That is
the product exactly: a second opinion from a model that is not the actor,
advisory rather than authoritative. It matches the safety property both
`claude-in-codex` (review-only) and `codex_delegate` ("returns a diff you apply
yourself") were deliberately built around.

Tool names read well with the model as a parameter rather than a prefix:
`amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_status`,
with `model: "claude" | "codex" | "kimi"`.

`peerpanel` is the alternative if `delegate` becomes central and the product is
really a bench of workers rather than an advisor.

## Merge scoping

Measured, not estimated. Normalizing model names away (`codex`/`kimi` -> `YY`,
etc.) and diffing `codex-in-claude` against `moonbridge`:

| Module | Diff lines after normalization |
|---|---|
| `preflight.py` | 16 |
| `normalize.py` | 54 |
| `errors.py` | 80 |
| `param_contracts.py` | 97 |
| `orchestration.py` | 226 |
| `backend.py` | 253 |
| `config.py` | 539 |
| `schemas.py` | 539 |
| `cli_contract.py` | 1435 |
| `server.py` | 1578 |

### Findings

- **`moonbridge` is a trimmed fork of `codex-in-claude`.** Identical 21-module
  layout; tool surfaces differ by exactly one tool (`transfer`, Codex-only).
- **Divergence sits where it should.** The largest diffs are `server.py`,
  `config.py`, and `cli_contract.py`. `cli_contract.py` is *supposed* to be
  per-backend, so much of that number is not duplication to eliminate — it is
  the layer a backend abstraction correctly isolates.
- **`claude-in-codex` is the outlier.** Different lineage: `jobs.py`,
  `context.py`, `_job_worker.py` where the others have `orchestration.py`,
  `manifest.py`, `errors.py`, `param_contracts.py`. No `delegate`, no `events`,
  no `rate_limited`; it alone has `adversarial_review`.

### Tool surface

Shared by all three (15): `consult`, `consult_async`, `review_changes`,
`review_changes_async`, `dry_run`, `job_cancel`, `job_consume_result`,
`job_list`, `job_result`, `job_status`, `models`, `status`, `capabilities`,
`auth_required`, `not_found`.

Divergent (7): `delegate`, `delegate_async`, `delegate_dry_run` (not in
`claude-in-codex`); `transfer` (Codex only); `events`, `rate_limited` (not in
`claude-in-codex`); `adversarial_review` (Claude only).

### Scale

~38k LOC source and ~64k LOC tests across the three repos. Versions are badly
skewed (0.22.0 / 0.9.0 / 0.3.0), so a merge means one release line and three
existing user populations to migrate.

## Recommendation

**Sequence it in two steps. Do not attempt a three-way merge.**

**Step 1 — merge `codex-in-claude` + `moonbridge`.** They are already the same
codebase. This is mostly deleting a fork and proving the backend abstraction
against two real CLIs. Low risk, and it is where most of the duplicated
maintenance actually lives. Name the merged project here, not before — you will
know more about what it is by then.

**Step 2 — bring in `claude-in-codex`.** Only once the abstraction has survived
contact. Needs a lineage migration (`jobs.py` -> `orchestration.py`) and a
decision on `adversarial_review` and the review-only policy. Doing that while
also inventing the abstraction compounds two hard problems.

## Open decisions

- ~~Trademark clearance for `amicus`.~~ Decided 2026-09-08: proceed without it (ADR 0013).
- **Policy divergence.** `claude-in-codex` is deliberately review-only with no
  `delegate`. In a merged server that is either a per-backend capability flag or
  a unified policy — and unifying it *upward* weakens a guarantee that was built
  on purpose.
- **Release-coupling risk.** One `FINGERPRINT` and one release line means a
  backend-specific breakage can block releases for all three.
- **Env var migration.** Three prefixes (`CLAUDE_IN_CODEX_*` 13 vars,
  `CODEX_IN_CLAUDE_*` 13, `MOONBRIDGE_*` 10) collapse to one. Breaking for
  existing users; wants a deprecation shim on a minor bump.
- Whether the merged server keeps three separate live-integration gates (three
  CLIs, three auth models, three paid test suites) or gates them per-backend.
