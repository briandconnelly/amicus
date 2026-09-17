# ADR 0031: the marketplace pointer decides what users run

**Status:** Accepted (2026-09-16)

Supersedes [ADR 0015](0015-mcp-json-pins-an-already-published-release.md).
The design, its probes and its review are in `docs/superpowers/specs/2026-09-16-amicus-release-activation-design.md`.

## Context

ADR 0015 had `.mcp.json` pin the previous release until a follow-up pin-move PR advanced it, and called the gap a self-healing degradation.
It rested on an assumption its own "What would reopen this" named: that a plugin host re-reads the manifest.
It does not.

Claude Code 2.1.273 and Codex CLI 0.154.0 both copy the installed plugin into a directory keyed by `plugin.json`'s version and re-materialize only when that version changes.
Two consequences followed (issue #117).
An install taken between the 0.3.0 release merge and its pin-move runs the 0.2.0 server under 0.3.0's skills, and stays that way.
More broadly, any install taken mid-cycle froze whatever skills and commands were on `main` against the previous release's server: 32 commits touched `skills/` or `commands/` between v0.2.0 and v0.3.0.
Every tag since the bootstrap is itself skewed, because ADR 0015 required its pin to trail the version it shipped.

## Decision

`.claude-plugin/marketplace.json`'s plugin entry pins a published release tag by `ref` and `sha`, so hosts install the tag snapshot instead of `main`.
`sha` is required and must equal the tag's peeled commit, because a host silently serves `sha` over a disagreeing `ref`, and the `v*` ruleset's admin bypass means a tag can move.

`.mcp.json` names its own release again and rejoins rule 19's version literals, so a tag's skills and server always match.

ADR 0015's invariant — the pointer users follow names an already-published release — is kept, and moves from `.mcp.json` to the marketplace pointer.
A `chore(release):` PR advances the pointer after publishing, and a release is not complete until it merges.

The pointer first activates at 0.4.0.
No existing tag is consistent enough to point at, and pointing at `v0.3.0` would be a no-op for every install already keyed `0.3.0`.
Until then the entry stays `"./"`, which the checker accepts only up to 0.4.0.

## Consequences

- Plugin users install a self-consistent snapshot, and changes on `main` reach no one until a release.
- `scripts/check_release_state.py` requires the pin to equal the release, and checks the pointer's shape, that it trails the release, and that its tag is annotated, matches `sha` and agrees with itself.
  A `--base` mode checks a pull request's pointer change, so the pointer never moves backwards and never returns to `"./"`.
- `docs/RELEASING.md` step 3 creates the release tag locally before checking, since the pin now names it; step 6 pushes that tag rather than creating it.
- These checks prove structure, never publication: that the pointed-at release reached PyPI remains the maintainer's assertion, as rule 23 already requires of the rule-20 record.
- Nothing automated notices a forgotten pointer PR; it is a checklist step.
  Users stay on the previous, working release until it merges.

## What would reopen this

- A host that resolves the plugin from the marketplace's branch rather than the entry's `ref` and `sha`, or that stops keying its cache by version.
- PyPI becoming the documented install channel, which would move `.mcp.json`'s pin off git tags.
