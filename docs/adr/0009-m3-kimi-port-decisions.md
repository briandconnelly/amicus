# ADR 0009: What the M3 Kimi port kept, changed, and dropped

**Status:** Accepted (2026-09-06, M3)

## Context

M3 ports moonbridge's Kimi adapter, CLI contract, handshake staging, normalizer and model catalog behind the M0 plugin seam, onto the M1 orchestration loop.
Kimi differs from Codex in three ways that shape every decision below: it has no sandbox and no approvals, its prompt is argv-only, and it has no last-message output.
The maintainer approved the choices below in the M3 planning session.

## Decisions

- A consult outside a git repository runs in an empty temp dir (`EmptyDirSite`, prefix `amicus-wt-`) with `NO_REPO_WARNING` stamped on `meta.security_warnings`; review and delegate keep failing `not_a_git_repo`.
- `empty_response` is an outcome inspection: `KimiBackend` implements pontonier's `OutcomeInspector`, so a zero-exit run with no answer file and no assistant text is refused as a result without any Kimi branch in the loop.
- Pre-spend effort validation is the adapter's `validate_request`: shape, then the live catalog (which decides alone when it names the alias), then the fallback vocabulary only when the catalog is silent, and fail open on an unlisted alias; the refusal carries `details.allowed_values` and a repair naming `amicus_models`.
- `instructions_append` rides the handshake prompt file as a leading section composed by `schemas.instructions.compose`; consult and review only.
- Artifacts (Kimi's answer file, Codex's last message) are read through a hardened reader, `orchestration.run._read_bounded`: no symlinks, no FIFOs, regular files only, 1 MB cap; `cli.read_answer_file` was not ported, since the hardened reader is the one reader every backend uses.
- `src/amicus/orchestration/run.py` now calls `finalize` and `finalize.apply_exec` before outcome inspection and classification, so a failure envelope's meta carries the session id and usage the run produced, mirroring moonbridge's `runspace.apply_run_meta`; this was a porting gap the Task 7 differential exposed in the shared loop, not a Kimi-only change.
- The Kimi classifier strips ANSI SGR sequences before sanitizing (`cli._strip_ansi`), because pontonier's `sanitize_echo*` only deletes the ESC byte and leaves the rest of an SGR sequence in place.
- Kimi 0.41.0 is supported on the captured evidence in `docs/kimi-help/0.41.0/`; the behavioural probes are inherited from moonbridge's 0.39.1 findings and re-checked only where the live gate can observe them.
- Names: `AMICUS_KIMI_*` with `MOONBRIDGE_` legacy twins (none for `BIN`), agent `amicus-readonly`, handshake prefix `amicus-kimi-handshake-`; `AMICUS_KIMI_EXTRA_ARGS` is always refused with the reason.
- Not ported: tiers and sandbox defaults, `WORKTREE_BASE`, the handshake-dir diff exclusion, `reconcile_dropped_model` (the loop's `stamp_run` already does it), the `extra_args_rejected` classifier branch.
- The model catalog is probed live with a 300 s in-process cache; provider names, base URLs and API keys are never parsed.
- The classifier receives the last message and the site sanitizer and sanitizes before truncating, as the spec requires; `finalize` carries `cached_input_tokens`.
- Differentials against moonbridge (`tests/fixtures/kimi_differentials.json`, captured at the sibling commit the fixture names) compare a projection: argv modulo temp paths, the binary token and the agent name; envelope codes after generalization, `temporary`, `retry_after_ms`, usage, session id, summary/verdict/findings, and four leak checks.

## Consequences

- M4 reuses the loop, the sites and the hardened reader unchanged; Claude's outcome inspector follows the same seam Kimi's does.
- A Kimi release that changes a flag or a stream-json line shape shows up as `cli_contract_changed` at run time and as a failed evidence test once the new help is captured under `docs/kimi-help/<version>/`.
- The `finalize`-before-classify reorder in the shared loop means a partial run's failure envelope can now carry a `usage` block; `render_failure`'s own `failure.usage` still takes precedence when set, so this only fills in a usage/session id that was previously dropped on failure.
