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

1. Merge PR B (the milestone work, version literals untouched).
2. Open and merge PR C, the `chore(release):` PR described by AGENTS.md rule 19.
   Roll `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z] - YYYY-MM-DD` section, and leave a fresh empty `## [Unreleased]` above it.
   Change no version literal unless the version itself is changing.
   For 0.1.0 no literal moves: `pyproject.toml`, `src/amicus/__init__.py`, both `plugin.json` files, and `.mcp.json`'s `@v0.1.0` pin already agree, and the tag is what makes that pin resolve.
   Regenerate `uv.lock` with `uv lock` in this same PR, per AGENTS.md rule 19 — `uv.lock` mirrors the version rather than declaring it, and `prek.toml`'s `uv-lock-check` hook runs `uv lock --check` whenever `pyproject.toml` changes, so a release PR that skips this fails its own hook.
3. Check out the merged commit into a clean tree and confirm `git status --porcelain` is empty.
4. Run `uv run python scripts/record_live_gate_evidence.py`.
   This spends real quota on all three backends and requires the maintainer's authorization in the session where it runs.
5. Run `AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py -v --no-cov` and confirm the freshness assertion passes.
6. Run the gate defined by AGENTS.md rule 2.
7. Tag that unchanged commit and push the tag.

## What happens next

Pushing the tag starts `.github/workflows/publish.yml`.
The `build` job runs first, then the `pypi` job waits for the `pypi` environment's required reviewer.
Approve that deployment deliberately once you have confirmed the build artifacts look right.
The upload is irreversible: PyPI does not allow re-uploading a version, even a broken one.
A pause here is the workflow waiting on you, not a hang.

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
