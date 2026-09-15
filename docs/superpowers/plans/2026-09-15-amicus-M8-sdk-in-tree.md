# amicus M8 Implementation Plan: the backend SDK moves in-tree

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Copy pontonier v0.9.0 into amicus as `amicus.sdk`, switch every amicus import to it, and drop the `pontonier==0.9.0` dependency without changing anything on the wire or in a stored job record.

**Architecture:** The move is mechanical and lands first, beside the still-installed pontonier, so every commit stays green.
amicus then switches its own imports, drops the dependency, and gains the import contracts, logging change, plugin API bump and prose sweep the spec names, each as its own task.
A provenance check rebuilds the move commit from pontonier's tag and must produce an empty diff, so review never has to read the 8,144 moved lines.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `prek`, `perl` (for the rewrite, because macOS `sed -E` has no `\b`).
Runtime after M8: `anyio>=4`, `fastmcp>=4.0,<4.1`, `mcp>=2.1,<2.3`, `pydantic>=2`.

**Spec:** `docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md` (read it before Task 0; it is the source of every requirement here, and its section numbers are cited as "spec §N").
Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`; binding repo rules: `AGENTS.md`.

## Global Constraints

- Repo `/Users/bdc/projects/amicus`; work in the worktree `/Users/bdc/projects/amicus-wt-m8` on branch `feat/m8-sdk-in-tree`.
  The branch has no upstream on purpose; Task 10 pushes it with `-u`.
  Never commit to `main`.
- Baseline at `65c525b` (the spec's last commit): 1,514 passed, 1 skipped, 18 deselected; coverage 96.98%; 237 files formatted; `Contracts: 3 kept, 0 broken`; `FINGERPRINT = "amicus/0.1/schema-30"`; `RESULT_FORMAT = 6`.
- Gate (AGENTS.md rule 2), run from the worktree:
  ```sh
  uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest
  ```
  The coverage floor (`fail_under = 95`) is never lowered (rule 4).
- `FINGERPRINT` and `RESULT_FORMAT` must not move (spec §2).
  If any test that pins a fixture under `tests/fixtures/` fails, STOP and report it: the spec's claim is wrong, and regenerating a pin is not an M8 action.
- The pontonier checkout `/Users/bdc/projects/pontonier` is read-only (rule 17).
  Use only `git -C /Users/bdc/projects/pontonier rev-parse`, `ls-tree` and `show`; never check out, edit or run anything there.
  Read the tag, never its working tree, which has unrelated uncommitted edits.
- `scripts/` is untouched: `scripts/capture_codex_differentials.py` and `scripts/capture_kimi_differentials.py` keep importing pontonier (spec change 5).
- Off limits (rule 9): `.github/**`, `AGENTS.md`, `CLAUDE.md`.
- Rule 18: never write a prompt input to disk, to argv or to a log.
  Task 10's Codex brief is composed at call time and is never saved, committed or pasted into the PR body.
- Rules 5 and 6: never run `-m integration`; never touch the guard in `tests/conftest.py`.
- Spend: Task 10 makes one paid Codex review, and only after the maintainer authorizes it in the current session.
  No other task spends.
- Commits: Conventional Commits with an imperative lowercase subject and no trailing period, types and scopes from `scripts/check_commit_message.py`.
  The `sdk` scope exists from Task 0 onward and may not be used before it.
  End every commit message body with the line `🤖 Generated with Claude Code`.
  The commit-msg hook enforces the format.
- Markdown under `docs/`: one sentence per line (rule 16).
  Save this checker once as `$SCRATCH/check16.py`, and run `uv run python "$SCRATCH/check16.py" <paths>` on every file a task creates under `docs/` before committing it:
  ```python
  import re, sys, pathlib
  bad = []
  for path in sys.argv[1:]:
      fence = False
      for n, line in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
          if line.lstrip().startswith('```'): fence = not fence; continue
          if fence or line.lstrip().startswith(('|', '#', '>')): continue
          if re.search(r'(?<![A-Z0-9])\. [A-Z]', line): bad.append(f'{path}:{n}')
  print('rule 16 violations:', bad or 'none')
  assert not bad
  ```
- Tooling traps in this repo:
  - `git diff` runs difftastic; pass `--no-ext-diff` whenever you read or pipe a diff.
  - Any `pytest` run on a subset of tests needs `--no-cov`, because `fail_under` applies to every run that measures coverage.
  - Commit before a mutation control, then undo the mutation with `git checkout -- <file>`; doing it the other way round destroys uncommitted work.
  - A PostToolUse hook runs ruff's fixer on every edited Python file and deletes an import that has no usage yet, so add the usage before the import.
- `$SCRATCH` below means a directory outside both repositories that you may write to, such as your session scratchpad.

## Decisions

The spec's decisions 1 to 6 and changes 1 to 6 are settled and are not reopened here.
These are the plan's own rulings on how to carry them out:

1. **The move script and the provenance check live in this plan and the PR body, not in the repo.**
   Both run once, and CI has no pontonier checkout to run them against.
2. **M8's structural guards live in one new test module, `tests/test_sdk_in_tree.py`.**
   It proves four things: nothing under `src/` or `tests/` imports pontonier, pontonier is not installed, the SDK root names its origin and carries no version lookup, and `src/` names pontonier only as provenance or one of the four kept defaults.
   Every scan in it has a planted-positive control, so an empty result cannot come from a broken scan.
3. **The SDK contract's forbidden list is written out, and a test keeps it equal to the set of top-level modules.**
   import-linter cannot express "everything except `amicus.sdk`", and a hand list would go stale the day a module is added.
4. **Task order keeps every commit green.**
   The copy coexists with the installed pontonier (Task 1), amicus switches its imports (Task 2), and only then does the dependency go (Task 3).
5. **The Codex review in Task 10 covers only the diff after the move commit.**
   The provenance check covers the move itself, and a squash that included it would be about 21,000 added lines, past the review's 200,000-byte input cap.
6. **The follow-up issues are filed (Task 8) before the docs are written (Task 9),** so ADR 0029 can cite their numbers.

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `src/amicus/sdk/**` (26 files) | pontonier v0.9.0's `core`, `backend`, `conventions` and `testing` layers, file names kept. |
| `tests/sdk/**` (29 test modules, `conftest.py`, empty `__init__.py`) | pontonier's own suite, minus `tests/test_version.py`. |
| `tests/test_sdk_in_tree.py` | M8's structural guards (Decision 2). |
| `docs/adr/0029-the-backend-sdk-lives-in-tree.md` | The recorded decision; closes #13. |

**Modified:**

| Path | Change |
| --- | --- |
| `scripts/check_commit_message.py`, `tests/test_check_commit_message.py` | `sdk` scope (Task 0). |
| About 88 files under `src/amicus/` and `tests/` outside the SDK, including `tests/fixtures/fakebackend/src/fakebackend/__init__.py` | Imports switch from `pontonier.*` to `amicus.sdk.*` (Task 2). |
| `pyproject.toml`, `uv.lock`, `src/amicus/sdk/__init__.py`, `tests/test_packaging.py` | Dependency dropped, version lookup removed (Task 3). |
| `pyproject.toml`, `tests/test_import_contracts.py` | Two import contracts (Task 4). |
| `src/amicus/obs.py`, `tests/test_obs.py`, `tests/test_log_redaction.py`, `tests/test_fastmcp_argument_log.py` | The separate `pontonier` logger goes (Task 5). |
| `src/amicus/plugin.py`, `tests/test_plugin.py` | `PLUGIN_API_VERSION = 2` (Task 6). |
| About 25 files under `src/amicus/` | Prose sweep R5 (Task 7). |
| `docs/adr/0023-…`, `docs/superpowers/specs/2026-09-04-amicus-design.md`, `docs/MIGRATION.md`, `docs/DEPRECATING-SIBLINGS.md`, `README.md`, `CHANGELOG.md` | Docs (Task 9). |

---

### Task 0: Allow the `sdk` commit scope

**Files:**
- Modify: `scripts/check_commit_message.py` (`ALLOWED_SCOPES`, after `"backends",`)
- Test: `tests/test_check_commit_message.py`

**Interfaces:**
- Produces: the commit scope `sdk`, used by every later task.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_check_commit_message.py`:

```python
def test_sdk_scope_is_allowed():
    from scripts.check_commit_message import ALLOWED_SCOPES

    assert "sdk" in ALLOWED_SCOPES
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_check_commit_message.py::test_sdk_scope_is_allowed -v --no-cov`
Expected: FAIL with `AssertionError` on `"sdk" in ALLOWED_SCOPES`.

- [ ] **Step 3: Add the scope**

In `scripts/check_commit_message.py`, change

```python
    "backends",
    "packaging",
```

to

```python
    "backends",
    "sdk",
    "packaging",
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_check_commit_message.py -v --no-cov`
Expected: every test PASSES.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_commit_message.py tests/test_check_commit_message.py
git commit -F - <<'EOF'
chore: allow the sdk commit scope

M8 moves pontonier's code into amicus.sdk; AGENTS.md rule 13 adds the
scope in the same change that first needs it.

🤖 Generated with Claude Code
EOF
```

---

### Task 1: Copy pontonier v0.9.0 into `amicus.sdk` (the mechanical move)

**Files:**
- Create: `src/amicus/sdk/**` (26 files), `tests/sdk/**` (29 test modules, `conftest.py`, `__init__.py`)

**Interfaces:**
- Consumes: the `sdk` scope (Task 0).
- Produces: the package `amicus.sdk` with pontonier 0.9.0's public names at `amicus.sdk.<layer>.<module>`, for example `amicus.sdk.core.runtime.CommandRun`, `amicus.sdk.core.jobs.JobStore`, `amicus.sdk.backend.protocol.AgentBackend`, `amicus.sdk.backend.contract.BackendContract`, `amicus.sdk.conventions.envelope.REPAIR_STEPS` and `amicus.sdk.testing.conformance.check_contract`.
  Also produces `$MOVE`, the move commit's SHA, which Task 10 uses.
  At the end of this task pontonier is still installed and amicus still imports it; nothing outside the new directories changes.

- [ ] **Step 1: Save the move script**

Save as `$SCRATCH/m8-move.sh`:

```bash
#!/usr/bin/env bash
# M8 mechanical move: pontonier v0.9.0 -> amicus.sdk, with rewrites R1-R3 only (spec §1).
# usage: m8-move.sh <pontonier-checkout> <amicus-root> <ruff-executable>
set -euo pipefail
P=$1 R=$2 RUFF=$3
TAG=v0.9.0
test "$(git -C "$P" rev-parse "$TAG^{commit}")" = 185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d
# R1: imports and dotted references.
R1='s/\bpontonier\.(core|backend|conventions|testing)\b/amicus.sdk.$1/g; s/\bfrom pontonier import\b/from amicus.sdk import/g; s/^import pontonier$/import amicus.sdk/'
# R2: the moved tests' bare-name helper imports.
R2='s/^from conftest import/from tests.sdk.conftest import/; s/^from (test_\w+) import/from tests.sdk.$1 import/; s/^from tests\.(test_\w+) import/from tests.sdk.$1 import/'
git -C "$P" ls-tree -r --name-only "$TAG" -- src/pontonier | while IFS= read -r f; do
  d="$R/src/amicus/sdk/${f#src/pontonier/}"
  mkdir -p "$(dirname "$d")"
  git -C "$P" show "$TAG:$f" | perl -pe "$R1" > "$d"
done
git -C "$P" ls-tree -r --name-only "$TAG" -- tests | while IFS= read -r f; do
  if [ "$f" = tests/test_version.py ]; then continue; fi
  d="$R/tests/sdk/${f#tests/}"
  mkdir -p "$(dirname "$d")"
  git -C "$P" show "$TAG:$f" | perl -pe "$R1" | perl -pe "$R2" > "$d"
done
: > "$R/tests/sdk/__init__.py"
# R3: re-sort the rewritten imports, nothing else.
cd "$R" && "$RUFF" check --fix --select I001 --quiet src/amicus/sdk tests/sdk
```

- [ ] **Step 2: Run it**

```bash
cd /Users/bdc/projects/amicus-wt-m8
bash "$SCRATCH/m8-move.sh" /Users/bdc/projects/pontonier "$PWD" "$PWD/.venv/bin/ruff"
find src/amicus/sdk -name '*.py' | wc -l      # expect 26
ls tests/sdk/test_*.py | wc -l                # expect 29
ls tests/sdk/conftest.py tests/sdk/__init__.py
grep -rn -E '^\s*(from|import) pontonier' src/amicus/sdk tests/sdk   # expect no output
```

Expected: the tag assertion passes silently, the counts are 26 and 29, both files exist, and the grep prints nothing.

- [ ] **Step 3: Run the moved tests**

Run: `uv run pytest tests/sdk -q --no-cov -p no:cacheprovider`
Expected: `1483 passed`.
If a module fails to collect with `cannot import name ... from 'conftest'`, R2 missed a helper import; fix the script's R2 pattern, delete `src/amicus/sdk` and `tests/sdk`, and rerun Step 2, never hand-edit a moved file.

- [ ] **Step 4: Run the full gate**

Run the gate from Global Constraints.
Expected: all green, `Contracts: 3 kept, 0 broken`, coverage ≥95%, and about 2,998 passed (the baseline plus Task 0's test plus 1,483).

- [ ] **Step 5: Commit the move, alone**

```bash
git add src/amicus/sdk tests/sdk
git commit -F - <<'EOF'
refactor(sdk): copy pontonier v0.9.0 into amicus.sdk

A mechanical copy of pontonier's v0.9.0 tag (commit
185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d): src/pontonier -> src/amicus/sdk
and tests -> tests/sdk, file names kept, tests/test_version.py left out.
The only edits are the import rewrite (R1), the test-helper import
rewrite (R2) and ruff's import sort (R3). pontonier stays installed and
amicus's own imports are unchanged until the next commit.

🤖 Generated with Claude Code
EOF
MOVE=$(git rev-parse HEAD); echo "MOVE=$MOVE" | tee "$SCRATCH/m8-move-sha.txt"
```

- [ ] **Step 6: Run the provenance check, with its control**

```bash
cd /Users/bdc/projects/amicus-wt-m8
MOVE=$(git rev-parse HEAD)
git worktree add --detach "$SCRATCH/prov" "$MOVE^"
bash "$SCRATCH/m8-move.sh" /Users/bdc/projects/pontonier "$SCRATCH/prov" "$PWD/.venv/bin/ruff"
git -C "$SCRATCH/prov" add -A src/amicus/sdk tests/sdk
git -C "$SCRATCH/prov" diff --no-ext-diff --cached --stat "$MOVE" -- src/amicus/sdk tests/sdk | tee "$SCRATCH/m8-provenance.txt"
echo "(empty above = the move commit is exactly the script's output)"
# Control: the same comparison must see a one-line drift.
echo '# drift' >> "$SCRATCH/prov/src/amicus/sdk/core/jsoncache.py"
git -C "$SCRATCH/prov" add -A src/amicus/sdk
git -C "$SCRATCH/prov" diff --no-ext-diff --cached --stat "$MOVE" -- src/amicus/sdk tests/sdk
git worktree remove --force "$SCRATCH/prov"
```

Expected: the first diff prints nothing and `$SCRATCH/m8-provenance.txt` is empty; the control prints `1 file changed, 1 insertion(+)` for `jsoncache.py`.
If the first diff is not empty, STOP: the move commit contains something the script did not produce.
Keep `$SCRATCH/m8-provenance.txt` and the control's output for the PR body (Task 10).

---

### Task 2: Switch amicus's own imports to `amicus.sdk`

**Files:**
- Create: `tests/test_sdk_in_tree.py`
- Modify: every file under `src/` and `tests/` outside `src/amicus/sdk` and `tests/sdk` that names `pontonier.<layer>` or `from pontonier import` (about 88 files, including `tests/fixtures/fakebackend/src/fakebackend/__init__.py`); nothing under `scripts/`

**Interfaces:**
- Consumes: `amicus.sdk` (Task 1).
- Produces: `tests/test_sdk_in_tree.py` with `ROOT: Path` and `_pontonier_imports(root: Path) -> list[str]`, which Tasks 3 and 7 extend.

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_sdk_in_tree.py`:

```python
"""M8's structural guards: pontonier's code lives in amicus.sdk, and nothing reaches the old
package. Each scan has a planted-positive control, so an empty result is evidence rather than
a broken scan."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# scripts/ is exempt: the differential capture scripts run inside a sibling's virtualenv and
# feed that sibling's own pontonier objects (M8 spec, change 5).
SCANNED = ("src", "tests")


def _pontonier_imports(root: Path) -> list[str]:
    hits: list[str] = []
    for base in SCANNED:
        for path in sorted((root / base).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                if any(n == "pontonier" or n.startswith("pontonier.") for n in names):
                    hits.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    return sorted(hits)


def test_nothing_under_src_or_tests_imports_pontonier():
    assert _pontonier_imports(ROOT) == []


def test_the_import_scan_detects_a_planted_import(tmp_path):
    planted = tmp_path / "src" / "planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("from pontonier.core import runtime\nimport pontonier\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    assert _pontonier_imports(tmp_path) == ["src/planted.py:1", "src/planted.py:2"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_sdk_in_tree.py -v --no-cov`
Expected: `test_nothing_under_src_or_tests_imports_pontonier` FAILS, listing file:line entries across about 88 files; the control PASSES.

- [ ] **Step 3: Rewrite the imports**

```bash
cd /Users/bdc/projects/amicus-wt-m8
R1='s/\bpontonier\.(core|backend|conventions|testing)\b/amicus.sdk.$1/g; s/\bfrom pontonier import\b/from amicus.sdk import/g; s/^import pontonier$/import amicus.sdk/'
git grep -l -E 'pontonier\.(core|backend|conventions|testing)|from pontonier import|^import pontonier$' \
  -- src tests ':!src/amicus/sdk' ':!tests/sdk' ':!tests/test_sdk_in_tree.py' \
  | tee "$SCRATCH/m8-switched.txt" | xargs perl -pi -e "$R1"
wc -l < "$SCRATCH/m8-switched.txt"     # about 88
uv run ruff check --fix --select I001 --quiet src tests
```

R1 also rewrites dotted references inside docstrings, comments and string literals, such as the planted source in `tests/test_log_redaction.py`'s scan control; that is intended, because the scan it controls is rewritten the same way.
`tests/test_sdk_in_tree.py` is excluded, because rewriting its planted import would turn its control into a no-op.

- [ ] **Step 4: Run the guard and the gate**

Run: `uv run pytest tests/test_sdk_in_tree.py -v --no-cov`
Expected: both tests PASS.
Then run the full gate.
Expected: all green; pontonier is still installed, but nothing imports it.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -F - <<'EOF'
refactor(sdk): import the sdk from amicus.sdk instead of pontonier

Rewrites every pontonier import under src/ and tests/ (the fakebackend
wheel fixture included) to amicus.sdk, and adds the guard that keeps it
so. scripts/ keeps its pontonier imports: the capture scripts run inside
a sibling's virtualenv.

🤖 Generated with Claude Code
EOF
```

- [ ] **Step 6: Mutation control (after the commit)**

```bash
echo 'import pontonier  # mutation' >> src/amicus/errors.py
uv run pytest tests/test_sdk_in_tree.py::test_nothing_under_src_or_tests_imports_pontonier -q --no-cov   # expect FAIL naming src/amicus/errors.py
git checkout -- src/amicus/errors.py
```

---

### Task 3: Drop the pontonier dependency and the SDK's version lookup

**Files:**
- Modify: `pyproject.toml:25`, `uv.lock`, `src/amicus/sdk/__init__.py`, `tests/test_packaging.py:56-61`
- Test: `tests/test_sdk_in_tree.py`

**Interfaces:**
- Consumes: `tests/test_sdk_in_tree.py` (Task 2).
- Produces: an environment in which `importlib.util.find_spec("pontonier") is None`, and an `amicus.sdk` with a docstring naming commit `185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d` and no `__version__`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_packaging.py`, replace

```python
    assert names == ["anyio", "fastmcp", "mcp", "pontonier", "pydantic"]
    assert "pontonier==0.9.0" in deps
```

with

```python
    assert names == ["anyio", "fastmcp", "mcp", "pydantic"]
```

Append to `tests/test_sdk_in_tree.py` (the function bodies first, then add `import importlib.util` and `import amicus.sdk` to the imports at the top, so the formatter hook does not strip them):

```python
def test_pontonier_is_not_installed():
    """amicus runs without the pontonier distribution: nothing requires it any more, and
    `uv sync` removes what nothing requires."""
    assert importlib.util.find_spec("pontonier") is None


def test_the_sdk_root_names_its_origin_and_has_no_version_lookup():
    """R4: the package root cites the tag's commit instead of asking the pontonier
    distribution for a version it no longer has."""
    assert not hasattr(amicus.sdk, "__version__")
    assert "185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d" in (amicus.sdk.__doc__ or "")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_sdk_in_tree.py tests/test_packaging.py::test_runtime_dependencies_are_exactly_the_spec_set -v --no-cov`
Expected: the packaging test, `test_pontonier_is_not_installed` and `test_the_sdk_root_names_its_origin_and_has_no_version_lookup` FAIL.

- [ ] **Step 3: Drop the dependency and replace the package root (R4)**

Delete the line `    "pontonier==0.9.0",` from `[project] dependencies` in `pyproject.toml`, then:

```bash
uv lock && uv sync
```

Replace the whole of `src/amicus/sdk/__init__.py` with:

```python
"""The backend SDK amicus's backends are built on, and the lifecycle they run under.

Copied in M8 from pontonier v0.9.0 (commit 185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d,
https://github.com/briandconnelly/pontonier), which amicus no longer depends on; ADR 0029
records why. Four layers: ``amicus.sdk.core`` (jobs, idempotency, worktrees, diff
gathering, redaction, the subprocess runtime, workspace resolution), ``amicus.sdk.backend``
(the backend protocol and contract, FROZEN at ``CONTRACT_API_VERSION = 1``: required members
are stable, and new behavior lands as defaulted fields or optional capability protocols),
``amicus.sdk.conventions`` (error vocabulary, annotations, fingerprint, preflight, prompt
framings) and ``amicus.sdk.testing`` (the conformance kit, which the registry runs on every
plugin it loads). ``amicus.sdk.core`` never imports the other three.
"""
```

- [ ] **Step 4: Run the tests and the full gate**

```bash
uv run python -c "import importlib.util as u; print(u.find_spec('pontonier'))"   # expect None
uv run pytest tests/test_sdk_in_tree.py tests/test_packaging.py -v --no-cov
```

Expected: `None`, then every test PASSES, including the slow ones, `test_the_committed_manifest_command_starts_a_real_server` and the wheel-seam tests, which install amicus into a fresh virtualenv without pontonier.
Then run the full gate.
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/amicus/sdk/__init__.py tests/test_packaging.py tests/test_sdk_in_tree.py
git commit -F - <<'EOF'
build(deps): drop the pontonier dependency

amicus.sdk carries the code, so pontonier==0.9.0 leaves the runtime
dependencies and uv.lock. The sdk's package root no longer looks up the
pontonier distribution's version, which raised PackageNotFoundError once
it was gone; it cites the tag's commit instead (R4).

🤖 Generated with Claude Code
EOF
```

---

### Task 4: Enforce the SDK's import boundaries

**Files:**
- Modify: `pyproject.toml` (after the last `[[tool.importlinter.contracts]]` block)
- Test: `tests/test_import_contracts.py`

**Interfaces:**
- Produces: contracts named exactly `the sdk never imports the rest of amicus` and `sdk core is a leaf layer`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_import_contracts.py`, change `"Contracts: 3 kept, 0 broken"` to `"Contracts: 5 kept, 0 broken"`, add `import tomllib` to the imports, and append:

```python
def _contracts() -> dict[str, dict]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {c["name"]: c for c in config["tool"]["importlinter"]["contracts"]}


def test_the_sdk_contract_forbids_every_other_top_level_module():
    """A new top-level module is forbidden to the sdk the day it lands, not when someone
    remembers to extend the list."""
    package = ROOT / "src" / "amicus"
    top = {
        f"amicus.{p.stem}"
        for p in package.iterdir()
        if (p.suffix == ".py" and p.stem != "__init__")
        or (p.is_dir() and (p / "__init__.py").exists())
    } - {"amicus.sdk"}
    forbidden = set(_contracts()["the sdk never imports the rest of amicus"]["forbidden_modules"])
    assert forbidden == top


def test_sdk_core_stays_a_leaf_layer():
    contract = _contracts()["sdk core is a leaf layer"]
    assert contract["source_modules"] == ["amicus.sdk.core"]
    assert set(contract["forbidden_modules"]) == {
        "amicus.sdk.backend",
        "amicus.sdk.conventions",
        "amicus.sdk.testing",
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_import_contracts.py -v --no-cov`
Expected: all three FAIL (`3 kept` in the output, and `KeyError` on the missing contract names).

- [ ] **Step 3: Add the contracts**

Append to `pyproject.toml` after the `tools never import the server module` contract:

```toml
[[tool.importlinter.contracts]]
name = "the sdk never imports the rest of amicus"
type = "forbidden"
source_modules = ["amicus.sdk"]
forbidden_modules = [
    "amicus._worker",
    "amicus.appstate",
    "amicus.backends",
    "amicus.compaction",
    "amicus.config",
    "amicus.errors",
    "amicus.jobs",
    "amicus.manifest",
    "amicus.middleware",
    "amicus.obs",
    "amicus.orchestration",
    "amicus.packaging",
    "amicus.plugin",
    "amicus.registry",
    "amicus.request",
    "amicus.result_format_snapshot",
    "amicus.schemas",
    "amicus.server",
    "amicus.surface",
    "amicus.tools",
    "amicus.wire_shape_snapshot",
]

# Ported from pontonier's only contract: core never imports the rest of the sdk.
[[tool.importlinter.contracts]]
name = "sdk core is a leaf layer"
type = "forbidden"
source_modules = ["amicus.sdk.core"]
forbidden_modules = ["amicus.sdk.backend", "amicus.sdk.conventions", "amicus.sdk.testing"]
```

If `ls src/amicus` shows a top-level module this list lacks, add it; the completeness test is the authority.

- [ ] **Step 4: Run the tests and the gate**

Run: `uv run lint-imports && uv run pytest tests/test_import_contracts.py -v --no-cov`
Expected: `Contracts: 5 kept, 0 broken`, and all three tests PASS.
Then run the full gate.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_import_contracts.py
git commit -F - <<'EOF'
chore(sdk): enforce the sdk's import boundaries

Two import-linter contracts: amicus.sdk never imports the rest of
amicus, and amicus.sdk.core stays a leaf layer (pontonier's own
contract, ported). A test keeps the first contract's list equal to the
set of top-level modules.

🤖 Generated with Claude Code
EOF
```

- [ ] **Step 6: Mutation control (after the commit)**

```bash
echo 'import amicus.errors  # mutation' >> src/amicus/sdk/core/jsoncache.py
uv run lint-imports | grep -E 'BROKEN|Contracts:'   # expect both new contracts BROKEN
git checkout -- src/amicus/sdk/core/jsoncache.py
```

---

### Task 5: Log the SDK under the `amicus` logger

**Files:**
- Modify: `src/amicus/obs.py` (docstring lines 9-15, `LIBRARY_LOGGER_NAME` at line 55, the comment at line 78, `configure()` at lines 480-509)
- Modify: `tests/test_obs.py:19`, `tests/test_log_redaction.py` (docstring lines 4-6, line 35, lines 76, 82-100, line 179), `tests/test_fastmcp_argument_log.py` (lines 326-330, 337-341, 413-417)
- Test: `tests/test_obs.py`, `tests/test_log_redaction.py`

**Interfaces:**
- Consumes: the SDK's loggers, which are `logging.getLogger(__name__)` in `amicus.sdk.core.idempotency`, `amicus.sdk.core.jobs` and `amicus.sdk.core.runtime`.
- Produces: `obs` with no `LIBRARY_LOGGER_NAME`; `obs.configure` configures `ROOT_LOGGER_NAME` only.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_obs.py`:

```python
def test_configure_leaves_no_pontonier_logger_tree(clean_env):
    """M8: the SDK logs under `amicus.sdk`, so no second logger tree is configured."""
    obs.configure(config.settings({}), force=True)
    assert not hasattr(obs, "LIBRARY_LOGGER_NAME")
    assert logging.getLogger("pontonier").handlers == []
```

In the same file, replace `    assert logging.getLogger("pontonier").propagate is False` with `    assert logging.getLogger("amicus.sdk").propagate is True`.

Append to `tests/test_log_redaction.py`, after `test_an_exception_passed_as_a_message_argument_renders_as_its_type`:

```python
def test_an_sdk_record_reaches_the_policy_handlers(logs):
    """The SDK's core modules log on `logging.getLogger(__name__)`, so their records come from
    `amicus.sdk.*`, a subtree of `amicus`, and reach the handlers `obs.configure` installs
    there by propagation. No second logger tree is configured for them."""
    logs.logger_for("amicus.sdk.core.jobs").info("sdk record %s", "reached")
    for text in _both(logs):
        assert "sdk record reached" in text


def test_an_sdk_record_is_lost_when_its_subtree_stops_propagating(logs, monkeypatch):
    """Mutation control for the test above: cut `amicus.sdk` off from `amicus` and the same
    record reaches neither handler, so the positive result is evidence of propagation. INFO
    stays below `logging.lastResort`'s WARNING floor, so no fallback handler writes it."""
    monkeypatch.setattr(logging.getLogger("amicus.sdk"), "propagate", False)
    logs.logger_for("amicus.sdk.core.jobs").info("sdk record %s", "reached")
    for text in _both(logs):
        assert "sdk record reached" not in text
```

- [ ] **Step 2: Run them to verify the new obs test fails**

Run: `uv run pytest tests/test_obs.py tests/test_log_redaction.py -v --no-cov`
Expected: `test_configure_leaves_no_pontonier_logger_tree` FAILS on `hasattr`; the two new log-redaction tests PASS already (propagation holds today), which is why the control exists.

- [ ] **Step 3: Change `obs.py`**

In the module docstring, replace

```text
message from an innocent one, and ``pontonier``'s ``exc_summary``/``redact_text`` cannot
help: they mask *secrets* and control characters, which is a different question. So the
policy withholds the whole category rather than guessing case by case, and it is enforced
where output is produced rather than at each call site, because the call sites include
``pontonier``'s own — `runtime.py` logs ``("stdout capture failed: %s", exc,
exc_info=True)`` through these handlers, and this package does not own that line.
```

with

```text
message from an innocent one, and the SDK's ``exc_summary``/``redact_text`` cannot help:
they mask *secrets* and control characters, which is a different question. So the policy
withholds the whole category rather than guessing case by case, and it is enforced where
output is produced rather than at each call site, because the call sites include the SDK's
own: ``amicus.sdk.core.runtime`` logs ``("stdout capture failed: %s", exc, exc_info=True)``
through these handlers.
```

Delete the line `LIBRARY_LOGGER_NAME = "pontonier"`.

Replace the comment line

```text
# through types this module has never seen. Both `amicus` and `pontonier` log only these.
```

with

```text
# through types this module has never seen. Everything under `amicus` logs only these.
```

Replace the whole `configure` function with:

```python
def configure(settings: Settings, *, force: bool = False) -> logging.Logger:
    """Configure the amicus logger, under which the SDK logs as ``amicus.sdk.*``, and take
    over the fastmcp and mcp ones for stderr (issue #79), once (idempotent unless ``force``)."""
    global _configured  # noqa: PLW0603
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if _configured and not force:
        return logger
    formatter = PolicyFormatter(_LOG_FORMAT)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    _remove_handlers(logger)
    stderr_handler = PolicyStreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    if settings.log_file:
        try:
            file_handler = PolicyFileHandler(settings.log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            logger.warning(
                "could not open AMICUS_LOG_FILE %r; logging to stderr only", settings.log_file
            )
    level = max(logging.getLevelNamesMapping()[settings.log_level], logging.WARNING)
    _own_dependency_loggers(formatter, level)
    _configured = True
    return logger
```

- [ ] **Step 4: Update the tests that named the old logger**

In `tests/test_log_redaction.py`:

- In the module docstring, replace these two lines
  ```text
  it holds for every call site that logs through them, amicus's own and `pontonier`'s alike
  (`obs.configure` attaches handlers to both logger names and turns propagation off). It is
  ```
  with these three:
  ```text
  it holds for every call site that logs through them, amicus's own and the SDK's alike
  (the SDK logs under `amicus.sdk`, and `obs.configure` attaches handlers to `amicus` and
  turns its propagation off). It is
  ```
- Delete `LIBRARY_LOGGER = "pontonier"`.
- Replace `for target in (child, configured, logging.getLogger(LIBRARY_LOGGER)):` with `for target in (child, configured):`.
- Replace the `read` method and the teardown after `yield Sink()`:
  ```python
          def read(self) -> tuple[str, str]:
              for handler in configured.handlers:
                  if isinstance(handler, POLICY_HANDLERS):
                      handler.flush()
              return stderr.getvalue(), log_file.read_text(encoding="utf-8")

      yield Sink()
      # Leaving the handlers attached would leave an open file handle on `tmp_path` and point
      # any later record at a `StringIO` belonging to a finished test.
      for handler in configured.handlers[:]:
          configured.removeHandler(handler)
          handler.close()
      obs._configured = False
  ```
- Replace `logs.logger_for("pontonier.probe")` with `logs.logger_for("amicus.sdk.core.runtime")`.

In `tests/test_fastmcp_argument_log.py`:

- Replace
  ```python
              for name in (
                  *obs.DEPENDENCY_LOGGER_NAMES,
                  obs.ROOT_LOGGER_NAME,
                  obs.LIBRARY_LOGGER_NAME,
              ):
  ```
  with `            for name in (*obs.DEPENDENCY_LOGGER_NAMES, obs.ROOT_LOGGER_NAME):`.
- Replace both teardown loops of the form `for name in (obs.ROOT_LOGGER_NAME, obs.LIBRARY_LOGGER_NAME):` with a single target at the same indentation:
  ```python
      target = logging.getLogger(obs.ROOT_LOGGER_NAME)
      for handler in target.handlers[:]:
          target.removeHandler(handler)
          handler.close()
  ```

Then confirm nothing names the old constant: `git grep -n LIBRARY_LOGGER -- src tests` prints nothing.

- [ ] **Step 5: Run the tests and the gate**

Run: `uv run pytest tests/test_obs.py tests/test_log_redaction.py tests/test_fastmcp_argument_log.py -v --no-cov`
Expected: all PASS.
Then run the full gate.

- [ ] **Step 6: Commit**

```bash
git add src/amicus/obs.py tests/test_obs.py tests/test_log_redaction.py tests/test_fastmcp_argument_log.py
git commit -F - <<'EOF'
refactor(sdk): log the sdk under the amicus logger

The sdk's modules log on amicus.sdk.*, a subtree of amicus, so their
records reach the policy handlers obs.configure installs on amicus. The
separate pontonier logger tree is no longer configured; a propagation
test and its mutation control pin the new route.

🤖 Generated with Claude Code
EOF
```

---

### Task 6: Move the plugin API to version 2

**Files:**
- Modify: `src/amicus/plugin.py:27`
- Test: `tests/test_plugin.py:13` and `:20`

**Interfaces:**
- Produces: `amicus.plugin.PLUGIN_API_VERSION == 2` (spec decision 6).

- [ ] **Step 1: Write the failing test**

In `tests/test_plugin.py`, change `assert p.PLUGIN_API_VERSION == 1` to `assert p.PLUGIN_API_VERSION == 2`, and `assert fp.api_version == 1` to `assert fp.api_version == 2`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_plugin.py -v --no-cov`
Expected: `test_constants` and `test_fake_plugin_is_a_complete_plugin` FAIL.

- [ ] **Step 3: Bump the constant**

In `src/amicus/plugin.py`, change `PLUGIN_API_VERSION = 1` to `PLUGIN_API_VERSION = 2`.
Confirm it stays off the wire: `git grep -n PLUGIN_API_VERSION -- src` lists only `plugin.py` and `registry.py`.

- [ ] **Step 4: Run the tests and the gate**

Run: `uv run pytest tests/test_plugin.py tests/test_wheel_seam.py -v --no-cov`
Expected: all PASS; the wheel-seam negative control still rejects `PLUGIN_API_VERSION + 1` by reason `api_version`.
Then run the full gate; the manifest and fingerprint pins must pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/amicus/plugin.py tests/test_plugin.py
git commit -F - <<'EOF'
feat(plugin)!: move the plugin api to version 2

A backend plugin now hands amicus amicus.sdk types instead of
pontonier's, so the declared plugin API moves from 1 to 2. The bump
rejects only a plugin that pins api_version=1, because the field
defaults to the running amicus's own constant (#115).

🤖 Generated with Claude Code
EOF
```

---

### Task 7: Sweep the prose that treats pontonier as a dependency (R5)

**Files:**
- Modify: the files in the table below
- Test: `tests/test_sdk_in_tree.py`

**Interfaces:**
- Consumes: `ROOT` from `tests/test_sdk_in_tree.py` (Task 2).
- Produces: `_unexplained_pontonier_lines(src: Path) -> list[str]`.

- [ ] **Step 1: Write the failing test and its control**

Append to `tests/test_sdk_in_tree.py`:

```python
# The only lines under src/ that may name pontonier after M8 (spec §1, R5): the origin note in
# the sdk's package root, a link into pontonier's repository, and the four defaults that keep
# their literal until a follow-up renames them.
_PONTONIER_DEFAULTS = frozenset(
    {
        'WORKTREE_PREFIX = "pontonier-worktree-"',
        'identity_name: str = "pontonier"',
        'identity_email: str = "pontonier@local"',
        'return tempfile.mkdtemp(prefix="pontonier-nohooks-")',
    }
)


def _unexplained_pontonier_lines(src: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        if rel == "amicus/sdk/__init__.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "pontonier" not in line.lower():
                continue
            if "briandconnelly/pontonier" in line or line.strip() in _PONTONIER_DEFAULTS:
                continue
            hits.append(f"{rel}:{n}")
    return hits


def test_src_names_pontonier_only_as_provenance_or_a_kept_default():
    assert _unexplained_pontonier_lines(ROOT / "src") == []


def test_the_prose_scan_detects_a_planted_mention(tmp_path):
    planted = tmp_path / "amicus" / "x.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        '"""Built on Pontonier."""\nURL = "https://github.com/briandconnelly/pontonier"\n',
        encoding="utf-8",
    )
    assert _unexplained_pontonier_lines(tmp_path) == ["amicus/x.py:1"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_sdk_in_tree.py -v --no-cov`
Expected: `test_src_names_pontonier_only_as_provenance_or_a_kept_default` FAILS, listing about 40 lines; the control PASSES.

- [ ] **Step 3: Apply the rewording**

Each row is an exact phrase to find (line numbers are approximate after Task 2's import sort) and its replacement.
Change nothing else on the line.

| File | Find | Replace with |
| --- | --- | --- |
| `src/amicus/registry.py` (~4) | `pontonier conformance violation` | `SDK conformance violation` |
| `src/amicus/wire_shape_snapshot.py` (~174) | `carrying pontonier's own capped hint` | `carrying the SDK's own capped hint` |
| `src/amicus/wire_shape_snapshot.py` (~175) | `not pontonier's 10000 (#95)` | `not the SDK's 10000 (#95)` |
| `src/amicus/plugin.py` (~3) | `A plugin bundles pontonier's frozen contract and adapter` | `A plugin bundles the SDK's frozen contract and adapter` |
| `src/amicus/plugin.py` (~6) | `inspection is a pontonier capability` | `inspection is an SDK capability` |
| `src/amicus/backends/claude/adversarial.py` (~50) | `as pontonier's framings do it.` | `as the SDK's framings do it.` |
| `src/amicus/backends/claude/__init__.py`, `codex/__init__.py`, `kimi/__init__.py` (1) | `assembles the frozen pontonier contract` | `assembles the frozen SDK contract` |
| `src/amicus/backends/claude/adapter.py`, `codex/adapter.py`, `kimi/adapter.py` (1) | `on the pontonier lifecycle` | `on the SDK lifecycle` |
| `src/amicus/backends/claude/contract.py`, `codex/contract.py`, `kimi/contract.py` | `# --- The pontonier contract` | `# --- The SDK contract` |
| `src/amicus/backends/claude/cli.py` (2) | `into a pontonier ClassifiedFailure` | `into an SDK ClassifiedFailure` |
| `src/amicus/backends/codex/cli.py` (1-2) | `into a` at the end of line 1, then `pontonier ClassifiedFailure` at the start of line 2 | `into an`, then `SDK ClassifiedFailure` |
| `src/amicus/backends/kimi/cli.py` (2) | `into a pontonier ClassifiedFailure` | `into an SDK ClassifiedFailure` |
| `src/amicus/backends/kimi/cli.py` (~249) | `(pontonier's shared one)` | `(the SDK's shared one)` |
| `src/amicus/schemas/envelope.py` (~21) | `(the same shape pontonier's` | `(the same shape the SDK's` |
| `src/amicus/schemas/codes.py` (~3) | `DERIVED from pontonier's shared taxonomy` | `DERIVED from the SDK's shared taxonomy` |
| `src/amicus/schemas/codes.py` (~23) | `The four codes pontonier mints per backend` | `The four codes the SDK mints per backend` |
| `src/amicus/orchestration/prompts.py` (1) | `the framings (pontonier's,` | `the framings (the SDK's,` |
| `src/amicus/orchestration/prompts.py` (~56) | `(pontonier has none)` | `(the SDK has none)` |
| `src/amicus/jobs/taskmap.py` (~6) | `The lock mirrors pontonier's own approach` | `The lock mirrors the SDK's own approach` |
| `src/amicus/jobs/taskmap.py` (~26) | `pontonier's job store (import-linter` | `the SDK's job store (import-linter` |
| `src/amicus/jobs/taskmap.py` (~27) | `but pontonier's own store API` | `but the SDK's own store API` |
| `src/amicus/jobs/polling.py` (3) | `pontonier 0.9.0 caps its own hint at MAX_POLL_AFTER_MS = 10000,` | `The SDK's JobStore caps its own hint at MAX_POLL_AFTER_MS = 10000,` |
| `src/amicus/jobs/polling.py` (4) | `and JobStore takes no cap (briandconnelly/pontonier#29)` | `and takes no cap (briandconnelly/pontonier#29)` |
| `src/amicus/jobs/polling.py` (7) | `The formula stays pontonier's own;` | `The formula stays the SDK's own;` |
| `src/amicus/jobs/lifecycle.py` (1) | `over pontonier's JobStore` | `over the SDK's JobStore` |
| `src/amicus/jobs/lifecycle.py` (~86) | `a new pontonier outcome` | `a new SDK outcome` |
| `src/amicus/jobs/lifecycle.py` (~92) | `An unexpected pontonier outcome` | `An unexpected SDK outcome` |
| `src/amicus/sdk/testing/__init__.py` (1) | `Importable test kit for bridges built on pontonier.` | `Importable test kit for backends built on amicus.sdk.` |

Two more phrases contain backticks, so they are given as blocks.
In `src/amicus/errors.py` (~line 3), replace

```text
pontonier's `repair_rules()` are the defaults
```

with

```text
The SDK's `repair_rules()` are the defaults
```

In `src/amicus/sdk/core/__init__.py` (line 5), replace

```text
the ``pontonier`` package
```

with

```text
the ``amicus.sdk`` package
```

If the test still lists a line the table does not name, reword it the same way (pontonier as "the SDK", its modules as `amicus.sdk.*`) and add the row to the PR body.
Never add a line to `_PONTONIER_DEFAULTS` to make the test pass.

- [ ] **Step 4: Run the tests and the gate**

Run: `uv run pytest tests/test_sdk_in_tree.py -v --no-cov`
Expected: all PASS.
Then run the full gate; `ruff format --check` catches a reworded line that now overflows 100 columns.

- [ ] **Step 5: Commit**

```bash
git add -A src tests/test_sdk_in_tree.py
git commit -F - <<'EOF'
docs(sdk): name the in-tree sdk in amicus's own prose

Docstrings and comments that presented pontonier as a library amicus
depends on now name the SDK (R5). A test keeps src/ naming pontonier only
as provenance or one of the four worktree defaults a follow-up retires.

🤖 Generated with Claude Code
EOF
```

---

### Task 8: File the follow-up issues

**Files:** none (GitHub only).

**Interfaces:**
- Produces: `$SCRATCH/m8-issues.txt` with one `key=number` line for each of `jobs`, `orchestration`, `schemas`, `pair_parity`, `classify`, `defaults`, `m27`, `m28`, `m31` and `m15`; Task 9 cites them.

- [ ] **Step 1: Check for duplicates**

Run `gh issue list --state all --search "<the title's first five words>"` for each title below, and skip any that already exists, recording its number instead.

- [ ] **Step 2: File the six dissolution issues**

Use `gh issue create --label refactor --label "priority: low" --title "<title>" --body-file -` with each body below, appending `key=<number>` to `$SCRATCH/m8-issues.txt` from the printed URL.
Every body ends with the line `Follow-up to ADR 0029 (M8).`

| Key | Title | Body |
| --- | --- | --- |
| `jobs` | Dissolve amicus.sdk: move the job store into amicus.jobs | Move `amicus.sdk.core.jobs`, `core.idempotency` and `core.jsoncache` into `amicus.jobs`. Fold in the poll-cap workaround from `src/amicus/jobs/polling.py` (#95), which exists only because the store's own hint stops at 10 s (briandconnelly/pontonier#29). |
| `orchestration` | Dissolve amicus.sdk: move worktree, gitdiff, runtime and workspace into amicus.orchestration | Move `amicus.sdk.core.worktree`, `core.gitdiff`, `core.runtime` and `core.workspace` into `amicus.orchestration`, keeping `core.gitproc`, `core.streamcap` and `core.redaction` wherever their remaining importers need them. The `sdk core is a leaf layer` import contract must be rewritten, not dropped. |
| `schemas` | Dissolve amicus.sdk: move the conventions vocabulary into amicus.schemas | Move `amicus.sdk.conventions.envelope`, `annotations` and `fingerprint` into `amicus.schemas`. A backend plugin imports `BackendErrorVocabulary` and `AnnotationEffects`, so this changes every plugin's imports again; decide whether it moves `PLUGIN_API_VERSION` (see #115). |
| `pair_parity` | Move testing.pair_parity out of the wheel into tests/support | Nothing under `src/` reaches `amicus.sdk.testing.pair_parity`, so it belongs in `tests/support`. `testing.conformance` and `testing.surface_honesty` stay in the wheel: the registry runs conformance on every plugin it loads, and conformance calls `surface_honesty`. |
| `classify` | Retire amicus.sdk.backend.classify | No amicus backend uses `classify.py`; only the conformance fakes in `tests/sdk/test_conformance_fakes.py` do. Give the fakes their own `classify_failure`, then delete `classify.py` and `tests/sdk/test_classify.py`. |
| `defaults` | Retire the pontonier-named defaults in amicus.sdk.core.worktree | Four literals still name pontonier: `WORKTREE_PREFIX`, the `WorktreeConfig` identity pair and the `pontonier-nohooks-` temporary-directory prefix. amicus overrides the first three (`src/amicus/orchestration/isolation.py:19-21`), so only the nohooks prefix reaches the filesystem. Remove the literals from `_PONTONIER_DEFAULTS` in `tests/test_sdk_in_tree.py` as they go. |

- [ ] **Step 3: File the four mirror issues**

Read each original with `gh issue view <n> -R briandconnelly/pontonier` first, so the one-sentence summary in the body is accurate.
Labels: `bug` and `priority: low` for `m27`, `m28` and `m15`; `enhancement` and `priority: low` for `m31`.

| Key | Original | Module in amicus | Title |
| --- | --- | --- | --- |
| `m27` | #27 | `amicus.sdk.core.jobs` | JobStore._rmtree: a partial delete leaves a record that reports a finished job as failed (mirrors briandconnelly/pontonier#27) |
| `m28` | #28 | `amicus.sdk.core.jobs` | JobStore: expired-record cleanup ignores a failed _rmtree (mirrors briandconnelly/pontonier#28) |
| `m31` | #31 | `amicus.sdk.core.jobs` | JobStore: no public way to discard a failed, cancelled or timed-out record (mirrors briandconnelly/pontonier#31) |
| `m15` | #15 | `amicus.sdk.testing.conformance` | conformance: a clean result reads as stronger evidence than it is (mirrors briandconnelly/pontonier#15) |

Each body is this template, with the row's values substituted:

```markdown
Mirrors briandconnelly/pontonier#<original>, which stays open for the sibling projects.

Since M8 (ADR 0029) amicus carries the same code in `<module>`, so this is amicus's behaviour too: <one sentence summarizing the original, from its own text>.

Fix it here in amicus; carrying the fix back to pontonier for the siblings is the maintainer's call, because AGENTS.md rule 17 keeps agents out of that checkout.
```

For `m27` and `m31`, add the line `ADR 0022 describes the behaviour as amicus ships it.`; for `m31`, also add `amicus #94 chose to report the case rather than delete the record.`

- [ ] **Step 4: Comment on #103**

```bash
gh issue comment 103 --body-file - <<'EOF'
M8 moves pontonier's code into amicus as `amicus.sdk`, and ADR 0029 reads ADR 0005's "added upstream, never invented here" as `amicus.sdk.conventions.envelope.REPAIR_STEPS`.
Once M8 merges, this no longer waits on briandconnelly/pontonier#30: the missing repair step can be added in amicus.
EOF
```

- [ ] **Step 5: Verify the record**

Run: `cat "$SCRATCH/m8-issues.txt"`
Expected: ten `key=number` lines, with every key above present exactly once.

---

### Task 9: Record the decision and update the docs

**Files:**
- Create: `docs/adr/0029-the-backend-sdk-lives-in-tree.md`
- Modify: `docs/adr/0023-dependency-loggers-are-owned-at-a-warning-floor.md`, `docs/superpowers/specs/2026-09-04-amicus-design.md` (lines ~138, 181 and the Milestones table), `docs/MIGRATION.md:210`, `docs/DEPRECATING-SIBLINGS.md` (lines 15 and 55), `README.md` (Development table), `CHANGELOG.md` (`## [Unreleased]`)

**Interfaces:**
- Consumes: `$SCRATCH/m8-issues.txt` (Task 8).

- [ ] **Step 1: Write ADR 0029**

Create `docs/adr/0029-the-backend-sdk-lives-in-tree.md` with the content below, then replace every `{key}` token with the number recorded for that key in `$SCRATCH/m8-issues.txt`, and `{date}` with the output of `date -u +%F`.

```markdown
# ADR 0029: the backend SDK lives in amicus

**Status:** Accepted ({date})

## Context

pontonier was created as the shared core of codex-in-claude, moonbridge and claude-in-codex.
Those three were combined into amicus, which is now the only consumer still being developed.
Keeping the core in its own repository cost a second release process, an exact pin (`pontonier==0.9.0`) and a version bump for every SDK change amicus needed.
Issue #13 asked whether the two should stay separate repositories or become one uv workspace.
The design is `docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md`, approved by the maintainer on 2026-09-15 and reviewed by Codex before it was planned.

## Decision

**Neither: pontonier's code is copied into amicus as `amicus.sdk`, and amicus stops depending on pontonier.**
The copy is pontonier's `v0.9.0` tag, commit `185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d`, with every file name kept.
It landed as one mechanical commit whose only edits are an import rewrite, a test-helper import rewrite and ruff's import sort, and a provenance check rebuilt that commit from the tag with an empty diff.
History and blame stay in pontonier's repository.

**Move first, dissolve later.**
`amicus.sdk` keeps pontonier's four layers, `core`, `backend`, `conventions` and `testing`.
import-linter keeps `amicus.sdk` from importing the rest of amicus, and `amicus.sdk.core` from importing the other three layers.
Merging the modules into the amicus packages that own each concern is follow-up work: #{jobs}, #{orchestration}, #{schemas}, #{pair_parity}, #{classify} and #{defaults}.

**pontonier stays published for the siblings.**
It is feature-frozen at 0.9.0 and maintained only for codex-in-claude, moonbridge and claude-in-codex until they are archived.
From M8 on, amicus's copy is authoritative for amicus, and nothing keeps the two copies aligned.
A fix that also affects a sibling's pinned pontonier is the maintainer's to backport, because AGENTS.md rule 17 keeps agents out of that checkout.

**ADR 0005's repair vocabulary is now in-tree.**
ADR 0005 says a `RepairStep` comes from `REPAIR_STEPS` and "is added upstream, never invented here".
Upstream now means `amicus.sdk.conventions.envelope.REPAIR_STEPS`, so adding a step is an ordinary amicus change.
That unblocks #103, which was waiting on briandconnelly/pontonier#30.

**The plugin API moves to version 2.**
A third-party backend now hands amicus `amicus.sdk` types rather than pontonier's, so `PLUGIN_API_VERSION` moves from 1 to 2.
The bump rejects only a plugin that pins `api_version=1`, because `BackendPlugin.api_version` defaults to the running amicus's own constant; #115 tracks that.
No release can enable a third-party backend yet, so no running deployment is affected.

## Consequences

`FINGERPRINT` and `RESULT_FORMAT` do not move: no fingerprint category covers a dependency or a module path, and no stored job record carries a pontonier-named value.
The pinned manifest, wire-shape and result-format fixtures pass unchanged.

The separate `pontonier` logger is gone.
The SDK's modules log on `amicus.sdk.*`, a subtree of `amicus`, so their records reach the policy handlers `obs.configure` installs there; ADR 0023 carries a note.

Four literal defaults in `amicus.sdk.core.worktree` still name pontonier: the worktree prefix, the git identity pair and the `pontonier-nohooks-` temporary-directory prefix.
amicus passes its own prefix and identity, so only the last reaches the filesystem, and #{defaults} retires all four.

Five open pontonier issues describe behaviour amicus ships, and each has an amicus issue: briandconnelly/pontonier#27 is #{m27}, #28 is #{m28}, #31 is #{m31}, #15 is #{m15}, and #30 is #103.
briandconnelly/pontonier#29 is already worked around in `src/amicus/jobs/polling.py` (#95), and #5 to #8 are redaction enhancements with no defect visible in amicus.

`scripts/capture_codex_differentials.py` and `scripts/capture_kimi_differentials.py` keep importing pontonier, because they run inside a sibling's virtualenv and feed that sibling's own objects.

AGENTS.md still says amicus is built on the pontonier SDK; it changes in a PR of its own (rule 9).
```

Run `grep -n '{' docs/adr/0029-the-backend-sdk-lives-in-tree.md`.
Expected: no output.
Then run the rule 16 check on the new file.
Expected: `rule 16 violations: none`.

- [ ] **Step 2: Add the ADR 0023 note**

In `docs/adr/0023-dependency-loggers-are-owned-at-a-warning-floor.md`, insert after the `**Status:** Accepted (2026-09-13)` line, with one blank line on each side:

```markdown
**Note (M8, ADR 0029):** the separate `pontonier` logger this ADR names is gone.
The SDK now logs under `amicus.sdk.*`, which `obs.configure` covers through the `amicus` logger.
```

- [ ] **Step 3: Update the design spec**

In `docs/superpowers/specs/2026-09-04-amicus-design.md`:

- Replace `` `amicus.config.envspec`, `amicus.schemas.codes` and pontonier, never `` with `` `amicus.config.envspec`, `amicus.schemas.codes` and `amicus.sdk`, never ``.
- Replace `PLUGIN_API_VERSION = 1; ENTRY_POINT_GROUP = "amicus.backends"` with `PLUGIN_API_VERSION = 2; ENTRY_POINT_GROUP = "amicus.backends"`.
- Add this row after the M7 row of the Milestones table:
  ```markdown
  | M8 | The backend SDK moves in-tree: pontonier v0.9.0 copied into `amicus.sdk`, the dependency dropped, `PLUGIN_API_VERSION` 2 (`docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md`, ADR 0029) | the provenance check rebuilds the move commit from the tag with an empty diff; gate green with pontonier uninstalled; `FINGERPRINT` and `RESULT_FORMAT` unchanged |
  ```

- [ ] **Step 4: Update MIGRATION, DEPRECATING-SIBLINGS and the README**

In `docs/MIGRATION.md`, replace

```text
While a job runs the hint grows with its elapsed time to a ceiling of 30 s, not pontonier's 10 s.
```

with

```text
While a job runs the hint grows with its elapsed time to a ceiling of 30 s, not the 10 s the SDK's job store uses by default.
```

In `docs/DEPRECATING-SIBLINGS.md`, replace the whole line that begins `It does not replace` with

```text
It does not deprecate `pontonier`: amicus carries pontonier's code as `amicus.sdk` and no longer depends on it (ADR 0029), but pontonier stays published, feature-frozen at 0.9.0, for these three siblings until they are archived.
```

In the same file, after the line that begins `Archiving or gutting any of the three sibling checkouts`, add

```text
Because pontonier is maintained only for these siblings (ADR 0029), archiving the last of them is also the point at which pontonier itself can be archived.
```

In `README.md`'s Development table, replace the row

```text
| What is being built and why | `docs/superpowers/specs/2026-09-04-amicus-design.md` |
```

with

```text
| What is being built and why | `docs/superpowers/specs/2026-09-04-amicus-design.md`; for M8, `docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md` |
```

- [ ] **Step 5: Add the CHANGELOG entry**

Under `## [Unreleased]` in `CHANGELOG.md`, add:

```markdown
### Changed

- amicus no longer depends on `pontonier`. Its backend SDK is now part of amicus, as
  `amicus.sdk` (#13, ADR 0029): the same code as pontonier 0.9.0, copied from its `v0.9.0`
  tag with the imports rewritten. Nothing on the wire or in a stored job result changes, and
  `FINGERPRINT` does not move. A third-party backend distribution imports the SDK types from
  `amicus.sdk` instead of `pontonier` and declares plugin API version 2: `PLUGIN_API_VERSION`
  moved from 1 to 2, so the registry rejects a plugin that pins `api_version=1` (#115 covers
  one that leaves it unset). No release can enable a third-party backend yet, so no running
  deployment is affected.
```

- [ ] **Step 6: Verify the docs and run the gate**

```bash
git grep -n -i pontonier -- docs/MIGRATION.md README.md
git --no-pager diff --no-ext-diff --stat
```

Expected: `MIGRATION.md` and `README.md` no longer mention pontonier, and the diff touches only the seven files this task names.
Then run the full gate, since `docs/MIGRATION.md` and the README are read by tests.

- [ ] **Step 7: Commit**

```bash
git add docs README.md CHANGELOG.md
git commit -F - <<'EOF'
docs(sdk): record that the backend sdk lives in amicus

ADR 0029 records the decision and closes the question in #13; ADR 0023,
the design spec, MIGRATION.md, DEPRECATING-SIBLINGS.md, the README and
the CHANGELOG follow it.

🤖 Generated with Claude Code
EOF
```

---

### Task 10: Milestone gate, perturbation check, Codex review and the draft PR

**Files:** none in the repo, unless the review finds something to fix.

**Interfaces:**
- Consumes: `$MOVE` (Task 1), `$SCRATCH/m8-provenance.txt` (Task 1), `$SCRATCH/m8-issues.txt` (Task 8).

- [ ] **Step 1: Run the milestone gate**

```bash
cd /Users/bdc/projects/amicus-wt-m8
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest
uv run prek run --all-files
uv run python -c "import importlib.util as u; print(u.find_spec('pontonier'))"
grep -E '^FINGERPRINT|^RESULT_FORMAT' src/amicus/schemas/fingerprint.py
```

Expected: all green with `Contracts: 5 kept, 0 broken`, coverage ≥95% (the probe measured 96.66%), about 3,009 passed (the baseline's 1,514, the 1,483 moved tests, and 12 new ones), `None`, `FINGERPRINT = "amicus/0.1/schema-30"` and `RESULT_FORMAT: int = 6`.
Record the pass, skip and coverage numbers for the PR body.

- [ ] **Step 2: Perturbation check**

The milestone's claim is that the surface did not move, so show that the tests pinning it can fail:

```bash
perl -pi -e 's/Every known backend with enabled\/available state/Every known backend with enabled or available state/' src/amicus/tools/discovery.py
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -5    # expect failures in the manifest-snapshot tests
git checkout -- src/amicus/tools/discovery.py
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -2    # expect all passing again
```

Record which tests failed under the perturbation for the PR body.

- [ ] **Step 3: Codex review of everything after the move**

Ask the maintainer to authorize one paid Codex review in the current session, and stop here until they do.
Then build an unreferenced squash of the work after the move (Decision 5); it creates no ref and needs no branch switch:

```bash
MOVE=$(sed -n 's/^MOVE=//p' "$SCRATCH/m8-move-sha.txt")
SQUASH=$(git commit-tree "HEAD^{tree}" -p "$MOVE" -m "M8 after the move, squashed for review")
echo "$SQUASH"
```

Run `amicus_backends(detail="full")` for codex, then `amicus_review_changes_dry_run` with `backend="codex"`, `scope="commit"`, `commit=$SQUASH` and `workspace_root="/Users/bdc/projects/amicus"`, which is the main checkout, because worktrees are outside Codex's roots.
The dry run must report `coverage.status: complete` and `prompt_bytes` below `max_input_bytes`; if not, stop and report.
Then make the one paid `amicus_review_changes` call with the same scope, an `idempotency_key` and `timeout_seconds=600`.
Compose `extra_context` at call time and never save it (rule 18).
It must say:
- the objective;
- that the diff is M8 minus the mechanical move, which the provenance check covers;
- that files Codex reads from disk are `main`'s versions, and only the diff shows the change;
- where the spec and pontonier's tag live, and that both are read-only;
- what to check: conformance to the spec, the logging change, the strength of the new tests and their controls, and the accuracy of the docs' claims;
- your own beliefs, labeled as yours.
Read `ok`, `review_status`, `coverage`, `findings_diagnostics` and `lists_diagnostics` before the findings.
Verify each finding against source before acting on it, fix the confirmed ones in ordinary commits with the gate green, and record declined ones with evidence.
Do not run a second review unless the maintainer asks.

- [ ] **Step 4: Push and open the draft PR**

```bash
git push -u origin feat/m8-sdk-in-tree
```

Write the PR body to `$SCRATCH/m8-pr.md`, never quoting the Codex brief.
It must have these sections: Summary (spec and ADR links, `Closes #13`); The move (the tag, the commit, `$MOVE`, the provenance output and its control); Gate (Step 1's numbers and the baseline's); Perturbation (Step 2); Codex review (verdict, confidence, coverage, each finding and what was done); Follow-ups (the ten issues from `$SCRATCH/m8-issues.txt`, #103's comment, #115); and After merge (the next step below).
End it with the line `🤖 Generated with Claude Code`.

```bash
gh pr create --draft --base main --head feat/m8-sdk-in-tree \
  --title "refactor(sdk)!: move the backend sdk into amicus" --body-file "$SCRATCH/m8-pr.md"
```

If a draft PR for this branch already exists, update its body with `gh pr edit --body-file` instead.
Mark it ready for review (`gh pr ready`) once CI is green and the Codex findings are resolved.
Never merge it or approve it (rule 8).

- [ ] **Step 5: After merge (not part of this PR)**

Two small PRs follow the maintainer's merge.
The first is a governance PR (rule 9) that changes AGENTS.md's "built on FastMCP and the pontonier backend SDK" sentence and its Siblings paragraph to match ADR 0029.
The second, `docs: delete the executed M8 plan`, removes this file, as the execution model requires once a plan is executed and merged.
