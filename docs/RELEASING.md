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

Confirm a ruleset targeting `refs/tags/v*` whose rules restrict `creation` as well as `update` and `deletion`, and whose bypass list contains no agent identity.
Creation is the load-bearing rule.
`.github/workflows/publish.yml` triggers on `push: tags: ["v*"]`, so any identity that can create a `v*` tag can trigger a publish without rules 19 and 20 having been satisfied first.
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
TestPyPI already has the name claimed under this project; pypi.org does not yet have a release.

## The release sequence

Rules 19 and 20 together shape this sequence, and a future maintainer should not "simplify" it back.
Rule 20 requires the live-gate evidence to cover the exact commit being tagged.
Rule 19 requires the tag push to be the only work that follows the PR C merge, because the interval in which `main` names a tag that does not yet exist cannot be made zero, only closed as fast as possible.
The tag does not have to point at `main`'s head; it has to point at the commit the evidence covers.
An ordinary merge commit keeps the PR C branch tip in `main`'s history as one of the merge commit's two parents, so tagging that branch tip is legitimate, and it is exactly the commit the evidence names — no fast-forward or branch-protection change is required to satisfy both rules.
The tag therefore deliberately points at a commit that is in `main`'s history but is not `main`'s head, and the checks in step 5 below prove the two commits' trees are identical.

1. Merge PR B (the milestone work, version literals untouched).
2. Open PR C, the `chore(release):` PR described by AGENTS.md rule 19, and do not merge it yet.
   Roll `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z] - YYYY-MM-DD` section, and leave a fresh empty `## [Unreleased]` above it.
   Change no version literal unless the version itself is changing.
   For 0.1.0 no literal moves: `pyproject.toml`, `src/amicus/__init__.py`, both `plugin.json` files, and `.mcp.json`'s `@v0.1.0` pin already agree, and the tag is what makes that pin resolve.
   Regenerate `uv.lock` with `uv lock` in this same PR, per AGENTS.md rule 19 — `uv.lock` mirrors the version rather than declaring it, and `prek.toml`'s `uv-lock-check` hook runs `uv lock --check` whenever `pyproject.toml` changes, so a release PR that skips this fails its own hook.
3. Check out the PR C branch tip (not `main`) into a clean tree and confirm `git status --porcelain` is empty.
   Record the branch tip's SHA; call it the release commit, and note it well — it is the commit that gets tagged, and it will not be `main`'s head after the next step.
   If the PR C branch gains any commit after this point — an "Update branch" click, or a review pushing a change — this step must be redone from the new tip: the evidence would otherwise cover a commit that is no longer what step 4 actually merges.
   The evidence run below spends real quota on all three backends; a maintainer who has to redo this step must not reuse the earlier record, even though re-spending that quota is tempting.
   Run `uv run python scripts/record_live_gate_evidence.py`.
   The script itself forces `AMICUS_REQUIRE_LIVE=1` into each backend's subprocess environment, so prefixing the command with it is optional; its own usage string documents `AMICUS_REQUIRE_LIVE=1 uv run python scripts/record_live_gate_evidence.py`, and either form runs the same live gates.
   This spends real quota on all three backends and requires the maintainer's authorization in the session where it runs.
   Run `AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py -v --no-cov` and confirm the freshness assertion passes.
   Run the gate defined by AGENTS.md rule 2.
   The 24-hour freshness window this evidence carries (`validate`'s `max_age_hours`) is checked only here, at step 3, and nothing re-checks it afterward: if PR C then sits in review overnight, the tag could be pushed on evidence the mechanism itself would now reject.
   Merge PR C, the next step, before the day is out — otherwise this step must be repeated.
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
6. Push the tag pointing at the release commit, not at `main`'s head: `git tag vX.Y.Z <release-sha>`, then push it.
   Nothing but step 5's read-only checks happens between step 4 and step 6.

A maintainer who instead wants the tag to be `main`'s own head has a permitted alternative: a direct fast-forward push of the PR C branch to `main` (`git checkout main && git merge --ff-only <pr-branch> && git push origin main`) achieves that, if this repository's branch protection allows a direct push to `main`.
This runbook cannot say whether it does: `gh api repos/briandconnelly/amicus/branches/main/protection` returned `403 Resource not accessible by integration` to the token available while writing it, so that setting is unverified here, and this document does not assert it either way.
Treat the ordinary-merge-commit path above as the default; use the fast-forward alternative only if a maintainer confirms it is actually available.

## What happens next

Pushing the tag starts `.github/workflows/publish.yml`.
The `build` job runs first, then the `pypi` job waits for the `pypi` environment's required reviewer.
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
   uvx --from git+https://github.com/briandconnelly/amicus.git@vX.Y.Z amicus-mcp
   ```

   Drive it with one JSON-RPC `initialize` request over stdin and assert `serverInfo.name == "amicus"` and the expected version.
   This is the first and only check that the `.mcp.json` pin actually resolves; it cannot be run before the tag exists.
3. Run a negative control: the same command against a version that does not exist must fail.

## Rollback

A published PyPI version cannot be withdrawn, only yanked.
A pushed tag can be deleted, but the protection ruleset in the preconditions above deliberately prevents that, and deleting a tag that users may already have installed from is itself a break.
The remedy for a bad release is a new patch release, not a rewrite of history.
