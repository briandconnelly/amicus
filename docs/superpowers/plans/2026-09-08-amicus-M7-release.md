# amicus M7 — Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
Take amicus from merged-and-untagged to tag-ready: a changelog, a rehearsed release runbook, a machine-checked live-gate evidence mechanism, verified sibling differentials, the M6 carryovers closed, and a maintainer checklist for deprecating the siblings — without pushing a tag or publishing to pypi.org.

**Architecture:**
This milestone ships three separate pull requests, in order.
PR A is a governance-only change to `AGENTS.md` and must be merged before any task below is executed.
PR B is this plan.
PR C is a `chore(release): release 0.1.0` metadata PR that the maintainer merges immediately before tagging.
The three authorized live-gate runs happen after PR C merges, on a clean checkout of the exact commit that will be tagged — not on this branch.

**Tech Stack:**
Python 3.11+, `uv`, `ruff`, `ty`, `pytest`, `import-linter`, `prek`, GitHub Actions.
The evidence recorder is pure standard library, following `scripts/check_commit_message.py`.

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — the M7 row of the Milestones table and the "Verification (all milestones)" section.

## Global Constraints

- `uv` for every project and package operation. Never pip, poetry or conda.
- The gate, verbatim, is `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`.
- Never lower `fail_under` in `pyproject.toml`. It is `95`; the current branch coverage on `main` is 96.98%.
- Never run `-m integration` except where this plan says so, and only after asking the maintainer in the current session.
- Never weaken the guard in `tests/conftest.py` that makes real backend binaries unreachable for unit tests.
- Commit messages are Conventional Commits using only the types and scopes in `scripts/check_commit_message.py`. The scopes this plan uses — `docs`, `ci`, `release`, `skills`, `packaging` — all already exist. Do not add a scope.
- Under `docs/`, write Markdown with one sentence per line.
- Never edit a sibling checkout (`~/projects/codex-in-claude`, `~/projects/moonbridge`, `~/projects/claude-in-codex`, `~/projects/pontonier`). Reading them is allowed and this plan does read them.
- Never write a prompt input to disk, argv or a log. Task 5 and Task 8 touch prompt-bearing documents; both record ids and `sha256` values only.
- Do not change `.github/**`, `AGENTS.md` or `CLAUDE.md` in this PR. Rule 9 forces those into their own PR, which is PR A.
- Do not push a git tag. Do not publish to pypi.org. Do not run `gh workflow run`.

## Preconditions

- [ ] PR A is merged to `main` and this branch is rebased onto it. PR A must contain, at minimum: the Release coordination section; the narrowly scoped exception to AGENTS.md rule 7 and execution-model rule 5 that authorizes PR C as a separate non-milestone PR; the statement that live-gate evidence is taken on the commit that will be tagged; and the settled wording of rule 18 with respect to authored differential fixtures.
- [ ] `git -C ~/projects/amicus-wt-m7 status --short` is empty and the branch is `feat/m7-release`.

## What this milestone deliberately does not prove

Write these into the PR description verbatim at Task 10; they are the honest limits of the work.

- The evidence file is hand-forgeable. It is an honest-mistake guard, not an attestation.
- The `pypi` job in `.github/workflows/publish.yml`, its `github.event_name == 'push'` clause, and its tag/version gate remain unexercised. The TestPyPI dry run of 2026-09-08 does not count as evidence for them: it was dispatched against `refs/heads/main`, a branch, so the `pypi` job was skipped, and the original one-clause condition would have skipped it too.
- That `.mcp.json`'s `git+…@v0.1.0` source resolves is untested and untestable before the tag exists. `tests/test_packaging.py::test_the_committed_manifest_command_starts_a_real_server` substitutes a locally built wheel for that one field.

---

### Task 1: CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CHANGELOG.md` with a `## [Unreleased]` section. Task 3's runbook and PR C both refer to it by that exact heading.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
def test_changelog_has_an_unreleased_section():
    """PR C rolls `## [Unreleased]` into a dated section, so that heading must exist.

    The release procedure in `docs/RELEASING.md` edits this heading by exact text. A
    renamed or missing heading turns that step into a silent no-op, which is how a
    release ships with an empty changelog entry.
    """
    text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
    assert text.startswith("# Changelog\n"), "the file must open with the Keep a Changelog title"
    assert "\n## [Unreleased]\n" in text, "the rollover target heading is missing"
    assert "0.1.0" in text, "the first release's entries must be recorded"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_packaging.py::test_changelog_has_an_unreleased_section -v --no-cov`
Expected: FAIL with `FileNotFoundError` naming `CHANGELOG.md`.

- [ ] **Step 3: Write the changelog**

Create `CHANGELOG.md` following Keep a Changelog. Every entry below is derived from merged history — run `git log --oneline --merges main` and `git log --format='%s' main` to confirm each before writing it. Do not invent entries.

```markdown
# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One MCP server for three second-opinion backends — `codex`, `kimi` and `claude` — with the backend as a tool parameter rather than a separate server (M0–M4).
- Synchronous verbs: `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_adversarial_review`, and their dry-run twins.
- Discovery surface: `amicus_backends`, `amicus_capabilities`, `amicus_models`, `amicus_status`, and the MCP resources that back them.
- A jobs surface: `_async` twins of the paid verbs, `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_list`, `amicus_job_cancel`, with idempotency keys, restart survival and task-id lookup (M2).
- `task=True` on the four paid synchronous tools behind the `AMICUS_TASKS` flag (M5).
- Packaging for both hosts: a `.claude-plugin/` manifest, a `.codex-plugin/` manifest, an `amicus-mcp` console script, and the `collaborating-with-amicus` skill (M6).
- Release automation: a tag- and dispatch-triggered publish workflow with trusted publishing to TestPyPI and PyPI.

### Known limitations

- The tagged publish path to pypi.org has never run. Only the TestPyPI dispatch path has been exercised.
- Eval scenarios S6 and S7 in `skills/collaborating-with-amicus/tests/scenarios.md` are not closed; see their `status` fields and ADR 0012.

[Unreleased]: https://github.com/briandconnelly/amicus/commits/main
```

Fill the `### Added` list from actual history rather than copying it blindly; the shape above is the required structure, and every claim in it must be checked against the repository before it ships.

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run pytest tests/test_packaging.py::test_changelog_has_an_unreleased_section -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Prove the test can fail**

Temporarily rename the `## [Unreleased]` heading to `## Unreleased`, re-run the test, and confirm it FAILS naming the rollover target. Restore the heading and confirm it passes again. Record both outcomes in the task's commit body.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md tests/test_packaging.py
git commit -m "docs(release): add a changelog covering M0 through M6"
```

---

### Task 2: The live-gate evidence recorder

**Files:**
- Create: `scripts/record_live_gate_evidence.py`
- Create: `tests/test_release_evidence.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the three live test files `tests/test_codex_live.py`, `tests/test_kimi_live.py`, `tests/test_claude_live.py`.
- Produces:
  - `validate(record: dict, *, head: str, tree_clean: bool, now: datetime, max_age_hours: int = 24) -> list[str]` — returns a list of human-readable problems; an empty list means the record is usable release evidence.
  - `EVIDENCE_PATH = Path(".release-evidence/live-gates.json")` and `FAILURE_PATH = Path(".release-evidence/live-gates.failed.json")`.
  - `BACKENDS = ("codex", "kimi", "claude")`.
  - The record shape, which Task 3's runbook documents:

```json
{
  "batch_id": "32 lowercase hex characters",
  "recorded_at": "2026-09-08T18:00:00+00:00",
  "commit": "40 lowercase hex characters",
  "tree_clean": true,
  "backends": {
    "codex": {"test_file": "tests/test_codex_live.py", "exit_status": 0, "cli_version": "codex-cli 0.153.4"},
    "kimi": {"test_file": "tests/test_kimi_live.py", "exit_status": 0, "cli_version": "..."},
    "claude": {"test_file": "tests/test_claude_live.py", "exit_status": 0, "cli_version": "..."}
  }
}
```

**Design notes the implementer must not deviate from:**

- All-or-nothing. The script runs all three gates in one invocation. `EVIDENCE_PATH` is written only when all three exit 0 on a clean tree; otherwise the script writes `FAILURE_PATH` for diagnosis, leaves any previous `EVIDENCE_PATH` untouched, and exits nonzero. A stale success file surviving a failed run is acceptable and intended — the freshness check rejects it on the commit mismatch.
- One `batch_id` per invocation, shared by all three backend entries. A record whose entries disagree is invalid.
- `validate` is pure: it takes the record and the facts to compare against, and returns problems. It never reads the filesystem or shells out. This is what makes the negative controls ordinary unit tests instead of manual mutations.
- This is an honest-mistake guard, not an attestation. Say so in the module docstring.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_evidence.py`:

```python
"""The release-evidence record is checked by `validate`, so these controls are real tests.

The record itself is a gitignored local file a maintainer can hand-write, so it proves
nothing against a determined author. It is an honest-mistake guard: it catches evidence
taken on the wrong commit, on a dirty tree, from a partial run, or too long ago. Every
rejection path below is exercised, because a validator that cannot fail is not a check.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "record_live_gate_evidence.py"
_spec = importlib.util.spec_from_file_location("record_live_gate_evidence", _SCRIPT)
assert _spec is not None and _spec.loader is not None
evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evidence)

HEAD = "a" * 40
NOW = datetime(2026, 9, 8, 18, 0, 0, tzinfo=timezone.utc)


def _record(**overrides):
    record = {
        "batch_id": "b" * 32,
        "recorded_at": (NOW - timedelta(hours=1)).isoformat(),
        "commit": HEAD,
        "tree_clean": True,
        "backends": {
            name: {
                "test_file": f"tests/test_{name}_live.py",
                "exit_status": 0,
                "cli_version": f"{name}-cli 1.0.0",
            }
            for name in evidence.BACKENDS
        },
    }
    record.update(overrides)
    return record


def test_a_complete_fresh_record_is_accepted():
    assert evidence.validate(_record(), head=HEAD, tree_clean=True, now=NOW) == []


def test_a_record_for_another_commit_is_rejected():
    problems = evidence.validate(_record(commit="c" * 40), head=HEAD, tree_clean=True, now=NOW)
    assert any("commit" in p for p in problems), problems


def test_a_dirty_tree_now_is_rejected():
    problems = evidence.validate(_record(), head=HEAD, tree_clean=False, now=NOW)
    assert any("clean" in p for p in problems), problems


def test_a_record_taken_on_a_dirty_tree_is_rejected():
    problems = evidence.validate(_record(tree_clean=False), head=HEAD, tree_clean=True, now=NOW)
    assert any("clean" in p for p in problems), problems


def test_a_missing_backend_is_rejected():
    record = _record()
    del record["backends"]["kimi"]
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("kimi" in p for p in problems), problems


def test_a_nonzero_exit_status_is_rejected():
    record = _record()
    record["backends"]["claude"]["exit_status"] = 1
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("claude" in p for p in problems), problems


def test_an_expired_record_is_rejected():
    record = _record(recorded_at=(NOW - timedelta(hours=25)).isoformat())
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert any("old" in p or "age" in p for p in problems), problems


def test_a_malformed_record_is_rejected_without_raising():
    problems = evidence.validate({"nonsense": True}, head=HEAD, tree_clean=True, now=NOW)
    assert problems, "a record missing every required field must be rejected, not accepted"


def test_a_future_timestamp_is_rejected():
    record = _record(recorded_at=(NOW + timedelta(hours=2)).isoformat())
    problems = evidence.validate(record, head=HEAD, tree_clean=True, now=NOW)
    assert problems, "a record from the future is a clock or forgery problem, not evidence"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_release_evidence.py -v --no-cov`
Expected: collection FAILS with `FileNotFoundError` for `scripts/record_live_gate_evidence.py`.

- [ ] **Step 3: Write the script**

Create `scripts/record_live_gate_evidence.py`. Pure standard library. It must expose `BACKENDS`, `EVIDENCE_PATH`, `FAILURE_PATH` and `validate` exactly as specified in the Interfaces block, plus a `main()` that:

1. Resolves `git rev-parse HEAD` and `git status --porcelain`.
2. Refuses to run at all on a dirty tree, with a message naming the dirty paths.
3. Runs, for each backend in `BACKENDS`, `AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov <test_file>` as a subprocess, capturing the exit status, and records the backend CLI version by whatever probe that backend's live test already uses.
4. Writes `EVIDENCE_PATH` only when every exit status is 0 and the tree is still clean afterwards; otherwise writes `FAILURE_PATH` and returns 1.
5. Prints one line per backend as it goes, so a maintainer watching a paid run can see which gate is running.

`validate` returns a list of problem strings covering, at minimum: missing or malformed fields; a `commit` that is not `head`; `tree_clean` false in the record; `tree_clean` false now; any backend in `BACKENDS` absent from `backends`; any `exit_status` that is not 0; a `recorded_at` older than `max_age_hours`; a `recorded_at` in the future; and `batch_id` inconsistency if the shape ever grows per-entry batch ids.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_release_evidence.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Add the env-gated freshness assertion**

Add `json`, `os` and `subprocess` to the standard-library imports at the TOP of `tests/test_release_evidence.py`, and `import pytest` to the third-party group — not above the new test.
`ruff` enforces import placement and `uv run ruff check .` is part of the gate, so imports written mid-file fail before the test ever runs.

Then append the test itself:

```python
@pytest.mark.skipif(
    os.environ.get("AMICUS_RELEASE_CHECK") != "1",
    reason="release-only: reads the gitignored evidence file, which CI cannot have",
)
def test_the_recorded_evidence_covers_this_exact_commit():
    """Run with AMICUS_RELEASE_CHECK=1 on the commit about to be tagged."""
    path = Path(__file__).resolve().parent.parent / evidence.EVIDENCE_PATH
    assert path.exists(), f"no live-gate evidence at {path}; run scripts/record_live_gate_evidence.py"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()
    problems = evidence.validate(
        json.loads(path.read_text()),
        head=head,
        tree_clean=not dirty,
        now=datetime.now(timezone.utc),
    )
    assert problems == [], "; ".join(problems)
```

- [ ] **Step 6: Prove the gate is actually gated, in both directions**

Run: `uv run pytest tests/test_release_evidence.py -v --no-cov`
Expected: the new test reports SKIPPED.

Run: `AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py::test_the_recorded_evidence_covers_this_exact_commit -v --no-cov`
Expected: FAIL with "no live-gate evidence at ...". This is the known positive that proves the assertion runs when enabled — a skip and a pass look identical otherwise. Record both outcomes in the commit body.

- [ ] **Step 7: Ignore the evidence directory**

Add to `.gitignore`, under a new comment:

```gitignore
# Release evidence (local, per-maintainer; never committed)
.release-evidence/
```

Verify: `mkdir -p .release-evidence && touch .release-evidence/live-gates.json && git status --porcelain` shows nothing, then `rm -rf .release-evidence`.

- [ ] **Step 8: Commit**

```bash
git add scripts/record_live_gate_evidence.py tests/test_release_evidence.py .gitignore
git commit -m "ci(release): record and validate live-gate evidence for the tag target"
```

---

### Task 3: The release runbook

**Files:**
- Create: `docs/RELEASING.md`
- Modify: `README.md` (the "Where things are" table)

**Interfaces:**
- Consumes: `scripts/record_live_gate_evidence.py` and `AMICUS_RELEASE_CHECK` from Task 2; `CHANGELOG.md`'s `## [Unreleased]` heading from Task 1.
- Produces: the procedure PR C and the maintainer follow.

- [ ] **Step 1: Write the runbook**

Create `docs/RELEASING.md`, one sentence per line. It must contain, in this order:

1. **Who may do this.** Only the maintainer. An agent may prepare PR C but never merges it, never pushes a tag, and never dispatches the publish workflow — `gh workflow run` returns 403 for the App token, and that is a boundary, not an obstacle to route around.
2. **Preconditions, each with the command that checks it and the output that means yes.**
   - The `v*` tag protection ruleset exists. Read it back: `gh api repos/briandconnelly/amicus/rulesets` and confirm a ruleset targeting `refs/tags/v*` with `deletion` and `update` rules. A settings page that looks right is not evidence; the M6 environment check found exactly that failure mode.
   - The `pypi` environment has `required_reviewers` and a `tag` deployment policy limited to `v*`: `gh api repos/briandconnelly/amicus/environments/pypi` and `gh api repos/briandconnelly/amicus/environments/pypi/deployment-branch-policies`. The policy must be typed `tag`, not `branch`; a branch policy blocks every release and the environments endpoint alone does not distinguish them.
   - A PyPI trusted publisher is registered for `briandconnelly/amicus`, `publish.yml`, environment `pypi`.
   - Trademark clearance for the name `amicus` is resolved, or the maintainer has decided to proceed without it. TestPyPI is already claimed; pypi.org is not.
3. **The release sequence.**
   - Merge PR B.
   - Open and merge PR C: roll `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`, leave a fresh empty `## [Unreleased]`, and change no version literal unless the version itself is changing. For 0.1.0 no literal moves: `pyproject.toml`, `src/amicus/__init__.py`, both `plugin.json` files and `.mcp.json`'s `@v0.1.0` already agree, and the tag is what makes that pin resolve.
   - Check out the merged commit into a clean tree and confirm `git status --porcelain` is empty.
   - Run `uv run python scripts/record_live_gate_evidence.py`. This spends real quota on all three backends and requires the maintainer's authorization in the session where it runs.
   - Run `AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py -v --no-cov` and confirm the freshness assertion passes.
   - Run the full gate.
   - Tag that unchanged commit and push the tag.
4. **What happens next, so a pause is not mistaken for a hang.** The `build` job runs, then the `pypi` job waits for the `pypi` environment's required reviewer. Approve it deliberately. The upload is irreversible and PyPI does not allow re-uploading a version.
5. **Post-tag completion checks, labeled as release completion rather than as a pre-tag gate.**
   - `curl -s https://pypi.org/pypi/amicus/json | head -c 200` returns the release rather than a 404.
   - Install from the public tag exactly as a user would, using the committed manifest's own source: `uvx --from git+https://github.com/briandconnelly/amicus.git@vX.Y.Z amicus-mcp`, driven with one JSON-RPC `initialize` over stdin, asserting `serverInfo.name == "amicus"` and the expected version. This is the first and only check that the `.mcp.json` pin actually resolves; it cannot be run before the tag exists.
   - A negative control: the same command against a version that does not exist must fail.
6. **A rollback note.** A published PyPI version cannot be withdrawn, only yanked. A pushed tag can be deleted, but the protection ruleset deliberately prevents that, and deleting a tag users may already have installed from is itself a break. The remedy for a bad release is a new patch release.

- [ ] **Step 2: Run every read-only command in the runbook**

Execute each `gh api` and `curl` command in step 2 and step 5 of the document as written, and record the real output in the task's commit body. Where a precondition is not yet satisfied — the tag ruleset may not exist yet — say so plainly in the commit body and leave the runbook step in place; it is a maintainer action, not a defect in the document.

This step exists because every defect in the publish-workflow plan was found by running something rather than by reading it, and twice a plan's own verification list passed while a real defect was live.

- [ ] **Step 3: Add the runbook to the README index**

Add a row to the README's "Where things are" table pointing at `docs/RELEASING.md`. Read the surrounding rows first and match their wording; the publish-workflow follow-ups PR found that a row for the publish workflow already existed and blind addition would have duplicated it.

- [ ] **Step 4: Run the gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`
Expected: green, coverage at or above the current floor.

- [ ] **Step 5: Commit**

```bash
git add docs/RELEASING.md README.md
git commit -m "docs(release): add the release runbook and index it"
```

---

### Task 4: Verify the sibling differentials have not drifted

**Files:**
- Read only: `~/projects/codex-in-claude`, `~/projects/moonbridge`, `~/projects/claude-in-codex`
- Modify: `docs/adr/` — a new ADR only if a difference is found

**Interfaces:**
- Consumes: `tests/fixtures/{codex,kimi,claude}_differentials.json`, each of which records the `sibling_commit` it was captured from.
- Produces: a recorded no-drift result, or a disposition for each difference.

**Known state at plan time, which the first step re-checks rather than assumes:** every fixture's `sibling_commit` equals its sibling's current HEAD — `fcd2674` for codex-in-claude, `f6df12d` for moonbridge, `93dddc3` for claude-in-codex. If that still holds, this task is a verification, not a re-capture.

- [ ] **Step 1: Compare recorded capture commits against the siblings' current HEADs**

```bash
cd ~/projects/amicus-wt-m7
for f in codex kimi claude; do
  printf '%s fixture: ' "$f"
  python3 -c "import json;print(json.load(open('tests/fixtures/${f}_differentials.json'))['sibling_commit'])"
done
for d in codex-in-claude moonbridge claude-in-codex; do
  printf '%s HEAD: ' "$d"
  git -C ~/projects/"$d" log -1 --format=%h
done
```

Expected if nothing has drifted: `fcd2674`/`fcd2674`, `f6df12d`/`f6df12d`, `93dddc3`/`93dddc3`.

- [ ] **Step 2: Run the differential suite and confirm it is green**

Run: `uv run pytest tests/test_codex_result_differential.py tests/test_kimi_result_differential.py tests/test_claude_result_differential.py tests/test_codex_argv_differential.py tests/test_kimi_argv_differential.py tests/test_claude_argv_differential.py -q --no-cov`
Expected: 93 passed.

- [ ] **Step 3: Prove the suite can fail**

A green differential suite against unchanged fixtures proves nothing on its own. Perturb one committed fixture — change a single argv token in `tests/fixtures/codex_differentials.json` — re-run the suite, and confirm it FAILS naming that case. Restore the fixture with `git checkout --` and confirm green again. Record both outcomes.

- [ ] **Step 4: If and only if a sibling has moved, re-capture into a scratch path and dispose of each difference**

Do not write into `tests/fixtures/` in this step. Capture to the scratch directory, diff against the committed fixture, and for every difference record one of three dispositions with a reason: **adopt** (a sibling fix amicus should take), **document** (an intentional divergence), or **regression** (an amicus defect). Adoption that changes behavior is not a fixture edit — it is a code change, and if it touches any category in `FINGERPRINT_COVERS` it requires a `FINGERPRINT` bump with regenerated pins in its own commit per rule 10, and a `RESULT_FORMAT` bump per rule 11 if a stored result's shape changes. Stop and ask the maintainer before adopting anything; that is a milestone-scope decision, not an implementer's call.

- [ ] **Step 5: Record the outcome**

Write the result — including the no-drift case — into the PR description at Task 10, naming the three commit pairs compared and the perturbation control that was run.

- [ ] **Step 6: Commit only if something changed**

If nothing drifted, there is nothing to commit for this task; say so explicitly in the PR description rather than manufacturing a commit.

---

### Task 5: Correct the S6-F1 fixture-id claim

**Files:**
- Modify: `skills/collaborating-with-amicus/tests/scenarios.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a truthful "Used by" column for `S6-F1`.

**The defect.** The prompt-id table says `S6-F1` is used by "S6, all runs", while the notes below it admit the hash is computed from "the abbreviated rendering that was committed" and that run 4's fixture bytes "were never committed". `docs/host-captures/s6-old-text-new-grader/claude-code/2.1.263/transcript.md:61` says the same thing from the other side: it used the committed rendering because run 4's bytes could not be reproduced. One id is therefore claimed to pin two different bodies.

- [ ] **Step 1: Establish what each run actually used**

Read `skills/collaborating-with-amicus/tests/scenarios.md` (the prompt-id table, the S6 section, and every S6 row of the run log), `docs/host-captures/s6-old-text-new-grader/claude-code/2.1.263/transcript.md`, `docs/host-captures/s6-response-contract/claude-code/2.1.263/transcript.md`, and `docs/host-captures/free-scenarios/claude-code/2.1.263/transcript.md`. Write down, per run, which body it used and whether those bytes were ever committed.

- [ ] **Step 2: Correct the claim, not the hash**

Change the `Used by` cell so it names only the runs the hash actually pins, and state plainly that the earlier runs' fixture bytes were never committed and are unrecoverable. Do not change the `sha256` value: it correctly pins the committed rendering, and changing a hash to make a claim true is the inverse of the fix. Do not add prompt text — rule 18 keeps it out of the repository, and the ids-and-hashes scheme exists precisely so this correction needs no bodies.

If the evidence in Step 1 shows the claim was already accurate, change nothing and record that finding instead. A carryover item that turns out to be a non-issue is closed by evidence, not by an edit.

- [ ] **Step 3: State plainly what does and does not check this**

No test reads `scenarios.md`. Confirm that rather than assuming it:

```bash
grep -rln "scenarios.md" tests/ || echo "no test reads scenarios.md"
```

Expected: `no test reads scenarios.md`.

So this correction rests entirely on the document review in Step 1, and the suite cannot catch a mistake in it.
Run `uv run pytest -q --no-cov` to confirm nothing else regressed, and record in the PR description that this task has no automated coverage.
Recomputing the hashes is not available as a check either: the prompt bodies were removed from the repository under rule 18, which is the deliberate cost recorded in ADR 0012.

- [ ] **Step 4: Commit**

```bash
git add skills/collaborating-with-amicus/tests/scenarios.md
git commit -m "docs(skills): say which S6 runs the committed S6-F1 hash actually pins"
```

---

### Task 6: Close the empty-label hole in the review-artifact test

**Files:**
- Modify: `tests/test_review_artifact.py:119-125`

**Interfaces:**
- Consumes: nothing.
- Produces: a `test_every_finding_carries_all_five_labeled_lines` that fails on empty values.

**The defect.** The test checks that each of the five field labels appears in a finding, and nothing more. A finding whose five labels all carry empty values passes. This is the fifth instance of a bug class in this file; four others were found and closed during M6, and the file's own docstrings record how each was proven by mutation.

- [ ] **Step 1: Prove the hole exists**

Write a temporary test, or a scratch snippet, that runs the existing assertion body against a synthetic finding whose five labels are present with empty values, and confirm it PASSES. That is the known positive: without it, "the test now fails on empty values" is a claim rather than a result.

- [ ] **Step 2: Tighten the assertion**

Require each label to be followed by a non-empty value on its own line. Match the file's existing style — the surrounding tests use `re.findall` over `TEXT` and carry a docstring explaining what mutation proved the old form inadequate. Write that docstring; it is the file's established convention and the reason the previous four holes stayed closed.

- [ ] **Step 3: Run it against the real artifact**

Run: `uv run pytest tests/test_review_artifact.py -v --no-cov`
Expected: PASS against the committed walk. If it now FAILS, the walk genuinely has an empty label — fix the walk, do not loosen the test, and record which finding was empty.

- [ ] **Step 4: Prove the tightened test can fail**

Blank one label's value in a scratch copy of the walk, run the test against it, confirm FAIL, and restore. Record the outcome.

- [ ] **Step 5: Commit**

```bash
git add tests/test_review_artifact.py
git commit -m "test(skills): fail the review-artifact check on empty finding labels"
```

---

### Task 7: Correct the design spec's gate rows

**Files:**
- Modify: `docs/superpowers/specs/2026-09-04-amicus-design.md` — the Milestones table, M6 and M7 rows

**Interfaces:**
- Consumes: the outcomes recorded in ADR 0012 and in `docs/host-captures/`.
- Produces: a Milestones table that describes what was actually discharged.

**The three corrections:**

1. The M6 row reads "FakePlugin as a wheel". After Copilot's C6 correction that is only half true: a third-party wheel loads via the entry point, but `config._profile` rejects any `AMICUS_BACKENDS` token outside `BACKEND_IDS` and `BackendParam` is `Literal["codex","kimi","claude"]`, so such a plugin can be neither enabled nor called. Say what was proven and what was not.
2. The M6 row reads "install smoke from both manifests". The Codex host was driven through a scoped `CODEX_HOME/config.toml`, so Codex's own plugin loader was never exercised. Say so.
3. The M7 row reads "all three live gates green and enforced". Enforcement is a local pre-tag gate, not a CI job: GitHub-hosted runners have no authenticated `codex`, `kimi` or `claude`, and running them per release would spend quota on every release. Replace the wording with what M7 actually builds, and reference `docs/RELEASING.md`.

- [ ] **Step 1: Verify each claim before rewriting it**

For correction 1, read `src/amicus/config/` and `src/amicus/schemas/` and confirm the `BACKEND_IDS` and `BackendParam` constraints still read as described. For correction 2, read the Codex host capture under `docs/host-captures/install-smoke/codex/` and confirm the scoped `CODEX_HOME`. Do not restate a prior session's finding without re-checking it; the spec is the requirements document and a wrong correction is worse than the original.

- [ ] **Step 2: Rewrite the three rows**

Keep the table's existing column structure and one-sentence-per-line style elsewhere in the document. Do not restate rule 2's gate definition; AGENTS.md is its single definition and other documents link there.

- [ ] **Step 3: Confirm nothing asserts the old wording**

Run: `uv run pytest -q --no-cov`
Expected: green. If a test asserted the old row text, that test is now the thing to update, and it must be updated deliberately rather than by loosening its assertion.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-04-amicus-design.md
git commit -m "docs: correct the M6 and M7 gate rows to what was actually discharged"
```

---

### Task 8: S6 and S7 eval runs

**Files:**
- Modify: `skills/collaborating-with-amicus/tests/scenarios.md` — the S6 and S7 `status` fields and run log
- Create: `docs/host-captures/<capture-name>/<host>/<version>/transcript.md`

**Interfaces:**
- Consumes: the prompt ids and hashes already in `scenarios.md`.
- Produces: run-log rows and a capture per run.

**Budget and authority.** At most **eight** paid backend calls across this whole task. Ask the maintainer before each run. A scenario that still fails is recorded as a failure with its evidence and does **not** block the release; do not spend beyond the cap chasing a pass, and do not weaken a grader to obtain one.

**Spend the budget one variable at a time.** S6's recorded pass changed the grader and the skill's response contract together, and the follow-up comparison run differed in three inputs at once, so F3 is not isolated. The first runs here must change exactly one thing against a recorded baseline.

- [ ] **Step 1: Write the run brief before spending anything**

For each planned run, write down in advance: the scenario, the prompt id and hash, the `AMICUS_BACKENDS` value, the host and version, the exact single variable that differs from the baseline run it is compared against, and what outcome would count as isolating F3. A run whose interpretation is decided afterwards is not an experiment.

- [ ] **Step 2: Ask the maintainer, then run S6's isolation runs**

Report the brief, get explicit approval, run, and capture. Record the prompt id and `sha256` — never the prompt text (rule 18).

- [ ] **Step 3: Grade mechanically against the recorded contract**

Grade over the `RESPONSE` section alone, per the Grading scope section of `scenarios.md`. Do not regrade earlier rows; the M6 maintainer ruling on retroactive regrading stands.

- [ ] **Step 4: Ask, then run S7 if budget remains**

S7's remedy is untested and it failed on both hosts. If fewer than two calls remain, stop and record that the budget was exhausted before S7 — an unrun scenario recorded as unrun is a better outcome than a rushed one.

- [ ] **Step 5: Update the status fields honestly**

A `status` other than `unrun` with no matching run-log row is invalid by the document's own rule. If S6 or S7 still fails, say so in the `status` field and name what remains unisolated.

- [ ] **Step 6: Commit**

```bash
git add skills/collaborating-with-amicus/tests/scenarios.md docs/host-captures/
git commit -m "test(skills): record the S6 isolation runs and their outcome"
```

---

### Task 9: The sibling deprecation checklist

**Files:**
- Create: `docs/DEPRECATING-SIBLINGS.md`
- Modify: `README.md` (the "Where things are" table)

**Interfaces:**
- Consumes: nothing.
- Produces: a maintainer hand-off document. No agent executes it.

- [ ] **Step 1: Write the checklist**

One sentence per line. It covers `codex-in-claude`, `moonbridge` and `claude-in-codex`, and for each names: the deprecation notice in the README, the PyPI classifier or yank decision, the plugin-marketplace listing, any pinned references from other repositories, and where users are pointed instead. Open with a line stating that these steps are executed by the maintainer in those repositories, because AGENTS.md rule 17 forbids an agent from editing a sibling checkout.

State the ordering constraint plainly: nothing in this checklist should run before amicus is actually published to pypi.org, because the checklist points users at a package that must exist.

- [ ] **Step 2: Verify each per-sibling fact by reading the sibling**

Read each sibling's README and `pyproject.toml` to confirm the package names, the marketplace listing and the current install instructions before writing them down. Read only — never edit.

- [ ] **Step 3: Index it in the README**

Add a row to the "Where things are" table, matching the surrounding rows' wording.

- [ ] **Step 4: Commit**

```bash
git add docs/DEPRECATING-SIBLINGS.md README.md
git commit -m "docs: add the sibling deprecation checklist for the maintainer"
```

---

### Task 10: Milestone close-out

**Files:**
- Modify: none, unless the gate finds something.

- [ ] **Step 1: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`
Expected: green, and never below the `fail_under` floor of 95. Record the actual coverage number in the PR description rather than asserting it matches a figure from an earlier milestone.

- [ ] **Step 2: Run the perturbation check the spec requires**

The spec's "Verification (all milestones)" section requires that a clean gate be distrusted until the surface is perturbed and the gate is confirmed to fail. Perturb one thing this milestone actually added — blank a required field in a synthetic evidence record and confirm `validate` rejects it, and separately confirm the `AMICUS_RELEASE_CHECK` assertion fails with no evidence file present. Record both.

- [ ] **Step 3: Confirm the release lockstep is machine-checked**

The M7 gate row's third clause is "release lockstep CI", and it is already discharged by existing tests rather than by new work in this plan.
Confirm that rather than asserting it:

Run: `uv run pytest tests/test_packaging.py -v --no-cov -k version`
Expected: the tests asserting that `pyproject.toml`, `src/amicus/__init__.py`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` and `.mcp.json`'s tag pin all agree are selected and pass.

Then prove they can fail: change the version in `.claude-plugin/plugin.json` to `0.1.1`, re-run, confirm FAILURE naming that file, and restore.
A lockstep check that has never been seen to fail is not evidence that the literals are pinned together.

- [ ] **Step 4: Confirm no forbidden file was touched**

Run: `git diff --stat main...HEAD -- .github AGENTS.md CLAUDE.md`
Expected: empty output. Any change here belongs in PR A and must be moved out of this branch.

- [ ] **Step 5: Confirm no tag was created and nothing was published**

Run: `git tag -l` and `git ls-remote --tags origin`
Expected: no `v*` tag. This milestone does not tag.

- [ ] **Step 6: Open the draft PR**

```bash
gh pr create --draft --base main \
  --title "feat(release): prepare amicus 0.1.0 for release" \
  --body-file /tmp/m7-pr-body.md
```

The body must record: the gate result and coverage; the perturbation check outcomes; the Task 4 drift result including the commit pairs compared; the S6/S7 outcomes and how much of the eight-call budget was spent; and, verbatim, the "What this milestone deliberately does not prove" section from the top of this plan.

- [ ] **Step 7: Stop**

Do not merge. Do not approve. Do not tag. AGENTS.md rule 8 reserves all three to the maintainer, and the release sequence in `docs/RELEASING.md` begins only after the maintainer merges this PR and then PR C.

---

## After this PR — not part of it

PR C (`chore(release): release 0.1.0`) and the tag sequence are documented in `docs/RELEASING.md` and executed by the maintainer.
The three authorized live-gate runs happen there, on the merged commit that will be tagged, not on this branch.
