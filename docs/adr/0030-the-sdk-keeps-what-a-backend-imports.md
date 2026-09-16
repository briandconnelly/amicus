# ADR 0030: amicus.sdk keeps what a backend imports

**Status:** Accepted (2026-09-15)

## Context

ADR 0029 copied pontonier into amicus as `amicus.sdk` and left "merging the modules into the amicus packages that own each concern" to #118 through #123.
Three of those issues named a destination the module's own importers cannot reach: two of them a backend cannot, and the third the sdk itself cannot.
The design spec lets `backends/*` import `amicus.plugin`, `amicus.config.envspec`, `amicus.schemas.codes` and `amicus.sdk`, and the import contract "backends never import the server layer" forbids `amicus.orchestration` and `amicus.jobs`.
It does not forbid `amicus.schemas`, which a backend already imports; the boundary that rules out #120's destination is the sdk's own.
Yet all three backends run their CLIs through `core.runtime`, which #119 would have moved to `amicus.orchestration`.
All three clean their own diagnostics with the alias-aware `sanitize_echo_prose` in `core.worktree`, which was bound for `amicus.orchestration` too.
The Codex backend reads its model cache through `core.jsoncache`, which #118 would have moved to `amicus.jobs`.
And `sdk.backend.protocol` imports `REPAIR_STEPS` from `conventions.envelope`, which #120 would have moved to `amicus.schemas`, a package the contract "the sdk never imports the rest of amicus" puts out of the sdk's reach.
Following the issues literally meant weakening one of those contracts, or dissolving the sdk into a new plugin-facing package that would be the same layer under another name.

## Decision

**`amicus.sdk` stays, as the layer a backend imports, and what only the server uses leaves it.**
A module stays when a backend, or an sdk module a backend relies on, imports it.
Otherwise it moves to the amicus package that owns its concern.

What stays: `backend.protocol` and `backend.contract`; `conventions.envelope`, `conventions.annotations` and `conventions.preflight`; `core.runtime`, `core.streamcap`, `core.redaction`, `core.jsoncache` and `core.pathalias`; `testing.conformance` and `testing.surface_honesty`.

What leaves:

- `core.worktree`, `core.gitdiff` and `core.gitproc` move to `amicus.orchestration`, and `core.workspace` merges into `amicus.orchestration.workspace` (#119).
  Worktree's path-alias helpers are split out into the new `core.pathalias` first, because the backends need them and never need the worktree lifecycle.
- `core.jobs` becomes `amicus.jobs.store`, and `core.idempotency` becomes `amicus.jobs.idempotency` (#118).
- `conventions.fingerprint` merges into `amicus.schemas.fingerprint`, and `conventions.prompts` merges into `amicus.orchestration.prompts` (#120).
- `testing.pair_parity` moves to `tests/support` (#121), and `backend.classify` is deleted (#122).

**The import contracts do not change.**
"The sdk never imports the rest of amicus" keeps a module that stays from depending on one that left.
"Backends never import the server layer" keeps a backend from depending on one that left.
"sdk core is a leaf layer" still describes what remains of `amicus.sdk.core`.

**The plugin API does not move.**
The types a backend hands amicus stay where they are, so `PLUGIN_API_VERSION` stays at 2 and #115 is unaffected.

## Consequences

#118, #119 and #120 are narrower than filed: `core.runtime`, `core.jsoncache`, `conventions.envelope` and `conventions.annotations` stay in `amicus.sdk`.
A module that leaves takes its import path with it and leaves no compatibility shim, because no release has shipped `amicus.sdk`.
The sdk's test suite stays in `tests/sdk/`, including the tests of modules that left, because those tests rely on its `conftest.py` git isolation; only their imports change.
AGENTS.md lists what `amicus.sdk` holds, so it changes in a PR of its own once the moves land (rule 9).
