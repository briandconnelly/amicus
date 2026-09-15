# ADR 0029: the backend SDK lives in amicus

**Status:** Accepted (2026-09-15)

## Context

pontonier was created as the shared core of codex-in-claude, moonbridge and claude-in-codex.
Those three were combined into amicus, which is now the only consumer still being developed.
Keeping the core in its own repository cost a second release process, an exact pin (`pontonier==0.9.0`) and a version bump for every SDK change amicus needed.
Issue #13 asked whether the two should stay separate repositories or become one uv workspace.
The design is `docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md`, approved by the maintainer on 2026-09-15 and reviewed by Codex before it was planned.

## Decision

**Neither: pontonier's code is copied into amicus as `amicus.sdk`, and amicus stops depending on pontonier.**
The copy is pontonier's `v0.9.0` tag, commit `185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d`, with every file name kept.
It landed as one mechanical commit whose only edits are an import rewrite, a test-helper import rewrite and ruff's import sort, and a provenance check rebuilt that commit from the tag with an empty diff.
History and blame stay in pontonier's repository.

**Move first, dissolve later.**
`amicus.sdk` keeps pontonier's four layers, `core`, `backend`, `conventions` and `testing`.
import-linter keeps `amicus.sdk` from importing the rest of amicus, and `amicus.sdk.core` from importing the other three layers.
Merging the modules into the amicus packages that own each concern is follow-up work: #118, #119, #120, #121, #122 and #123.
ADR 0030 narrows that follow-up: `amicus.sdk` keeps the modules a backend imports, and only those the server alone uses move out.

**pontonier stays published for the siblings.**
It is feature-frozen at 0.9.0 and maintained only for codex-in-claude, moonbridge and claude-in-codex until they are archived.
From M8 on, amicus's copy is authoritative for amicus, and nothing keeps the two copies aligned.
A fix that also affects a sibling's pinned pontonier is the maintainer's to backport, because AGENTS.md rule 17 keeps agents out of that checkout.

**ADR 0005's repair vocabulary is now in-tree.**
ADR 0005 says a `RepairStep` comes from `REPAIR_STEPS` and "is added upstream, never invented here".
Upstream now means `amicus.sdk.conventions.envelope.REPAIR_STEPS`, so adding a step is an ordinary amicus change.
That unblocks #103, which was waiting on briandconnelly/pontonier#30.

**The plugin API moves to version 2.**
A third-party backend now hands amicus `amicus.sdk` types rather than pontonier's, so `PLUGIN_API_VERSION` moves from 1 to 2.
The bump rejects only a plugin that pins `api_version=1`, because `BackendPlugin.api_version` defaults to the running amicus's own constant; #115 tracks that.
No release can enable a third-party backend yet, so no running deployment is affected.

## Consequences

`FINGERPRINT` and `RESULT_FORMAT` do not move: no fingerprint category covers a dependency or a module path, and no stored job record carries a pontonier-named value.
The pinned manifest, wire-shape and result-format fixtures pass unchanged.

The separate `pontonier` logger is gone.
The SDK's modules log on `amicus.sdk.*`, a subtree of `amicus`, so in a process that has called `obs.configure` their records reach the policy handlers it installs there; ADR 0023 carries a note.
The job worker never calls `obs.configure`, so there an SDK record falls through to `logging.lastResort` and the worker's `stderr.log`, exactly as the `pontonier` logger's records did before M8; #128 tracks that.

Four literal defaults in the worktree module still name pontonier: the worktree prefix, the git identity pair and the `pontonier-nohooks-` temporary-directory prefix.
It was `amicus.sdk.core.worktree` when this ADR was accepted, and #119 moved it to `amicus.orchestration.worktree`.
amicus passes its own prefix and identity, so only the last reaches the filesystem, and #123 retires all four.

Five open pontonier issues describe behaviour amicus ships, and each has an amicus issue: briandconnelly/pontonier#27 is #124, #28 is #125, #31 is #126, #15 is #127, and #30 is #103.
briandconnelly/pontonier#29 is already worked around in `src/amicus/jobs/polling.py` (#95), and #5 to #8 are redaction enhancements with no defect visible in amicus.

`scripts/capture_codex_differentials.py` and `scripts/capture_kimi_differentials.py` keep importing pontonier, because they run inside a sibling's virtualenv and feed that sibling's own objects.

AGENTS.md still says amicus is built on the pontonier SDK; it changes in a PR of its own (rule 9).

`amicus.sdk` import paths are not yet stable for plugin authors, because #118 to #123 move its modules during the 0.x dissolution and #120 moves the conventions types a plugin imports.
