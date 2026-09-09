# ADR 0014: Carry the release predicate on the annotated tag, and say what it proves

**Status:** Accepted (2026-09-09, before the 0.1.0 release)

## Context

Issue #25 found that nothing between the tag push and the PyPI upload consulted rules 19 or 20.
The chain was verified rather than assumed: `.release-evidence/` is gitignored, so no CI job could see the rule-20 record; the only validator ran under `AMICUS_RELEASE_CHECK=1`, which nothing in CI sets; `.github/workflows/publish.yml` triggered on `push: tags: ["v*"]` unconditionally; and the sole gate on the `pypi` job compared the tag text to the wheel filename's version.
Any identity able to create a `v*` tag published, whatever the rules said.

The issue asked for a deliberate choice between two honest end states: accept the rules as conventions and stop describing them as controls, or make the predicate readable by the publish workflow so the job can refuse.
Its own framing is the reason the middle state was untenable — rules documented as controls but enforced by nobody produce confidence in proportion to the documentation rather than the mechanism.

The circularity that had blocked the obvious fix: a record naming commit X cannot live inside commit X, which is why the record was gitignored in the first place.

## Decision

Both, split by what is actually provable, and never conflated.

**The evidence travels on the annotated tag.**
The rule-20 record is the tag's message, verbatim (`git tag -a vX.Y.Z -F .release-evidence/live-gates.json --cleanup=verbatim`).
The tag is the object rule 21's ruleset protects and the object whose push triggers the publish, so the evidence and the trigger are the same push and cannot be separated.

**A new `verify` job runs `scripts/check_release_state.py` on the tagged commit, and `pypi` depends on it.**
It carries no `environment:`, deliberately.
GitHub holds *every step* of an environment job behind that environment's required reviewer, so a check placed inside `pypi` would run only after the approval it exists to inform.
`verify`'s job summary is therefore what the reviewer reads before approving.

**The script's two halves are documented as being worth different amounts.**
Release-state coherence — every rule-19 version literal, the dated `CHANGELOG.md` section, and `uv lock --check` — are facts of the tagged tree, so a pass proves them.
The live-gate half proves only that a well-formed record naming this commit exists and asserts three passing suites.
It cannot prove the runs happened, because the maintainer's machine produces the record.
Rule 23 forbids any document or output describing it as more, and the job summary says so to the reviewer in the same breath as reporting the pass.

**Freshness is not checked after tagging.**
`record_live_gate_evidence.validate` keeps its 24-hour window for the local pre-tag check, where a stale record can still be replaced by re-running the gates.
A tag is immutable: applying that window in CI would let queue time or a slow deployment approval turn a legitimate tag into one that can never be published.
`validate` was split into `validate_record` (structure, commit identity, three passing suites) and the freshness layer above it, so both callers share one implementation.

## Consequences

- The `pypi` job cannot run until `verify` passes, so a tag pushed without a conforming record fails before any human is asked to approve a deployment.
- A lightweight tag is refused outright: it has no message and so can carry no evidence.
- Signing the tag stays possible; the parser cuts a trailing signature block before reading JSON.
- Rule 19's procedural clauses — two PRs, an ordinary merge commit, the maintainer rather than an agent merging, the tag pushed immediately — remain conventions.
  No CI job can establish them, and this repository now says so in AGENTS.md instead of implying the workflow covers them.
- Fixing this exposed a real gap in the existing validator: `batch_id` was checked only when present, so a record omitting it from all three backend entries validated clean, and the property the docstring claimed — one shared run produced this whole record — was not actually checkable.
  `batch_id` is now a required backend field, with a negative control for the omission path.

## Alternatives rejected

- **A git note or a dedicated `refs/release-evidence/<sha>` ref.**
  A second ref, pushed separately from the tag, mutable separately from the tag, and needing extra fetch machinery in `actions/checkout`.
  The interval between pushing it and pushing the tag would be one more sequencing convention of exactly the kind this ADR is trying to reduce.
- **A signed tag, or the record's `sha256` in the tag message instead of the record.**
  A hash still needs a transport for the record it names.
  A signature binds the assertion to a key, but rule 21's ruleset already restricts who may create the tag, so it would add a key-management burden for no additional guarantee against the one actor the record cannot be trusted against anyway — its author.
- **Validating inside the `pypi` job.**
  Post-approval; see above.
- **Adding the rule-2 gate to `verify`.**
  It would be neither the defined multi-version CI gate nor evidence about the live runs, and a passing single-version subset invites being read as a tag-time gate that it is not.
  The `build` job's wheel smoke test already exercises the tagged artifact.
- **Accepting the rules as pure convention (issue #25's option 1).**
  Rejected as the whole answer, because the mechanizable half really is mechanizable, but adopted as the other half: what cannot be enforced is now stated rather than implied.

## What would reopen this

- A trustworthy way to attest the live runs themselves — a self-hosted runner with authenticated backends, or a signed attestation from a machine the maintainer does not also author records on.
  That would move the live-gate half from assertion to evidence.
- Issue #26 changing what `.mcp.json` pins.
  The `.mcp.json` literal check assumes a `@v{version}` git tag pin, and would need to follow that decision.
