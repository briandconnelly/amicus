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

An isolated `CLAUDE_CONFIG_DIR` and a local git marketplace, against **Claude Code 2.1.273** on macOS.
Arms 1 to 7 use a `file://` remote; arm 8 uses this repository's real https remote.
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
| 7 | entry carries `ref: v1` with **`sha` of v2** | installs v2's content: **`sha` silently wins** |
| 8 | entry pins this repository over **https** at `ref: v0.2.0` | installs `0.2.0`, the exact shape this design ships |

Arms 2 and 4 are the positive control for arm 1's negative: the instrument can see a change, so "no change" is a finding rather than a dead probe.
Arm 6 also showed the catalog **description** coming from `main` while the plugin body stayed pinned.

Supporting observation from the host's own catalog cache: 88 real marketplace entries use `git-subdir` with `ref` and `sha`, and 151 use `url` with `sha`, so a ref-pinned plugin source is an ordinary shape rather than an exotic one.

## The design

### The marketplace entry becomes the release pointer

`.claude-plugin/marketplace.json`'s plugin entry stops using `"source": "./"` and pins the published tag:

```json
{ "source": "url", "url": "https://github.com/briandconnelly/amicus.git", "ref": "vX.Y.Z" }
```

Users therefore install the **tag snapshot**: skills, commands, `plugin.json` and `.mcp.json` frozen together and mutually consistent.
`main` may change freely between releases without reaching anyone, which is what closes the mid-cycle skew.

`ref` alone, with no `sha`.
Arm 7 showed that a `sha` disagreeing with its `ref` is served silently, so the pair is a way to ship the wrong tree while the human-readable field says otherwise.
Rule 21's ruleset already makes a `v*` tag immutable, which is the property a `sha` would otherwise add.
If a `sha` is ever introduced, the release checker must require it to equal `git rev-parse <ref>^{commit}`, the peeled commit rather than the annotated tag object.

### `.mcp.json` becomes self-referential again

The pin names its own tag and rejoins rule 19's list of version literals.
This is safe now in a way it was not under ADR 0015: nobody installs from `main`, so `main` naming a tag that does not yet exist reaches no user.
On the tag — the copy users actually run — the pin names that same tag, so the server and the skills that call it always agree.

### Rule 24 moves rather than dies

The invariant "this pointer names an already-published release, never the one being released" is right, and ADR 0015's reasoning for it stands.
It simply attaches to the wrong file today.
It transfers from `.mcp.json` to the marketplace entry's `ref`.

### The release sequence keeps today's ordering

The **order** of `docs/RELEASING.md`'s steps is unchanged, including the ancestry, `origin/main^2` and tree-identity checks that run **before** the tag is pushed.
Two steps change in content rather than position.
Step 2's "Do **not** touch `.mcp.json`" (line 105) inverts: the pin is a version literal again and moves with the others.
Step 7's small `chore(release):` PR advances `marketplace.json`'s `ref` instead of `.mcp.json`'s pin.
Unlike the pin-move it replaces, this one reaches hosts, because the version at the new ref differs from the version at the old one.

An earlier draft of this design moved the tag before the merge, to shrink the window in which `main` advertised a release nobody could install.
That is no longer needed: under this design `main` is not an install source, so the window reaches no user.
The irreversible acts stay behind the checks that inform them, which is what pushing the tag early would have given up.

### Release activation is enforced on `main`

Tagging and publishing does not expose a release to marketplace users; only the pointer PR does.
No predicate evaluated against an immutable tag can prove that a later commit will happen.

A `main`-only CI job therefore asserts that the marketplace `ref` equals the version the tree declares.
It goes red when the release PR merges and clears when the pointer PR lands, so a forgotten pointer PR is loud instead of silent.

It must **not** gate pull requests.
As a PR gate it would block the release PR itself, whose whole purpose is to raise the declared version while the pointer still trails.

While it is red, users install release N-1, which under this design is a self-consistent and working snapshot.
That is the degradation ADR 0015 intended, and here it genuinely self-heals.

### The transition activates at 0.4.0

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

The first internally consistent tag since the bootstrap will be `v0.4.0`, whose `.mcp.json` names its own tag.

The same 0.4.0 bump is what repairs every currently stuck install, since `0.4.0` is a cache key none of them holds.

### What `scripts/check_release_state.py` gains

Facts of the tagged tree, which a pass **proves**:

- `.mcp.json`'s pin equals the version being released, replacing today's "names something no newer than this version".
- Both `plugin.json` files equal that version, as now.
- The marketplace entry names exactly this repository, with a `ref` matching `^v\d+\.\d+\.\d+$`.
- That `ref` is older than the version being released — rule 24's invariant in its new home.
- The entry carries no `version`, no `strict: false` and no component-definition field, so functional surface can only come from the pinned source.

Facts provable once tags are fetched:

- The marketplace `ref` exists and is an annotated tag.
- At that ref, both `plugin.json` files and `.mcp.json` all name that same version.
  This is the self-consistency check that `v0.3.0` would have failed, and it is the one that makes a ref safe to point at.

Claims a pass does **not** establish, and which no document may describe as proven:

- That the pointer PR merged.
- That any user refreshed their marketplace, or that a host re-materialized.
- That the target was published to PyPI.
- That either host loaded the result correctly.

The existing honesty posture of rules 20 and 23 extends to these unchanged: state what is machine-checked, and name the rest as assertion.

## What this design does not claim

The probes cover **one host at one version** — Claude Code 2.1.273 — with a whole-repo `url` source.
Arm 8 exercised this repository's https remote for a fresh install only.
Moving a ref, a same-version switch and the `sha` precedence were probed over `file://`, not https.

Codex is not covered at all.
`docs/host-captures/install-smoke/codex/0.153.4/notes.md` records that the Codex plugin loader was never exercised and `plugin.json` never read, and nothing here changes that.
`.codex-plugin/plugin.json` is carried on the tag like every other manifest, so Codex users are not made worse off, but the spec claims documented support rather than observed behavior, and says so wherever it is mentioned.

Arm 6 tested one shape of component injection — a relative path resolving against the plugin root.
It did not test `strict: false` or absolute paths, so the allowlist check above is a guard against shapes not probed rather than a restatement of what was.

## Alternatives rejected

**Keep ADR 0015 and bump a plugin-only version in the pin-move PR.**
It would make the pin-move visible, but only the pin-move.
Mid-cycle skew — the 11 commits above — stays untouched, and `plugin.json`'s version stops meaning the released version.

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

## What would reopen this

- A host that reads the marketplace entry but resolves the plugin from the marketplace's own branch rather than the entry's `ref`.
- A `ref` that stops being honored for an https `url` source, or a host that begins keying its cache by something other than the plugin version.
- Codex behavior, once probed, differing enough that one pointer cannot serve both hosts.
- PyPI becoming the documented install channel, which would move `.mcp.json`'s pin off git tags and change what the self-consistency check reads.

## Work split

Three pull requests, because rule 9 keeps governance and `.github/` separate from ordinary work.

1. **Design and checker.** This spec, a new ADR superseding 0015, `docs/RELEASING.md`'s step 7, and `scripts/check_release_state.py` with its tests.
   `.claude-plugin/marketplace.json` itself does not move here: its ref cannot name `v0.4.0` before that tag exists.
2. **Governance.** AGENTS.md rules 19 and 24, and the "Releases" section of the context notes.
3. **Workflow.** The `main`-only activation job under `.github/workflows/`, pinned by SHA per rule 14.

The pointer itself moves during the 0.4.0 release, as step 7 of the sequence, not in any of these three.
