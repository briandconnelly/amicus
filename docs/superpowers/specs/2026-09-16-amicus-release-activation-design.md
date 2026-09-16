# Release activation: the marketplace pointer decides what users run

**Status:** Proposed (2026-09-16).
**Issue:** #117.
**Supersedes on acceptance:** ADR 0015, and AGENTS.md rule 24 in its current form.

## The problem

`.mcp.json` commits `uvx --from git+https://github.com/briandconnelly/amicus.git@vX.Y.Z amicus-mcp`.
ADR 0015 has a release leave that pin naming the *previous* release, and a follow-up pin-move PR advance it once the new tag exists.
ADR 0015 calls the interval between those two merges "a soft, self-healing degradation".

It does not self-heal, and the interval is not the whole defect.

### What a host actually does

Users add this repository as a plugin marketplace.
The host clones `main`, copies that working tree into a directory keyed by `plugin.json`'s `version`, and re-materializes only when that version changes.
A change to `main` that does not move the version never reaches an installed plugin, however many times the marketplace is refreshed.

Two consequences follow, and the second is the larger one.

**The pin-move never arrives.**
For 0.3.0 the release PR merged at 08:16:35 local, leaving `main` pinned at `@v0.2.0` exactly as ADR 0015 prescribes; the pin-move merged at 08:31:16.
A plugin installed at 08:29:44 froze `main`-at-the-merge into a directory named `0.3.0`, and that install still runs the **0.2.0** server: 18 tools instead of 19, and the discovery call every slash command begins with fails on the unknown `detail` argument.
`git diff v0.3.0 1d8e9f9` is empty, which is why issue #117 read the cached copy as the tag snapshot; the host never fetched the tag.

**Every mid-cycle install is skewed the same way.**
`git log --oneline v0.2.0..v0.3.0 -- skills/ commands/` returns 32 commits — a new slash command, a renamed tool, reworded polling instructions — none of them the release commit, and all of which landed on `main` while `plugin.json` still said `0.2.0`.
Anyone installing at any point in that cycle froze the newest skills and commands against the previous release's server pin.
The pin-move window is one instance of this, not the whole of it.

`main` is a mutable branch serving a version-keyed cache, and the version only moves at a release.
That mismatch is the defect; the pin-move window is a symptom.

## What was established by probe

An isolated `CLAUDE_CONFIG_DIR` and a local marketplace, against **Claude Code 2.1.273** on macOS, with a whole-repo `url` source.
Arms 1 to 7 use a `file://` remote; arms 8 and 9 use this repository's real https remote.
Marker A, B and C are distinct contents in both a skill body and `.mcp.json`.

| arm | setup | result |
| --- | --- | --- |
| 1 | content A→B, version unchanged, `marketplace update` | not re-materialized: still A, `gitCommitSha` stale |
| 1b | as above, then explicit `plugin update` | refused: "already at the latest version (0.1.0)" |
| 2 | version 0.1.0→0.2.0 | new directory `0.2.0`, content B |
| 3 | entry pinned `ref: v1`; `main` at C / 0.3.0 | installs `0.1.0` / **A** — the tag, not `main` |
| 4 | ref moved v1→v2 | updates to `0.2.0` / B |
| 5 | source `./`→`ref` whose version equals the cached one | **no-op**: "already at the latest version (0.3.0)", content unchanged |
| 6 | entry declares `skills` at a path existing only on `main` | not loaded; `plugin details` reports only the tag's skill |
| 7 | entry carries `ref: v1` with the **`sha` of v2** | installs v2's content: **`sha` silently wins** |
| 8 | https, `ref: v0.2.0`, no `sha` | installs `0.2.0` |
| 9 | https, the production shape below at `v0.1.0`, then `ref` and `sha` both advanced to `v0.2.0` | installs `0.1.0`, then updates to `0.2.0` |

Arms 2 and 4 are the positive control for arm 1's negative: the instrument can see a change, so "no change" is a finding rather than a dead probe.
Arm 6 also showed the catalog **description** coming from `main` while the plugin body stayed pinned.
Arm 9 is the exact shape this design ships, exercised for both a fresh install and a pointer advance.

Arms 5 and 7 were probed over `file://` only.

## The design

### The marketplace entry becomes the release pointer

`.claude-plugin/marketplace.json`'s single plugin entry stops using `"source": "./"` and pins a published tag.
The complete entry, with `source` as a nested object:

```json
{
  "name": "amicus",
  "description": "One MCP server for every second-opinion model: consult, review, and delegate with the backend as a parameter.",
  "source": {
    "source": "url",
    "url": "https://github.com/briandconnelly/amicus.git",
    "ref": "vX.Y.Z",
    "sha": "<40-hex peeled commit of vX.Y.Z>"
  }
}
```

After activation, users install the **tag snapshot**: skills, commands, `plugin.json` and `.mcp.json` frozen together.
`main` may change freely between releases without reaching anyone, which is what closes the mid-cycle skew.

### The pointer carries both `ref` and `sha`, bound to each other

A `v*` tag is not immutable.
Rule 21's ruleset stops agent identities from creating, moving or deleting one, but `docs/RELEASING.md` records that its bypass list holds the repository admin role, whose bypass is `always`.
A bypass applies to the whole ruleset, so the admin can move or delete a release tag.
A `sha` is therefore real protection: it keeps serving the reviewed commit even if the tag is later moved.

Arm 7 is why the pair is dangerous on its own: a `sha` that disagrees with its `ref` is served silently, while the human-readable field says otherwise.
The release checker neutralizes that by requiring `sha` to equal `git rev-parse <ref>^{commit}` — the **peeled** commit, never the annotated tag object's own SHA.
With that equality enforced, the two fields cannot disagree without failing a check.

Both values are known when they are written, because the pointer only ever names a tag that already exists.

### `.mcp.json` becomes self-referential again

The pin names its own tag and rejoins rule 19's list of version literals.
On a tag — the copy users run once activation is complete — the pin names that same tag, so the server and the skills that call it always agree.

After activation, `main` naming a tag that does not yet exist reaches no user, because nobody installs from `main`.
**Before** activation that is not true, and the transition section below deals with it.

### Rule 24 moves rather than dies

The invariant "this pointer names an already-published release, never the one being released" is right, and ADR 0015's reasoning for it stands.
It attaches to the wrong file today, and transfers from `.mcp.json` to the marketplace entry's `ref`.

The checker cannot prove that invariant, and nothing may describe it as proven.
It can prove a necessary structural condition: that the `ref` names an existing, internally consistent tag older than the version being released.
"Already published" — that the tag reached GitHub and its PyPI upload completed — remains a maintainer assertion, confirmed by `docs/RELEASING.md`'s post-tag checks, exactly as rule 23 already requires of the rule-20 record.

### The release sequence keeps today's ordering

The **order** of `docs/RELEASING.md`'s steps is unchanged, including the ancestry, `origin/main^2` and tree-identity checks that run **before** the tag is pushed.
Four steps change in content rather than position.

- **Step 2.** "Do **not** touch `.mcp.json`" inverts: the pin is a version literal again and moves with the others.
- **Step 3.** After the evidence run writes `.release-evidence/live-gates.json`, create the annotated tag **locally**, using exactly the command step 6 prescribes today: `git tag -a vX.Y.Z -F .release-evidence/live-gates.json --cleanup=verbatim <release-sha>`.
  Then run `check_release_state.py --tag vX.Y.Z --commit <release-sha>`, so the strict predicate — including that `.mcp.json`'s pinned tag exists and that the tag carries a record naming the release commit — passes unmodified against a tag that exists only in this checkout.
  A local tag is reversible, so nothing in the checker needs a pre-tag exception.
  If step 3 must be redone because the branch gained a commit, delete the local tag with `git tag -d vX.Y.Z` and recreate it against the new tip.
- **Step 6.** Stops creating the tag, which step 3 already did — `git tag -a` on an existing name fails with `fatal: tag 'vX.Y.Z' already exists`.
  It reruns `check_release_state.py --tag vX.Y.Z --commit <release-sha>` immediately before `git push origin vX.Y.Z`, so the tag pushed is one that passed the checker as it stands.
- **Step 7.** The small `chore(release):` PR advances `marketplace.json`'s `ref` and `sha` instead of `.mcp.json`'s pin.
  Unlike the pin-move it replaces, this one reaches hosts, because the version at the new ref differs from the version at the old one.

An earlier draft moved the tag before the merge, to shrink the window in which `main` advertised a release nobody could install.
After activation that window reaches no user, so the irreversible acts stay behind the checks that inform them.

### The transition activates at 0.4.0

#### Why 0.4.0, and not a pointer at an existing tag

The first release under this design must carry a version never previously cached, which means **0.4.0**.

Pointing the ref at `v0.3.0` first would achieve nothing.
Arm 5 showed that a source change to a ref whose version equals the cached version is a no-op, and every affected install is already keyed `0.3.0`.

No existing tag is a snapshot worth pointing at, either:

| tag | `plugin.json` | `.mcp.json` | consistent |
| --- | --- | --- | --- |
| `v0.1.0` | 0.1.0 | `@v0.1.0` | yes |
| `v0.2.0` | 0.2.0 | `@v0.1.0` | **no** |
| `v0.3.0` | 0.3.0 | `@v0.2.0` | **no** |

This is not an accident of one release.
ADR 0015 required the pin to trail the version being released, so it guaranteed that every tag after the bootstrap would carry a server one release older than its own skills.
`v0.1.0` is consistent only because the bootstrap had no earlier tag to name and pinned itself.
Arm 8 installed `v0.2.0` over https and received exactly that skew: a directory keyed `0.2.0` whose `.mcp.json` launches `@v0.1.0`.

The first internally consistent tag since the bootstrap will be `v0.4.0`, and the same bump repairs every currently stuck install, since `0.4.0` is a cache key none of them holds.

#### The pre-activation state

Until the 0.4.0 pointer PR merges, the entry's `source` stays `"./"` and `main` **is** still the install source.
That is the only state this repository can be in before a consistent tag exists, so the checker must accept it — and must stop accepting it as soon as it is no longer necessary.

The checker accepts `"./"` only while `pyproject.toml` declares a version no higher than `0.4.0`.
That key is read from the tree, not from git tags, which is what ADR 0015's rejected bootstrap exceptions got wrong: a `--no-tags` or shallow checkout cannot fake a declared version.
No release after 0.4.0 can satisfy it.

A version key alone would let a tree it should reject through.
Between the 0.4.0 pointer PR and the 0.5.0 release PR the declared version is still `0.4.0`, so a PR reverting the entry to `"./"` would satisfy it; so would a PR that lowered the version literals back to `0.4.0` at any later point and restored `"./"`.
The pull-request check therefore also compares against the base branch, under "Transition" below, and that comparison — not the version key — is what makes activation one-way.
The version key's job is narrower: it lets the pre-activation state exist at all, and it stops a `"./"` tree from ever being released above 0.4.0.

#### The one-time merge-to-tag window

At the 0.4.0 merge, `main` is still the install source and its `.mcp.json` names `@v0.4.0` before that tag exists.
An install landing between the merge and the tag push caches version `0.4.0` with a pin that does not resolve yet, so the server fails to start.

That failure is loud, and it is expected to heal without re-materializing: the cached content is correct but early, and the same pin string resolves once the tag exists.
That expectation is reasoned, not probed: a failed resolution should leave no tool environment behind to reuse, so the next launch retries.
ADR 0015 established only that a populated `uvx` cache is reused offline, which does not settle how a failed resolution is treated.

Rule 19 already requires the tag push to be the next work after the merge, which keeps this window to minutes.
It occurs once, at 0.4.0, and never again.

#### Nothing else merges between the 0.4.0 merge and its pointer PR

An install from `main` in that interval is keyed `0.4.0`.
The pointer PR moves the source to `ref: v0.4.0`, whose version is also `0.4.0`, so by arm 5 it will **not** re-materialize that install.
If `main` still equals the release tree, the frozen copy is consistent and nothing is lost.
If anything else merged in between, the frozen copy is skewed and stays that way until 0.5.0.

For the 0.4.0 transition only, `docs/RELEASING.md` therefore extends rule 19's "the tag push is the next work after the merge" to "nothing merges to `main` until the pointer PR does".

### What the checks read, exactly

One function validates the marketplace file, called from two places with different evidence available.
Every rule below fails closed: a key, shape or value not listed is a failure, so an unknown future key fails rather than passing silently, and adding one means changing the checker in the same PR.

**Shape, a fact of any checkout.**
Strictness goes where it affects what executes: the plugin entry and its source have **exactly** the listed keys.
The root and `owner` only need their required fields with the right types; other metadata there is allowed, because it cannot change which snapshot runs.
The file as it stands today passes every rule, so PR 1 needs no change to it.

| JSON path | keys | value constraints |
| --- | --- | --- |
| `$` (root) | requires `name`, `plugins` | `name` is `"amicus"`; `plugins` is an array of exactly one element |
| `$.plugins[0]` | exactly `name`, `description`, `source` | `name` is `"amicus"`; `description` is a non-empty string |
| `$.plugins[0].source` | — | the string `"./"` under the pre-activation rule, **or** the object below |
| `$.plugins[0].source` as an object | exactly `source`, `url`, `ref`, `sha` | `source` is `"url"`; `url` is `"https://github.com/briandconnelly/amicus.git"`; `ref` matches `^v\d+\.\d+\.\d+$`; `sha` matches `^[0-9a-f]{40}$` |

The exact key set on the entry excludes `version`, `strict` and every component-definition key, such as `skills` (which arm 6 showed an entry may carry) or `mcpServers`, without enumerating them.
`description`'s text is not checked: it is catalog copy, read from `main` regardless.
Tests cover each class of rule with a representative case — an extra entry key, a missing source key, a malformed `ref` and `sha`, a wrong `url` — rather than every combination.

**Consistency, facts that require the tags to be fetched:**

- The tag named by `ref` exists and is annotated.
- `git rev-parse <ref>^{commit}` equals `sha`.
- At that commit, both `plugin.json` files and `.mcp.json` all name the version `ref` names.
  This is the check every tag since the bootstrap would fail, and it is what makes a ref safe to point at.

**Ordering, which depends on what is being checked.**
Versions compare as three integers, never as strings, so `v0.10.0` is newer than `v0.9.0`.

- In the release predicate, `ref` is strictly **older** than the version being released: the tagged release commit predates its own pointer PR.
- In the pull-request check, `ref` is **no newer** than the declared version: equal after a pointer PR, older during a release.
  That is an upper bound only, and it cannot stop a pointer moving backwards; the transition rules below do.

**Transition, relative to the pull request's base branch.**
Only the pull-request check has a base to compare against, and rule 8 routes every agent change to `main` through a pull request, so this is where rollback is stopped.
The check reads the base's file with `git show <base-sha>:.claude-plugin/marketplace.json`, against the base commit the pull-request event names.
Whether the maintainer can push to `main` without a pull request is not established: `docs/RELEASING.md` records that reading `main`'s branch protection returned 403 to the token available here.

- Base source is the object form: head source must also be the object form.
  Activation is one-way; `"./"` never returns once `main` has left it.
- Both are the object form: head `ref` is no older than base `ref`.
  A pointer may stay put or advance, never retreat.
- Base source is `"./"`: head may keep `"./"`, subject to the pre-activation rule, or move to the object form.
  This is the only transition the 0.4.0 pointer PR makes.

These are required in addition to the no-newer bound, not instead of it.
PR 1's negative tests include each rollback that motivated them: object form back to `"./"`; `v0.4.0` back to the internally consistent `v0.1.0`; and version literals lowered to `0.4.0` together with `"./"` restored.

The release predicate has no base, so it cannot detect a regression by itself.
It relies on the pull-request check having stopped one before the release commit existed.
A push to `main` that bypasses pull requests bypasses this rule too, and nothing catches it; that gap is accepted.

`.mcp.json` separately equals the version being released, replacing today's "names something no newer than this version", and both `plugin.json` files equal it as now.

**Where it runs, and what each run proves:**

- `scripts/check_release_state.py`, locally at step 3 and in the `verify` job on the tag.
  A local pass proves the shape and whatever tags this checkout has fetched; `verify` fetches full history and tags, so its pass covers the consistency checks against the remote as `actions/checkout` sees it.
- A job in the existing `.github/workflows/test.yml` that fetches tags and the base commit, and runs the same function with the no-newer ordering plus the transition rules against the base.
  It validates the pointer PR before it merges, and it cannot block a release PR, because a release PR leaves the pointer at a valid earlier tag and unchanged from its base.

**What no pass establishes, and no document may describe as proven:**

- That the pointer PR merged, or will.
- That the named release was published to PyPI.
- That any user refreshed their marketplace, or that a host re-materialized.
- That either host loaded the result correctly.

The honesty posture of rules 20 and 23 extends to these unchanged: state what is machine-checked, and name the rest as assertion.

### Activation is a checklist item

Tagging and publishing does not expose a release to marketplace users; only the pointer PR does, and no check against an immutable tag can make a later commit happen.
`docs/RELEASING.md` makes advancing the pointer an explicit post-publish step, and a release is not complete until it has merged.

Until it does, users install release N-1, which after activation is a self-consistent, working snapshot.
That is the degradation ADR 0015 intended, and it ends when the pointer PR merges.
Nothing automated watches for a forgotten pointer PR; for a rarely released, single-maintainer project the checklist is proportionate.

## What this design does not claim

The Claude Code probes cover **one version**, 2.1.273, with a whole-repo `url` source.
Arm 9 exercised the production shape over https for a fresh install and a pointer advance.
The same-version no-op (arm 5) and `sha` precedence (arm 7) were probed over `file://` only.

The self-healing of the one-time 0.4.0 window is reasoned, not probed.

Arm 6 tested one shape of component injection, a relative path resolving against the plugin root.
It did not test `strict: false` or absolute paths, so the closed key set above is a guard against shapes not probed rather than a restatement of what was.

**Codex is probed for a fresh install, a re-add and the passive upgrade path.**
Against Codex CLI 0.154.0, with an isolated `CODEX_HOME` whose control listed no marketplaces while the real one listed four:

| arm | setup | result |
| --- | --- | --- |
| C1 | production shape at `v0.1.0` + peeled `sha`, fresh install | reads `.claude-plugin/marketplace.json`, parses the nested `url`, `ref` and `sha`, and installs the tag snapshot into `plugins/cache/<marketplace>/amicus/0.1.0` with both plugin manifests and the tag's `.mcp.json` |
| C2 | pointer advanced to `v0.2.0`, then `codex plugin add` re-run | installs `0.2.0` and **removes** the `0.1.0` directory |
| C3 | git marketplace served over local `http://`; pointer advanced upstream to `v0.2.0`; then **only** `codex plugin marketplace upgrade` | re-materializes to `0.2.0` with v0.2.0's `.mcp.json`; the control, an upgrade with nothing changed upstream, stays at `0.1.0` |
| C4 | `briandconnelly/briandconnelly-plugins` over GitHub https, added at branch `feat/amicus` (`cwms` 0.6.0); configured ref moved to `main` (`cwms` 0.7.0); then **only** `marketplace upgrade` | re-materializes `cwms` from `0.6.0` to `0.7.0`; the control, an upgrade with the ref unchanged, stays at `0.6.0` |

So on every path probed Codex resolves the tag snapshot under a version-keyed cache, and C3 shows a passive upgrade picks up a pointer advance that changes the version — the change 0.4.0 makes for every stuck install.
C3 exercises the `ref` and `sha` pointer over a local `http://` git remote, because Codex rejects `file://`; C4 confirms the same passive upgrade over GitHub's https, read-only, by moving the configured ref between two existing branches.
`upgrade` resolves the marketplace's configured ref with `git ls-remote`, which matches branch and tag names only, so a marketplace added at a commit SHA cannot be upgraded; the marketplace should be added tracking a branch, as it is today.
The Codex counterpart of arm 5, a same-version change, was not probed, and nothing in this design depends on it.

## Alternatives rejected

**Keep ADR 0015 and bump a plugin-only version in the pin-move PR.**
It would make the pin-move visible, but only the pin-move.
Mid-cycle skew stays untouched, and `plugin.json`'s version stops meaning the released version.

**Self-referential pin with the tag pushed before the merge.**
This was the approved direction until the probes reframed the problem.
It closes the pin-move window and nothing else, and it pays for that with a tag pushed before its commit is on `main`, which starts `publish.yml` before the ancestry and tree-identity checks that exist to inform it.
Rule 22 forbids recovering that safety inside the `pypi` job.

**A separate release-only marketplace repository.**
This was the first external recommendation, and it reaches the same property.
The ref-pinned entry achieves it within this repository, so a second repository would be a second thing to publish, protect and keep in step for no additional guarantee.

**Drop `version` from `plugin.json` so the cache is keyed by commit.**
Observed on four `claude-plugins-official` plugins, which are cached under commit SHAs.
It would make every commit to `main` re-materialize, which trades a stale install for a churning one, discards version identity in the catalog, and depends on host behavior more delicate than a documented `ref`.

**An automated activation monitor.**
Drafts specified a check on `main`, then a scheduled workflow with a grace period, publish-run correlation and issue escalation.
Pointer lag leaves users on a working release and is fixed by the same human PR the checklist already requires, so the machinery cost more than the risk it removed.

## What would reopen this

- A host that resolves the plugin from the marketplace's own branch rather than the entry's `ref` and `sha`.
- A host that stops honoring `sha` over `ref`, or stops keying its cache by the plugin version.
- A later Codex release whose passive `marketplace upgrade` stops re-materializing a plugin whose pointer advanced to a new version.
- The repository admin bypass on the `v*` ruleset being removed, which would make the `sha` redundant rather than protective.
- PyPI becoming the documented install channel, which would move `.mcp.json`'s pin off git tags and change what the consistency check reads.

## Work split

Three pull requests, because rule 9 keeps governance and `.github/` separate from ordinary work.

1. **Design and checker.** This spec; a new ADR superseding 0015; `docs/RELEASING.md` steps 2, 3, 6 and 7 and the 0.4.0 transition rule; and the marketplace validation function in `scripts/check_release_state.py` with its tests, including the pre-activation rule and a negative test for each fail-closed key.
   `.claude-plugin/marketplace.json` does not move here, and does not need to: its current `"./"` passes under the pre-activation rule.
2. **Governance.** AGENTS.md rules 19 and 24, and the "Releases" section of its context notes.
3. **Workflow.** One job added to the existing `.github/workflows/test.yml`, running the marketplace check on pull requests with tags and the base commit fetched, each new `uses:` pinned by SHA per rule 14.
   It needs `contents: read` and nothing more.

The pointer itself moves during the 0.4.0 release, as step 7 of the sequence, and in none of these three.
