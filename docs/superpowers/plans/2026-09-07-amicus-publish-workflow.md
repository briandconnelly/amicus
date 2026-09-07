# amicus Publish Workflow Implementation Plan

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
- This plan touches `.github/workflows/` and therefore nothing else.
  No `src/`, no `tests/`, no `docs/` beyond this plan and the README row.
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

- [ ] **Step 1: Resolve the action SHAs before writing anything**

Rule 14 needs full commit SHAs, and they must be looked up, not recalled.

```sh
for repo in actions/checkout astral-sh/setup-uv pypa/gh-action-pypi-publish; do
  echo "== $repo"
  gh api "repos/$repo/tags" --jq '.[0:3][] | "\(.name) \(.commit.sha)"'
done
```

Record the tag and SHA pairs; use them verbatim in the next step.

- [ ] **Step 2: Write the workflow**

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
          /tmp/smoke/bin/amicus-mcp --help
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
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@<SHA>  # v<version>
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@<SHA>  # v<version>
```

The `amicus-mcp --help` step is the point of the build job: it proves the console script the manifests invoke actually exists in the built wheel.
M6's manifest smoke proved that locally; this proves it for the artifact that would ship.

If `amicus-mcp` has no `--help` (it is an MCP stdio server, so it may not), replace that line with a startup probe that sends an `initialize` request on stdin and asserts a response, rather than deleting the check.
Verify which applies before writing: `uv run amicus-mcp --help; echo "exit=$?"`.

- [ ] **Step 3: Run the pinning check (rule 3)**

Run: `uv run python scripts/check_github_actions_pinning.py`
Expected: exit 0.

- [ ] **Step 4: Confirm the pinning check can fail**

Replace one `uses:` SHA with a tag (`actions/checkout@v4`), rerun the check, and confirm it FAILS naming that line.
Restore the SHA and rerun to green.
A pinning check that passes on an unpinned action is not evidence.

- [ ] **Step 5: Confirm no `pull_request_target` exists (rule 15)**

Run: `grep -rn "pull_request_target" .github/ || echo "none"`
Expected: `none`.

- [ ] **Step 6: Validate the workflow parses**

Run: `uv run python -c "
import yaml, pathlib
doc = yaml.safe_load(pathlib.Path('.github/workflows/publish.yml').read_text())
assert set(doc['jobs']) == {'build', 'testpypi', 'pypi'}
assert doc['jobs']['pypi']['if'].startswith('startsWith(github.ref')
assert doc['jobs']['testpypi']['permissions']['id-token'] == 'write'
print('ok')
"`
Expected: `ok`.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci(release): add the publish workflow with a TestPyPI dry run"
```

---

### Task 2: Prove it against TestPyPI

**Files:**
- Modify: `README.md` (one row in "Where things are")

**Interfaces:**
- Consumes: the workflow from Task 1, once its PR is open.
- Produces: evidence the release path works end to end, without publishing to PyPI.

- [ ] **Step 1: Ask before dispatching**

The dry run uploads a real artifact to TestPyPI under the name `amicus`, which is a public namespace claim on that index.
The README lists trademark clearance for the name as an open maintainer-only question.
**Stop and ask the maintainer before the first dispatch.**
If they decline, mark this task blocked and say so in the PR body rather than skipping it silently.

- [ ] **Step 2: Dispatch the dry run**

Run: `gh workflow run publish.yml -f target=testpypi --ref <this branch>`
Then: `gh run watch`

- [ ] **Step 3: Verify the artifact, not just the green check**

Run:

```sh
uv venv /tmp/testpypi-smoke
uv pip install --python /tmp/testpypi-smoke/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ amicus
/tmp/testpypi-smoke/bin/python -c "import amicus; print(amicus.__version__)"
```

Expected: the version installs from TestPyPI and imports.
A green workflow run proves the upload returned 200; it does not prove the artifact is installable.

- [ ] **Step 4: Record the outcome and update the README**

Add a "Release automation" row pointing at this plan.
Record the TestPyPI run URL and the install-smoke result in the PR body.

- [ ] **Step 5: Commit and open the PR**

```bash
git add README.md
git commit -m "docs(release): index the publish workflow plan"
gh pr create --draft --title "ci(release): add the publish workflow"
```

Rule 8: never merge, never approve.

---

## Self-Review

**Spec coverage.** This plan builds the mechanism M7's "release" gate triggers; it deliberately does not publish, which stays M7's and the maintainer's decision.

**Placeholder scan.** `<SHA>` and `<version>` are explicitly resolved in Task 1 Step 1 before use, and the plan says so rather than leaving them as fill-in-later.
The `--help` uncertainty is resolved by a named probe rather than an assumption.

**Known gaps.** TestPyPI is not PyPI: index behavior, name availability and trusted-publishing configuration can differ between them.
A green TestPyPI run reduces release risk; it does not eliminate it.
The `pypi` job is therefore unexercised until M7 tags a release, and this plan says so rather than implying the path is proven.
