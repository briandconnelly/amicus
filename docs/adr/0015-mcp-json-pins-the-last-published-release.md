# ADR 0015: `.mcp.json` pins the last published release, not the version being released

**Status:** Accepted (2026-09-09, immediately after the 0.1.0 release)

## Context

`.mcp.json` commits `uvx --from git+https://github.com/briandconnelly/amicus.git@v{version} amicus-mcp`, and rule 19 listed that pin among the version literals a release PR moves together.
The pin therefore named the version being released, which is a tag that does not exist until after that PR merges and the maintainer pushes the tag.

Issue #26 asked whether a self-referential future-tag pin is the right way to express "install the version this repo is", because three separate costs follow from it.
A fresh install from `main` fails outright during the window between the release merge and the tag push.
The real install path is first exercised by the production tag, which `tests/test_packaging.py` says outright — its slow smoke substitutes a locally built wheel for the one `--from` field, so tag resolvability is unproven until it is irreversible.
And rule 19's "push the tag immediately, before any other work" clause is mitigation for this design rather than an independent safety property.

The decisive fact is what the manifest actually is.
Users install by adding this repository as a plugin marketplace, so the `.mcp.json` a fresh install reads is the one on `main` — not a copy carried on the tag.
A manifest read from `main` cannot name an artifact that only exists after `main` has already moved.

Two further facts were established by probe rather than assumed, because the alternatives turn on them.

**A commit SHA resolves where a future tag cannot.**
`uvx --from git+https://github.com/briandconnelly/amicus.git@<sha> amicus-mcp` was run against a real commit on `origin/main`; it resolved, built and launched the server over GitHub's git transport.
The release commit's SHA therefore exercises transport, clean-machine build and console script before any tag exists.

**`uvx` reuses a cached tool environment without querying the index.**
With a populated cache, `uvx --offline --from cowsay cowsay` succeeded; with an empty cache the same command failed, so the pass is evidence and not an artifact of a broken probe.
The version in the requirement string is thus not merely a reproducibility statement — it is the cache-busting mechanism by which an existing user receives an update.
When a user updates their marketplace clone and the pin changes from `@v0.1.0` to `@v0.2.0`, the requirement string differs and uv resolves afresh.

## Decision

`.mcp.json` pins the newest release that has **already been published**, and a release never moves it.

The pin stops being a rule-19 version literal.
A `chore(release):` PR moves `pyproject.toml`, `src/amicus/__init__.py` and both `plugin.json` files as before, and leaves `.mcp.json` alone.
A separate, small `chore(release):` PR moves the pin to the new tag once that tag exists.

`main` therefore names a tag that exists at every moment in the project's life after the first release:

| moment | pin | resolvable |
| --- | --- | --- |
| release PR for 0.2.0 merges | `@v0.1.0` | yes |
| `v0.2.0` pushed | `@v0.1.0` | yes |
| PyPI publish completes | `@v0.1.0` | yes |
| pin-move PR merges | `@v0.2.0` | yes |

0.1.0 was the bootstrap and has already happened: it was tagged and published on 2026-09-09, its pin reads `@v0.1.0`, and no literal moved.
It created the only tag its own pin could name, so `main` has satisfied the invariant since that tag was pushed and the window is already closed.
0.2.0 is therefore the first release to follow the sequence this ADR describes, and the bootstrap branch below can never be taken again in this repository.

`scripts/check_release_state.py` stops asserting that the pin equals the version being released.
It asserts instead that the pin has the expected shape, that it names a version no newer than the one being released, and that the pinned tag actually exists.
That last check is worth more than the one it replaces: the old equality was true by construction on any tree a release PR had touched, while "the tag this manifest sends users to exists" is a fact about the world.

The bootstrap is the one exception, and it is identified positively: a repository with **no `v*` tags at all** whose pin names the version being released.
That is the first release naming the tag it is about to create, and it is unreachable a second time.
The exception is deliberately not "the pin equals the version being released".
That was the first attempt, and review found it too broad: on a later release a pin mistakenly bumped to the version being released would satisfy it, skip the check, and restore the very window this ADR removes — while the publish workflow would not catch the mistake either, because by then the tag has been pushed and does exist.
A failed tag listing is reported rather than read as "no tags", so a broken instrument cannot silently take the bootstrap path.

## Consequences

- A fresh install is never broken by a release in progress.
  During the interval between the tag push and the pin-move PR, a new user gets version N-1, which works, instead of a hard failure.
- Existing users still receive updates, because the pin still changes once per release and still busts the `uvx` cache.
- Releases cost one extra small PR.
  That PR is not a release under rule 19 and needs no live-gate evidence: it moves a pointer to a tag that already exists and is already published.
- The install path becomes testable before it is irreversible.
  `docs/RELEASING.md` gains a pre-tag rehearsal that runs the committed manifest's own command with the release commit's SHA substituted for the tag.
  What stays unproven until the tag is pushed is only that the string `vX.Y.Z` resolves, which is the trivial part of an install.
- `main` advertises N-1 for as long as the pin-move PR takes.
  This is a soft, self-healing degradation, and it is the price of never advertising something that does not exist.
- ADR 0014 is unaffected.
  The `verify` job, the evidence carried on the annotated tag, and `pypi` depending on `verify` all stand; this is the `.mcp.json` literal-check update that ADR 0014's "What would reopen this" anticipated.

## Alternatives rejected

- **Keep the pin as the version being released (issue #26's option a).**
  The window stays, and it stays a hard failure rather than a degradation.
  Adding only the SHA rehearsal would have answered the testability complaint while leaving the outage in place.
- **Pin the PyPI distribution at an exact version, `amicus=={version}`.**
  The same window wearing different clothes, and wider.
  `amicus==0.1.0` does not resolve until `publish.yml`'s `pypi` job has uploaded it, and that job waits on the `pypi` environment's required reviewer, so the window becomes however long an approval takes rather than the seconds between a merge and a tag push.
- **An unpinned distribution, `--from amicus`.**
  This was the recommendation of an adversarial consult, and the probe above is why it was not taken.
  It does remove the window from the second release onward, but the requirement string then never changes, so a user's `uvx` cache can serve a stale build indefinitely with no signal that a newer one exists.
  Trading a seconds-long, self-healing outage for a silent permanent one is a bad trade.
  It would also make PyPI the install channel for the first time; `README.md` documents the git source, not `pip install amicus`.
- **A mutable git ref, `@main`.**
  Removes the outage, but makes the artifact users run mutable and unversioned, and bypasses the release boundary entirely.
- **Generate the pin at build or publish time.**
  Does not reach the problem.
  A fresh marketplace install reads the manifest from `main`; nothing generated on the tag or publish side changes what that file says.

## What would reopen this

- PyPI becoming the documented install channel.
  The pin would then name a distribution rather than a git tag, and the invariant here ("name something already published") would carry over unchanged, but the shape check and `README.md` would both move.
- Evidence that a plugin host copies `.mcp.json` at install time and never re-reads it.
  That would change how an update reaches an existing user, which is the mechanism the cache probe above is about.
  This was not established either way; `docs/RELEASING.md` treats it as unknown rather than assuming it.
