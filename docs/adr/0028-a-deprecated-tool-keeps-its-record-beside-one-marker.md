# ADR 0028: a deprecated tool keeps its full record beside one lifecycle marker

**Status:** Accepted (2026-09-14)

## Context

Issue #98: `amicus_dry_run` is named like a preview for any paid call, but it previews only `amicus_review_changes`.
Its sibling `amicus_delegate_dry_run` names its target, and consult and adversarial review have no preview at all, so an agent wanting one of those can reasonably pick `amicus_dry_run`.

Renaming it is the first deprecation amicus has made.
`amicus_capabilities.deprecation_policy` already promised that a deprecated tool "stays discoverable for two minor releases with a deprecation marker in its lifecycle _meta naming the replacement", but `lifecycle_meta` only ever emitted `{stability}`, so the marker had no shape.
`[9.rename]` treats a rename as remove-plus-add and keeps the old name for the documented window, `[9.deprecation-marker]` fixes the marker's fields, and `[9.tier-metadata]` puts it on the capability's own discovery record and in the capability summary.

## Decision

**The review preview is `amicus_review_changes_dry_run`, and `amicus_dry_run` stays as a deprecated alias.**
Both register one handler, so they cannot drift.
Each returns its own name as `tool`, so the alias's result is the one its callers already branch on, and an error names the tool that was called.

**The marker is one object, `deprecation`, beside `stability` in `dev.bconnelly.amicus/lifecycle`.**
Its fields are exactly `since`, `removal_at_or_after`, `replaced_by` and `migration`, and a null `replaced_by` is published, never dropped.
Its presence is the deprecation signal and its absence the not-deprecated one.
It never replaces the tier: the alias stays `experimental`.
The same object rides the tool's `amicus_capabilities` row at both detail levels, where every other row carries `deprecation: null`.
One table, `DEPRECATED_TOOLS` in `src/amicus/tools/_meta.py`, is the source for both carriers, and every reader goes through an accessor rather than importing it by value.

**The alias keeps its whole record.**
Its input schema, annotations and outputSchema are byte-identical to the record `amicus_dry_run` had before the rename; only its title, description and lifecycle `_meta` change.
A lean alias without an outputSchema was drafted to save about 4 KB and rejected: `[3.output-schema]` binds every data-bearing tool, and its carve-out reaches only a result nothing parses.
The description leads with the deprecation, because a host may never show `_meta` to the model.
It then keeps the replacement's description whole, so the sentence saying a preview does not bound what the backend reads survives on either name.

**The alias sits last among the free tools.**
`FREE_TOOLS` and `TOOL_ORDER` are the cost and wire-order taxonomies, and deprecation is orthogonal to both, so there is no deprecated group.
The alias is registered after the discovery tools, so every other tool keeps its relative wire order.

**The window is 0.3.0 to 0.5.0, written as constants, and amicus removes the tool at `removal_at_or_after`.**
`since` names the first release that ships the deprecation.
The tree still declares 0.2.0, because a work PR leaves the version literals alone (AGENTS.md rule 19).
The dates are not derived from `__version__`: a derived date would move fingerprint-covered metadata inside the release PR, which may move only version literals.
Two checks hold them instead.
`scripts/check_release_state.py` rejects a release outside any window: one before `since`, or one at or past `removal_at_or_after` with the entry still listed.
It reads the table with `ast`, because the `verify` job cannot import amicus, and a test pins that read against the runtime table.
`tests/test_meta.py` fails once the tree declares a version at or past a window's end, so that release waits for an ordinary removal PR.

## Consequences

tools/list grows by 9,042 bytes on the `all` profile, to 113,718, almost all of it the alias's record.
The budget is raised with that narrative in `tests/test_discovery_cost.py`, and the bytes come back at removal.

`FINGERPRINT` moves to `schema-27`.
No dry run is ever stored as a job result (`JOB_RESULT_MODELS` holds only the four paid verbs), so `RESULT_FORMAT` stays 6.

If the next release is not 0.3.0, both dates move in an ordinary PR before it; the release predicate says so if they do not.

Commands, the skill, the README, MIGRATION.md and the spec name the new tool, and a test keeps every command off the alias.
ADRs 0002 and 0007, whose standing decisions name `amicus_dry_run`, carry a status note pointing here; ADR 0019 mentions it only as history.
Previews for consult and adversarial review stay out of scope.

Codex was consulted once on the draft design, at high reasoning effort.
It rejected the lean alias for the reason above and asked that the deprecated description keep the safety sentence.
It recommended the release-state check and the removal ratchet, asked that the marker test cover both carriers, and found stale tool counts in the README, the skill, the spec and four test files.
All of it was taken.
Codex then reviewed the finished branch once and returned `concerns` at high confidence, with one low finding: ADRs 0002 and 0007 still taught the deprecated name as current guidance.
They now carry the status note above, and this ADR no longer claims that every doc names the new tool.
