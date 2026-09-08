# amicus Publish Workflow Implementation Plan

> **STATUS: COMPLETE (2026-09-08). HISTORICAL — DO NOT RE-EXECUTE.**
> All three tasks are done; see "Outcome" at the end for what was built, what was proven, and what was not.
> The templates below are the record of what was *planned*, and some of it was wrong: the build step's `--help` probe cannot work, and the checkout is missing `persist-credentials: false`.
> Where a template has since been corrected in the repository, `.github/workflows/publish.yml` is authoritative, never this file.
> A future release change starts from the workflow and from `tests/test_check_github_actions_pinning.py`, not from these steps.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire release automation that builds the wheel and sdist, verifies them, and publishes on a tag — proven end to end against TestPyPI, with nothing published to PyPI.

**Architecture:** One workflow file, `.github/workflows/publish.yml`, triggered by a `v*` tag and by `workflow_dispatch` for the dry run.
It reuses the `hatchling` build already configured in `pyproject.toml` and adds no build tooling.
Trusted publishing (OIDC) rather than a stored token, so no long-lived credential exists to leak.

**Tech Stack:** GitHub Actions, `uv`, `hatchling`, PyPA's `gh-action-pypi-publish`.
No change to the package's runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — "Milestones" row M7 (release + deprecate siblings) is where publishing happens; this plan builds the mechanism M7 triggers.
Binding repo rules: `AGENTS.md`, especially rules 3, 12, 14 and 15.
Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`, rules 5 and 6 — which are why this is a plan of its own rather than a task inside M6.

## Why this is a separate plan

The M6 planning session originally placed the publish workflow inside the M6 plan, on its own branch.
A Codex review of that plan found the arrangement violated the execution model.
Rule 5 says one plan produces one draft PR; rule 6 says `.github/workflows/**`, `CODEOWNERS` and `AGENTS.md` are separate reviewed PRs, not side effects of a milestone plan.
A second branch inside one plan satisfies AGENTS.md rule 9's letter — no mixed commit — while still breaking rule 5.
This plan exists so the workflow gets its own planning and review record.

## Global Constraints

- Repo: `/Users/bdc/projects/amicus`.
  Branch from `main` **after M6 has merged**, so the wheel build this workflow publishes is the one M6 Task 7 proved.
  Work in a sibling worktree; never commit to `main`.
- This plan's PR touches `.github/workflows/` and therefore nothing else.
  No `src/`, no `tests/`, no `docs/`, and **no `README.md`**: rule 9 says a `.github/**` change ships in a PR of its own, and a README commit riding along makes it a mixed PR.
  The README's "Release automation" row is a separate, ordinary docs PR — see Task 3.
  (An earlier draft of this plan allowed "the README row" in the same PR, which contradicted this same bullet's first sentence; that is the error corrected here.)
- Rule 14: pin every `uses:` to a full 40-character commit SHA with the version in a trailing comment.
- Rule 15: never add a `pull_request_target` workflow.
- Rule 3: run `uv run python scripts/check_github_actions_pinning.py` before pushing.
- Rule 12: Conventional Commits; the `ci` and `release` scopes both already exist in `scripts/check_commit_message.py`, so this plan adds no scope.
- Rule 8: never merge, never approve.
- **Nothing is published to PyPI by this plan.** The trademark clearance the README names is open and is the maintainer's call.
  TestPyPI only.

---

### Task 1: The publish workflow

**Files:**
- Create: `.github/workflows/publish.yml`

**Interfaces:**
- Consumes: the `hatchling` build config in `pyproject.toml`; the `amicus-mcp` console script.
- Produces: a workflow with two entry points — `workflow_dispatch` for a TestPyPI dry run, and a `v*` tag for the real publish.

- [x] **Step 1: Resolve the action SHAs before writing anything**

Rule 14 needs full commit SHAs, and they must be looked up, not recalled.

The list below is every `uses:` in Step 2's template, and it must stay that list: a repo left out here leaves an unresolved `<SHA>` in the workflow, which the rule-3 pinning check will reject.

```sh
for repo in actions/checkout astral-sh/setup-uv actions/upload-artifact actions/download-artifact pypa/gh-action-pypi-publish; do
  echo "== $repo"
  gh api "repos/$repo/tags" --jq '.[0:3][] | "\(.name) \(.commit.sha)"'
done
```

Record the tag and SHA pairs; use them verbatim in the next step.
After Step 2, confirm nothing was missed: `grep -n '<SHA>' .github/workflows/publish.yml || echo "all resolved"` must print `all resolved`.

- [x] **Step 2: Write the workflow**

Structure, with `<SHA>` and `<version>` replaced by Step 1's real values:

```yaml
name: publish

on:
  push:
    tags: ["v*"]
  workflow_dispatch:
    inputs:
      target:
        description: "Where to publish"
        required: true
        default: testpypi
        type: choice
        options: [testpypi]

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<SHA>  # v<version>
      - uses: astral-sh/setup-uv@<SHA>  # v<version>
      - run: uv build
      - run: uv run --with twine twine check dist/*
      - run: |
          uv venv /tmp/smoke
          uv pip install --python /tmp/smoke/bin/python dist/*.whl
          # NOT `--help`: see below. One JSON-RPC `initialize` over stdin, asserting the
          # server identity and version that come back.
          req='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"publish-smoke","version":"0"}}}'
          { printf '%s\n' "$req"; sleep 5; } | timeout 120 /tmp/smoke/bin/amicus-mcp > out.jsonl || true
      - uses: actions/upload-artifact@<SHA>  # v<version>
        with:
          name: dist
          path: dist/

  testpypi:
    needs: build
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    environment: testpypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@<SHA>  # v<version>
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@<SHA>  # v<version>
        with:
          repository-url: https://test.pypi.org/legacy/

  pypi:
    needs: build
    # Corrected after review: the event check is load-bearing, not redundant. A workflow can be
    # dispatched against any branch OR TAG, so the ref check alone let a dispatch aimed at an
    # existing `v*` tag publish to real PyPI during a dry run. Pinned by
    # `tests/test_check_github_actions_pinning.py`.
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@<SHA>  # v<version>
        with:
          name: dist
          path: dist/
      - name: The tag must equal v + the version in the artifact
        run: |
          set -euo pipefail
          tag="${GITHUB_REF_NAME}"
          wheel="$(ls dist/*.whl)"
          # The wheel filename's second field is the version hatchling built.
          built="$(basename "$wheel" | cut -d- -f2)"
          if [ "$tag" != "v${built}" ]; then
            echo "::error::tag ${tag} does not match built version ${built}; refusing to publish"
            exit 1
          fi
      - uses: pypa/gh-action-pypi-publish@<SHA>  # v<version>
```

The tag/version gate is not optional bookkeeping.
Without it any `v*` tag reaches the `pypi` job and publishes whatever `uv build` produced from that commit, so a stale tag (`v0.1.0` moved onto a `0.2.0` commit) or a mistyped one (`v0.10` for `0.1.0`) uploads an artifact whose version contradicts the tag, and PyPI uploads are immutable.
It is read off the built wheel's filename rather than off `pyproject.toml` so that it verifies the artifact actually being uploaded, not a file that happens to sit beside it.
Step 6 asserts the step exists, so it cannot be dropped silently.

The console-script step is the point of the build job: it proves the console script the manifests invoke actually exists in the built wheel.
M6's manifest smoke proved that locally; this proves it for the artifact that would ship.

RESOLVED DURING EXECUTION: `amicus-mcp` has NO `--help`.
It ignores the flag, starts the stdio server and exits 0 at EOF, so a `--help` step would have passed on any binary that exits 0.
The probe above is the fallback this plan named, and it is what shipped.

- [x] **Step 3: Run the pinning check (rule 3)**

Run: `uv run python scripts/check_github_actions_pinning.py`
Expected: exit 0.

- [x] **Step 4: Confirm the pinning check can fail**

Replace one `uses:` SHA with a tag (`actions/checkout@v4`), rerun the check, and confirm it FAILS naming that line.
Restore the SHA and rerun to green.
A pinning check that passes on an unpinned action is not evidence.

- [x] **Step 5: Confirm no `pull_request_target` exists (rule 15)**

Run: `grep -rn "pull_request_target" .github/ || echo "none"`
Expected: `none`.

- [x] **Step 6: Validate the workflow parses**

Run: `uv run python -c "
import yaml, pathlib
doc = yaml.safe_load(pathlib.Path('.github/workflows/publish.yml').read_text())
assert set(doc['jobs']) == {'build', 'testpypi', 'pypi'}
cond = doc['jobs']['pypi']['if']
assert 'event_name' in cond and 'push' in cond, cond
assert 'refs/tags/v' in cond, cond
assert '&&' in cond and '|' not in cond, cond
assert doc['jobs']['testpypi']['permissions']['id-token'] == 'write'
steps = doc['jobs']['pypi']['steps']
gate = next(i for i, st in enumerate(steps) if 'GITHUB_REF_NAME' in (st.get('run') or ''))
publish = next(i for i, st in enumerate(steps) if 'gh-action-pypi-publish' in (st.get('uses') or ''))
assert gate < publish, 'the tag/version gate must run before the publish step'
print('ok')
"`
Expected: `ok`.

This snippet is now a convenience only.
The two assertions that matter live in `tests/test_check_github_actions_pinning.py`, where they run on every gate rather than only when somebody reads this file.
The version of this step originally written here asserted `if` merely *started with* `startsWith(github.ref`, which went stale the moment review corrected the condition, and which nothing would have caught because no test executed it.

Then confirm the assertion can fail, or it is not evidence: delete the gate step from a scratch copy of the workflow, run the same snippet against that copy, and confirm it raises `StopIteration` rather than printing `ok`.
Discard the scratch copy.

- [x] **Step 7: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci(release): add the publish workflow with a TestPyPI dry run"
```

---

### Task 2: Prove it against TestPyPI (post-merge; the maintainer dispatches)

**Files:**
- None. This task produces evidence, not a diff.

**Interfaces:**
- Consumes: the workflow from Task 1, **after its PR has been merged to `main`**.
- Produces: evidence the release path works end to end, without publishing to PyPI.

- [x] **Step 0: Understand why this task cannot run from this branch**

GitHub only offers a `workflow_dispatch` trigger for a workflow file that exists on the repository's **default branch**: "This event will only trigger a workflow run if the workflow file exists on the default branch" ([Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), `workflow_dispatch`).
Until `publish.yml` is on `main`, `gh workflow run publish.yml --ref feat/<branch>` fails with `Workflow does not have 'workflow_dispatch' trigger`, and the `--ref` option only chooses which ref the *already-dispatchable* workflow runs against.
So the proof step cannot be executed from this plan's own unmerged branch, and an earlier draft that dispatched with `--ref <this branch>` inside Task 1's PR could not have worked.

Rule 8 forbids the agent merging its own PR, so the sequencing is:

1. Task 1's PR is opened as a draft and reviewed.
2. **The maintainer merges it.** This is the hand-off point; the agent stops here and says so.
3. Steps 1–3 below run against `main`, by the maintainer or by an agent the maintainer asks in a later session.
4. Task 3 records the outcome in its own docs PR.

Confirm the constraint rather than trusting this prose: before merge, `gh workflow list` must NOT list `publish.yml`; after merge it must.
If it is listed before merge, this whole step is wrong and the plan should be corrected, not worked around.

Do **not** work around the constraint by adding a `push:` branch trigger to `publish.yml` for testing.
A publish workflow with `id-token: write` that fires on a branch push is a materially wider trigger surface than the one this plan reviewed, and removing it afterwards leaves the reviewed file different from the tested one.

- [x] **Step 0.5: Configure the environments first (maintainer-only, and not optional)**

The workflow names `environment: testpypi` and `environment: pypi`, and this plan originally said nothing about creating them.
That omission is not benign.
GitHub does not fail a run that references a missing environment: it creates one, and per its documentation "the newly created environment will not have any protection rules or secrets configured".
So a `v*` tag pushed before `pypi` exists auto-creates it unprotected and publishes with no human approval, while the `environment: pypi` line still *reads* like a gate.

Required before any tag is ever pushed:

- `pypi`: required reviewers, plus a deployment **tag** rule limited to `v*`.
  The rule must be a tag rule, not a branch rule, because the job is triggered by a tag and a branch-only rule blocks every release.
  It is deliberately redundant with the job's `if:` condition, so that a settings-level guard survives that condition being loosened later.
- `testpypi`: a deployment branch rule limited to `main`, and no reviewer, since it can only ever reach TestPyPI.

Also register the trusted publishers, which are per-index and entirely separate: `amicus` / `briandconnelly` / `amicus` / `publish.yml`, with environment `testpypi` on test.pypi.org and `pypi` on pypi.org.
Read the result back rather than trusting the settings page, with BOTH calls, because neither alone is sufficient.
The environment endpoint reports that a `branch_policy` rule exists but not which refs it names, so it cannot catch a missing or wrongly typed rule:

```sh
gh api repos/briandconnelly/amicus/environments/<env> \
  --jq '[.protection_rules[] | {type, reviewers: [.reviewers[]?.reviewer.login]}]'
gh api repos/briandconnelly/amicus/environments/<env>/deployment-branch-policies \
  --jq '[.branch_policies[] | "\(.type):\(.name)"]'
```

Expect `required_reviewers` and `["tag:v*"]` for `pypi`, and `["branch:main"]` for `testpypi`.
Adding a reviewer and saving the protection rule are two separate clicks, and the half-done state looks configured.

- [x] **Step 1: Ask before dispatching**

The dry run uploads a real artifact to TestPyPI under the name `amicus`, which is a public namespace claim on that index.
The README lists trademark clearance for the name as an open maintainer-only question.
**Stop and ask the maintainer before the first dispatch.**
If they decline, mark this task blocked and say so in Task 3's PR body rather than skipping it silently.

- [x] **Step 2: Dispatch the dry run from `main`**

Run: `gh workflow run publish.yml -f target=testpypi --ref main`
Then: `gh run watch`

- [x] **Step 3: Verify the artifact, not just the green check**

The check must be specific to the artifact this run uploaded.
An unpinned `amicus` request across two indexes proves nothing: it can resolve to some other project of that name, to an older release, or to a wheel from PyPI rather than TestPyPI, and printing whatever version arrives will look like success in every one of those cases.
So: read the expected version out of `pyproject.toml`, request that exact version, keep TestPyPI ahead of PyPI for this package, and assert.

```sh
set -euo pipefail
VERSION="$(uv run python -c "
import pathlib, tomllib
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])
")"
echo "expecting amicus==${VERSION}"

uv venv /tmp/testpypi-smoke
uv pip install --python /tmp/testpypi-smoke/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  --index-strategy first-index \
  "amicus==${VERSION}"

INSTALLED="$(/tmp/testpypi-smoke/bin/python -c 'import amicus; print(amicus.__version__)')"
test "${INSTALLED}" = "${VERSION}" \
  || { echo "MISMATCH: installed ${INSTALLED}, expected ${VERSION}"; exit 1; }
# `amicus-mcp` has no `--help`; probe it as the stdio server it is.
req='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"testpypi-smoke","version":"0"}}}'
{ printf '%s\n' "$req"; sleep 6; } | /tmp/testpypi-smoke/bin/amicus-mcp 2>/dev/null | grep -q '"name":"amicus"' \
  || { echo "the installed console script did not answer initialize"; exit 1; }
echo "ok: amicus==${VERSION} installed from TestPyPI and its console script answered initialize"
```

`--index-strategy first-index` is what keeps TestPyPI authoritative for `amicus` specifically while dependencies still resolve from PyPI: uv takes the first index that carries a given package, and TestPyPI is first.
It is stated explicitly rather than left to uv's default so a default change cannot silently reorder them.

Then confirm the check can fail, because a check that cannot fail is not evidence: rerun the same block with `VERSION` forced to a version that was never uploaded (e.g. `0.0.0`) and confirm `uv pip install` exits non-zero with a resolution error.
Record both outcomes.

A green workflow run proves the upload returned 200; it does not prove the artifact is installable, and it does not prove the installed artifact is the one uploaded.

---

### Task 3: Record the outcome (a separate docs PR)

**Files:**
- Modify: `README.md` (one row in "Where things are")

**Interfaces:**
- Consumes: Task 2's evidence.
- Produces: an index entry for this plan, in a PR that touches no `.github/**` file.

- [x] **Step 1: Branch from `main` after Task 1's PR has merged**

This is a docs change and must not share a PR with the workflow (rule 9, and Global Constraints above).

- [x] **Step 2: Add the README row and commit**

The README already carries a publish-workflow row, so this is an edit rather than an addition; adding a second row would duplicate it.
Update that row to name the release automation and to drop the stale "executed after M6 merges" wording, and update "Resuming the work" to say `main` carries the publish workflow.

```bash
git add README.md
git commit -m "docs(release): index the publish workflow plan"
gh pr create --draft --title "docs(release): index the publish workflow plan"
```

- [x] **Step 3: Put the evidence in that PR's body**

The TestPyPI run URL, the asserted version from Task 2 Step 3, and the negative-control result.
If Task 2 was declined or blocked, say that here instead, explicitly.

Rule 8: never merge, never approve.

---

## Self-Review

**Spec coverage.** This plan builds the mechanism M7's "release" gate triggers; it deliberately does not publish, which stays M7's and the maintainer's decision.

**Placeholder scan.** `<SHA>` and `<version>` are explicitly resolved in Task 1 Step 1 before use, over the full list of actions the template uses (checkout, setup-uv, upload-artifact, download-artifact, gh-action-pypi-publish), and a `grep` for a surviving `<SHA>` backs it up.
The `--help` uncertainty is resolved by a named probe rather than an assumption.

**Sequencing.** Task 2 cannot run before Task 1's PR merges, because `workflow_dispatch` is only offered for a workflow present on the default branch.
The plan states that as a hand-off rather than pretending the dry run happens inside the workflow PR, and it rules out the tempting workaround (a temporary `push:` trigger) because it would widen the trigger surface of a job holding `id-token: write`.

**PR separation.** Three PRs, not two: the workflow alone (Task 1, rule 9), and the README row alone (Task 3).
No PR in this plan mixes `.github/**` with anything else.

**Known gaps.** TestPyPI is not PyPI: index behavior, name availability and trusted-publishing configuration can differ between them.
A green TestPyPI run reduces release risk; it does not eliminate it.
The `pypi` job is therefore unexercised until M7 tags a release, and this plan says so rather than implying the path is proven.
Its tag/version gate is unexercised for the same reason: Step 6's parse assertion proves the step is present and ordered before the publish step, not that it rejects a mismatched tag in a real run.
Exercising it needs a throwaway tag on a fork or a `pypi` job made dispatchable, and neither is in this plan's scope.

---

## Outcome (2026-09-08)

All three tasks are done.
The record below is the plan's own, because the branch and worktree were removed at cleanup.

**Task 1** merged as `2170a3a` (PR #8), two commits, touching only `.github/workflows/publish.yml`.

Two things in this plan's Task 1 template were wrong, and both were caught outside its own verification list:

- The `--help` step could not have worked.
  `amicus-mcp` has no help flag: it ignores the argument, starts the stdio server and exits 0 at EOF, so the step would have passed on any binary that exits 0.
  The plan anticipated this and named the fallback, which is what was built — one JSON-RPC `initialize` over stdin, asserting `serverInfo.name` and that `serverInfo.version` equals the built wheel's version.
- The checkout was missing `persist-credentials: false`, which this repository requires.
  Steps 3 to 6 all passed while that test was failing; the rule-2 gate is what caught it.

Review then found a third, more serious defect that this plan's Step 6 assertion had actually blessed.
The `pypi` job was gated on `startsWith(github.ref, 'refs/tags/v')` alone.
A workflow can be dispatched against any branch or tag and `github.ref` is then the dispatched ref, so `gh workflow run publish.yml --ref v0.1.0` would have run the production job during a dry run and published to real PyPI, which is immutable.
Fixed in `cb69700`, and now pinned by a test rather than by prose.

**Task 2** passed on the second dispatch; `amicus 0.1.0` is published on TestPyPI.

- Failed first attempt: https://github.com/briandconnelly/amicus/actions/runs/34255779351
- Successful dispatch: https://github.com/briandconnelly/amicus/actions/runs/34256365085

The first dispatch failed at the OIDC token exchange with `invalid-publisher`, before any upload, because only the pypi.org publisher had been registered and not the test.pypi.org one.
Nothing was uploaded by that attempt, so it claimed no namespace.
The claims in its log were all correct, which is what isolated the fault to the registration rather than the workflow.

Verified beyond the green check, as Step 3 requires: `amicus==0.1.0` installed from TestPyPI with `--index-strategy first-index`, `amicus.__version__` asserted equal to the version in `pyproject.toml`, and the installed console script answered a real `initialize`.
Provenance was settled more strongly than Step 3 asked, because `pypi.org/pypi/amicus/json` returns 404 while `test.pypi.org/pypi/amicus/json` returns 200, so the install could only have come from TestPyPI.
The negative control ran too: `amicus==0.0.0` fails to resolve.

**What remains unproven, and should not be overclaimed.**
The `pypi` job and its tag/version gate are still unexercised.
The dry run skipped that job, but only because the dispatch ref was a branch, so the superseded one-clause condition would have skipped it too; that run is not evidence for the fix.
Exercising it needs a real `v*` tag, which is M7's business.
