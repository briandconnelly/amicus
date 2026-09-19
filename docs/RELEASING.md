# Releasing amicus

This is the procedure for shipping a tagged version of amicus to PyPI.

## Who may do this

Only the maintainer runs this procedure to completion.
An agent may prepare the release PR described below, but an agent never merges it, never pushes a tag, and never dispatches the publish workflow.
`gh workflow run` returns 403 for the App token that agents in this repository use.
That is a boundary, not an obstacle to route around.

## Preconditions

Check every precondition below before starting the release sequence.
Each one names the command that checks it and the output that means yes.

### The `v*` tag ruleset exists

AGENTS.md rule 21 requires a repository ruleset that restricts creation, update, and deletion of `v*` tags, with no agent identity permitted to bypass it.
Read it back:

```sh
gh api repos/briandconnelly/amicus/rulesets
```

Confirm a ruleset targeting `refs/tags/v*` whose rules restrict `creation` as well as `update` and `deletion`.

The next two checks look alike and are not.
One is about the ruleset; the other is about whoever ran the command.
Read them in that order, and note which identity `gh` is authenticated as before you start — `gh auth status` names it.

**Check one, rule 21 itself — identity-independent, but an agent cannot run it.**
The bypass list must contain no agent identity: no entry whose `actor_type` is `Integration`.
An App token's response omits the `bypass_actors` key **entirely** rather than returning it, so an agent reading this endpoint cannot see the list at all.
An absent key is not an empty list, and an agent must not report rule 21 as satisfied from one.
This check is the maintainer's to run, under their own account.

**Check two, whether you can push the tag — identity-dependent.**
Read the ruleset itself, `gh api repos/briandconnelly/amicus/rulesets/<id>`, and confirm `current_user_can_bypass` is not `never`.
That field describes the identity whose token made the request, not the repository.
Under the App token that agents use it reads `never`, which is the correct and required state for an agent: rule 21 demands exactly that.
An agent that reads `never` here has learned nothing about the maintainer, and must not report the release blocked — nor "fix" it by adding a bypass actor for the identity it is running as, which would be the `Integration` entry rule 21 forbids.
Only the maintainer, under their own account, gets a meaningful answer.
As of 2026-09-09 that answer is `always`, because the bypass list holds `RepositoryRole` 5 (repository admin).

A ruleset with an empty `bypass_actors` list satisfies rule 21 perfectly and blocks the release, because the restriction applies to the repository owner too — this happened on 2026-09-08 and was caught only by reading the ruleset back.
The fix is to add the repository admin role to the bypass list, never to weaken a rule: rule 21 forbids agent identities from bypassing, not you.
Creation is the load-bearing rule.
`.github/workflows/publish.yml` triggers on `push: tags: ["v*"]`, so any identity that can create a `v*` tag can start a publish run.
Since ADR 0014 the `verify` job stands between that run and the upload, and refuses a tag that does not carry a conforming rule-20 record — but `verify` reads a record the tag's own author wrote, so the ruleset remains the control that decides who may author one.
A settings page that looks right is not evidence; the M6 environment check found exactly that failure mode by reading the API back instead of trusting the UI.

### The `pypi` environment requires a reviewer and is scoped to `v*` tags

```sh
gh api repos/briandconnelly/amicus/environments/pypi
gh api repos/briandconnelly/amicus/environments/pypi/deployment-branch-policies
```

The first command must show a `required_reviewers` protection rule.
The second must show a branch policy entry with `"type": "tag"` and `"name": "v*"`.
The policy must be typed `tag`, not `branch`.
A branch policy blocks every release, because a release is never made from a branch, and the environment endpoint alone does not distinguish a tag policy from a branch policy.

### A PyPI trusted publisher is registered

A trusted publisher must be registered on pypi.org for `briandconnelly/amicus`, workflow `publish.yml`, environment `pypi`.
This is configured on PyPI's own project settings page and has no read-only API this runbook can probe; confirm it by looking at the PyPI project's "Publishing" settings directly.

### Trademark clearance for the name `amicus`

Trademark clearance for the name `amicus` is resolved, or the maintainer has decided to proceed without it.
This was decided on 2026-09-08: `docs/adr/0013-proceed-without-trademark-clearance.md` records the decision to publish without clearance, the consequences accepted, and what would reopen it.
Read that ADR rather than relying on anyone's recollection, and confirm nothing listed under "What would reopen this" has since happened.
TestPyPI has the name claimed under this project, and pypi.org has carried a release since 0.1.0 was published on 2026-09-09.
The name is therefore established on both indexes; this precondition is about clearance, not about claiming the name.

### The README describes the released tool

`README.md` reads as a user-facing document: what amicus does, how to install it, and a high-level overview of how to use it.
The maintainer requires this before any release, so it is a precondition rather than a nicety.
Check two things by reading the file.
First, its install section must not still carry the pre-release note saying amicus is unpublished and that the instructions work from the first tagged release onward — once you are releasing, that sentence is false and must be removed in the release PR.
Second, its "Status and known limits" section must not claim anything the release contradicts, in particular the line stating amicus has never been published to PyPI.

### The backend CLIs are current and checked

A release vouches for the `codex`, `kimi` and `claude` that are installed when its rule-20 evidence is recorded, and those CLIs release far more often than amicus does.
Do this last among the preconditions, immediately before the evidence run in the release sequence, because a check done a week earlier describes CLIs that have since moved.

First bring each CLI to its latest release on the machine that will record the evidence.
`codex` and `claude` are npm packages, so `npm view @openai/codex version` and `npm view @anthropic-ai/claude-code version` name the latest and the usual npm upgrade installs it.
`kimi` is Kimi Code, which updates itself: run `kimi upgrade`.
Its latest version cannot be read from outside the CLI, and PyPI's `kimi-cli` is a different distribution whose version says nothing about it.

Then run the mechanical half, which spends nothing: it runs `--version`, `--help` and each backend's free login probe, and sends no prompt.

```sh
uv run python scripts/check_backend_compat.py
```

Yes is exit status 0, with each backend reported as installed and authenticated, no `FAIL` line, and `same flags` against its newest committed capture.
A `FAIL` line names what is wrong: a CLI that is not installed or not authenticated, a `--help` that could not be read, a warning `amicus_backends` would raise (such as an installed version outside the contract's supported set), a flag amicus always sends that `--help` no longer declares as an option, an installed version behind the latest release npm reports, or an npm lookup that failed.
It fails closed: help that cannot be read, or a latest release that cannot be looked up, is a failure rather than a pass, and `--offline` exists to say out loud that the lookup was skipped, which is not good enough for a release.
A flag counts only where `--help` declares it as an option, never where another option's description happens to name it.
`FLAGS DIFFER` is not by itself a failure, since upstream adds flags constantly, but every removed flag must be looked up in that backend's `contract.py` before going on.
`latest unknown` is expected for kimi and is a failure for nothing; it is why `kimi upgrade` comes first.

When a CLI's version has no capture of its own, commit one with the change that adds support for it, so the next release has something to compare against.

```sh
uv run python scripts/check_backend_compat.py --write
```

Adding a minor to a backend's `SUPPORTED_VERSIONS` is its own PR, made the way #112 and #194 were: a zero-spend comparison against the previous minor, recorded in the PR.
`tests/test_codex_contract.py`, `tests/test_kimi_contract.py` and `tests/test_claude_contract.py` then hold every committed capture to the flags the contract sends.

The script cannot do the other half, which AGENTS.md rule 18 requires before every release: the carrier re-check.
Rule 18 exempts a backend's native prompt carrier only where no documented or observed way to avoid it has been found on the CLI release being validated.
For each of the three versions the script printed, read that CLI's `--help` and its release notes since the previous amicus release for anything that would avoid a listed carrier: a flag or setting that stops kimi keeping a session, a way to hand kimi its prompt without a file, or a codex channel for developer instructions other than `-c` on argv.
If one has appeared, the exemption no longer holds for that carrier, and using the new mechanism is a change to make before this release rather than after it.
If none has, say so in the release PR, naming the three versions, so the next reader can see the looking was done and on what.
The probe that stands behind kimi's session store, and what it did not test, is `docs/kimi-help/0.43.1/FINDINGS.md`.

## The release sequence

Rules 19 and 20 together shape this sequence, and a future maintainer should not "simplify" it back.
Rule 20 requires the live-gate evidence to cover the exact commit being tagged.
Rule 19 requires the tag push to be the only work that follows the PR C merge, so that `main`'s version literals and the published tag agree without a gap.
Since ADR 0031, `.mcp.json` pins the release being made, and plugin users install the tag the marketplace pointer names rather than `main`, so promptness no longer protects plugin installs.
It still matters for two readers of `main`: someone copying README's "Any other MCP client" command, whose pin names a tag that does not exist until it is pushed, and, for the 0.4.0 transition only, every plugin user, because until step 7 merges `main` is still the install source.
The tag does not have to point at `main`'s head; it has to point at the commit the evidence covers.
An ordinary merge commit keeps the PR C branch tip in `main`'s history as one of the merge commit's two parents, so tagging that branch tip is legitimate, and it is exactly the commit the evidence names — no fast-forward or branch-protection change is required to satisfy both rules.
The tag therefore deliberately points at a commit that is in `main`'s history but is not `main`'s head, and the checks in step 5 below prove the two commits' trees are identical.

1. Merge PR B (the milestone work, version literals untouched).
2. Open PR C, the `chore(release):` PR described by AGENTS.md rule 19, and do not merge it yet.
   Roll `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z] - YYYY-MM-DD` section, and leave a fresh empty `## [Unreleased]` above it.
   That date is **UTC** (`date -u +%F`), not the local date of whoever prepares the PR.
   The two disagree for part of every day in this maintainer's timezone, and the tag, the publish run and the PyPI record are all stamped in UTC, so a local date makes the changelog disagree with every other artifact of the same release.
   0.1.0 predates this convention and is dated `2026-09-08`, its local date; it was tagged on 2026-09-09 UTC, and that section is left as it shipped rather than rewritten.
   Change no version literal unless the version itself is changing.
   The literals are `pyproject.toml`, `src/amicus/__init__.py` and both `plugin.json` files.
   Move `.mcp.json`'s pin to `vX.Y.Z` with the other literals: per ADR 0031 it names the release being made, so a host installing this tag runs this release's server.
   Move README's "Any other MCP client" example to the same pin in this PR; `tests/test_packaging.py::test_readme_example_mirrors_the_mcp_json_pin` fails if the two differ.
   Do **not** touch `.claude-plugin/marketplace.json`: its pointer names the previous release until step 7 advances it.
   Regenerate `uv.lock` with `uv lock` in this same PR, per AGENTS.md rule 19 — `uv.lock` mirrors the version rather than declaring it, and `prek.toml`'s `uv-lock-check` hook runs `uv lock --check` whenever `pyproject.toml` changes, so a release PR that skips this fails its own hook.
3. Check out the PR C branch tip (not `main`) into a clean tree and confirm `git status --porcelain` is empty.
   Record the branch tip's SHA; call it the release commit, and note it well — it is the commit that gets tagged, and it will not be `main`'s head after the next step.
   If the PR C branch gains any commit after this point — an "Update branch" click, or a review pushing a change — this step must be redone from the new tip: the evidence would otherwise cover a commit that is no longer what step 4 actually merges.
   The evidence run below spends real quota on all three backends; a maintainer who has to redo this step must not reuse the earlier record, even though re-spending that quota is tempting.
   Immediately before it, run the backend-CLI precondition above, `uv run python scripts/check_backend_compat.py` and the rule-18 carrier re-check, because the evidence vouches for exactly the CLI versions installed at this moment.
   Run `uv run python scripts/record_live_gate_evidence.py`.
   The script itself forces `AMICUS_REQUIRE_LIVE=1` into each backend's subprocess environment, so prefixing the command with it is optional; its own usage string documents `AMICUS_REQUIRE_LIVE=1 uv run python scripts/record_live_gate_evidence.py`, and either form runs the same live gates.
   This spends real quota on all three backends and requires the maintainer's authorization in the session where it runs.
   Run `AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py -v --no-cov` and confirm the freshness assertion passes.
   Create the annotated tag **locally**, exactly as it will be pushed, so the checker can verify the pin and the tag before anything leaves this machine:

   ```sh
   git tag -a vX.Y.Z -F .release-evidence/live-gates.json --cleanup=verbatim <release-sha>
   ```

   Run `uv run python scripts/check_release_state.py --tag vX.Y.Z --commit <release-sha>` and confirm it prints `release predicate holds for vX.Y.Z`.
   It needs the local tag: `.mcp.json` pins `vX.Y.Z`, and the checker requires that tag to exist, with no pre-tag exception.
   If this step must be redone because the branch gained a commit, delete the local tag with `git tag -d vX.Y.Z` first, then recreate it against the new tip.
   That is the same tree check the `verify` job will run after the tag is pushed, so a failure here is a failure you would otherwise discover with an immutable tag already in place.
   Rehearse the real install path against the release commit, which is the check that used to be impossible before the tag existed:

   ```sh
   printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"rehearsal","version":"0"}}}' \
     | UV_CACHE_DIR="$(mktemp -d)" uvx --from "git+https://github.com/briandconnelly/amicus.git@<release-sha>" amicus-mcp
   ```

   Substitute the release commit's SHA for the tag and change nothing else: a commit SHA resolves over the same git transport a tag does, and it exists before the tag does.
   A clean `UV_CACHE_DIR` is what makes this mean anything — `uvx` reuses a cached tool environment without contacting any index, so a warm cache can answer from a build you already had.
   Confirm the server answers `initialize` with `serverInfo.name == "amicus"` and the version being released.
   This proves git transport, a clean-machine build, the console script and the wire handshake before anything irreversible happens.
   What it does not prove is that the string `vX.Y.Z` resolves, which is the trivial remainder and is covered by the post-tag checks.
   Run the gate defined by AGENTS.md rule 2.
   The 24-hour freshness window this evidence carries (`validate`'s `max_age_hours`) is checked only here, at step 3, and deliberately not by CI afterward: a tag is immutable, so a window applied after tagging could let queue time or a slow deployment approval turn a legitimate tag into one that can never be published.
   The window is therefore yours to honor: merge PR C, the next step, before the day is out — otherwise this step must be repeated.
4. Merge PR C with an ordinary merge commit: `gh pr merge --merge`.
   This is the strategy this repository already uses for its PRs, including #7 through #10.
   Squash and rebase are forbidden here, not merely discouraged: both create a new commit and drop the release commit from `main`'s history entirely, which would destroy the subject the evidence names, leaving no commit in `main`'s history for the tag to legitimately point at.
   Do not re-run `AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py` after this merge "just to be sure": the recorded evidence names the release commit, which is no longer `main`'s HEAD once the merge commit exists, so the freshness assertion fails by design from here on.
   That designed failure is not a stop signal; it is expected, and a cautious re-check at this point will read as one anyway if you are not expecting it.
5. Run `git fetch origin` first.
   `gh pr merge --merge` updates GitHub, not the local `origin/main` remote-tracking ref, so any check below run against a stale local ref can pass while meaning nothing — a check run against a stale ref is worse than no check, because it looks like evidence.
   Run `git merge-base --is-ancestor <release-sha> origin/main && echo ok`.
   `git merge-base --is-ancestor` prints nothing itself and exits non-zero on failure, so the `&& echo ok` is what makes success visible: `ok` printed means the release commit is in `main`'s history, and any non-zero exit (no `ok`) means it is not, and the release must stop.
   Run `git rev-parse origin/main^2`.
   It must print the release commit's SHA.
   If the command fails outright, `main`'s head is not a merge commit at all, meaning the merge was squashed or rebased despite the prohibition in step 4, and the release must stop.
   If it instead succeeds but prints a different SHA, the merge was an ordinary merge commit but of a branch tip the recorded evidence does not cover — the PR C branch gained a commit after step 3 was run — and the release must stop for that reason instead; do not diagnose this case as a squash or rebase.
   Run `git diff --stat <release-sha> origin/main`.
   It must print nothing, which is what proves the tree the tag will point at and the tree `main` now holds are identical; any output means something else merged in between, and the release must stop.
6. Push the annotated tag step 3 created, which points at the release commit rather than `main`'s head and whose message is the evidence record verbatim.
   Do not create it again: `git tag -a` on a name that already exists fails with `fatal: tag 'vX.Y.Z' already exists`.
   Rerun the checker against it immediately before pushing:

   ```sh
   uv run python scripts/check_release_state.py --tag vX.Y.Z --commit <release-sha>
   git push origin vX.Y.Z
   ```

   AGENTS.md rule 20 requires this form, and the `verify` job refuses a lightweight tag: `.release-evidence/` is gitignored, so the tag message is the only carrier that reaches CI.
   `--cleanup=verbatim` keeps the JSON byte-for-byte; the default cleanup would also parse, but exactness is free here.
   Confirm before pushing that `git cat-file -t vX.Y.Z` prints `tag` (not `commit`, which would mean a lightweight tag) and that `git tag -l --format='%(contents)' vX.Y.Z | python -c 'import json,sys; json.load(sys.stdin)'` exits 0.
   Nothing but step 5's read-only checks happens between step 4 and step 6.
7. Once the publish has completed and the post-tag checks below have passed, open a small `chore(release):` PR that advances `.claude-plugin/marketplace.json`'s pointer to the new tag.
   A release is not complete until this PR merges: tagging and publishing expose it to no plugin user, because hosts install the tag the pointer names.
   Set `ref` to `vX.Y.Z` and `sha` to `git rev-parse vX.Y.Z^{commit}` — the peeled commit, not the tag object — then run `uv run python scripts/check_release_state.py --base origin/main` and confirm it prints `marketplace pointer check holds.`
   It is not a release under rule 19 and needs no live-gate evidence: it moves a pointer to a tag that is already published.
   Unlike ADR 0015's pin-move it replaces, it reaches installed plugins, because the version at the new tag differs from the one they hold.

   **The 0.4.0 transition.**
   Until this step first merges for 0.4.0, the entry's `source` is `"./"` and plugin users install `main` directly.
   For that release only, this PR replaces `"./"` with the pointer, and nothing else merges to `main` between PR C and this PR: an install from `main` in that interval is keyed `0.4.0`, and the pointer PR, also `0.4.0`, will not replace it.

A maintainer who instead wants the tag to be `main`'s own head has a permitted alternative: a direct fast-forward push of the PR C branch to `main` (`git checkout main && git merge --ff-only <pr-branch> && git push origin main`) achieves that, if this repository's branch protection allows a direct push to `main`.
This runbook cannot say whether it does: `gh api repos/briandconnelly/amicus/branches/main/protection` returned `403 Resource not accessible by integration` to the token available while writing it, so that setting is unverified here, and this document does not assert it either way.
Treat the ordinary-merge-commit path above as the default; use the fast-forward alternative only if a maintainer confirms it is actually available.

## What happens next

Pushing the tag starts `.github/workflows/publish.yml`.
The `build` job runs first, then `verify`, and only then does the `pypi` job wait for the `pypi` environment's required reviewer.
`verify` runs `scripts/check_release_state.py` against the tagged commit and writes its result to the run summary, so read that summary before approving — it is there for exactly this moment, and it is why the check does not live in the `pypi` job, whose every step would run only after your approval.
Read what the summary claims precisely.
Release-state coherence is proven: the version literals, the dated changelog section and `uv.lock` really do agree on the tagged tree.
The live-gate line is not proof the three suites ran; it reports that the record you wrote is well formed and names this commit.
You are the only evidence that the runs happened, which is what AGENTS.md rule 23 is about.
Approve that deployment deliberately once you have confirmed the build artifacts look right.
The upload is irreversible: PyPI does not allow re-uploading a version, even a broken one.
A pause here is the workflow waiting on you, not a hang.
The tagged `pypi` job itself has never actually run: its condition is `github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`, and both dispatches exercised so far (2026-09-08, TestPyPI: `34255779351`, which failed at the OIDC token exchange, and `34256365085`, which succeeded) ran against `refs/heads/main`, a branch, so that job was skipped both by the current two-clause condition and by the original one-clause condition it replaced.
Approving that first real deployment is authorizing untested territory, not a rerun of something already proven.

## Post-tag completion checks

Run these once the tag is pushed and the publish workflow has completed.
They confirm the release actually landed; they are not a pre-tag gate.

1. Confirm the release is live on PyPI:

   ```sh
   curl -s https://pypi.org/pypi/amicus/json | head -c 200
   ```

   This must return the release metadata, not a 404.
2. Install from the public tag exactly as a user would, using the committed manifest's own source:

   ```sh
   printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"post-tag","version":"0"}}}' \
     | UV_CACHE_DIR="$(mktemp -d)" uvx --from "git+https://github.com/briandconnelly/amicus.git@vX.Y.Z" amicus-mcp
   ```

   Assert `serverInfo.name == "amicus"` and the expected version in the reply.
   The fresh `UV_CACHE_DIR` is part of the command, not a note beside it: a warm cache answers without resolving anything, so a copy-pasted command without it can pass while proving nothing.
   Step 3's rehearsal already proved transport, build and handshake against the release commit's SHA, so what this adds is narrow but real — that the tag *ref* resolves, which is all that separated the rehearsal from the thing itself.
   This is what step 7's pointer PR is waiting on: do not point the marketplace at a tag whose install you have not just run.
3. Run a negative control: the same command against a version that does not exist must fail.
   Without it, a warm cache or a silently-substituted binary would make check 2 pass no matter what.

## Rollback

A published PyPI version cannot be withdrawn, only yanked.
A pushed tag can be deleted, but the protection ruleset in the preconditions above deliberately prevents that, and deleting a tag that users may already have installed from is itself a break.
The remedy for a bad release is a new patch release, not a rewrite of history.
