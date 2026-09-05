# amicus M0 Implementation Plan: scaffold, schemas, plugin seam, schema-only surface, tasks spike

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `amicus` repository with its tooling, the complete agent-visible surface (all 18 tools, 6 resources, the error envelope and parameter matrix) registered schema-only, the backend plugin seam and registry, the manifest snapshot and discovery-cost ratchets per profile, and a tasks-extension spike whose findings are recorded.

**Architecture:** One FastMCP 4 app built by `amicus.server.create_app(settings, registry)`; every tool is registered by `amicus.tools.register_all` in a fixed order from shared parameter aliases (`schemas/params.py`) and published output schemas (`schemas/results.py`). Backends reach the server only through `amicus.plugin.BackendPlugin` objects loaded by `amicus.registry.BackendRegistry`, which never raises on a bad backend. In M0 no real backend loads (their packages arrive in M1/M3/M4), so every paid tool validates its arguments pre-spend and then returns a `not_implemented` error envelope; the discovery tools, resources, envelope, fingerprint and manifest are real.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `hatchling`, `prek`. Runtime: `pontonier==0.9.0`, `fastmcp>=4.0,<4.1`, `mcp>=2.1,<2.2`, `pydantic>=2`, `anyio>=4`. Dev-only: `fastmcp[tasks]` (the spike), `jsonschema`.

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — "Milestones" row M0, "Architecture", "Tool surface", "Plugin interface", "Error envelope and codes", "Annotations, lifecycle metadata, capability summary, workspace", "Config", "Testing architecture". Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`.

## Global Constraints

- Repo: `/Users/bdc/projects/amicus`. Work on branch `feat/m0-scaffold` in a sibling git worktree `../amicus-wt-m0`. Never commit to `main`.
- Package `amicus` under `src/`, console script `amicus-mcp`, version `0.1.0`, `requires-python = ">=3.11"`, MIT, hatchling.
- Dependencies exactly: `anyio>=4`, `pontonier==0.9.0`, `fastmcp>=4.0,<4.1`, `mcp>=2.1,<2.2`, `pydantic>=2`. `fastmcp[tasks]` is a dev-group dependency only in M0.
- Gate: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest` at ≥95% branch coverage, plus `uv run prek run --all-files`. Coverage floor is never lowered.
- Import rules (import-linter, Task 17): `amicus.backends.*` may import `amicus.plugin`, `amicus.config.envspec`, `amicus.schemas.codes`, `pontonier.*`, never `amicus.tools`, `amicus.server`, `amicus.orchestration`; `amicus.orchestration`, `amicus.jobs` never import `amicus.server` or `amicus.tools`.
- Tool surface: exactly 18 tools in the fixed order given in Task 12; 6 resources; no prompts; the prompts capability and the `io.modelcontextprotocol/ui` extension are suppressed.
- Fingerprint: `FINGERPRINT = "amicus/0.1/schema-1"` for the whole milestone. Snapshot or fingerprint regeneration is always its own commit.
- Commit messages: Conventional Commits `type(scope): subject`; scopes from `scripts/check_commit_message.py` (Task 1); imperative lowercase subject, no trailing period. End every commit body with the attribution trailer given in the session.
- Markdown: one sentence per line.
- Off limits in this plan: `.github/workflows/**`, `CODEOWNERS`, `AGENTS.md` (a separate reviewed PR); releasing; merging or approving your own PR.
- Every `uv run` below assumes `uv sync` has been run once (Task 1). Use `uv run --no-sync` while iterating if syncing is slow.

---

### Task 0: Worktree and baseline

**Files:** none modified.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /Users/bdc/projects/amicus
git worktree add ../amicus-wt-m0 -b feat/m0-scaffold main
cd ../amicus-wt-m0
```

If `superpowers:using-git-worktrees` is available, use it instead; the branch name must be `feat/m0-scaffold`.

- [ ] **Step 2: Confirm the prerequisites**

Run: `curl -s https://pypi.org/pypi/pontonier/0.9.0/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"`
Expected: `0.9.0`.

Run: `ls /Users/bdc/projects/skills/agent-friendly-mcp/SKILL.md /Users/bdc/projects/skills/agent-friendly-github/SKILL.md /Users/bdc/projects/skills/agent-friendly-docs/SKILL.md /Users/bdc/projects/skills/separating-context-from-constraints/SKILL.md`
Expected: four paths printed, no error.

---

### Task 1: Repository tooling and package skeleton

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `prek.toml`, `.gitignore`, `.gitattributes`, `scripts/check_commit_message.py`, `scripts/check_github_actions_pinning.py`, `src/amicus/__init__.py`, `src/amicus/py.typed`, `tests/conftest.py`, `tests/test_packaging.py`, `tests/test_check_commit_message.py`

**Interfaces:**
- Produces: `amicus.__version__ == "0.1.0"`, `amicus.SERVER_NAME == "amicus"`; `tests/conftest.py` fixture `clean_env` (strips `AMICUS_*` and the legacy prefixes) and helper `make_run`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "amicus"
version = "0.1.0"
description = "One MCP server for every second-opinion model: consult, review, and delegate with the backend as a parameter"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [{ name = "Brian Connelly" }]
keywords = ["mcp", "codex", "kimi", "claude-code", "code-review", "delegation", "second-opinion"]
classifiers = [
    "Development Status :: 2 - Pre-Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Software Development",
]
dependencies = [
    "anyio>=4",
    "pontonier==0.9.0",
    # Minor-line caps: fastmcp documents that breaking changes may land in minor releases.
    # Widening either cap is a deliberate upgrade PR, not a resolver decision.
    "fastmcp>=4.0,<4.1",
    "mcp>=2.1,<2.2",
    "pydantic>=2",
]

[project.urls]
Homepage = "https://github.com/briandconnelly/amicus"
Repository = "https://github.com/briandconnelly/amicus"
Issues = "https://github.com/briandconnelly/amicus/issues"

[project.scripts]
amicus-mcp = "amicus.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/amicus"]

[dependency-groups]
dev = [
    # The tasks spike (M0) needs the real extension; production wiring lands in M5.
    "fastmcp[tasks]>=4.0,<4.1",
    "import-linter>=2",
    "jsonschema>=4.26",
    "prek>=0.4.5",
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-cov>=7",
    "ruff>=0.15.15",
    "ty>=0.0.1a7",
]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "PIE", "RUF", "PL", "PT", "TID", "TC", "ARG", "PTH"]
ignore = [
    "PLR0913",  # too-many-args: tool handlers legitimately take many params
    "PLR0917",  # too-many-positional-args: same
    "PLR0911",  # too-many-returns: dispatch/classify handlers branch per error case
    "PLR0912",  # too-many-branches: same
    "PLR2004",  # magic-value: noisy for literals
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ARG", "PLR2004", "S101", "TC001", "TC002", "TC003", "PT006", "PT011", "PT018", "PLC0415", "RUF059", "SLF001"]

[tool.ty.src]
include = ["src"]

[tool.ty.rules]
unresolved-import = "warn"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
addopts = "--cov=amicus --cov-report=term-missing --strict-markers --strict-config -m 'not integration'"
markers = [
    "integration: live tests requiring a backend CLI; opt in with `pytest -m integration --no-cov`",
]

[tool.coverage.run]
source = ["src/amicus"]
branch = true

[tool.coverage.report]
fail_under = 95
show_missing = true

[tool.importlinter]
root_package = "amicus"

[[tool.importlinter.contracts]]
name = "backends never import the server layer"
type = "forbidden"
source_modules = ["amicus.backends"]
forbidden_modules = ["amicus.tools", "amicus.server", "amicus.orchestration", "amicus.jobs", "amicus.middleware", "amicus.errors", "amicus.registry", "amicus.manifest"]

[[tool.importlinter.contracts]]
name = "orchestration and jobs never import the server layer"
type = "forbidden"
source_modules = ["amicus.orchestration", "amicus.jobs"]
forbidden_modules = ["amicus.server", "amicus.tools"]
```

- [ ] **Step 2: Write `LICENSE`, `.gitignore`, `.gitattributes`, `prek.toml`**

`LICENSE`: copy `/Users/bdc/projects/codex-in-claude/LICENSE` verbatim (MIT, 2026, Brian Connelly).

`.gitignore` (note: `docs/superpowers/` is TRACKED here, unlike the siblings, because the spec and plans live in this repo by the execution model):

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/

# Environments
.venv/
.env
.env.*

# Secrets / credentials (never commit)
*.pem
*.key
*.p12
*.pfx
credentials.json
*_credentials.json

# Tooling caches
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
.ty_cache/

# OS
.DS_Store
```

`.gitattributes`:

```gitattributes
# Normalize line endings across agent/dev platforms; check out LF everywhere.
* text=auto eol=lf
*.png binary
*.jpg binary
```

`prek.toml`:

```toml
# prek (https://prek.j178.dev) — local Git hooks mirroring the CI gate.
# One-time: `uv run prek install --prepare-hooks`.
default_install_hook_types = ["pre-commit", "pre-push", "commit-msg"]

[[repos]]
repo = "builtin"
hooks = [
  { id = "trailing-whitespace" },
  { id = "end-of-file-fixer" },
  { id = "check-merge-conflict" },
  { id = "detect-private-key" },
  { id = "check-added-large-files" },
  { id = "check-yaml" },
  { id = "check-toml" },
  { id = "check-json" },
]

[[repos]]
repo = "local"
hooks = [
  { id = "ruff-check", name = "ruff check", language = "system", entry = "uv run ruff check --force-exclude --fix", types = ["python"] },
  { id = "ruff-format", name = "ruff format", language = "system", entry = "uv run ruff format --force-exclude", types = ["python"] },
  { id = "ty", name = "ty check", language = "system", entry = "uv run ty check", types_or = ["python", "toml"], files = "(\\.py|^pyproject\\.toml)$", pass_filenames = false },
  { id = "lint-imports", name = "import-linter", language = "system", entry = "uv run lint-imports", types = ["python"], pass_filenames = false },
  { id = "actions-pinning", name = "github actions sha pinning", language = "system", entry = "uv run python scripts/check_github_actions_pinning.py", files = "^\\.github/workflows/.*\\.ya?ml$", pass_filenames = false },
  { id = "uv-lock-check", name = "uv lock --check", language = "system", entry = "uv lock --check", pass_filenames = false, files = "^(pyproject\\.toml|uv\\.lock|uv\\.toml)$" },
]

[[repos]]
repo = "local"
hooks = [
  { id = "pytest", name = "pytest", language = "system", entry = "uv run pytest", stages = ["pre-push"], pass_filenames = false, always_run = true },
]

[[repos]]
repo = "local"
hooks = [
  { id = "commit-msg", name = "conventional commit", language = "system", entry = "uv run python scripts/check_commit_message.py", stages = ["commit-msg"], pass_filenames = true },
]
```

- [ ] **Step 3: Write the two scripts**

`scripts/check_github_actions_pinning.py`: copy `/Users/bdc/projects/codex-in-claude/scripts/check_github_actions_pinning.py` verbatim (pure stdlib; exits 2 "nothing to scan" while this repo has no workflows, which the prek hook only triggers on workflow files anyway).

`scripts/check_commit_message.py`: copy `/Users/bdc/projects/codex-in-claude/scripts/check_commit_message.py`, then replace the `ALLOWED_SCOPES` tuple with:

```python
# Optional scopes: the codebase areas of this repo.
ALLOWED_SCOPES = (
    "schemas",
    "plugin",
    "registry",
    "config",
    "errors",
    "middleware",
    "server",
    "tools",
    "resources",
    "manifest",
    "orchestration",
    "jobs",
    "tasks",
    "backends",
    "packaging",
    "docs",
    "ci",
    "deps",
    "release",
)
```

Then: `chmod +x scripts/check_commit_message.py scripts/check_github_actions_pinning.py`

- [ ] **Step 4: Write the package skeleton**

`src/amicus/__init__.py`:

```python
"""amicus: one MCP server for every second-opinion model."""

from __future__ import annotations

__version__ = "0.1.0"
SERVER_NAME = "amicus"
```

`src/amicus/py.typed`: empty file.

- [ ] **Step 5: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import os

import fastmcp
import pytest
from pontonier.core.runtime import CommandRun

# Run the suite with fastmcp's camelCase compatibility bridge OFF so any camelCase read
# that sneaks in fails today as a hard AttributeError instead of on the next major.
fastmcp.settings.mcp_camelcase_compat = False

# The env prefixes this server reads: its own, and the three legacy prefixes the shim
# consults. Stripped so tests see built-in defaults.
ENV_PREFIXES = ("AMICUS_", "CODEX_IN_CLAUDE_", "MOONBRIDGE_", "CLAUDE_IN_CODEX_")


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every amicus and legacy env var so tests see built-in defaults."""
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def make_run(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    elapsed_ms: int = 5,
    timed_out: bool = False,
) -> CommandRun:
    return CommandRun(stdout, stderr, exit_code, elapsed_ms, timed_out)
```

- [ ] **Step 6: Write the packaging and commit-message tests**

`tests/test_packaging.py`:

```python
"""Packaging invariants: version literals agree, classifiers match the floor."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import amicus

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_version_literal_matches_package():
    assert _pyproject()["project"]["version"] == amicus.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", amicus.__version__)


def test_python_floor_matches_classifiers():
    project = _pyproject()["project"]
    floor = project["requires-python"]
    assert floor == ">=3.11"
    minors = sorted(
        int(c.rsplit(".", 1)[1])
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    )
    assert minors[0] == 11
    assert minors == list(range(minors[0], minors[-1] + 1))


def test_runtime_dependencies_are_exactly_the_spec_set():
    deps = _pyproject()["project"]["dependencies"]
    names = sorted(re.split(r"[<>=!\[]", d, maxsplit=1)[0] for d in deps)
    assert names == ["anyio", "fastmcp", "mcp", "pontonier", "pydantic"]
    assert "pontonier==0.9.0" in deps


def test_console_script_points_at_server_main():
    assert _pyproject()["project"]["scripts"] == {"amicus-mcp": "amicus.server:main"}
```

`tests/test_check_commit_message.py`:

```python
"""The commit-msg hook accepts this repo's scopes and rejects the rest."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_commit_message.py"
_spec = importlib.util.spec_from_file_location("check_commit_message", _SCRIPT)
assert _spec is not None and _spec.loader is not None
ccm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccm)


def test_valid_scoped_header_passes():
    assert ccm.validate("feat(schemas): add the parameter matrix") is None


def test_unknown_scope_fails():
    assert ccm.validate("feat(nope): x") == "scope 'nope' is not allowed"


def test_capitalized_subject_fails():
    assert ccm.validate("fix: Capitalized") == "subject must not start with a capital letter"


def test_git_generated_forms_are_skipped():
    assert ccm.validate('Revert "feat: x"') is None
    assert ccm.validate("Merge branch 'main'") is None


def test_main_reports_a_file(tmp_path, capsys):
    msg = tmp_path / "MSG"
    msg.write_text("chore(packaging): bump\n", encoding="utf-8")
    assert ccm.main([str(msg)]) == 0
    msg.write_text("bad message\n", encoding="utf-8")
    assert ccm.main([str(msg)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert ccm.main([]) == 1
```

- [ ] **Step 7: Sync and run the gate pieces that exist**

Run: `uv sync`
Expected: resolves `pontonier==0.9.0`, `fastmcp 4.0.x`, `fastmcp-tasks`, creates `uv.lock`.

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: ruff/ty clean; pytest passes; coverage reports 100% for the two-line package.
If `ruff format --check` flags a file, run `uv run ruff format src tests scripts` and re-run.

- [ ] **Step 8: Install the hooks and commit**

```bash
uv run prek install --prepare-hooks
git add pyproject.toml uv.lock LICENSE prek.toml .gitignore .gitattributes scripts src tests
git commit -m "chore(packaging): scaffold the amicus package and tooling

Copies the codex-in-claude tooling conventions (uv, ruff, ty, pytest at
a 95% branch-coverage floor, prek hooks, conventional-commit scopes) and
declares the exact runtime dependency set from the design spec."
```

---

### Task 2: Vendored dev skills, ADR skeleton, README

**Files:**
- Create: `.agents/skills/{agent-friendly-mcp,agent-friendly-github,agent-friendly-docs,separating-context-from-constraints}/` (copies), `docs/adr/README.md`, `docs/adr/0001-annotations-follow-the-worst-enabled-backend.md`, `docs/adr/0002-backend-options-is-a-closed-superset.md`, `docs/adr/0003-workspace-resolution.md`, `docs/adr/0004-tasks-and-jobs.md`, `docs/adr/0005-error-envelope-and-repair-precedence.md`, `docs/adr/0006-fingerprint-and-surface-digest.md`
- Modify: `README.md`

- [ ] **Step 1: Vendor the canonical skills**

```bash
mkdir -p .agents/skills
for s in agent-friendly-mcp agent-friendly-github agent-friendly-docs separating-context-from-constraints; do
  rsync -a --exclude '__pycache__' --exclude '.pytest_cache' "/Users/bdc/projects/skills/$s/" ".agents/skills/$s/"
done
ls .agents/skills/*/SKILL.md
```

Expected: four `SKILL.md` paths.

- [ ] **Step 2: Write the ADR index and six ADRs**

`docs/adr/README.md`:

```markdown
# Architecture decision records

Decisions that shape the agent-visible surface, one file each, numbered in the order they were made.
Status is one of Proposed, Accepted, Superseded.
The design spec (`docs/superpowers/specs/2026-09-04-amicus-design.md`) names each ADR where the decision applies.
```

`docs/adr/0001-annotations-follow-the-worst-enabled-backend.md`:

```markdown
# ADR 0001: Tool annotations follow the worst enabled backend

**Status:** Accepted (2026-09-04, M0)

## Context

One tool serves several backends whose observable effects differ.
Claude's config modes may run workspace hooks, so claude-in-codex marks paid tools `destructiveHint: true`.
Codex and Kimi confine writes to a throwaway worktree, so their bridges mark paid tools `destructiveHint: false`.
An annotation set is static per tool, but the backend is a per-call parameter.

## Decision

Annotate each tool for its worst enabled backend, per `[3.ap-mode-annotations]`.
The enabled set comes from `AMICUS_BACKENDS` (default: every in-tree backend), so a profile that enables Claude advertises paid tools as `destructiveHint: true`, and a codex/kimi-only profile advertises `false`.
Each backend's own `AnnotationEffects` is published on `amicus_backends` so an agent can read the per-backend truth.
Job reads (`amicus_job_status`, `amicus_job_result`, `amicus_job_list`) advertise `readOnlyHint: true` under the observable-scope reading (`[3.mutation-scope]`), documented on `amicus_capabilities.annotations_reading`.

## Consequences

- A user who enables Claude pays mutation-grade approval friction on codex-only calls; this is a deliberate UX regression, disclosed on `amicus_capabilities`.
- The manifest snapshot and discovery-cost ratchet are measured per profile, because the annotations differ per profile.
- Host approval behaviour is captured in M6 (`docs/superpowers/specs` → "Annotations").
```

`docs/adr/0002-backend-options-is-a-closed-superset.md`:

```markdown
# ADR 0002: `backend_options` is a closed superset object

**Status:** Accepted (2026-09-04, M0)

## Context

Codex, Kimi and Claude each have backend-specific knobs (`isolation`, `config_mode`, `access`, `max_budget_usd`).
An open `dict` parameter would let a misspelled key pass validation and silently reach a paid run.

## Decision

`backend_options` is one Pydantic model with `additionalProperties: false` whose fields are the union of every backend's options, each described with the backends that accept it and its allowed values.
Applicability is validated pre-spend in `amicus.tools._resolve`: a key or value the selected backend does not accept fails as `invalid_arguments` with `details.field = "backend_options.<key>"` and `allowed_values` for that backend.
`amicus_dry_run` and `amicus_delegate_dry_run` echo the resolved values.
Adding a backend option changes the schema and bumps the fingerprint deliberately.

## Consequences

- First-call correctness: an agent reads one closed schema and cannot send a key that is silently dropped.
- `OptionSpec` on the plugin carries defaults and applicability, not the schema; the schema is owned by `amicus.schemas.options`.
```

`docs/adr/0003-workspace-resolution.md`:

```markdown
# ADR 0003: Workspace resolution never silently falls back to the server cwd

**Status:** Proposed (2026-09-04; implemented in M1)

## Context

The MCP server launches from its install directory, so a cwd fallback silently targets the wrong repository.
codex-in-claude resolves explicit `workspace_root` → first file root → server cwd with a warning.

## Decision

Explicit `workspace_root` → handshake-era file roots (see codex-in-claude ADR 0004 D5) → structured `invalid_workspace_root`.
The server cwd is used only under `AMICUS_ALLOW_CWD_WORKSPACE=1`, and then the resolved path is disclosed in `meta.workspace_warning`.

## Consequences

- Sessionless (2026-07-28) clients must pass `workspace_root`; the parameter description says so.
- M1 implements the resolver and the roots probe; M0 declares the setting.
```

`docs/adr/0004-tasks-and-jobs.md`:

```markdown
# ADR 0004: Async is both durable jobs and the tasks extension

**Status:** Proposed (2026-09-04; spike in M0, wiring in M5)

## Context

Durable `JobStore` jobs survive a dropped connection and a server restart, and every host can drive them through ordinary tools.
The `io.modelcontextprotocol/tasks` extension (SEP-2663) is the spec-native lifecycle, but it is an extension the host must negotiate and it needs a Docket backend.

## Decision

Keep the `_async` twins and `amicus_job_*` as the universal path.
Additionally register the four paid sync tools with `task=True` when `AMICUS_TASKS=1` and the `fastmcp[tasks]` extra is installed.
Persist a `task_id → job_id` mapping at task creation so `amicus_job_list(task_id=...)` recovers the job behind a task.
Cancellation propagation is explicit: an unkeyed task cancels its job; a keyed job survives and the cancel result names its `job_id`.

## Spike report (M0)

Filled in by Task 16 of the M0 plan.
```

`docs/adr/0005-error-envelope-and-repair-precedence.md`:

```markdown
# ADR 0005: One error envelope, backend-aware repair precedence

**Status:** Accepted (2026-09-04, M0)

## Context

pontonier owns the code taxonomy and default `RepairRule`s but not wire serialization.
claude-in-codex's `ErrorInfo` uses `retryable` plus a typed `action`; codex-in-claude and moonbridge use `temporary` plus a structured `repair` object.

## Decision

Adopt the codex-in-claude shape: `code`, `message`, `backend`, `temporary`, `retry_after_ms` (always present), one `repair {next_step, tool, arguments, alternative}`, `details {field|fields, reason, allowed_values}`, `invalid_arguments[]`, `request_id`.
`details.value` is emitted only for known-safe values; the policy is disclosed on `amicus://error-envelope`.
Rendering precedence: a plugin's `repair_overrides` win per code, then pontonier's `repair_rules()` defaults, then amicus-local rules; backend-local codes are preserved verbatim; `generalize()` rewrites only `<id>_not_found`, `<id>_auth_required`, `<id>_auth_indeterminate`, `<id>_rate_limited` to `backend_*` so the catalog stays closed while `error.backend` names the backend.
A non-`None` `ClassifiedFailure.retryable` overrides the rule's `temporary`.
Resource-read failures carry the same envelope in JSON-RPC `error.data` with `machine_code`/`human_message`.

## Consequences

- One serializer (`amicus.errors`) is the only producer of the wire shape.
- `RepairStep` is pontonier's `REPAIR_STEPS` vocabulary; a new symbol is added upstream, never invented here.
```

`docs/adr/0006-fingerprint-and-surface-digest.md`:

```markdown
# ADR 0006: Fingerprint plus surface digest; cache hints left at the SDK default

**Status:** Accepted (2026-09-04, M0)

## Context

The siblings pin a hand-bumped `FINGERPRINT` and guard it with a committed manifest snapshot.
A hand-bumped string cannot prove the surface changed; a digest cannot be read by a human.

## Decision

`amicus_capabilities` reports both: the static `FINGERPRINT` (`amicus/0.1/schema-N`, bumped by hand on any covered change) and `surface_digest`, the sha256 of the canonical manifest JSON computed from the live app.
The committed snapshot (`tests/fixtures/manifest_snapshot.<profile>.json`) and pinned hash guard both per profile.
`ttlMs`/`cacheScope` stay at the SDK default (`ttlMs: 0`, `cacheScope: "private"`): fastmcp applies one server-wide hint to every list and read result, and `amicus://models/{backend}` is volatile, so a positive TTL would be wrong for it.
The manifest pins the emitted values so a framework change is reviewed, not silent.

## Consequences

- `surface_digest` and `fingerprint` are excluded from the manifest capture (self-referential), as are release-variable versions.
- Revisit the TTL when fastmcp offers per-resource hints.
```

- [ ] **Step 3: Update `README.md`**

Replace the paragraph `**Not yet implemented.** This repository currently holds only the design and execution plan.` with:

```markdown
**Status:** milestone M0 (scaffold and schema-only surface).
Every tool is registered with its final schema; paid tools return `not_implemented` until their backend lands (M1 Codex, M3 Kimi, M4 Claude).

## Development

```sh
uv sync
uv run prek install --prepare-hooks   # one-time local hooks
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```
```

Also add a row to the "Where things are" table: `| The M0 plan (scaffold, schemas, plugin seam, tasks spike) | `docs/superpowers/plans/2026-09-04-amicus-M0-scaffold-and-surface.md` |` and a row `| Architecture decisions | `docs/adr/` |`.

- [ ] **Step 4: Commit**

```bash
git add .agents docs/adr README.md
git commit -m "docs: vendor the dev skills and add the ADR skeleton

The four canonical agent-friendliness skills are copied from
~/projects/skills so any harness reading this repo finds them. ADRs
0001, 0002, 0005 and 0006 are accepted by the M0 design; 0003 and 0004
are proposed and filled in by M1 and the M0 tasks spike."
```

---

### Task 3: Codes, fingerprint constants

**Files:**
- Create: `src/amicus/schemas/__init__.py`, `src/amicus/schemas/codes.py`, `src/amicus/schemas/fingerprint.py`
- Test: `tests/test_codes.py`

**Interfaces:**
- Produces: `codes.BACKEND_IDS: tuple[str, ...] = ("codex", "kimi", "claude")`, `codes.BackendId` (Literal), `codes.VERBS`, `codes.Verb`, `codes.GENERALIZED_BACKEND_CODES`, `codes.LOCAL_CODES`, `codes.ERROR_CODES: tuple[str, ...]` (sorted), `codes.ErrorCode` (Literal), `codes.REPAIR_STEPS: tuple[str, ...]`, `codes.RepairStep` (Literal), `codes.generalize_code(code: str, backend_id: str) -> str`; `fingerprint.FINGERPRINT`, `fingerprint.FINGERPRINT_COVERS`, `fingerprint.FINGERPRINT_COVERS_DESC`, `fingerprint.RESULT_FORMAT`, `fingerprint.JSON_SCHEMA_DIALECT`, `fingerprint.LIFECYCLE_META_KEY`, `fingerprint.TRIAGE_META_KEY`, `fingerprint.PROTOCOL_REVISION`.

- [ ] **Step 1: Write the failing test**

`tests/test_codes.py`:

```python
"""The closed code catalog is derived from pontonier's taxonomy, not restated."""

from __future__ import annotations

from typing import get_args

from pontonier.backend.contract import BackendContract  # noqa: F401 - import smoke
from pontonier.conventions import envelope as pe

from amicus.schemas import codes, fingerprint


def test_backend_ids_are_the_v1_set_in_order():
    assert codes.BACKEND_IDS == ("codex", "kimi", "claude")
    assert get_args(codes.BackendId) == codes.BACKEND_IDS


def test_verbs_are_the_four_paid_kinds():
    assert codes.VERBS == ("consult", "review_changes", "adversarial_review", "delegate")


def test_error_codes_cover_the_universal_taxonomy_and_generalized_backend_codes():
    catalog = set(codes.ERROR_CODES)
    assert pe.UNIVERSAL_CODES <= catalog
    assert codes.GENERALIZED_BACKEND_CODES == frozenset(
        {
            "backend_not_found",
            "backend_auth_required",
            "backend_auth_indeterminate",
            "backend_rate_limited",
        }
    )
    assert codes.GENERALIZED_BACKEND_CODES <= catalog
    # Feature codes for features some v1 backend declares.
    assert {"invalid_model", "empty_response"} <= catalog
    # amicus-local codes.
    assert codes.LOCAL_CODES == frozenset(
        {"not_implemented", "backend_unavailable", "feature_unsupported"}
    )
    assert codes.LOCAL_CODES <= catalog
    # No per-backend minted code leaks into the closed catalog.
    for backend in codes.BACKEND_IDS:
        assert pe.backend_codes(backend).isdisjoint(catalog)
    assert codes.ERROR_CODES == tuple(sorted(catalog))
    assert set(get_args(codes.ErrorCode)) == catalog


def test_repair_steps_are_pontoniers_vocabulary():
    assert set(codes.REPAIR_STEPS) == pe.REPAIR_STEPS
    assert codes.REPAIR_STEPS == tuple(sorted(pe.REPAIR_STEPS))
    assert set(get_args(codes.RepairStep)) == pe.REPAIR_STEPS


def test_generalize_rewrites_only_the_four_minted_codes():
    assert codes.generalize_code("codex_not_found", "codex") == "backend_not_found"
    assert codes.generalize_code("kimi_rate_limited", "kimi") == "backend_rate_limited"
    assert codes.generalize_code("claude_auth_indeterminate", "claude") == (
        "backend_auth_indeterminate"
    )
    assert codes.generalize_code("claude_auth_required", "claude") == "backend_auth_required"
    # A backend-local code is preserved verbatim.
    assert codes.generalize_code("user_config_rejected", "codex") == "user_config_rejected"
    # Another backend's minted code is not this backend's to rewrite.
    assert codes.generalize_code("codex_not_found", "kimi") == "codex_not_found"


def test_fingerprint_constants():
    assert fingerprint.FINGERPRINT == "amicus/0.1/schema-1"
    assert fingerprint.RESULT_FORMAT == 1
    assert fingerprint.JSON_SCHEMA_DIALECT == "https://json-schema.org/draft/2020-12/schema"
    assert fingerprint.LIFECYCLE_META_KEY == "dev.bconnelly.amicus/lifecycle"
    assert fingerprint.PROTOCOL_REVISION == "2026-07-28"
    assert "tool_names" in fingerprint.FINGERPRINT_COVERS
    assert "Release identity is excluded:" in fingerprint.FINGERPRINT_COVERS_DESC
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_codes.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'amicus.schemas'`.

- [ ] **Step 3: Write the modules**

`src/amicus/schemas/__init__.py`:

```python
"""Wire contracts: codes, envelope, results, parameters, options, fingerprint."""
```

`src/amicus/schemas/codes.py`:

```python
"""Closed value sets: backend ids, verbs, the error-code catalog, repair steps.

The catalog is DERIVED from pontonier's shared taxonomy so it cannot drift from it:
universal codes, the four per-backend codes generalized to ``backend_*`` (the concrete
backend rides ``error.backend``), the feature codes some v1 backend declares, and the
amicus-local codes. A backend-LOCAL code (codex's ``user_config_rejected``) joins this
catalog when its backend is ported, as a deliberate fingerprint bump.
"""

from __future__ import annotations

from typing import Literal

from pontonier.conventions import envelope as _pe

BACKEND_IDS: tuple[str, ...] = ("codex", "kimi", "claude")
BackendId = Literal["codex", "kimi", "claude"]

VERBS: tuple[str, ...] = ("consult", "review_changes", "adversarial_review", "delegate")
Verb = Literal["consult", "review_changes", "adversarial_review", "delegate"]

# The four codes pontonier mints per backend, generalized so the catalog stays closed.
_MINTED_SUFFIXES = ("_not_found", "_auth_required", "_auth_indeterminate", "_rate_limited")
GENERALIZED_BACKEND_CODES = frozenset(f"backend{s}" for s in _MINTED_SUFFIXES)

# Feature codes for the features the v1 backends declare (kimi: model_validation and
# empty_response_detection). Codex's `transfer` is deferred, so its codes are not minted.
_FEATURE_CODES = _pe.feature_codes(frozenset({"model_validation", "empty_response_detection"}))

LOCAL_CODES = frozenset(
    {
        # The tool is registered but its backend has not landed in this release.
        "not_implemented",
        # The registry recorded the backend as unavailable (import, conformance, config).
        "backend_unavailable",
        # The backend does not declare the feature this verb needs (e.g. claude+delegate).
        "feature_unsupported",
    }
)

ERROR_CODES: tuple[str, ...] = tuple(
    sorted(_pe.UNIVERSAL_CODES | GENERALIZED_BACKEND_CODES | _FEATURE_CODES | LOCAL_CODES)
)
ErrorCode = Literal[
    "backend_auth_indeterminate",
    "backend_auth_required",
    "backend_not_found",
    "backend_rate_limited",
    "backend_unavailable",
    "cli_contract_changed",
    "context_too_large",
    "empty_response",
    "extra_args_rejected",
    "feature_unsupported",
    "git_unavailable",
    "idempotency_conflict",
    "idempotency_in_progress",
    "idempotency_result_unavailable",
    "input_too_large",
    "internal_error",
    "invalid_arguments",
    "invalid_base",
    "invalid_commit",
    "invalid_json",
    "invalid_model",
    "invalid_paths",
    "invalid_reasoning_effort",
    "invalid_scope",
    "invalid_workspace_root",
    "job_cancelled",
    "job_failed",
    "job_not_found",
    "job_result_incompatible",
    "job_running",
    "job_timeout",
    "nonzero_exit",
    "not_a_git_repo",
    "not_implemented",
    "resource_not_found",
    "schema_violation",
    "timeout",
    "unexpanded_env_placeholder",
    "unsupported_detail",
    "unsupported_isolation",
    "unsupported_sandbox",
    "unsupported_tier",
    "workspace_outside_roots",
    "worktree_error",
]

REPAIR_STEPS: tuple[str, ...] = tuple(sorted(_pe.REPAIR_STEPS))
RepairStep = Literal[
    "authenticate",
    "correct_arguments",
    "correct_config",
    "init_git_repo",
    "inspect_and_retry",
    "install_backend",
    "install_git",
    "list_jobs",
    "list_resources",
    "poll_job_status",
    "reduce_input",
    "retry_after_delay",
    "retry_then_report",
    "start_new_job",
    "update_plugin",
    "use_allowed_value",
    "use_new_idempotency_key",
    "use_workspace_in_roots",
]


def generalize_code(code: str, backend_id: str) -> str:
    """Rewrite ``<backend_id><suffix>`` to ``backend<suffix>`` for the four minted codes.

    Every other code — universal, feature, or backend-local — is returned verbatim."""
    for suffix in _MINTED_SUFFIXES:
        if code == f"{backend_id}{suffix}":
            return f"backend{suffix}"
    return code
```

`src/amicus/schemas/fingerprint.py`:

```python
"""Surface identity: the hand-bumped FINGERPRINT and what it covers (ADR 0006)."""

from __future__ import annotations

# Bump on any externally observable change to a category below; the committed manifest
# snapshot (tests/test_manifest.py) fails on drift and its message says to bump this.
FINGERPRINT = "amicus/0.1/schema-1"

# Persisted result-format version stamped into job records (M2); moves only when a
# stored result.json shape an older reader's closed schema could reject changes.
RESULT_FORMAT: int = 1

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
PROTOCOL_REVISION = "2026-07-28"

# Namespaced _meta keys (convention extensions, per the agent-friendly-mcp native-vs-
# convention rule). `lifecycle` carries {stability, deprecation} on every tool and
# resource record ([9.tier-metadata]); `triage` carries size metadata on resources.
LIFECYCLE_META_KEY = "dev.bconnelly.amicus/lifecycle"
TRIAGE_META_KEY = "dev.bconnelly.amicus/triage"

FINGERPRINT_COVERS: tuple[str, ...] = (
    "tool_names",
    "tool_input_schemas",
    "tool_output_schemas",
    "tool_descriptions",
    "tool_annotations",
    "tool_lifecycle_meta",
    "error_codes",
    "value_enums",
    "resource_metadata",
    "resource_templates",
    "prompts",
    "initialize_response",
    "discover_response",
    "modern_result_envelopes",
    "error_envelope_schema",
    "result_meta_schema",
    "capabilities_result_schema",
    "parameter_contracts",
    "capabilities_payload",
    "capability_guarantees",
)

FINGERPRINT_COVERS_DESC = (
    "A contract-semantic change in any listed category changes the fingerprint; nothing "
    "outside them does. Release identity is excluded: serverInfo.version, version, "
    "server_version change every release WITHOUT moving the fingerprint. surface_digest "
    "is the sha256 of the built manifest and moves with the fingerprint, never alone."
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_codes.py -v --no-cov`
Expected: all PASS. If `test_error_codes_cover...` fails on `ERROR_CODES == tuple(sorted(catalog))` because the `ErrorCode` Literal disagrees with the derived tuple, fix the Literal to match the derived tuple (the tuple is the authority; the Literal exists so pydantic can publish the enum).

- [ ] **Step 5: Commit**

```bash
git add src/amicus/schemas tests/test_codes.py
git commit -m "feat(schemas): derive the closed code catalog from pontonier's taxonomy

Backend ids, verbs, the error-code catalog (universal + generalized
backend_* + feature + local codes), the repair-step vocabulary and the
fingerprint constants. generalize_code rewrites only the four minted
per-backend codes so the catalog stays closed while error.backend names
the backend (ADR 0005)."
```

---

### Task 4: Error envelope, Meta, and the schema-publishing helpers

**Files:**
- Create: `src/amicus/schemas/publish.py`, `src/amicus/schemas/envelope.py`
- Test: `tests/test_envelope.py`, `tests/test_publish.py`

**Interfaces:**
- Consumes: `codes.ErrorCode`, `codes.RepairStep`, `codes.BackendId`, `fingerprint.FINGERPRINT`, `fingerprint.JSON_SCHEMA_DIALECT`, `amicus.__version__`.
- Produces (`publish`): `published_schema(*success_models, opaque_fields=None) -> dict`, `OPAQUE_ERROR_BRANCH`, `OPAQUE_META`, `RESULT_META_POINTER_DESC`, `ERROR_POINTER_DESC`, `KEPT_DESCRIPTIONS: set[str]` (mutable registry other modules add to before calling `published_schema`).
- Produces (`envelope`): models `Usage`, `ContextSummary`, `Workspace`, `InvalidArgument`, `Repair`, `ErrorDetail`, `ErrorInfo`, `ErrorResult`, `Meta`; constants `ERROR_ENVELOPE_SCHEMA`, `RESULT_META_SCHEMA`; functions `dump_success(model) -> dict`, `server_version_field()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_envelope.py`:

```python
"""The §6 envelope shape: invariants pydantic enforces and the published schemas encode."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from amicus import __version__
from amicus.schemas import envelope as e
from amicus.schemas.fingerprint import FINGERPRINT, JSON_SCHEMA_DIALECT


def test_repair_next_step_is_symbolic_and_optionals_default_none():
    r = e.Repair(next_step="poll_job_status")
    assert (r.tool, r.arguments, r.alternative) == (None, None, None)
    with pytest.raises(ValidationError):
        e.Repair(next_step="not_a_step")


def test_errorinfo_requires_temporary_and_retry_after_ms_in_schema():
    schema = e.ErrorInfo.model_json_schema()
    assert "temporary" in schema["required"]
    assert "retry_after_ms" in schema["required"]
    assert "backend" in schema["properties"]


def test_errorinfo_non_temporary_forbids_retry_after_ms():
    with pytest.raises(ValidationError):
        e.ErrorInfo(code="internal_error", message="x", temporary=False, retry_after_ms=5)
    with pytest.raises(ValidationError):
        e.ErrorInfo(code="backend_rate_limited", message="x", temporary=True, retry_after_ms=-1)
    ok = e.ErrorInfo(
        code="backend_rate_limited", message="x", backend="codex", temporary=True, retry_after_ms=1
    )
    assert ok.backend == "codex"


def test_errorinfo_rejects_unknown_code_and_malformed_backend_id():
    with pytest.raises(ValidationError):
        e.ErrorInfo(code="codex_not_found", message="x", temporary=False, retry_after_ms=None)
    # `backend` is an open lowercase identifier (third-party plugins carry their own id),
    # not the v1 enum; only the shape is validated.
    with pytest.raises(ValidationError):
        e.ErrorInfo(
            code="internal_error", message="x", backend="Not-An-Id", temporary=False, retry_after_ms=None
        )
    assert e.ErrorInfo(
        code="internal_error", message="x", backend="fake", temporary=False, retry_after_ms=None
    ).backend == "fake"


def test_errordetail_field_and_fields_are_exclusive_and_value_is_absent():
    assert "value" not in e.ErrorDetail.model_fields
    assert e.ErrorDetail(field="question").field == "question"
    assert e.ErrorDetail(fields=["a", "b"]).fields == ["a", "b"]
    with pytest.raises(ValidationError):
        e.ErrorDetail(field="a", fields=["a", "b"])
    with pytest.raises(ValidationError):
        e.ErrorDetail(fields=[])
    with pytest.raises(ValidationError):
        e.ErrorDetail(fields=["a", "a"])
    assert "minItems" in json.dumps(e.ErrorDetail.model_json_schema()["properties"]["fields"])


def test_meta_defaults_and_identity():
    m = e.Meta()
    assert m.cwd is None and m.backend is None
    assert m.fingerprint == FINGERPRINT
    assert m.server_version == __version__
    assert len(m.request_id) == 32
    assert m.elapsed_ms == 0 and m.truncated is False
    with pytest.raises(ValidationError):
        e.Meta(backend="Not-An-Id")
    with pytest.raises(ValidationError):
        e.Meta(unknown_key=1)


def test_meta_field_names_are_the_documented_set():
    assert list(e.Meta.model_fields) == [
        "backend",
        "cwd",
        "workspace_source",
        "workspace_warning",
        "roots_source",
        "model",
        "reasoning_effort",
        "timeout_seconds",
        "elapsed_ms",
        "command_exit_code",
        "session_id",
        "truncated",
        "truncation_hint",
        "compat_warnings",
        "security_warnings",
        "redacted_paths",
        "usage",
        "context_summary",
        "job_id",
        "job_kind",
        "task_id",
        "idempotency_replayed",
        "backend_details",
        "request_id",
        "fingerprint",
        "server_version",
    ]


def test_usage_carries_cache_fields():
    u = e.Usage(input_tokens=1, cached_input_tokens=2, cache_creation_input_tokens=3)
    assert (u.cached_input_tokens, u.cache_creation_input_tokens) == (2, 3)
    assert u.total_tokens is None


def test_error_envelope_schema_is_hardened():
    s = e.ERROR_ENVELOPE_SCHEMA
    assert s["$schema"] == JSON_SCHEMA_DIALECT
    assert "ok" in s["required"]
    info = s["$defs"]["ErrorInfo"]
    assert info["if"] == {"properties": {"temporary": {"const": False}}, "required": ["temporary"]}
    assert info["then"] == {"properties": {"retry_after_ms": {"const": None}}}
    # The offending-value policy is disclosed on the envelope resource ([6.offending-value]).
    assert "details.value" in s["description"]


def test_result_meta_schema_carries_dialect_and_delivered_shape_rule():
    s = e.RESULT_META_SCHEMA
    assert s["$schema"] == JSON_SCHEMA_DIALECT
    assert "backend" in s["properties"]
    assert "null-valued keys" in s["description"]


def test_dump_success_retains_nulls():
    class Model(e.SuccessBase):
        tool: str = "amicus_consult"
        summary: str = "s"

    out = e.dump_success(Model(meta=e.Meta()))
    assert out["ok"] is True
    assert "cwd" in out["meta"] and out["meta"]["cwd"] is None
```

`tests/test_publish.py`:

```python
"""published_schema: success branches plus one opaque error branch, noise stripped."""

from __future__ import annotations

from typing import Literal

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from amicus.schemas import publish
from amicus.schemas.envelope import Meta, SuccessBase


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str  # a real field named `title` must survive the title-strip
    n: int = Field(default=0, description="generated noise to strip")


class One(SuccessBase):
    tool: Literal["one"] = "one"
    summary: str
    inner: Inner | None = None


class Two(SuccessBase):
    tool: Literal["two"] = "two"
    summary: str
    items: list[Inner] = Field(default_factory=list)


def test_single_model_schema_shape():
    s = publish.published_schema(One)
    assert s["$schema"] == publish.JSON_SCHEMA_DIALECT
    assert s["required"] == ["ok"]
    assert s["anyOf"][-1] == publish.OPAQUE_ERROR_BRANCH
    success = s["anyOf"][0]
    assert success["properties"]["meta"] == publish.OPAQUE_META
    assert "Meta" not in s["$defs"]
    assert "Inner" in s["$defs"]
    # Property NAMES named like annotation keywords survive; annotations are stripped.
    assert "title" in s["$defs"]["Inner"]["properties"]
    assert "description" not in s["$defs"]["Inner"]["properties"]["n"]
    assert "default" not in s["$defs"]["Inner"]["properties"]["n"]
    Draft202012Validator.check_schema(s)


def test_union_schema_keeps_both_success_branches():
    s = publish.published_schema(One, Two)
    assert len(s["anyOf"]) == 3
    assert {b["properties"]["tool"]["const"] for b in s["anyOf"][:2]} == {"one", "two"}


def test_opaque_fields_replace_named_properties_and_prune_their_defs():
    stub = {"type": "array", "description": "elsewhere"}
    publish.KEPT_DESCRIPTIONS.add("elsewhere")
    s = publish.published_schema(Two, opaque_fields={"items": stub})
    assert s["anyOf"][0]["properties"]["items"] == stub
    assert "Inner" not in s["$defs"]


def test_error_envelope_validates_against_any_published_schema():
    s = publish.published_schema(One)
    env = {
        "ok": False,
        "error": {"code": "internal_error", "message": "m", "temporary": True, "retry_after_ms": None},
        "meta": {},
    }
    Draft202012Validator(s).validate(env)
    with pytest.raises(Exception, match="is not valid"):
        Draft202012Validator(s).validate({"ok": True})


def test_success_payload_validates():
    s = publish.published_schema(One)
    payload = One(summary="s", meta=Meta()).model_dump(mode="json")
    Draft202012Validator(s).validate(payload)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_envelope.py tests/test_publish.py -v --no-cov`
Expected: FAIL with `ImportError` (no `amicus.schemas.envelope` / `publish`).

- [ ] **Step 3: Write `src/amicus/schemas/publish.py`**

```python
"""Advertised outputSchema construction (ported from codex-in-claude schemas.py).

Every tool advertises its success branch(es) plus ONE fully opaque error branch. The
full Meta object is collapsed to an opaque pointer (it is published once at
amicus://result-meta), generated title/description/default noise is stripped, and
$defs orphaned by the opaquing are pruned. Descriptions registered in
KEPT_DESCRIPTIONS survive the strip; register a pointer/semantic description there
BEFORE the schema that carries it is built.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, TypeAdapter

from amicus.schemas.fingerprint import JSON_SCHEMA_DIALECT

ERROR_POINTER_DESC = "Populated error envelope; full schema at resource amicus://error-envelope"
OPAQUE_ERROR_BRANCH: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "error", "meta"],
    "properties": {
        "ok": {"const": False},
        "error": {"type": "object", "description": ERROR_POINTER_DESC},
        "meta": {"type": "object"},
    },
}
RESULT_META_POINTER_DESC = (
    "Result metadata (backend, cwd, model, timeout, usage, job_id, and more); full "
    "schema at resource amicus://result-meta"
)
OPAQUE_META: dict[str, Any] = {"type": "object", "description": RESULT_META_POINTER_DESC}
_META_REF = {"$ref": "#/$defs/Meta"}

# Descriptions that survive _strip_schema_noise. Other modules add their pointer and
# semantic descriptions here at import time, before building their schemas.
KEPT_DESCRIPTIONS: set[str] = {ERROR_POINTER_DESC, RESULT_META_POINTER_DESC}

_SUBSCHEMA_MAPS = frozenset(
    ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas")
)


def _strip_schema_noise(node: object) -> object:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("title", "default"):
                continue
            if k == "description" and v not in KEPT_DESCRIPTIONS:
                continue
            if k in _SUBSCHEMA_MAPS and isinstance(v, dict):
                out[k] = {name: _strip_schema_noise(sub) for name, sub in v.items()}
            else:
                out[k] = _strip_schema_noise(v)
        return out
    if isinstance(node, list):
        return [_strip_schema_noise(v) for v in node]
    return node


def _opaque_meta_refs(node: object) -> object:
    if isinstance(node, dict):
        if node == _META_REF:
            return dict(OPAQUE_META)
        return {k: _opaque_meta_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_opaque_meta_refs(v) for v in node]
    return node


def _local_def_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            names.add(ref.split("/")[-1])
        for v in node.values():
            names |= _local_def_names(v)
    elif isinstance(node, list):
        for v in node:
            names |= _local_def_names(v)
    return names


def _prune_defs(doc: dict[str, Any]) -> dict[str, Any]:
    defs = doc.get("$defs")
    if not defs:
        return doc
    body = {k: v for k, v in doc.items() if k != "$defs"}
    reachable: set[str] = set()
    frontier = _local_def_names(body)
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in defs:
            continue
        reachable.add(name)
        frontier |= _local_def_names(defs[name])
    doc["$defs"] = {k: v for k, v in defs.items() if k in reachable}
    return doc


def published_schema(
    *success_models: type[BaseModel],
    opaque_fields: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A tool's advertised outputSchema: success branch(es) plus one opaque error branch.

    ``opaque_fields`` maps a top-level success-branch property to a compact stub; the
    closure it referenced is pruned, the same shrink Meta gets."""
    if len(success_models) == 1:
        adapter: TypeAdapter[Any] = TypeAdapter(success_models[0])
    else:
        union: Any = success_models[0]
        for m in success_models[1:]:
            union = union | m
        adapter = TypeAdapter(union)
    raw = adapter.json_schema(ref_template="#/$defs/{model}")
    branches = list(raw["anyOf"]) if "anyOf" in raw else [
        {k: v for k, v in raw.items() if k != "$defs"}
    ]
    doc: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DIALECT,
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "description": "true = success result, false = error result"},
        },
        "required": ["ok"],
        "anyOf": [*branches, OPAQUE_ERROR_BRANCH],
        "$defs": raw.get("$defs", {}),
    }
    if opaque_fields:
        for branch in branches:
            props = branch.get("properties")
            if not props:
                continue
            for field, stub in opaque_fields.items():
                if field in props:
                    props[field] = dict(stub)
    opaqued = _opaque_meta_refs(doc)
    assert isinstance(opaqued, dict)
    pruned = _prune_defs(opaqued)
    result = _strip_schema_noise(pruned)
    assert isinstance(result, dict)
    return result
```

Also add the description `"true = success result, false = error result"` to `KEPT_DESCRIPTIONS` (append to the set literal above), so the `ok` property keeps its description.

- [ ] **Step 4: Write `src/amicus/schemas/envelope.py`**

```python
"""The §6 error envelope, result metadata, and the success-envelope base (ADR 0005)."""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from amicus import __version__
from amicus.schemas import publish
from amicus.schemas.codes import ErrorCode, RepairStep
from amicus.schemas.fingerprint import FINGERPRINT, JSON_SCHEMA_DIALECT

WorkspaceSource = Literal["param", "roots", "cwd"]
RootsSource = Literal["client", "not_negotiated", "probe_failed"]
# A backend id on the wire is an open lowercase identifier (the same shape pontonier's
# BackendContract enforces), so a third-party plugin's id fits; the `backend` PARAMETER is
# the v1 enum. Every result field named backend/id uses this alias.
BackendRef = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


def server_version_field() -> Any:
    """Release identity beside the contract identity (`fingerprint`). A default_factory
    keeps the literal out of the published schemas, so a release moves no snapshot."""
    return Field(
        default_factory=lambda: __version__,
        description=(
            "amicus package version attributed to this result. A replayed job result "
            "preserves the version of the run that produced it. Omitted when a stored "
            "payload predates this field — never backfilled, never sent as null."
        ),
    )


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


class ContextSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0


class Workspace(BaseModel):
    """Compact workspace context for job-lifecycle success responses."""

    model_config = ConfigDict(extra="forbid")
    cwd: str
    workspace_source: WorkspaceSource | None = None
    workspace_warning: str | None = None


class Meta(BaseModel):
    """Execution metadata on every envelope. Every field is optional except the
    identity trio at the end; `cwd` is None when no workspace was resolved (argument
    errors, unimplemented tools). Backend-specific facts ride `backend_details`."""

    model_config = ConfigDict(extra="forbid")
    backend: BackendRef | None = None
    cwd: str | None = None
    workspace_source: WorkspaceSource | None = None
    workspace_warning: str | None = None
    roots_source: RootsSource | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int | None = None
    elapsed_ms: int = 0
    command_exit_code: int | None = None
    session_id: str | None = None
    truncated: bool = False
    truncation_hint: str | None = None
    compat_warnings: list[str] = Field(default_factory=list)
    security_warnings: list[str] = Field(default_factory=list)
    redacted_paths: list[str] = Field(default_factory=list)
    usage: Usage | None = None
    context_summary: ContextSummary | None = None
    job_id: str | None = None
    job_kind: str | None = None
    task_id: str | None = None
    idempotency_replayed: Literal[True] | None = None
    backend_details: dict[str, Any] | None = None
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    fingerprint: str = FINGERPRINT
    server_version: str | None = server_version_field()


class SuccessBase(BaseModel):
    """Every success envelope: `ok: true`, a `tool` discriminator, and `meta`."""

    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    meta: Meta


def dump_success(result: SuccessBase) -> dict[str, Any]:
    """Success envelopes retain null optionals (unlike serialize_error's exclude_none);
    the asymmetry is part of the persisted result format (RESULT_FORMAT)."""
    return result.model_dump(mode="json")


class InvalidArgument(BaseModel):
    """One field-level argument failure. The rejected VALUE is never echoed."""

    model_config = ConfigDict(extra="forbid")
    field: str
    reason: str
    allowed_values: list[str] | None = None
    field_withheld: bool = False


class Repair(BaseModel):
    """Machine-actionable recovery: a symbolic `next_step`, the single callable
    `tool`/`arguments`, and an optional prose `alternative` ([6.repair-object])."""

    model_config = ConfigDict(extra="forbid")
    next_step: RepairStep
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    alternative: str | None = None


class ErrorDetail(BaseModel):
    """§6 details. `value` is omitted by policy (disclosed on amicus://error-envelope).
    Exactly one of `field`/`fields`, or neither."""

    model_config = ConfigDict(extra="forbid")
    field: str | None = None
    fields: (
        Annotated[list[str], Field(min_length=1, json_schema_extra={"uniqueItems": True})] | None
    ) = None
    reason: str | None = None
    allowed_values: list[str] | None = None
    field_withheld: bool = False

    @model_validator(mode="after")
    def _one_of_field_or_fields(self) -> ErrorDetail:
        if self.field is not None and self.fields is not None:
            raise ValueError("ErrorDetail: set at most one of field/fields, never both")
        if self.fields is not None and len(set(self.fields)) != len(self.fields):
            raise ValueError("ErrorDetail.fields must not contain duplicates")
        return self


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: ErrorCode
    message: str
    backend: BackendRef | None = None
    temporary: bool = Field(...)
    retry_after_ms: int | None = Field(..., ge=0)
    repair: Repair | None = None
    details: ErrorDetail | None = None
    invalid_arguments: list[InvalidArgument] | None = None
    limit_bytes: int | None = None
    actual_bytes: int | None = None
    candidate_roots: list[str] | None = None
    resource_uri: str | None = None
    request_id: str | None = None

    @model_validator(mode="after")
    def _retry_after_only_when_temporary(self) -> ErrorInfo:
        if not self.temporary and self.retry_after_ms is not None:
            raise ValueError("retry_after_ms must be None when temporary is False")
        return self


class ErrorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[False] = False
    error: ErrorInfo
    meta: Meta


_OFFENDING_VALUE_POLICY = (
    "details.value is omitted for every caller-supplied input: a string parameter can "
    "receive a mispasted secret and best-effort redaction cannot catch a plain one, so "
    "the caller — who already holds what it sent — repairs from field, reason and "
    "allowed_values. Machine identifiers this server minted (job_id) are refused, never "
    "echoed, when they carry a control character."
)


def _harden_error_envelope_schema(schema: dict[str, Any]) -> dict[str, Any]:
    s = copy.deepcopy(schema)
    s["$schema"] = JSON_SCHEMA_DIALECT
    s["description"] = (
        "The full error envelope every ok:false tool result carries in structuredContent; "
        "resource-read failures carry error (with code/message renamed machine_code/"
        f"human_message) in JSON-RPC error.data. {_OFFENDING_VALUE_POLICY}"
    )
    required = s.setdefault("required", [])
    if "ok" not in required:
        required.append("ok")
    info = s["$defs"]["ErrorInfo"]
    info["if"] = {"properties": {"temporary": {"const": False}}, "required": ["temporary"]}
    info["then"] = {"properties": {"retry_after_ms": {"const": None}}}
    return s


ERROR_ENVELOPE_SCHEMA = _harden_error_envelope_schema(
    TypeAdapter(ErrorResult).json_schema(ref_template="#/$defs/{model}")
)

RESULT_META_SCHEMA: dict[str, Any] = TypeAdapter(Meta).json_schema(ref_template="#/$defs/{model}")
RESULT_META_SCHEMA["$schema"] = JSON_SCHEMA_DIALECT
RESULT_META_SCHEMA["description"] = (
    "The full result-metadata contract. Every success envelope's `meta` is advertised "
    "as an opaque pointer to this schema. On the wire a delivered success envelope drops "
    "meta's null-valued keys; absence means exactly what null means (not applicable / not "
    "reported). Error envelopes strip absent optionals except retry_after_ms."
)

# The `ok` discriminator description survives noise stripping on every published schema.
publish.KEPT_DESCRIPTIONS.add("true = success result, false = error result")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_envelope.py tests/test_publish.py tests/test_codes.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`
Expected: clean (run `uv run ruff format src tests` if formatting differs).

```bash
git add src/amicus/schemas/publish.py src/amicus/schemas/envelope.py tests/test_envelope.py tests/test_publish.py
git commit -m "feat(schemas): add the error envelope, Meta, and schema publishing

Ports codex-in-claude's ErrorInfo/Repair/ErrorDetail shape with a
backend field, the opaque-meta/opaque-error published_schema helper,
and the hardened error-envelope and result-meta schemas that the
amicus:// resources serve (ADR 0005, ADR 0006)."
```

---

### Task 5: Result models and published output schemas

**Files:**
- Create: `src/amicus/schemas/results.py`
- Test: `tests/test_results.py`

**Interfaces:**
- Consumes: `envelope.SuccessBase`, `envelope.Meta`, `envelope.Repair`, `envelope.Workspace`, `envelope.ContextSummary`, `envelope.Usage`, `publish.published_schema`, `codes.BackendId`, `codes.ErrorCode`, `fingerprint.*`.
- Produces: models `Finding`, `RawResponse`, `ConsultResult`, `ReviewResult`, `AdversarialReviewResult`, `DelegateResult`, `JobStarted`, `JobStatus`, `JobSummary`, `JobListResult`, `DryRunResult`, `WorktreePlan`, `DelegateDryRunResult`, `BackendStatus`, `BackendOptionInfo`, `BackendEntry`, `UnavailableEntry`, `BackendsResult`, `ModelInfo`, `ModelCatalogResult`, `TaskSupport`, `ToolCapability`, `CapabilitiesResult`; literals `Severity`, `Verdict`, `Confidence`, `ReviewScope`, `Untracked`, `Detail`, `CapabilitiesDetail`, `JobState`, `ToolStability`, `ReviewStatus`; schema constants `CONSULT_RESULT_SCHEMA`, `REVIEW_RESULT_SCHEMA`, `ADVERSARIAL_RESULT_SCHEMA`, `DELEGATE_RESULT_SCHEMA`, `JOB_STARTED_SCHEMA`, `JOB_STATUS_SCHEMA`, `JOB_RESULT_SCHEMA`, `JOB_LIST_SCHEMA`, `DRY_RUN_SCHEMA`, `DELEGATE_DRY_RUN_SCHEMA`, `BACKENDS_SCHEMA`, `MODEL_CATALOG_SCHEMA`, `CAPABILITIES_SCHEMA`, `CAPABILITIES_RESULT_SCHEMA`; `PAID_TOOLS: tuple[str, ...]` (the four sync paid tools' names, the `tool` discriminator values).

- [ ] **Step 1: Write the failing test**

`tests/test_results.py`:

```python
"""Result models: discriminators, published schemas, and the opaque job-result union."""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from amicus.schemas import results as r
from amicus.schemas.envelope import Meta, Repair
from amicus.schemas.fingerprint import JSON_SCHEMA_DIALECT

ALL_SCHEMAS = {
    "CONSULT_RESULT_SCHEMA": r.CONSULT_RESULT_SCHEMA,
    "REVIEW_RESULT_SCHEMA": r.REVIEW_RESULT_SCHEMA,
    "ADVERSARIAL_RESULT_SCHEMA": r.ADVERSARIAL_RESULT_SCHEMA,
    "DELEGATE_RESULT_SCHEMA": r.DELEGATE_RESULT_SCHEMA,
    "JOB_STARTED_SCHEMA": r.JOB_STARTED_SCHEMA,
    "JOB_STATUS_SCHEMA": r.JOB_STATUS_SCHEMA,
    "JOB_RESULT_SCHEMA": r.JOB_RESULT_SCHEMA,
    "JOB_LIST_SCHEMA": r.JOB_LIST_SCHEMA,
    "DRY_RUN_SCHEMA": r.DRY_RUN_SCHEMA,
    "DELEGATE_DRY_RUN_SCHEMA": r.DELEGATE_DRY_RUN_SCHEMA,
    "BACKENDS_SCHEMA": r.BACKENDS_SCHEMA,
    "MODEL_CATALOG_SCHEMA": r.MODEL_CATALOG_SCHEMA,
    "CAPABILITIES_SCHEMA": r.CAPABILITIES_SCHEMA,
}


@pytest.mark.parametrize("name", sorted(ALL_SCHEMAS))
def test_every_published_schema_is_valid_and_carries_the_dialect(name):
    s = ALL_SCHEMAS[name]
    Draft202012Validator.check_schema(s)
    assert s["$schema"] == JSON_SCHEMA_DIALECT
    assert s["anyOf"][-1]["properties"]["ok"] == {"const": False}


@pytest.mark.parametrize("name", sorted(ALL_SCHEMAS))
def test_error_catalog_is_not_inlined_per_tool(name):
    assert "backend_auth_required" not in json.dumps(ALL_SCHEMAS[name])


def test_paid_tool_discriminators():
    assert r.PAID_TOOLS == (
        "amicus_consult",
        "amicus_review_changes",
        "amicus_adversarial_review",
        "amicus_delegate",
    )
    assert r.ConsultResult(summary="s", meta=Meta()).tool == "amicus_consult"
    assert r.DelegateResult(summary="s", diff=None, meta=Meta()).tool == "amicus_delegate"
    review = r.ReviewResult(summary="s", verdict="pass", confidence="high", meta=Meta())
    assert review.review_status == "completed"


def test_job_result_schema_is_an_opaque_union_over_the_paid_tools():
    branch = r.JOB_RESULT_SCHEMA["anyOf"][0]
    assert set(branch["properties"]["tool"]["enum"]) == set(r.PAID_TOOLS)
    assert r.JOB_RESULT_SCHEMA["$defs"] == {}


def test_success_payloads_validate_against_their_schemas():
    meta = Meta(backend="codex")
    cases = [
        (r.CONSULT_RESULT_SCHEMA, r.ConsultResult(summary="s", meta=meta)),
        (
            r.REVIEW_RESULT_SCHEMA,
            r.ReviewResult(summary="s", verdict="concerns", confidence="low", meta=meta),
        ),
        (
            r.ADVERSARIAL_RESULT_SCHEMA,
            r.AdversarialReviewResult(summary="s", verdict="fail", confidence="high", meta=meta),
        ),
        (r.DELEGATE_RESULT_SCHEMA, r.DelegateResult(summary="s", diff="d", meta=meta)),
        (
            r.JOB_STARTED_SCHEMA,
            r.JobStarted(
                job_id="a" * 32,
                backend="codex",
                kind="amicus_consult",
                started_at="2026-09-04T00:00:00Z",
                deadline_seconds=1800,
                poll_after_ms=1000,
                expires_at=None,
                follow_up=Repair(next_step="poll_job_status", tool="amicus_job_status"),
                meta=meta,
            ),
        ),
    ]
    for schema, model in cases:
        Draft202012Validator(schema).validate(model.model_dump(mode="json"))


def test_capabilities_schema_opaques_tool_details_and_keeps_error_codes_required():
    props = r.CAPABILITIES_SCHEMA["anyOf"][0]["properties"]
    assert props["tool_details"]["type"] == "array"
    assert "capabilities-result" in props["tool_details"]["description"]
    assert "error_codes" in r.CAPABILITIES_SCHEMA["anyOf"][0]["required"]
    assert "ToolCapability" in r.CAPABILITIES_RESULT_SCHEMA["$defs"]


def test_backends_result_shape():
    entry = r.BackendEntry(
        id="codex",
        display_name="Codex",
        enabled=True,
        available=False,
        features=[],
        effects=r.EffectsInfo(paid_calls_destructive=False, job_reads_read_only=True),
        options=[],
    )
    res = r.BackendsResult(backends=[entry], unavailable=[], env_warnings=[], config_errors=[])
    assert res.ok is True and res.backends[0].status is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_results.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'results'`.

- [ ] **Step 3: Write `src/amicus/schemas/results.py`**

```python
"""Success result models for every tool, and their advertised outputSchemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from amicus.schemas import publish
from amicus.schemas.codes import ErrorCode
from amicus.schemas.envelope import (
    BackendRef,
    ContextSummary,
    Meta,
    Repair,
    SuccessBase,
    Workspace,
    server_version_field,
)
from amicus.schemas.fingerprint import (
    FINGERPRINT,
    FINGERPRINT_COVERS,
    FINGERPRINT_COVERS_DESC,
    JSON_SCHEMA_DIALECT,
    PROTOCOL_REVISION,
)

Severity = Literal["critical", "high", "medium", "low", "nit"]
Verdict = Literal["pass", "concerns", "fail", "unknown"]
Confidence = Literal["low", "medium", "high"]
ReviewScope = Literal["working_tree", "branch", "commit"]
Untracked = Literal["explicit_only", "include", "exclude"]
Detail = Literal["summary", "full"]
CapabilitiesDetail = Literal["summary", "full", "contracts"]
JobState = Literal["running", "done", "failed", "cancelled", "timeout"]
ToolStability = Literal["stable", "preview", "experimental"]
ReviewStatus = Literal["completed", "not_run"]

PAID_TOOLS: tuple[str, ...] = (
    "amicus_consult",
    "amicus_review_changes",
    "amicus_adversarial_review",
    "amicus_delegate",
)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    severity: Severity = "medium"
    file: str | None = None
    line: int | None = None
    evidence: str | None = None
    suggestion: str | None = None


class RawResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    session_id: str | None = None
    model: str | None = None


class _ModelResult(SuccessBase):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    raw_response: RawResponse | None = None


class ConsultResult(_ModelResult):
    tool: Literal["amicus_consult"] = "amicus_consult"


class ReviewResult(_ModelResult):
    tool: Literal["amicus_review_changes"] = "amicus_review_changes"
    verdict: Verdict
    confidence: Confidence
    review_status: ReviewStatus = "completed"
    context_summary: ContextSummary | None = None


class AdversarialReviewResult(_ModelResult):
    tool: Literal["amicus_adversarial_review"] = "amicus_adversarial_review"
    verdict: Verdict
    confidence: Confidence


class DelegateResult(_ModelResult):
    tool: Literal["amicus_delegate"] = "amicus_delegate"
    diff: str | None
    diffstat: str | None = None


# --- jobs -----------------------------------------------------------------------------


class JobStarted(SuccessBase):
    job_id: str
    backend: BackendRef
    kind: str
    status: Literal["running"] = "running"
    started_at: str
    deadline_seconds: int
    poll_after_ms: int
    expires_at: str | None
    task_id: str | None = None
    follow_up: Repair


class JobStatus(SuccessBase):
    job_id: str
    backend: BackendRef
    kind: str
    status: JobState
    elapsed_ms: int
    result_available: bool
    result_ok: bool | None
    poll_after_ms: int | None = None
    expires_at: str | None
    task_id: str | None = None
    workspace: Workspace
    cleanup_warnings: list[str] = Field(default_factory=list)


class JobSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    backend: BackendRef
    kind: str
    status: JobState
    started_at: str
    elapsed_ms: int
    result_available: bool
    result_ok: bool | None
    expires_at: str | None
    task_id: str | None = None


class JobListResult(SuccessBase):
    jobs: list[JobSummary]
    workspace: Workspace
    truncated: bool = False
    truncation_hint: str | None = None


# --- previews -------------------------------------------------------------------------


class DryRunResult(SuccessBase):
    tool: Literal["amicus_dry_run"] = "amicus_dry_run"
    backend: BackendRef
    would_call_model: bool
    scope: ReviewScope
    base: str | None = None
    commit: str | None = None
    paths: list[str] | None = None
    prompt_bytes: int
    context_summary: ContextSummary | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    backend_options: dict[str, Any] = Field(default_factory=dict)
    workspace: Workspace
    warnings: list[str] = Field(default_factory=list)


class WorktreePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_ref: str
    prefix: str


class DelegateDryRunResult(SuccessBase):
    tool: Literal["amicus_delegate_dry_run"] = "amicus_delegate_dry_run"
    backend: BackendRef
    task_bytes: int
    worktree: WorktreePlan
    model: str | None = None
    reasoning_effort: str | None = None
    backend_options: dict[str, Any] = Field(default_factory=dict)
    workspace: Workspace
    warnings: list[str] = Field(default_factory=list)


# --- discovery ------------------------------------------------------------------------


class BackendStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installed: bool
    version: str | None = None
    authenticated: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class EffectsInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paid_calls_destructive: bool
    job_reads_read_only: bool


class BackendOptionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    allowed_values: list[str] | None = None
    default: str | float | None = None


class BackendEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: BackendRef
    display_name: str
    enabled: bool
    available: bool
    status: BackendStatus | None = None
    features: list[str]
    effects: EffectsInfo
    options: list[BackendOptionInfo]
    egress: str | None = None
    carriers: str | None = None
    readonly_honesty: str | None = None
    implicit_context: str | None = None


class UnavailableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    reason: str
    detail: str


class BackendsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    backends: list[BackendEntry]
    unavailable: list[UnavailableEntry]
    env_warnings: list[str]
    config_errors: list[str]
    fingerprint: str = FINGERPRINT
    server_version: str | None = server_version_field()


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    display_name: str | None = None
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: list[str] | None = None


class ModelCatalogResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    backend: BackendRef
    available: bool
    models: list[ModelInfo]
    source: Literal["cache", "static", "live", "none"]
    fetched_at: str | None = None
    fingerprint: str = FINGERPRINT
    server_version: str | None = server_version_field()


class TaskSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    extension: str = "io.modelcontextprotocol/tasks"
    task_tools: list[str]
    fallback: str


_TOOL_STABILITY_DESC = (
    "Per-tool maturity override, advisory only. null inherits the top-level `stability`."
)
_TOOL_DETAILS_POINTER_DESC = (
    "Per-tool capability records; full schema via "
    "amicus_capabilities(include_schemas=['capabilities-result'])"
)
publish.KEPT_DESCRIPTIONS.update({_TOOL_STABILITY_DESC, _TOOL_DETAILS_POINTER_DESC})


class ToolCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    cost: Literal["free", "active"]
    stability: ToolStability | None = Field(default=None, description=_TOOL_STABILITY_DESC)
    backends: list[BackendRef] | None = None
    use_when: str | None = None
    required_params: list[str] = Field(default_factory=list)
    key_optional_params: list[str] = Field(default_factory=list)
    returns: str | None = None
    error_codes: list[ErrorCode] = Field(default_factory=list)


class CapabilitiesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    name: str
    version: str
    fingerprint: str = FINGERPRINT
    surface_digest: str
    server_version: str | None = server_version_field()
    fingerprint_covers: list[str] = Field(
        default_factory=lambda: list(FINGERPRINT_COVERS), description=FINGERPRINT_COVERS_DESC
    )
    protocol_revision: str = PROTOCOL_REVISION
    transport: str
    stability: str
    enabled_backends: list[BackendRef]
    active_tools: list[str]
    free_tools: list[str]
    job_tools: list[str]
    tool_details: list[ToolCapability] = Field(default_factory=list)
    error_codes: list[str]
    scope: list[str]
    negative_scope: list[str]
    prerequisites: list[str]
    deprecation_policy: str
    tool_error_carrier: str
    resource_error_carrier: str
    annotations_reading: str
    tasks: TaskSupport
    meta_fields: list[str]
    error_envelope_resource: str = "amicus://error-envelope"
    result_meta_resource: str = "amicus://result-meta"
    params_resource: str = "amicus://params"
    schemas: dict[str, Any] | None = None


publish.KEPT_DESCRIPTIONS.add(FINGERPRINT_COVERS_DESC)

CONSULT_RESULT_SCHEMA = publish.published_schema(ConsultResult)
REVIEW_RESULT_SCHEMA = publish.published_schema(ReviewResult)
ADVERSARIAL_RESULT_SCHEMA = publish.published_schema(AdversarialReviewResult)
DELEGATE_RESULT_SCHEMA = publish.published_schema(DelegateResult)
JOB_STARTED_SCHEMA = publish.published_schema(JobStarted)
JOB_STATUS_SCHEMA = publish.published_schema(JobStatus)
JOB_LIST_SCHEMA = publish.published_schema(JobListResult)
DRY_RUN_SCHEMA = publish.published_schema(DryRunResult)
DELEGATE_DRY_RUN_SCHEMA = publish.published_schema(DelegateDryRunResult)
BACKENDS_SCHEMA = publish.published_schema(BackendsResult)
MODEL_CATALOG_SCHEMA = publish.published_schema(ModelCatalogResult)
CAPABILITIES_SCHEMA = publish.published_schema(
    CapabilitiesResult,
    opaque_fields={"tool_details": {"type": "array", "description": _TOOL_DETAILS_POINTER_DESC}},
)

# amicus_job_result / amicus_job_consume_result return exactly the originating paid tool's
# envelope; the success branch is opaque and points at that tool's advertised schema.
_OPAQUE_JOB_SUCCESS_BRANCH: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "tool"],
    "properties": {
        "ok": {"const": True},
        "tool": {
            "enum": list(PAID_TOOLS),
            "description": (
                "Originating tool; the payload matches that tool's advertised outputSchema "
                "success branch — branch on this field."
            ),
        },
    },
}
JOB_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": JSON_SCHEMA_DIALECT,
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "description": "true = success result, false = error result"},
    },
    "required": ["ok"],
    "anyOf": [_OPAQUE_JOB_SUCCESS_BRANCH, publish.OPAQUE_ERROR_BRANCH],
    "$defs": {},
}

# Full capabilities shape, reachable via amicus_capabilities(include_schemas=[...]).
CAPABILITIES_RESULT_SCHEMA: dict[str, Any] = TypeAdapter(CapabilitiesResult).json_schema(
    ref_template="#/$defs/{model}"
)
CAPABILITIES_RESULT_SCHEMA["$schema"] = JSON_SCHEMA_DIALECT
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_results.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/schemas/results.py tests/test_results.py
git commit -m "feat(schemas): add the result models and published output schemas

One success model per tool with a tool discriminator, the opaque
job-result union over the four paid tools, and the discovery payloads
(backends catalog, model catalog, capabilities with surface_digest)."
```

---

### Task 6: Parameter matrix, aliases, and parameter contracts

**Files:**
- Create: `src/amicus/schemas/params.py`
- Test: `tests/test_params.py`

**Interfaces:**
- Consumes: `codes.BackendId`, `codes.VERBS`, `results.ReviewScope`, `results.Untracked`, `results.Detail`, `results.CapabilitiesDetail`, `results.JobState`, `options.BackendOptions` (Task 7 — this task's `BackendOptionsParam` alias imports it; write Task 7's `options.py` first if you execute out of order, or temporarily stub the import).
- Produces: `PARAM_MATRIX: dict[str, frozenset[str]]` (parameter → verbs), `REQUIRED_BY_VERB: dict[str, frozenset[str]]`, `SYNC_ONLY_PARAMS`, `ASYNC_ONLY_PARAMS`, `TOOL_VERB: dict[str, tuple[str, bool]]` (tool name → (verb, is_async)), `expected_params(tool_name) -> frozenset[str]`, `expected_required(tool_name) -> frozenset[str]`, the `Annotated` aliases named below, `ParamContract`, `PARAMETER_CONTRACTS`, `PARAMS_RESOURCE_URI = "amicus://params"`, `params_resource_body() -> dict`, `MIN_TIMEOUT_SECONDS = 10`, `MAX_TIMEOUT_SECONDS = 600`, `CONTROL_CHAR_FREE_PATTERN`.

Note: `CONTROL_CHAR_FREE_PATTERN` and the reasoning-effort bounds live here (the params module is the single home for parameter shape facts); `field_policy.py` (Task 7) re-exports the pattern.

- [ ] **Step 1: Write the failing test**

`tests/test_params.py`:

```python
"""The verb × backend parameter matrix from the spec, written before any schema."""

from __future__ import annotations

import pytest

from amicus.schemas import params as p

ALL = frozenset({"consult", "review_changes", "adversarial_review", "delegate"})


def test_matrix_matches_the_spec_table():
    assert p.PARAM_MATRIX["backend"] == ALL
    for name in ("workspace_root", "model", "reasoning_effort", "backend_options"):
        assert p.PARAM_MATRIX[name] == ALL, name
    assert p.PARAM_MATRIX["timeout_seconds"] == ALL
    assert p.PARAM_MATRIX["detail"] == ALL
    assert p.PARAM_MATRIX["idempotency_key"] == ALL
    assert p.PARAM_MATRIX["extra_context"] == {"consult", "review_changes", "adversarial_review"}
    assert p.PARAM_MATRIX["instructions_append"] == {"consult", "review_changes"}
    for name in ("scope", "base", "commit", "paths", "untracked", "focus"):
        assert p.PARAM_MATRIX[name] == {"review_changes", "adversarial_review"}, name
    assert p.PARAM_MATRIX["target"] == {"adversarial_review"}
    assert p.PARAM_MATRIX["evidence"] == {"adversarial_review"}
    assert p.PARAM_MATRIX["task"] == {"delegate"}
    assert p.PARAM_MATRIX["question"] == {"consult"}
    assert set(p.PARAM_MATRIX) == {
        "backend", "workspace_root", "model", "reasoning_effort", "timeout_seconds", "detail",
        "idempotency_key", "extra_context", "instructions_append", "scope", "base", "commit",
        "paths", "untracked", "focus", "target", "evidence", "task", "question",
        "backend_options",
    }


def test_sync_and_async_splits():
    assert p.SYNC_ONLY_PARAMS == {"timeout_seconds", "detail"}
    assert p.ASYNC_ONLY_PARAMS == {"idempotency_key"}
    assert p.expected_params("amicus_consult") == {
        "backend", "question", "workspace_root", "extra_context", "instructions_append",
        "model", "reasoning_effort", "timeout_seconds", "detail", "backend_options",
    }
    assert p.expected_params("amicus_consult_async") == {
        "backend", "question", "workspace_root", "extra_context", "instructions_append",
        "model", "reasoning_effort", "idempotency_key", "backend_options",
    }
    assert p.expected_params("amicus_delegate_async") == {
        "backend", "task", "workspace_root", "model", "reasoning_effort", "idempotency_key",
        "backend_options",
    }
    assert "instructions_append" not in p.expected_params("amicus_adversarial_review")
    assert "instructions_append" not in p.expected_params("amicus_delegate")


def test_required_sets():
    assert p.expected_required("amicus_consult") == {"backend", "question"}
    assert p.expected_required("amicus_review_changes") == {"backend"}
    assert p.expected_required("amicus_adversarial_review") == {"backend", "target"}
    assert p.expected_required("amicus_delegate_async") == {"backend", "task"}


def test_tool_verb_covers_the_eight_paid_tools():
    assert set(p.TOOL_VERB) == {
        "amicus_consult", "amicus_consult_async", "amicus_review_changes",
        "amicus_review_changes_async", "amicus_adversarial_review",
        "amicus_adversarial_review_async", "amicus_delegate", "amicus_delegate_async",
    }
    assert p.TOOL_VERB["amicus_review_changes_async"] == ("review_changes", True)


def test_unknown_tool_raises():
    with pytest.raises(KeyError):
        p.expected_params("amicus_nope")


def test_parameter_contracts_have_summary_and_full_and_point_at_the_resource():
    assert set(p.PARAMETER_CONTRACTS) == {
        "idempotency_key", "extra_context", "instructions_append", "reasoning_effort",
        "backend_options", "workspace_root",
    }
    for c in p.PARAMETER_CONTRACTS.values():
        assert c.summary and c.full
        assert p.PARAMS_RESOURCE_URI in c.summary
        assert len(c.summary) < len(c.full)
    body = p.params_resource_body()
    assert set(body["params"]) == set(p.PARAMETER_CONTRACTS)


def test_timeout_bounds_and_pattern():
    assert (p.MIN_TIMEOUT_SECONDS, p.MAX_TIMEOUT_SECONDS) == (10, 600)
    assert p.CONTROL_CHAR_FREE_PATTERN == r"^[^\x00-\x1F\x7F-\x9F]*$"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_params.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'params'`.

- [ ] **Step 3: Write `src/amicus/schemas/params.py`**

```python
"""The verb × backend parameter matrix, the Annotated parameter aliases every tool is
built from, and the compressed/full parameter contracts served at amicus://params.

The MATRIX is the authority: tests derive each tool's expected inputSchema property set
from it, so a tool cannot grow a parameter the spec table does not grant it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field

from amicus.schemas.codes import BackendId
from amicus.schemas.options import BackendOptions
from amicus.schemas.results import CapabilitiesDetail, Detail, JobState, ReviewScope, Untracked

_ALL = frozenset({"consult", "review_changes", "adversarial_review", "delegate"})
_REVIEWS = frozenset({"review_changes", "adversarial_review"})

PARAM_MATRIX: dict[str, frozenset[str]] = {
    "backend": _ALL,
    "workspace_root": _ALL,
    "model": _ALL,
    "reasoning_effort": _ALL,
    "timeout_seconds": _ALL,
    "detail": _ALL,
    "idempotency_key": _ALL,
    "backend_options": _ALL,
    "extra_context": frozenset({"consult", "review_changes", "adversarial_review"}),
    # Not on adversarial_review (the fixed critic stance is the product) nor delegate
    # (edits files: a caller stance would widen what an untrusted workspace can steer).
    "instructions_append": frozenset({"consult", "review_changes"}),
    "scope": _REVIEWS,
    "base": _REVIEWS,
    "commit": _REVIEWS,
    "paths": _REVIEWS,
    "untracked": _REVIEWS,
    "focus": _REVIEWS,
    "target": frozenset({"adversarial_review"}),
    "evidence": frozenset({"adversarial_review"}),
    "task": frozenset({"delegate"}),
    "question": frozenset({"consult"}),
}
REQUIRED_BY_VERB: dict[str, frozenset[str]] = {
    "consult": frozenset({"backend", "question"}),
    "review_changes": frozenset({"backend"}),
    "adversarial_review": frozenset({"backend", "target"}),
    "delegate": frozenset({"backend", "task"}),
}
SYNC_ONLY_PARAMS = frozenset({"timeout_seconds", "detail"})
ASYNC_ONLY_PARAMS = frozenset({"idempotency_key"})

TOOL_VERB: dict[str, tuple[str, bool]] = {
    "amicus_consult": ("consult", False),
    "amicus_consult_async": ("consult", True),
    "amicus_review_changes": ("review_changes", False),
    "amicus_review_changes_async": ("review_changes", True),
    "amicus_adversarial_review": ("adversarial_review", False),
    "amicus_adversarial_review_async": ("adversarial_review", True),
    "amicus_delegate": ("delegate", False),
    "amicus_delegate_async": ("delegate", True),
}


def expected_params(tool_name: str) -> frozenset[str]:
    """The inputSchema property set the matrix grants ``tool_name``."""
    verb, is_async = TOOL_VERB[tool_name]
    names = {name for name, verbs in PARAM_MATRIX.items() if verb in verbs}
    names -= ASYNC_ONLY_PARAMS if not is_async else SYNC_ONLY_PARAMS
    return frozenset(names)


def expected_required(tool_name: str) -> frozenset[str]:
    verb, _ = TOOL_VERB[tool_name]
    return REQUIRED_BY_VERB[verb]


# --- shape facts ------------------------------------------------------------------------

MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS = 10, 600
# No Unicode Cc code point (C0, DEL, C1). ECMA-safe; deliberately names no surrogates.
CONTROL_CHAR_FREE_PATTERN = r"^[^\x00-\x1F\x7F-\x9F]*$"
REASONING_EFFORT_MAX_LENGTH = 128
MAX_INSTRUCTIONS_APPEND_BYTES = 4096

PARAMS_RESOURCE_URI = "amicus://params"


@dataclass(frozen=True)
class ParamContract:
    """A parameter's compressed inline ``summary`` and authoritative ``full`` text."""

    name: str
    summary: str
    full: str


PARAMETER_CONTRACTS: dict[str, ParamContract] = {
    "workspace_root": ParamContract(
        name="workspace_root",
        summary=(
            "Absolute path of the repository the call targets. Sessionless (2026-07-28) "
            "clients must pass it; handshake-era clients may rely on their advertised file "
            "roots. The server never falls back to its own cwd unless the operator opts in. "
            f"Resolution rules: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Resolution precedence: explicit workspace_root → the client's handshake-era "
            "file roots (first root; an explicit value must lie inside one of them or the "
            "call fails as workspace_outside_roots) → invalid_workspace_root. The server's "
            "own cwd is used only when AMICUS_ALLOW_CWD_WORKSPACE=1, and then "
            "meta.workspace_warning discloses the resolved path. On an active call the "
            "workspace selects where the backend works, not what it can read: every "
            "backend CLI can read files outside it, up to everything the OS user can read."
        ),
    ),
    "idempotency_key": ParamContract(
        name="idempotency_key",
        summary=(
            "Optional dedup key scoped to THIS tool + backend + workspace. Same key + same "
            "args replays the prior result with no new spend; different args are refused "
            "(idempotency_conflict). Sync and _async are separate tools and never share a "
            f"key. Omit for none; retention is bounded. Lifecycle: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Reusing the key on the same tool with the same arguments (backend included) "
            "replays the existing run instead of paying for a duplicate: an _async call "
            "returns the same job_id. Reuse with different arguments is refused "
            "(idempotency_conflict); a key whose prior result was consumed or evicted is "
            "idempotency_result_unavailable; a still-publishing reservation is "
            "idempotency_in_progress (retry). A completed result stays replayable while "
            "its job record lives (its TTL). meta.idempotency_replayed=true marks a "
            "replayed (unpaid) response."
        ),
    ),
    "extra_context": ParamContract(
        name="extra_context",
        summary=(
            "Optional author intent/background, added as clearly-labeled UNTRUSTED prompt "
            "data. Redaction does NOT cover it — no live secrets. Full caveats and bounds: "
            f"{PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Added to the prompt as labeled untrusted data; the backend is instructed to "
            "treat embedded directives as data, not commands — best-effort prompt-injection "
            "mitigation, not a guarantee. It counts against the same input budget as the "
            "gathered diff, so an oversized value fails as input_too_large before any spend."
        ),
    ),
    "instructions_append": ParamContract(
        name="instructions_append",
        summary=(
            "Optional caller stance/focus text appended BEHIND this server's always-leading "
            "framing (codex: developer_instructions; claude: system_prompt_append; kimi: "
            "prompt framing). UNTRUSTED, grants no tools, best-effort compliance; may ride "
            f"the backend command line. Max {MAX_INSTRUCTIONS_APPEND_BYTES} bytes. Full "
            f"contract: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Normalized once (stripped; blank means omitted); refused pre-spend as "
            f"invalid_arguments when over {MAX_INSTRUCTIONS_APPEND_BYTES} bytes, when it "
            "carries a NUL, another C0 control (tab/LF/CR excepted), DEL, or a lone "
            "surrogate, or when it contains one of the server's framing marker lines. The "
            "backend is instructed not to let it determine a verdict; compliance is "
            "behavioral, not mechanical, and non-compliance may be silent. Each backend's "
            "carrier (argv or handshake file) is disclosed on amicus_backends. Never put "
            "secrets here; result envelopes report only a fingerprint of the text."
        ),
    ),
    "reasoning_effort": ParamContract(
        name="reasoning_effort",
        summary=(
            "Override the backend's reasoning effort for this call; omit for the backend's "
            "own resolution. An open per-model string the backend validates (commonly "
            "minimal|low|medium|high|xhigh); amicus_models lists each model's advertised "
            f"set (advisory). Rejection and bounds detail: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "A backend-rejected value fails as invalid_reasoning_effort (repair steers to "
            "amicus_models). Backends whose CLI silently ignores a bad effort (kimi) are "
            "validated pre-spend from the catalog. Control characters, surrogates, and "
            f"values over {REASONING_EFFORT_MAX_LENGTH} chars are rejected at the MCP "
            "boundary as invalid_arguments."
        ),
    ),
    "backend_options": ParamContract(
        name="backend_options",
        summary=(
            "Backend-specific knobs as one closed object: isolation (codex, kimi), "
            "config_mode and access and max_budget_usd (claude). A key or value the "
            "selected backend does not accept fails pre-spend as invalid_arguments naming "
            f"backend_options.<key>. Per-backend values: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "isolation — codex: inherit|ignore-config|ignore-rules (drop $CODEX_HOME "
            "config, then also execpolicy rules); kimi: inherit|ignore-skills. "
            "config_mode — claude: inherit|scoped|safe|bare (how much of the user's Claude "
            "config the run inherits). access — claude: toolless|readonly. max_budget_usd "
            "— claude: per-call spend cap, clamped to the operator's bounds. Unset keys "
            "take the backend's defaults; amicus_dry_run echoes the resolved values."
        ),
    ),
}


def params_resource_body() -> dict[str, Any]:
    return {
        "description": (
            "Full semantics for parameters whose tools/list description is a compressed "
            "summary. Each entry's `summary` ships inline; `full` is the authoritative "
            "contract."
        ),
        "params": {n: {"summary": c.summary, "full": c.full} for n, c in PARAMETER_CONTRACTS.items()},
    }


# --- Annotated aliases (the single home of every parameter description) ---------------

BackendParam = Annotated[
    BackendId,
    Field(description="Which backend answers: codex | kimi | claude. Required."),
]
OptionalBackendParam = Annotated[
    BackendId | None,
    Field(description="Restrict to one backend: codex | kimi | claude. Omit for all."),
]
QuestionParam = Annotated[
    str,
    Field(description="The question or ad-hoc diff to consult on. Must not be blank."),
]
TaskParam = Annotated[
    str,
    Field(
        description=(
            "The coding task to implement in a throwaway worktree; the diff is returned, "
            "never applied. Must not be blank."
        )
    ),
]
TargetParam = Annotated[
    str, Field(description="The plan, claim, or decision the adversarial critic attacks.")
]
EvidenceParam = Annotated[
    str | None, Field(description="Supporting evidence for the target. Omit for none.")
]
WorkspaceRootParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["workspace_root"].summary)
]
ExtraContextParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["extra_context"].summary)
]
InstructionsAppendParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["instructions_append"].summary)
]
ModelParam = Annotated[
    str | None,
    Field(
        description=(
            "Backend model slug; omit for the backend's default. amicus_models lists valid "
            "slugs (advisory). Control characters are rejected, not stripped."
        ),
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=256,
    ),
]
ReasoningEffortParam = Annotated[
    str | None,
    Field(
        description=PARAMETER_CONTRACTS["reasoning_effort"].summary,
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=REASONING_EFFORT_MAX_LENGTH,
    ),
]
TimeoutSecondsParam = Annotated[
    int | None,
    Field(
        description=(
            f"Deadline in seconds, clamped to {MIN_TIMEOUT_SECONDS}-{MAX_TIMEOUT_SECONDS}; "
            "omit for the server default (AMICUS_TIMEOUT_SECONDS). A sync call past its "
            "deadline is terminated and its partial work lost; prefer the _async twin."
        )
    ),
]
DetailParam = Annotated[
    Detail,
    Field(
        description=(
            "summary (default) omits raw_response.text; full includes it. Same shape "
            "either way."
        )
    ),
]
CapabilitiesDetailParam = Annotated[
    CapabilitiesDetail,
    Field(
        description=(
            "summary (default): name, cost, stability, backends, error_codes per tool; "
            "full adds use_when/returns/params; contracts omits tool_details."
        )
    ),
]
IdempotencyKeyParam = Annotated[
    str | None, Field(description=PARAMETER_CONTRACTS["idempotency_key"].summary, max_length=200)
]
BackendOptionsParam = Annotated[
    BackendOptions | None, Field(description=PARAMETER_CONTRACTS["backend_options"].summary)
]
ScopeParam = Annotated[
    ReviewScope,
    Field(
        description=(
            "working_tree (tracked changes vs HEAD), branch (vs `base`, default the "
            "upstream), or commit (one commit)."
        )
    ),
]
OptionalScopeParam = Annotated[
    ReviewScope | None,
    Field(description="Optionally attach a git diff to the critique: working_tree | branch | commit."),
]
BaseParam = Annotated[
    str | None,
    Field(
        description="Base ref for scope=branch; omit for the upstream. Control characters rejected.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=256,
    ),
]
CommitParam = Annotated[
    str | None,
    Field(
        description="Commit ref for scope=commit. Control characters rejected.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=256,
    ),
]
PathsParam = Annotated[
    list[str] | None,
    Field(description="Restrict the diff to these repo-relative paths. Omit for all."),
]
UntrackedParam = Annotated[
    Untracked,
    Field(
        description=(
            "working_tree only: explicit_only (default; untracked files named in paths), "
            "include (every non-ignored untracked file — opt-in egress), exclude."
        )
    ),
]
FocusParam = Annotated[
    str | None,
    Field(
        description=(
            "Narrow the review to one concern (e.g. 'locking'). UNTRUSTED caller text; a "
            "focused pass is never a full review."
        ),
        max_length=500,
    ),
]
JobIdParam = Annotated[
    str,
    Field(
        description="Job id from an _async call or meta.job_id. Control characters rejected.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=64,
    ),
]
TaskIdParam = Annotated[
    str | None,
    Field(
        description="Filter to the job behind this tasks-extension task id.",
        pattern=CONTROL_CHAR_FREE_PATTERN,
        max_length=128,
    ),
]
JobLimitParam = Annotated[
    int | None, Field(description="Return at most this many newest jobs (1-1000); omit for all.", ge=1, le=1000)
]
JobStatusFilterParam = Annotated[
    JobState | None, Field(description="Only jobs in this state; omit for all.")
]
IncludeSchemasParam = Annotated[
    list[str] | None,
    Field(
        description=(
            "Embed these documents in `schemas`: error-envelope, result-meta, "
            "capabilities-result, parameter-contracts. A resource-blind fallback."
        )
    ),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_params.py -v --no-cov`
Expected: all PASS (after Task 7's `options.py` exists; if you run before Task 7, the import fails — do Task 7 Step 3 first, then return).

- [ ] **Step 5: Commit**

```bash
git add src/amicus/schemas/params.py tests/test_params.py
git commit -m "feat(schemas): pin the verb x backend parameter matrix and aliases

The matrix from the design spec is the authority for every tool's
inputSchema property set; the Annotated aliases are the single home of
each parameter's description, and six parameters carry a compressed
summary plus a full contract served at amicus://params."
```

---

### Task 7: Closed `backend_options` and the field policy

**Files:**
- Create: `src/amicus/schemas/options.py`, `src/amicus/schemas/field_policy.py`
- Test: `tests/test_options.py`, `tests/test_field_policy.py`

**Interfaces:**
- Consumes: `codes.BackendId`, `codes.BACKEND_IDS`, `envelope.InvalidArgument`.
- Produces: `options.BackendOptions` (pydantic, `extra="forbid"`), `options.OPTION_ALLOWED_VALUES: dict[str, dict[str, tuple[str, ...] | None]]`, `options.option_violations(backend, options) -> list[InvalidArgument]`, `options.resolved_options(backend, options) -> dict[str, Any]`, `options.MAX_BUDGET_BOUNDS = (0.01, 100.0)`; `field_policy.CONTROL_CHAR_FREE_PATTERN`, `field_policy.REJECT_PARAMS`, `field_policy.PRESERVE_CARRIERS`, `field_policy.advertised_patterns(app) -> dict[str, str | None]` (async).

- [ ] **Step 1: Write the failing tests**

`tests/test_options.py`:

```python
"""backend_options: closed schema, per-backend applicability, allowed values (ADR 0002)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from amicus.schemas import options as o


def test_schema_is_closed_and_lists_every_option():
    schema = o.BackendOptions.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"isolation", "config_mode", "access", "max_budget_usd"}
    with pytest.raises(ValidationError):
        o.BackendOptions(sandbox="read-only")


def test_applicability_table():
    assert o.OPTION_ALLOWED_VALUES["isolation"] == {
        "codex": ("inherit", "ignore-config", "ignore-rules"),
        "kimi": ("inherit", "ignore-skills"),
    }
    assert o.OPTION_ALLOWED_VALUES["config_mode"] == {"claude": ("inherit", "scoped", "safe", "bare")}
    assert o.OPTION_ALLOWED_VALUES["access"] == {"claude": ("toolless", "readonly")}
    assert o.OPTION_ALLOWED_VALUES["max_budget_usd"] == {"claude": None}


def test_no_options_is_no_violation():
    assert o.option_violations("codex", None) == []
    assert o.option_violations("codex", o.BackendOptions()) == []
    assert o.resolved_options("codex", None) == {}


def test_inapplicable_key_names_the_key_and_the_backends_that_accept_it():
    [v] = o.option_violations("codex", o.BackendOptions(config_mode="safe"))
    assert v.field == "backend_options.config_mode"
    assert v.allowed_values is None
    assert "claude" in v.reason
    assert "codex" in v.reason


def test_wrong_value_for_this_backend_lists_its_allowed_values():
    [v] = o.option_violations("kimi", o.BackendOptions(isolation="ignore-rules"))
    assert v.field == "backend_options.isolation"
    assert v.allowed_values == ["inherit", "ignore-skills"]


def test_budget_bounds_are_in_the_schema_and_enforced():
    props = o.BackendOptions.model_json_schema()["properties"]["max_budget_usd"]
    branch = next(b for b in props["anyOf"] if b.get("type") == "number")
    assert (branch["minimum"], branch["maximum"]) == o.MAX_BUDGET_BOUNDS
    with pytest.raises(ValidationError):
        o.BackendOptions(max_budget_usd=0)
    assert o.option_violations("claude", o.BackendOptions(max_budget_usd=1.5)) == []
    [v] = o.option_violations("kimi", o.BackendOptions(max_budget_usd=1.5))
    assert v.field == "backend_options.max_budget_usd"


def test_resolved_options_echo_only_set_keys():
    opts = o.BackendOptions(isolation="ignore-config")
    assert o.resolved_options("codex", opts) == {"isolation": "ignore-config"}


def test_several_violations_are_all_reported_in_field_order():
    fields = [
        v.field
        for v in o.option_violations("kimi", o.BackendOptions(config_mode="safe", access="readonly"))
    ]
    assert fields == ["backend_options.config_mode", "backend_options.access"]
```

`tests/test_field_policy.py`:

```python
"""Machine identifiers are rejected, never sanitized; carriers are byte-exact."""

from __future__ import annotations

from amicus.schemas import field_policy as fp
from amicus.schemas import params


def test_pattern_has_one_home():
    assert fp.CONTROL_CHAR_FREE_PATTERN is params.CONTROL_CHAR_FREE_PATTERN


def test_reject_and_preserve_sets_are_disjoint_by_carrier_name():
    assert fp.REJECT_PARAMS == ("job_id", "base", "commit", "model", "task_id")
    leaf = {c.rsplit(".", 1)[-1].rstrip("[]") for c in fp.PRESERVE_CARRIERS}
    # `model`/`base`/`commit` appear on both sides on purpose: rejected as INPUTS,
    # replayed byte-exact as stored CARRIERS. Everything else is one or the other.
    assert leaf & set(fp.REJECT_PARAMS) == {"model", "base", "commit"}
```

The `advertised_patterns` test lands in Task 12 once tools exist.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_options.py tests/test_field_policy.py -v --no-cov`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the modules**

`src/amicus/schemas/options.py`:

```python
"""`backend_options`: one closed superset object with per-backend applicability (ADR 0002)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from amicus.schemas.envelope import InvalidArgument

MAX_BUDGET_BOUNDS: tuple[float, float] = (0.01, 100.0)

# option -> backend -> allowed values (None: a numeric option bounded by the schema).
# The backends absent for an option do not accept it.
OPTION_ALLOWED_VALUES: dict[str, dict[str, tuple[str, ...] | None]] = {
    "isolation": {
        "codex": ("inherit", "ignore-config", "ignore-rules"),
        "kimi": ("inherit", "ignore-skills"),
    },
    "config_mode": {"claude": ("inherit", "scoped", "safe", "bare")},
    "access": {"claude": ("toolless", "readonly")},
    "max_budget_usd": {"claude": None},
}


class BackendOptions(BaseModel):
    """The union of every backend's options; applicability is validated pre-spend."""

    model_config = ConfigDict(extra="forbid")
    isolation: Literal["inherit", "ignore-config", "ignore-rules", "ignore-skills"] | None = (
        Field(
            default=None,
            description=(
                "codex: inherit|ignore-config|ignore-rules; kimi: inherit|ignore-skills. "
                "Omit for the backend default (inherit)."
            ),
        )
    )
    config_mode: Literal["inherit", "scoped", "safe", "bare"] | None = Field(
        default=None,
        description="claude only: inherit|scoped|safe|bare. Omit for the server default.",
    )
    access: Literal["toolless", "readonly"] | None = Field(
        default=None, description="claude only: toolless|readonly. Omit for the server default."
    )
    max_budget_usd: float | None = Field(
        default=None,
        ge=MAX_BUDGET_BOUNDS[0],
        le=MAX_BUDGET_BOUNDS[1],
        description="claude only: per-call spend cap in USD, clamped to the operator bounds.",
    )


def _set_items(options: BackendOptions | None) -> list[tuple[str, Any]]:
    if options is None:
        return []
    return [(k, v) for k, v in options.model_dump().items() if v is not None]


def option_violations(backend: str, options: BackendOptions | None) -> list[InvalidArgument]:
    """Every key the selected backend does not accept, or whose value it does not accept,
    as `invalid_arguments` entries naming `backend_options.<key>`."""
    out: list[InvalidArgument] = []
    for key, value in _set_items(options):
        accepted = OPTION_ALLOWED_VALUES[key]
        if backend not in accepted:
            out.append(
                InvalidArgument(
                    field=f"backend_options.{key}",
                    reason=(
                        f"{key} is not accepted by backend {backend!r}; it applies to "
                        f"{', '.join(sorted(accepted))}"
                    ),
                )
            )
            continue
        allowed = accepted[backend]
        if allowed is not None and value not in allowed:
            out.append(
                InvalidArgument(
                    field=f"backend_options.{key}",
                    reason=f"{key} must be one of the allowed values for backend {backend!r}",
                    allowed_values=list(allowed),
                )
            )
    return out


def resolved_options(backend: str, options: BackendOptions | None) -> dict[str, Any]:
    """The set keys, for echoing in previews. Assumes `option_violations` was empty."""
    return {k: v for k, v in _set_items(options) if backend in OPTION_ALLOWED_VALUES[k]}
```

`src/amicus/schemas/field_policy.py`:

```python
"""Which agent-visible strings may carry a control character, and what happens when one
does. Machine identifiers are split by who can fix the value: caller inputs are REJECTED
at the MCP boundary by an advertised pattern; real filesystem/model identities are
PRESERVED byte-exact and escaped only where rendered. Never sanitize an identifier —
deleting a byte corrupts it into a different, valid-looking one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.schemas.params import CONTROL_CHAR_FREE_PATTERN as CONTROL_CHAR_FREE_PATTERN

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

REJECT_PARAMS: tuple[str, ...] = ("job_id", "base", "commit", "model", "task_id")

PRESERVE_CARRIERS: tuple[str, ...] = (
    "meta.cwd",
    "workspace.cwd",
    "error.repair.arguments.workspace_root",
    "error.candidate_roots",
    "findings[].file",
    "meta.session_id",
    "raw_response.session_id",
    "meta.model",
    "meta.base",
    "meta.commit",
    "meta.paths[]",
)


async def advertised_patterns(app: FastMCP) -> dict[str, str | None]:
    """Each tool parameter name → the `pattern` its inputSchema advertises. A parameter on
    several tools must advertise the same pattern everywhere; a disagreement resolves to
    None so a guard fails rather than passing on whichever tool was visited last."""
    found: dict[str, set[str | None]] = {}
    for tool in await app.list_tools():
        for name, schema in (tool.parameters or {}).get("properties", {}).items():
            branches = schema.get("anyOf", [schema])
            pattern = next((b.get("pattern") for b in branches if b.get("pattern")), None)
            found.setdefault(name, set()).add(pattern)
    return {n: ps.pop() if len(ps) == 1 else None for n, ps in found.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_options.py tests/test_field_policy.py tests/test_params.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/schemas/options.py src/amicus/schemas/field_policy.py tests/test_options.py tests/test_field_policy.py
git commit -m "feat(schemas): add the closed backend_options object and field policy

backend_options is one additionalProperties:false model whose per-
backend applicability and allowed values are validated pre-spend into
invalid_arguments entries naming backend_options.<key> (ADR 0002). The
field policy names which identifiers are rejected and which carriers
are preserved byte-exact."
```

---

### Task 8: Environment declarations and settings

**Files:**
- Create: `src/amicus/config/__init__.py`, `src/amicus/config/envspec.py`
- Test: `tests/test_envspec.py`, `tests/test_config.py`

**Interfaces:**
- Produces (`envspec`): `LEGACY_REMOVAL_VERSION = "0.3.0"`, `is_env_placeholder(value) -> bool`, `EnvVar(name, description, default=None, legacy=(), secret=False)`, `Resolved(name, value, source, warning)` with `source in {"env", "legacy", "default", "unset"}`, `EnvConflictError(ValueError)`, `EnvReport(warnings, errors, placeholders)`, `EnvNamespace(prefix, vars)` with `.names()`, `.resolve(name, environ=None) -> Resolved`, `.report(environ=None) -> EnvReport`.
- Produces (`config`): `Settings` (frozen dataclass; fields listed in Step 3), `GLOBAL_ENV: EnvNamespace`, `DEFAULT_TIMEOUT_SECONDS = 300`, `settings(environ=None) -> Settings`, `PROFILE_DEFAULT = ("codex", "kimi", "claude")`.

- [ ] **Step 1: Write the failing tests**

`tests/test_envspec.py`:

```python
"""Env declarations with a legacy shim: amicus name wins, legacy is read only when the
amicus name is unset (with a warning), a conflict is an error."""

from __future__ import annotations

import pytest

from amicus.config import envspec as es

NS = es.EnvNamespace(
    prefix="AMICUS_",
    vars=(
        es.EnvVar("AMICUS_TIMEOUT_SECONDS", "deadline", default="300",
                  legacy=("CODEX_IN_CLAUDE_TIMEOUT_SECONDS", "MOONBRIDGE_TIMEOUT_SECONDS")),
        es.EnvVar("AMICUS_MODEL", "model", legacy=()),
    ),
)


def test_namespace_validates_its_shape():
    with pytest.raises(ValueError, match="UPPER_SNAKE_"):
        es.EnvNamespace(prefix="amicus_", vars=())
    with pytest.raises(ValueError, match="must start with"):
        es.EnvNamespace(prefix="AMICUS_", vars=(es.EnvVar("OTHER_X", "d"),))
    assert NS.names() == ("AMICUS_TIMEOUT_SECONDS", "AMICUS_MODEL")


def test_amicus_name_wins_and_default_applies():
    r = NS.resolve("AMICUS_TIMEOUT_SECONDS", {"AMICUS_TIMEOUT_SECONDS": "60"})
    assert (r.value, r.source, r.warning) == ("60", "env", None)
    r = NS.resolve("AMICUS_TIMEOUT_SECONDS", {})
    assert (r.value, r.source) == ("300", "default")
    r = NS.resolve("AMICUS_MODEL", {})
    assert (r.value, r.source) == (None, "unset")


def test_legacy_is_read_only_when_amicus_is_unset_with_a_warning():
    r = NS.resolve("AMICUS_TIMEOUT_SECONDS", {"MOONBRIDGE_TIMEOUT_SECONDS": "45"})
    assert (r.value, r.source) == ("45", "legacy")
    assert "MOONBRIDGE_TIMEOUT_SECONDS" in r.warning
    assert es.LEGACY_REMOVAL_VERSION in r.warning
    # Both set and equal: the amicus value is used; the legacy copy is noted, not an error.
    r = NS.resolve(
        "AMICUS_TIMEOUT_SECONDS",
        {"AMICUS_TIMEOUT_SECONDS": "45", "MOONBRIDGE_TIMEOUT_SECONDS": "45"},
    )
    assert (r.value, r.source) == ("45", "env")
    assert r.warning and "ignored" in r.warning


def test_conflict_is_an_error():
    with pytest.raises(es.EnvConflictError, match="AMICUS_TIMEOUT_SECONDS"):
        NS.resolve(
            "AMICUS_TIMEOUT_SECONDS",
            {"AMICUS_TIMEOUT_SECONDS": "60", "CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "45"},
        )
    with pytest.raises(es.EnvConflictError):
        NS.resolve(
            "AMICUS_TIMEOUT_SECONDS",
            {"CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "1", "MOONBRIDGE_TIMEOUT_SECONDS": "2"},
        )


def test_unknown_name_is_a_programming_error():
    with pytest.raises(KeyError):
        NS.resolve("AMICUS_NOPE", {})


def test_placeholders():
    assert es.is_env_placeholder("${FOO}")
    assert es.is_env_placeholder(" ${FOO_bar1} ")
    assert not es.is_env_placeholder("$FOO")
    assert not es.is_env_placeholder("${1BAD}")
    assert not es.is_env_placeholder(None)


def test_report_collects_warnings_errors_and_placeholders():
    rep = NS.report(
        {
            "AMICUS_TIMEOUT_SECONDS": "60",
            "CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "45",
            "AMICUS_MODEL": "${MODEL}",
        }
    )
    assert rep.placeholders == ["AMICUS_MODEL"]
    assert any("AMICUS_TIMEOUT_SECONDS" in e for e in rep.errors)
    assert rep.warnings == []
    rep = NS.report({"MOONBRIDGE_TIMEOUT_SECONDS": "45"})
    assert len(rep.warnings) == 1 and rep.errors == []
```

`tests/test_config.py`:

```python
"""settings(): profile, clamps, tasks gate, and the env report it carries."""

from __future__ import annotations

from pathlib import Path

from amicus import config


def test_defaults(clean_env):
    s = config.settings({})
    assert s.enabled_backends == ("codex", "kimi", "claude")
    assert s.timeout_seconds == 300
    assert s.max_input_bytes == 200_000
    assert (s.job_ttl_seconds, s.job_max_seconds, s.job_max_count) == (86_400, 1_800, 50)
    assert s.state_dir == Path.home() / ".cache" / "amicus" / "jobs"
    assert s.log_level == "WARNING" and s.log_file is None
    assert s.tasks_enabled is False and s.tasks_backend_url == "memory://"
    assert s.host_name is None and s.allow_cwd_workspace is False
    assert s.env_warnings == () and s.config_errors == () and s.placeholders == ()


def test_profile_parsing_keeps_order_and_drops_unknown_with_an_error(clean_env):
    s = config.settings({"AMICUS_BACKENDS": "claude, codex"})
    assert s.enabled_backends == ("claude", "codex")
    s = config.settings({"AMICUS_BACKENDS": "codex,gemini"})
    assert s.enabled_backends == ("codex",)
    assert any("gemini" in e for e in s.config_errors)
    s = config.settings({"AMICUS_BACKENDS": ""})
    assert s.enabled_backends == ("codex", "kimi", "claude")


def test_clamps_and_bad_ints_warn(clean_env):
    s = config.settings({"AMICUS_TIMEOUT_SECONDS": "5", "AMICUS_JOB_MAX_SECONDS": "99999"})
    assert s.timeout_seconds == 10 and s.job_max_seconds == 7_200
    s = config.settings({"AMICUS_TIMEOUT_SECONDS": "lots"})
    assert s.timeout_seconds == 300
    assert any("AMICUS_TIMEOUT_SECONDS" in w for w in s.env_warnings)


def test_legacy_shim_and_conflict_surface_in_settings(clean_env):
    s = config.settings({"CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "120"})
    assert s.timeout_seconds == 120
    assert any("CODEX_IN_CLAUDE_TIMEOUT_SECONDS" in w for w in s.env_warnings)
    s = config.settings(
        {"AMICUS_TIMEOUT_SECONDS": "120", "MOONBRIDGE_TIMEOUT_SECONDS": "60"}
    )
    assert s.timeout_seconds == 120  # the amicus value is used; the conflict is reported
    assert any("MOONBRIDGE_TIMEOUT_SECONDS" in e for e in s.config_errors)


def test_placeholder_is_reported_and_treated_as_unset(clean_env):
    s = config.settings({"AMICUS_LOG_FILE": "${LOG}", "AMICUS_HOST_NAME": "Codex"})
    assert s.log_file is None and s.placeholders == ("AMICUS_LOG_FILE",)
    assert s.host_name == "Codex"


def test_flags(clean_env):
    s = config.settings({"AMICUS_TASKS": "1", "AMICUS_ALLOW_CWD_WORKSPACE": "true",
                         "AMICUS_TASKS_BACKEND_URL": "redis://x/0", "AMICUS_LOG_LEVEL": "debug"})
    assert s.tasks_enabled and s.allow_cwd_workspace
    assert s.tasks_backend_url == "redis://x/0" and s.log_level == "DEBUG"
    s = config.settings({"AMICUS_TASKS": "no", "AMICUS_LOG_LEVEL": "loud"})
    assert not s.tasks_enabled and s.log_level == "WARNING"


def test_settings_reads_the_process_environment_by_default(clean_env):
    clean_env.setenv("AMICUS_TIMEOUT_SECONDS", "42")
    assert config.settings().timeout_seconds == 42


def test_every_declared_var_has_a_description_and_is_documented():
    for var in config.GLOBAL_ENV.vars:
        assert var.description
        assert var.name.startswith("AMICUS_")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_envspec.py tests/test_config.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'amicus.config'`.

- [ ] **Step 3: Write the modules**

`src/amicus/config/envspec.py`:

```python
"""Declared environment variables with a legacy-name shim.

Every variable this server reads is declared once (name, description, default, legacy
names). The shim reads a legacy name only when the amicus name is unset and reports it
as a warning naming the removal version; a legacy value that disagrees with the amicus
value, or two legacy values that disagree, is an error. `${VAR}` placeholders an MCP
host failed to expand are detected and treated as unset.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

LEGACY_REMOVAL_VERSION = "0.3.0"

_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def is_env_placeholder(value: str | None) -> bool:
    """True when an env value is a literal, unexpanded `${...}` placeholder."""
    return value is not None and bool(_PLACEHOLDER_RE.match(value.strip()))


class EnvConflictError(ValueError):
    """Two names for one setting carry different values."""


@dataclass(frozen=True)
class EnvVar:
    name: str
    description: str
    default: str | None = None
    legacy: tuple[str, ...] = ()
    secret: bool = False


Source = Literal["env", "legacy", "default", "unset"]


@dataclass(frozen=True)
class Resolved:
    name: str
    value: str | None
    source: Source
    warning: str | None = None


@dataclass(frozen=True)
class EnvReport:
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EnvNamespace:
    prefix: str
    vars: tuple[EnvVar, ...]

    def __post_init__(self) -> None:
        if not self.prefix.endswith("_") or not self.prefix.isupper():
            raise ValueError(f"prefix {self.prefix!r} must be UPPER_SNAKE_ ending in _")
        for var in self.vars:
            if not var.name.startswith(self.prefix):
                raise ValueError(f"{var.name!r} must start with {self.prefix!r}")

    def names(self) -> tuple[str, ...]:
        return tuple(v.name for v in self.vars)

    def _var(self, name: str) -> EnvVar:
        for var in self.vars:
            if var.name == name:
                return var
        raise KeyError(name)

    def resolve(self, name: str, environ: Mapping[str, str] | None = None) -> Resolved:
        env = os.environ if environ is None else environ
        var = self._var(name)
        own = env.get(name)
        if is_env_placeholder(own):
            own = None
        legacy = [(n, env[n]) for n in var.legacy if n in env and not is_env_placeholder(env[n])]
        distinct = {v for _, v in legacy}
        if own is not None:
            if distinct - {own}:
                names = ", ".join(n for n, v in legacy if v != own)
                raise EnvConflictError(
                    f"{name} and legacy {names} are both set with different values; "
                    f"unset the legacy name(s)"
                )
            warning = None
            if legacy:
                warning = (
                    f"{', '.join(n for n, _ in legacy)} ignored: {name} is set "
                    f"(legacy names are removed in {LEGACY_REMOVAL_VERSION})"
                )
            return Resolved(name, own, "env", warning)
        if len(distinct) > 1:
            raise EnvConflictError(
                f"legacy names for {name} disagree: {', '.join(n for n, _ in legacy)}"
            )
        if legacy:
            legacy_name, value = legacy[0]
            return Resolved(
                name,
                value,
                "legacy",
                f"{name} read from legacy {legacy_name}; rename it — legacy names are "
                f"removed in {LEGACY_REMOVAL_VERSION}",
            )
        if var.default is not None:
            return Resolved(name, var.default, "default")
        return Resolved(name, None, "unset")

    def report(self, environ: Mapping[str, str] | None = None) -> EnvReport:
        env = os.environ if environ is None else environ
        rep = EnvReport()
        for var in self.vars:
            if is_env_placeholder(env.get(var.name)):
                rep.placeholders.append(var.name)
            try:
                resolved = self.resolve(var.name, env)
            except EnvConflictError as exc:
                rep.errors.append(str(exc))
                continue
            if resolved.warning:
                rep.warnings.append(resolved.warning)
        return rep
```

`src/amicus/config/__init__.py`:

```python
"""Operator settings resolved from the AMICUS_* namespace (with the legacy shim)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar
from amicus.schemas.codes import BACKEND_IDS
from amicus.schemas.params import MAX_TIMEOUT_SECONDS, MIN_TIMEOUT_SECONDS

PROFILE_DEFAULT: tuple[str, ...] = BACKEND_IDS
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_INPUT_BYTES = 200_000
DEFAULT_JOB_TTL_SECONDS = 86_400
DEFAULT_JOB_MAX_SECONDS = 1_800
DEFAULT_JOB_MAX_COUNT = 50
DEFAULT_LOG_LEVEL = "WARNING"
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_TRUE = frozenset({"1", "true", "yes", "on"})

_ALL_LEGACY = ("CODEX_IN_CLAUDE_", "MOONBRIDGE_", "CLAUDE_IN_CODEX_")


def _legacy(suffix: str, *prefixes: str) -> tuple[str, ...]:
    return tuple(f"{p}{suffix}" for p in (prefixes or _ALL_LEGACY))


GLOBAL_ENV = EnvNamespace(
    prefix="AMICUS_",
    vars=(
        EnvVar("AMICUS_BACKENDS", "Comma-separated enabled backends; default: every in-tree backend."),
        EnvVar("AMICUS_TIMEOUT_SECONDS", "Default sync deadline (10-600).", str(DEFAULT_TIMEOUT_SECONDS), _legacy("TIMEOUT_SECONDS")),
        EnvVar("AMICUS_MAX_INPUT_BYTES", "Byte budget for caller inputs plus the gathered diff.", str(DEFAULT_MAX_INPUT_BYTES), _legacy("MAX_INPUT_BYTES")),
        EnvVar("AMICUS_JOB_TTL", "Seconds a terminal job record is retained.", str(DEFAULT_JOB_TTL_SECONDS), _legacy("JOB_TTL")),
        EnvVar("AMICUS_JOB_MAX_SECONDS", "Background job wall-clock cap (60-7200).", str(DEFAULT_JOB_MAX_SECONDS), _legacy("JOB_MAX_SECONDS")),
        EnvVar("AMICUS_JOB_MAX_COUNT", "Retained job records per workspace (1-1000).", str(DEFAULT_JOB_MAX_COUNT), _legacy("JOB_MAX_COUNT")),
        EnvVar("AMICUS_STATE_DIR", "Directory for job records; default $XDG_CACHE_HOME/amicus/jobs."),
        EnvVar("AMICUS_LOG_LEVEL", "Diagnostic log level (stderr).", DEFAULT_LOG_LEVEL, _legacy("LOG_LEVEL", "CODEX_IN_CLAUDE_", "MOONBRIDGE_")),
        EnvVar("AMICUS_LOG_FILE", "Optional file mirroring the stderr log.", None, _legacy("LOG_FILE", "CODEX_IN_CLAUDE_", "MOONBRIDGE_")),
        EnvVar("AMICUS_TASKS", "1 to register the paid sync tools with the tasks extension.", "0"),
        EnvVar("AMICUS_TASKS_BACKEND_URL", "Docket backend for the tasks extension (memory:// or redis://).", "memory://"),
        EnvVar("AMICUS_HOST_NAME", "Override the host name used in prompt framing."),
        EnvVar("AMICUS_ALLOW_CWD_WORKSPACE", "1 to allow falling back to the server cwd (disclosed).", "0"),
    ),
)


@dataclass(frozen=True)
class Settings:
    enabled_backends: tuple[str, ...]
    timeout_seconds: int
    max_input_bytes: int
    job_ttl_seconds: int
    job_max_seconds: int
    job_max_count: int
    state_dir: Path
    log_level: str
    log_file: str | None
    tasks_enabled: bool
    tasks_backend_url: str
    host_name: str | None
    allow_cwd_workspace: bool
    env_warnings: tuple[str, ...]
    config_errors: tuple[str, ...]
    placeholders: tuple[str, ...]


def _bounded_int(name: str, value: str | None, default: int, lo: int, hi: int, warnings: list[str]) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        warnings.append(f"{name}={value!r} is not an integer; using {default}")
        return default
    return max(lo, min(hi, parsed))


def _profile(raw: str | None, errors: list[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return PROFILE_DEFAULT
    out: list[str] = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if token not in BACKEND_IDS and not token.isidentifier():
            errors.append(f"AMICUS_BACKENDS entry {token!r} is not a backend id")
            continue
        if token not in BACKEND_IDS:
            # A third-party plugin id: allowed through; the registry decides availability.
            errors.append(f"AMICUS_BACKENDS entry {token!r} is not an in-tree backend")
            continue
        if token not in out:
            out.append(token)
    return tuple(out) or PROFILE_DEFAULT


def settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Resolve every setting once. Never raises: problems ride `env_warnings`,
    `config_errors` and `placeholders` so `amicus_backends` can report them."""
    report = GLOBAL_ENV.report(environ)
    warnings = list(report.warnings)
    errors = list(report.errors)

    def get(name: str) -> str | None:
        try:
            return GLOBAL_ENV.resolve(name, environ).value
        except EnvConflictError:
            # Already recorded by report(); fall back to the amicus name or the default.
            import os

            env = os.environ if environ is None else environ
            own = env.get(name)
            return own if own is not None else GLOBAL_ENV._var(name).default

    state_raw = get("AMICUS_STATE_DIR")
    if state_raw:
        state_dir = Path(state_raw).expanduser()
    else:
        import os

        env = os.environ if environ is None else environ
        base = env.get("XDG_CACHE_HOME")
        state_dir = (Path(base).expanduser() if base else Path.home() / ".cache") / "amicus" / "jobs"
    level = (get("AMICUS_LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
    return Settings(
        enabled_backends=_profile(get("AMICUS_BACKENDS"), errors),
        timeout_seconds=_bounded_int("AMICUS_TIMEOUT_SECONDS", get("AMICUS_TIMEOUT_SECONDS"), DEFAULT_TIMEOUT_SECONDS, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, warnings),
        max_input_bytes=_bounded_int("AMICUS_MAX_INPUT_BYTES", get("AMICUS_MAX_INPUT_BYTES"), DEFAULT_MAX_INPUT_BYTES, 1_000, 10**9, warnings),
        job_ttl_seconds=_bounded_int("AMICUS_JOB_TTL", get("AMICUS_JOB_TTL"), DEFAULT_JOB_TTL_SECONDS, 60, 10**9, warnings),
        job_max_seconds=_bounded_int("AMICUS_JOB_MAX_SECONDS", get("AMICUS_JOB_MAX_SECONDS"), DEFAULT_JOB_MAX_SECONDS, 60, 7_200, warnings),
        job_max_count=_bounded_int("AMICUS_JOB_MAX_COUNT", get("AMICUS_JOB_MAX_COUNT"), DEFAULT_JOB_MAX_COUNT, 1, 1_000, warnings),
        state_dir=state_dir,
        log_level=level if level in VALID_LOG_LEVELS else DEFAULT_LOG_LEVEL,
        log_file=get("AMICUS_LOG_FILE") or None,
        tasks_enabled=(get("AMICUS_TASKS") or "0").strip().lower() in _TRUE,
        tasks_backend_url=get("AMICUS_TASKS_BACKEND_URL") or "memory://",
        host_name=get("AMICUS_HOST_NAME") or None,
        allow_cwd_workspace=(get("AMICUS_ALLOW_CWD_WORKSPACE") or "0").strip().lower() in _TRUE,
        env_warnings=tuple(warnings),
        config_errors=tuple(errors),
        placeholders=tuple(report.placeholders),
    )
```

Move the two inline `import os` statements to a single top-level `import os` (they are shown inline only to keep each block readable); ruff will flag them otherwise.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_envspec.py tests/test_config.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/config tests/test_envspec.py tests/test_config.py
git commit -m "feat(config): declare the AMICUS_ namespace with a legacy shim

Every variable is declared once with its legacy names; a legacy name is
read only when the amicus name is unset (warned, with the removal
version), a conflict is an error, and placeholders are detected.
settings() never raises: problems ride the Settings so amicus_backends
can report them."
```

---

### Task 9: Plugin API, in-tree declarations, registry, and the FakePlugin

**Files:**
- Create: `src/amicus/plugin.py`, `src/amicus/backends/__init__.py`, `src/amicus/registry.py`, `tests/support/__init__.py`, `tests/support/fakeplugin.py`
- Test: `tests/test_plugin.py`, `tests/test_registry.py`

**Interfaces:**
- Consumes: `pontonier.backend.contract.BackendContract`, `pontonier.backend.protocol.*`, `pontonier.conventions.envelope.{BackendErrorVocabulary, RepairRule}`, `pontonier.conventions.annotations.AnnotationEffects`, `pontonier.conventions.preflight.HelpProbe`, `pontonier.testing.conformance.{check_contract, check_backend}`, `amicus.config.envspec.EnvNamespace`.
- Produces (`plugin`): `PLUGIN_API_VERSION = 1`, `ENTRY_POINT_GROUP = "amicus.backends"`, `OptionSpec(name, maps_to, applies_to: frozenset[str], default=None)`, `StatusReport(installed, version=None, authenticated=None, warnings=())`, `ModelEntry(slug, display_name=None, default_reasoning_effort=None, supported_reasoning_efforts=None)`, `ModelListing(models, source, fetched_at=None)`, Protocols `StatusProbe.probe() -> StatusReport`, `ModelCatalogReader.read() -> ModelListing`, `BinaryResolver.resolve() -> str | None`, `FramingHook.frame(verb, framing, host_name) -> str`, `BackendPlugin` dataclass with `.backend_id` property.
- Produces (`backends`): `IN_TREE: dict[str, str]`, `KNOWN_EFFECTS: dict[str, AnnotationEffects]`, `KNOWN_DISPLAY_NAMES: dict[str, str]`.
- Produces (`registry`): `UnavailableBackend(backend_id, reason, detail)`, `BackendRegistry(available, unavailable)` with `.load(enabled, *, in_tree=None, entry_points=None)`, `.get(backend_id) -> BackendPlugin | None`, `.ids` property, `.unavailable_for(backend_id) -> UnavailableBackend | None`.
- Produces (`tests.support.fakeplugin`): `make_plugin(backend_id="fake", **overrides) -> BackendPlugin`, module attribute `plugin`, `FakeBackend`.

- [ ] **Step 1: Write the FakePlugin support module**

`tests/support/__init__.py`: empty.

`tests/support/fakeplugin.py`:

```python
"""A conforming fake backend plugin for the registry, discovery and forced-error tests.

Loaded through the real entry-point path (`amicus.registry`) by pointing an EntryPoint at
`tests.support.fakeplugin:plugin`, so the loading code is exercised end-to-end."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from pontonier.backend.contract import BackendContract, IsolationPolicy, ModelCatalog
from pontonier.backend.protocol import (
    ClassifiedFailure,
    ExecResult,
    PreparedRun,
    RunOutcome,
    RunRequest,
)
from pontonier.conventions.annotations import AnnotationEffects
from pontonier.conventions.envelope import BackendErrorVocabulary
from pontonier.conventions.preflight import HelpProbe

from amicus.config.envspec import EnvNamespace
from amicus.plugin import (
    PLUGIN_API_VERSION,
    BackendPlugin,
    ModelEntry,
    ModelListing,
    OptionSpec,
    StatusReport,
)


def make_contract(backend_id: str = "fake", features: frozenset[str] = frozenset()) -> BackendContract:
    return BackendContract(
        backend_id=backend_id,
        display_name=backend_id.title(),
        bin_name=backend_id,
        env_prefix=f"AMICUS_{backend_id.upper()}_",
        exec_argv_prefix=(),
        always_send_flags=("--json",),
        help_gated_flags=("--model",),
        forbidden_surface_phrases=("applies the diff to your working tree",),
        supported_features=features,
        readonly_honesty_statement="Read-only bounds writes, not reads.",
        implicit_context_disclosure="Auto-loads nothing.",
        structured_output="prompt_append",
        model_catalog=ModelCatalog("static", "advisory", "advisory"),
        isolation_policy=IsolationPolicy.SANDBOX_FLAG,
        needs_orphan_sweep=False,
        effort_silently_ignored_upstream=False,
    )


class FakeBackend:
    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        return None

    def prepare(self, request: RunRequest) -> Any:
        @contextlib.asynccontextmanager
        async def _cm() -> AsyncIterator[PreparedRun]:
            yield PreparedRun(argv=("fake",), env={}, cwd=request.cwd)

        return _cm()

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        return ExecResult(answer=outcome.run.stdout)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        return ClassifiedFailure(code="nonzero_exit", detail=outcome.run.stderr[:80])

    def list_models(self) -> tuple[str, ...]:
        return ("fake-1",)

    def auth_probe(self) -> bool | None:
        return True

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        return dict(env)


class _Status:
    def probe(self) -> StatusReport:
        return StatusReport(installed=True, version="fake 1.0", authenticated=True)


class _Models:
    def read(self) -> ModelListing:
        return ModelListing(models=(ModelEntry(slug="fake-1"),), source="static")


class _Binary:
    def resolve(self) -> str | None:
        return "/usr/bin/true"


def make_plugin(backend_id: str = "fake", **overrides: Any) -> BackendPlugin:
    fields: dict[str, Any] = {
        "contract": make_contract(backend_id, overrides.pop("features", frozenset({"delegate"}))),
        "backend": FakeBackend(),
        "options": (OptionSpec("isolation", "isolation", frozenset({"consult"}), "inherit"),),
        "status": _Status(),
        "models": _Models(),
        "binary": _Binary(),
        "help_probe": HelpProbe(help_argv=("true", "--help")),
        "vocabulary": BackendErrorVocabulary(
            backend_id, backend_id.title(), "Install fake.", "Log in to fake.", "amicus_backends"
        ),
        "env": EnvNamespace(prefix=f"AMICUS_{backend_id.upper()}_", vars=()),
        "effects": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
        "api_version": PLUGIN_API_VERSION,
    }
    fields.update(overrides)
    return BackendPlugin(**fields)


plugin = make_plugin()
```

- [ ] **Step 2: Write the failing tests**

`tests/test_plugin.py`:

```python
"""The plugin API: pure data plus runtime-checkable capability protocols."""

from __future__ import annotations

import dataclasses

from amicus import plugin as p
from tests.support import fakeplugin


def test_constants():
    assert p.PLUGIN_API_VERSION == 1
    assert p.ENTRY_POINT_GROUP == "amicus.backends"


def test_fake_plugin_is_a_complete_plugin():
    fp = fakeplugin.make_plugin()
    assert fp.backend_id == "fake"
    assert fp.api_version == 1
    assert isinstance(fp.status, p.StatusProbe)
    assert isinstance(fp.models, p.ModelCatalogReader)
    assert isinstance(fp.binary, p.BinaryResolver)
    assert fp.framing is None and fp.repair_overrides == {} and fp.local_codes == {}
    assert fp.egress == "" and fp.carriers == ""


def test_plugin_is_frozen():
    fp = fakeplugin.make_plugin()
    try:
        fp.api_version = 2  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("BackendPlugin must be frozen")


def test_option_spec_and_status_report_defaults():
    spec = p.OptionSpec("isolation", "isolation", frozenset({"consult"}))
    assert spec.default is None
    rep = p.StatusReport(installed=False)
    assert (rep.version, rep.authenticated, rep.warnings) == (None, None, ())
    listing = p.ModelListing(models=(), source="none")
    assert listing.fetched_at is None
```

`tests/test_registry.py`:

```python
"""BackendRegistry never raises on a bad backend; every failure is recorded."""

from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest

from amicus import backends, registry
from amicus.plugin import ENTRY_POINT_GROUP
from tests.support import fakeplugin


def _ep(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)


def test_in_tree_declarations():
    assert set(backends.IN_TREE) == {"codex", "kimi", "claude"}
    assert backends.IN_TREE["codex"] == "amicus.backends.codex:plugin"
    assert backends.KNOWN_EFFECTS["claude"].paid_calls_destructive is True
    assert backends.KNOWN_EFFECTS["codex"].paid_calls_destructive is False
    assert all(e.job_reads_read_only for e in backends.KNOWN_EFFECTS.values())
    assert backends.KNOWN_DISPLAY_NAMES["claude"] == "Claude Code"


def test_default_load_records_the_unported_in_tree_backends_as_unavailable():
    reg = registry.BackendRegistry.load(("codex", "kimi", "claude"), entry_points=())
    assert reg.available == {}
    assert set(reg.unavailable) == {"codex", "kimi", "claude"}
    assert reg.unavailable["codex"].reason == "import_failed"
    assert "amicus.backends.codex" in reg.unavailable["codex"].detail
    assert reg.get("codex") is None
    assert reg.ids == ()


def test_entry_point_plugin_loads_through_the_real_path():
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={}, entry_points=(_ep("fake", "tests.support.fakeplugin:plugin"),)
    )
    assert reg.ids == ("fake",)
    assert reg.get("fake") is fakeplugin.plugin
    assert reg.unavailable == {}


def test_factory_callables_are_called():
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:make_plugin"}, entry_points=()
    )
    assert reg.get("fake") is not None


def test_not_enabled_entry_points_are_ignored():
    reg = registry.BackendRegistry.load(
        ("codex",), in_tree={}, entry_points=(_ep("fake", "tests.support.fakeplugin:plugin"),)
    )
    assert reg.ids == () and reg.unavailable["codex"].reason == "not_installed"


def test_in_tree_ids_are_reserved_against_entry_points():
    reg = registry.BackendRegistry.load(
        ("codex",), in_tree={}, entry_points=(_ep("codex", "tests.support.fakeplugin:plugin"),)
    )
    assert reg.get("codex") is None
    assert reg.unavailable["codex"].reason == "reserved_id"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"api_version": 2}, "api_version"),
        ({"contract": fakeplugin.make_contract("other")}, "id_mismatch"),
    ],
)
def test_bad_plugins_are_recorded_not_raised(monkeypatch, override, reason):
    bad = fakeplugin.make_plugin(**override)
    monkeypatch.setattr(fakeplugin, "bad", bad, raising=False)
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:bad"}, entry_points=()
    )
    assert reg.get("fake") is None
    assert reg.unavailable["fake"].reason == reason


def test_contract_and_backend_conformance_failures_are_recorded(monkeypatch):
    # A contract whose own prose contains a phrase it bans fails check_contract.
    contract = fakeplugin.make_contract().__class__(
        **{
            **fakeplugin.make_contract().__dict__,
            "readonly_honesty_statement": "applies the diff to your working tree",
        }
    )
    monkeypatch.setattr(fakeplugin, "bad_contract", fakeplugin.make_plugin(contract=contract), raising=False)
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:bad_contract"}, entry_points=()
    )
    assert reg.unavailable["fake"].reason == "contract_violation"
    assert "forbidden phrase" in reg.unavailable["fake"].detail

    # A backend that is not structurally an AgentBackend fails check_backend.
    monkeypatch.setattr(fakeplugin, "bad_backend", fakeplugin.make_plugin(backend=object()), raising=False)
    reg = registry.BackendRegistry.load(
        ("fake",), in_tree={"fake": "tests.support.fakeplugin:bad_backend"}, entry_points=()
    )
    assert reg.unavailable["fake"].reason == "backend_violation"


def test_a_factory_that_raises_is_recorded():
    def boom():
        raise RuntimeError("no config")

    import tests.support.fakeplugin as fp

    fp.boom = boom  # type: ignore[attr-defined]
    try:
        reg = registry.BackendRegistry.load(
            ("fake",), in_tree={"fake": "tests.support.fakeplugin:boom"}, entry_points=()
        )
    finally:
        del fp.boom  # type: ignore[attr-defined]
    assert reg.unavailable["fake"].reason == "load_failed"
    assert "RuntimeError" in reg.unavailable["fake"].detail


def test_wrong_type_is_recorded():
    import tests.support.fakeplugin as fp

    fp.not_a_plugin = 42  # type: ignore[attr-defined]
    try:
        reg = registry.BackendRegistry.load(
            ("fake",), in_tree={"fake": "tests.support.fakeplugin:not_a_plugin"}, entry_points=()
        )
    finally:
        del fp.not_a_plugin  # type: ignore[attr-defined]
    assert reg.unavailable["fake"].reason == "load_failed"


def test_load_reads_installed_entry_points_by_default(monkeypatch):
    monkeypatch.setattr(
        registry, "_entry_points", lambda: (_ep("fake", "tests.support.fakeplugin:plugin"),)
    )
    reg = registry.BackendRegistry.load(("fake",), in_tree={})
    assert reg.ids == ("fake",)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_plugin.py tests/test_registry.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'amicus.plugin'`.

- [ ] **Step 4: Write the modules**

`src/amicus/plugin.py`:

```python
"""The backend plugin API: what a backend package hands amicus (pure data + protocols).

A plugin bundles pontonier's frozen contract and adapter with the amicus-side facts the
server needs: option specs, a status probe, a model-catalog reader, a binary resolver,
a help probe, the error vocabulary, an env namespace and the annotation effects. Outcome
inspection is a pontonier capability on `backend` itself (OutcomeInspector), so the
plugin carries nothing extra for it. Third-party backends register an entry point in
the `amicus.backends` group whose value is a BackendPlugin or a zero-argument factory.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.backend.contract import BackendContract
    from pontonier.backend.protocol import AgentBackend
    from pontonier.conventions.annotations import AnnotationEffects
    from pontonier.conventions.envelope import BackendErrorVocabulary, RepairRule
    from pontonier.conventions.preflight import HelpProbe

    from amicus.config.envspec import EnvNamespace

PLUGIN_API_VERSION = 1
ENTRY_POINT_GROUP = "amicus.backends"


@dataclass(frozen=True)
class OptionSpec:
    """One backend option: its `backend_options` key, the RunRequest field it maps to,
    the verbs it applies to, and the backend's default. The SCHEMA lives in
    amicus.schemas.options; this carries defaults and applicability only (ADR 0002)."""

    name: str
    maps_to: str
    applies_to: frozenset[str]
    default: Any = None


@dataclass(frozen=True)
class StatusReport:
    installed: bool
    version: str | None = None
    authenticated: bool | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelEntry:
    slug: str
    display_name: str | None = None
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ModelListing:
    models: tuple[ModelEntry, ...]
    source: Literal["cache", "static", "live", "none"]
    fetched_at: str | None = None


@runtime_checkable
class StatusProbe(Protocol):
    def probe(self) -> StatusReport: ...


@runtime_checkable
class ModelCatalogReader(Protocol):
    def read(self) -> ModelListing: ...


@runtime_checkable
class BinaryResolver(Protocol):
    def resolve(self) -> str | None: ...


@runtime_checkable
class FramingHook(Protocol):
    def frame(self, verb: str, framing: str, host_name: str) -> str: ...


@dataclass(frozen=True)
class BackendPlugin:
    contract: BackendContract
    backend: AgentBackend
    options: tuple[OptionSpec, ...]
    status: StatusProbe
    models: ModelCatalogReader
    binary: BinaryResolver
    help_probe: HelpProbe
    vocabulary: BackendErrorVocabulary
    env: EnvNamespace
    effects: AnnotationEffects
    repair_overrides: Mapping[str, RepairRule] = field(default_factory=dict)
    framing: FramingHook | None = None
    local_codes: Mapping[str, RepairRule] = field(default_factory=dict)
    # Agent-facing disclosures the contract does not carry: what a paid call sends where,
    # and which carriers (argv, handshake file) hold the prompt on this backend.
    egress: str = ""
    carriers: str = ""
    api_version: int = PLUGIN_API_VERSION

    @property
    def backend_id(self) -> str:
        return self.contract.backend_id
```

`src/amicus/backends/__init__.py`:

```python
"""In-tree backend declarations. The packages themselves land per milestone (M1 codex,
M3 kimi, M4 claude); until then the registry records each as unavailable, which is the
honest state, never a startup failure."""

from __future__ import annotations

from pontonier.conventions.annotations import AnnotationEffects

# backend id -> "module:attribute" of a BackendPlugin or a zero-argument factory.
IN_TREE: dict[str, str] = {
    "codex": "amicus.backends.codex:plugin",
    "kimi": "amicus.backends.kimi:plugin",
    "claude": "amicus.backends.claude:plugin",
}

# Declared effects used to annotate the tool surface BEFORE a plugin is loaded (tool
# annotations are static per profile). `job_reads_read_only` is amicus policy for every
# backend (ADR 0001); `paid_calls_destructive` is each backend's fact. A test in each
# backend's milestone pins plugin.effects against this table.
KNOWN_EFFECTS: dict[str, AnnotationEffects] = {
    "codex": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
    "kimi": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
    "claude": AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
}

KNOWN_DISPLAY_NAMES: dict[str, str] = {"codex": "Codex", "kimi": "Kimi", "claude": "Claude Code"}
```

`src/amicus/registry.py`:

```python
"""BackendRegistry: load enabled backends from in-tree factories and entry points.

Never raises on a bad backend: an import error, a wrong api_version, an id mismatch, a
pontonier conformance violation (`check_contract` AND `check_backend`) or a factory
exception is recorded as UnavailableBackend and reported by amicus_backends."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Literal

from pontonier.core.redaction import exc_summary
from pontonier.testing import conformance

from amicus import backends as in_tree_backends
from amicus.plugin import ENTRY_POINT_GROUP, PLUGIN_API_VERSION, BackendPlugin

Reason = Literal[
    "not_installed",
    "import_failed",
    "load_failed",
    "api_version",
    "id_mismatch",
    "reserved_id",
    "contract_violation",
    "backend_violation",
]


@dataclass(frozen=True)
class UnavailableBackend:
    backend_id: str
    reason: Reason
    detail: str


def _entry_points() -> Iterable[EntryPoint]:
    return entry_points(group=ENTRY_POINT_GROUP)


def _load_dotted(value: str) -> Any:
    module_name, _, attr = value.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr) if attr else module


def _materialize(obj: Any) -> BackendPlugin:
    if not isinstance(obj, BackendPlugin) and callable(obj):
        obj = obj()
    if not isinstance(obj, BackendPlugin):
        raise TypeError(f"expected a BackendPlugin, got {type(obj).__name__}")
    return obj


def _validate(backend_id: str, plugin: BackendPlugin) -> UnavailableBackend | None:
    if plugin.api_version != PLUGIN_API_VERSION:
        return UnavailableBackend(
            backend_id, "api_version",
            f"plugin api_version {plugin.api_version} != {PLUGIN_API_VERSION}",
        )
    if plugin.backend_id != backend_id:
        return UnavailableBackend(
            backend_id, "id_mismatch", f"plugin contract names {plugin.backend_id!r}"
        )
    violations = conformance.check_contract(plugin.contract)
    if violations:
        return UnavailableBackend(backend_id, "contract_violation", "; ".join(violations))
    violations = conformance.check_backend(plugin.contract, plugin.backend)
    if violations:
        return UnavailableBackend(backend_id, "backend_violation", "; ".join(violations))
    return None


class BackendRegistry:
    def __init__(
        self, available: dict[str, BackendPlugin], unavailable: dict[str, UnavailableBackend]
    ) -> None:
        self.available = available
        self.unavailable = unavailable

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self.available)

    def get(self, backend_id: str) -> BackendPlugin | None:
        return self.available.get(backend_id)

    def unavailable_for(self, backend_id: str) -> UnavailableBackend | None:
        return self.unavailable.get(backend_id)

    @classmethod
    def load(
        cls,
        enabled: Iterable[str],
        *,
        in_tree: Mapping[str, str] | None = None,
        entry_points: Iterable[EntryPoint] | None = None,
    ) -> BackendRegistry:
        tree = in_tree_backends.IN_TREE if in_tree is None else in_tree
        eps = {ep.name: ep for ep in (_entry_points() if entry_points is None else entry_points)}
        available: dict[str, BackendPlugin] = {}
        unavailable: dict[str, UnavailableBackend] = {}
        for backend_id in enabled:
            source: str | EntryPoint | None
            if backend_id in tree:
                source = tree[backend_id]
            elif backend_id in eps:
                if backend_id in in_tree_backends.IN_TREE:
                    unavailable[backend_id] = UnavailableBackend(
                        backend_id, "reserved_id",
                        f"{backend_id!r} is an in-tree backend id; an entry point may not claim it",
                    )
                    continue
                source = eps[backend_id]
            else:
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "not_installed",
                    f"no in-tree factory or {ENTRY_POINT_GROUP} entry point named {backend_id!r}",
                )
                continue
            try:
                raw = _load_dotted(source) if isinstance(source, str) else source.load()
            except ImportError as exc:
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "import_failed", exc_summary(exc)
                )
                continue
            except Exception as exc:  # noqa: BLE001 - any failure is recorded, never raised
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "load_failed", exc_summary(exc)
                )
                continue
            try:
                plugin = _materialize(raw)
            except Exception as exc:  # noqa: BLE001
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "load_failed", exc_summary(exc)
                )
                continue
            problem = _validate(backend_id, plugin)
            if problem is not None:
                unavailable[backend_id] = problem
                continue
            available[backend_id] = plugin
        return cls(available, unavailable)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_plugin.py tests/test_registry.py -v --no-cov`
Expected: all PASS. If `test_contract_and_backend_conformance_failures_are_recorded` fails because `BackendContract.__dict__` includes computed values, build the bad contract with `dataclasses.replace(fakeplugin.make_contract(), readonly_honesty_statement="applies the diff to your working tree")` instead (import `dataclasses` in the test).

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/plugin.py src/amicus/backends src/amicus/registry.py tests/support tests/test_plugin.py tests/test_registry.py
git commit -m "feat(plugin): add the backend plugin API and a never-raising registry

BackendPlugin bundles pontonier's contract and adapter with the amicus
facts the server needs; the registry loads in-tree factories then
amicus.backends entry points and records every failure (import,
api_version, id mismatch, check_contract, check_backend) as unavailable
instead of blocking startup. The FakePlugin exercises the entry-point
path end to end."
```

---

### Task 10: Backend-aware error rendering

**Files:**
- Create: `src/amicus/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: `pontonier.conventions.envelope.{repair_rules, RepairRule, BackendErrorVocabulary}`, `pontonier.backend.protocol.{ClassifiedFailure, RepairHint, Usage as PUsage}`, `codes.{ERROR_CODES, generalize_code}`, `envelope.*`, `plugin.BackendPlugin`.
- Produces: `NEUTRAL_VOCABULARY`, `KEEP_TABLE_TOOL` sentinel, `repair_table(plugin=None) -> dict[str, RepairRule]`, `make_error(code, message, *, backend=None, plugin=None, retry_after_ms=None, temporary=None, repair_next_step=None, repair_tool=KEEP_TABLE_TOOL, repair_arguments=None, repair_alternative=None, details=None, invalid_arguments=None, limit_bytes=None, actual_bytes=None, candidate_roots=None) -> ErrorInfo`, `serialize_error_info(error) -> dict`, `serialize_error(result) -> dict`, `error_envelope(code, message, meta, **kw) -> dict` (make + wrap + serialize), `render_failure(plugin, failure, meta) -> dict`.

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`:

```python
"""One serializer for the §6 envelope; pontonier rules are defaults, plugins override."""

from __future__ import annotations

import pytest
from pontonier.backend.protocol import ClassifiedFailure, RepairHint
from pontonier.backend.protocol import Usage as PUsage
from pontonier.conventions.envelope import RepairRule

from amicus import errors
from amicus.schemas.codes import ERROR_CODES
from amicus.schemas.envelope import ErrorDetail, ErrorResult, InvalidArgument, Meta
from tests.support import fakeplugin


def test_repair_table_covers_the_whole_catalog_and_no_more():
    table = errors.repair_table()
    assert set(table) == set(ERROR_CODES)
    assert table["backend_not_found"].next_step == "install_backend"
    assert table["not_implemented"].tool == "amicus_capabilities"
    assert "amicus_backends" in table["backend_unavailable"].alternative
    # Prose overrides name amicus tools, never a sibling's.
    assert "amicus_consult_async" in table["timeout"].alternative
    assert "codex" not in table["invalid_arguments"].alternative


def test_plugin_overrides_win_per_code_and_local_codes_are_added():
    plugin = fakeplugin.make_plugin(
        repair_overrides={
            "fake_auth_required": RepairRule("authenticate", None, False, "Run `fake login`.")
        },
        local_codes={"fake_only": RepairRule("inspect_and_retry", None, True, "fake-only")},
    )
    table = errors.repair_table(plugin)
    assert table["backend_auth_required"].alternative == "Run `fake login`."
    assert table["fake_only"].alternative == "fake-only"
    assert errors.repair_table()["backend_auth_required"].alternative != "Run `fake login`."


def test_make_error_derives_repair_and_temporary_from_the_table():
    info = errors.make_error("job_running", "still running", retry_after_ms=500)
    assert info.temporary is True and info.retry_after_ms == 500
    assert info.repair is not None
    assert info.repair.next_step == "poll_job_status" and info.repair.tool == "amicus_job_status"
    info = errors.make_error("invalid_scope", "bad", retry_after_ms=500)
    assert info.temporary is False and info.retry_after_ms is None
    info = errors.make_error("invalid_scope", "bad", temporary=True, retry_after_ms=5)
    assert info.retry_after_ms == 5


def test_make_error_repair_tool_three_states():
    keep = errors.make_error("job_not_found", "m")
    assert keep.repair is not None and keep.repair.tool == "amicus_job_list"
    cleared = errors.make_error("job_not_found", "m", repair_tool=None)
    assert cleared.repair is not None and cleared.repair.tool is None
    named = errors.make_error("job_not_found", "m", repair_tool="amicus_job_status")
    assert named.repair is not None and named.repair.tool == "amicus_job_status"


def test_invalid_arguments_requires_the_list_and_derives_details():
    with pytest.raises(ValueError, match="non-empty invalid_arguments"):
        errors.make_error("invalid_arguments", "m")
    with pytest.raises(ValueError, match="derived"):
        errors.make_error(
            "invalid_arguments", "m", details=ErrorDetail(field="x"),
            invalid_arguments=[InvalidArgument(field="x", reason="r")],
        )
    info = errors.make_error(
        "invalid_arguments", "m",
        invalid_arguments=[InvalidArgument(field="x", reason="r", allowed_values=["a"])],
    )
    assert info.details == ErrorDetail(field="x", reason="r", allowed_values=["a"])


def test_serialize_strips_none_but_keeps_retry_after_ms():
    info = errors.make_error("internal_error", "m", backend="codex")
    out = errors.serialize_error(ErrorResult(error=info, meta=Meta()))
    assert out["ok"] is False
    assert out["error"]["retry_after_ms"] is None
    assert "details" not in out["error"]
    assert out["error"]["backend"] == "codex"
    assert "cwd" not in out["meta"]
    assert errors.serialize_error_info(info)["code"] == "internal_error"


def test_error_envelope_helper():
    out = errors.error_envelope("not_implemented", "later", Meta(), backend="kimi")
    assert out["error"]["code"] == "not_implemented" and out["error"]["backend"] == "kimi"


def test_render_failure_generalizes_minted_codes_and_names_the_backend():
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(code="fake_rate_limited", detail="slow down", retry_after_ms=250)
    out = errors.render_failure(plugin, failure, Meta())
    err = out["error"]
    assert err["code"] == "backend_rate_limited" and err["backend"] == "fake"
    assert err["temporary"] is True and err["retry_after_ms"] == 250
    assert err["repair"]["next_step"] == "retry_after_delay"


def test_render_failure_honors_retryable_details_repair_and_usage():
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(
        code="timeout",
        detail="deadline",
        retryable=False,
        details={"field": "timeout_seconds", "reason": "exceeded"},
        repair=RepairHint(next_step="reduce_input", tool="amicus_consult", alternative="shrink"),
        usage=PUsage(input_tokens=3, cost_usd=0.5),
    )
    out = errors.render_failure(plugin, failure, Meta())
    err = out["error"]
    assert err["temporary"] is False and err["retry_after_ms"] is None
    assert err["details"] == {"field": "timeout_seconds", "reason": "exceeded", "field_withheld": False}
    assert err["repair"] == {"next_step": "reduce_input", "tool": "amicus_consult", "alternative": "shrink"}
    assert out["meta"]["usage"]["input_tokens"] == 3 and out["meta"]["usage"]["cost_usd"] == 0.5


def test_render_failure_maps_an_uncataloged_code_to_internal_error_with_the_detail():
    plugin = fakeplugin.make_plugin()
    out = errors.render_failure(plugin, ClassifiedFailure(code="mystery", detail="d"), Meta())
    assert out["error"]["code"] == "internal_error"
    assert "mystery" in out["error"]["message"] and "d" in out["error"]["message"]


def test_render_failure_tolerates_bad_details():
    plugin = fakeplugin.make_plugin()
    failure = ClassifiedFailure(code="nonzero_exit", detail="d", details={"field": "a", "fields": ["b"]})
    out = errors.render_failure(plugin, failure, Meta())
    assert out["error"]["details"] == {"reason": "field=a fields=['b']", "field_withheld": False}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'errors'`.

- [ ] **Step 3: Write `src/amicus/errors.py`**

```python
"""Construction and serialization of the error envelope (ADR 0005).

pontonier's `repair_rules()` are the defaults, minted with a neutral vocabulary so the
four per-backend codes come out as `backend_*`; amicus-local codes and prose overrides
sit on top; a plugin's `local_codes` are added and its `repair_overrides` win per code.
`render_failure` turns a backend's ClassifiedFailure into the wire envelope, honoring the
0.9.0 machine fields (`retryable`, `details`, `repair`, `usage`)."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from pontonier.conventions.envelope import BackendErrorVocabulary, RepairRule, repair_rules
from pydantic import ValidationError

from amicus.schemas.codes import ERROR_CODES, generalize_code
from amicus.schemas.envelope import (
    ErrorDetail,
    ErrorInfo,
    ErrorResult,
    InvalidArgument,
    Meta,
    Repair,
    Usage,
)

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.backend.protocol import ClassifiedFailure

    from amicus.plugin import BackendPlugin

NEUTRAL_VOCABULARY = BackendErrorVocabulary(
    backend_id="backend",
    display_name="the backend",
    install_hint="Install the CLI of the backend named in error.backend, then rerun amicus_backends.",
    login_hint="Log in to the CLI of the backend named in error.backend, then rerun amicus_backends.",
    status_tool="amicus_backends",
)
_FEATURES = frozenset({"model_validation", "empty_response_detection"})

_LOCAL_RULES: dict[str, RepairRule] = {
    "not_implemented": RepairRule(
        "update_plugin",
        "amicus_capabilities",
        False,
        "This tool's backend has not landed in this amicus release; amicus_capabilities "
        "lists what is implemented. Update amicus when the backend ships.",
    ),
    "backend_unavailable": RepairRule(
        "inspect_and_retry",
        "amicus_backends",
        False,
        "The backend failed to load; amicus_backends reports the reason. Fix it or pick "
        "another backend.",
    ),
    "feature_unsupported": RepairRule(
        "use_allowed_value",
        "amicus_backends",
        False,
        "This backend does not support this verb; amicus_backends lists each backend's "
        "features. Pick a backend that declares it.",
    ),
}

# Prose that must name amicus tools rather than a sibling's.
_PROSE_OVERRIDES: dict[str, str] = {
    "invalid_arguments": (
        "Check each tool's inputSchema (tools/list) or amicus_capabilities, then retry."
    ),
    "timeout": (
        "Retrying the same synchronous call will likely time out again. Prefer the matching "
        "async tool (amicus_consult_async / amicus_review_changes_async / "
        "amicus_adversarial_review_async / amicus_delegate_async), then poll "
        "amicus_job_status and fetch amicus_job_result. Otherwise narrow the task or raise "
        "timeout_seconds."
    ),
    "resource_not_found": (
        "List the available resource URIs via the MCP resources/list method (or "
        "amicus_capabilities), then retry with an exact URI."
    ),
    "job_not_found": "Call amicus_job_list to recover known job_ids in this workspace.",
    "job_running": "Poll amicus_job_status until result_available, honoring poll_after_ms.",
}
_TOOL_OVERRIDES: dict[str, str] = {
    "job_not_found": "amicus_job_list",
    "job_running": "amicus_job_status",
    "invalid_reasoning_effort": "amicus_models",
    "invalid_model": "amicus_models",
}


def repair_table(plugin: BackendPlugin | None = None) -> dict[str, RepairRule]:
    rules = dict(repair_rules(NEUTRAL_VOCABULARY, _FEATURES))
    rules.update(_LOCAL_RULES)
    for code, prose in _PROSE_OVERRIDES.items():
        rules[code] = dataclasses.replace(rules[code], alternative=prose)
    for code, tool in _TOOL_OVERRIDES.items():
        rules[code] = dataclasses.replace(rules[code], tool=tool)
    if plugin is not None:
        rules.update(plugin.local_codes)
        for code, rule in plugin.repair_overrides.items():
            rules[generalize_code(code, plugin.backend_id)] = rule
    return rules


class _KeepTableTool:
    __slots__ = ()


KEEP_TABLE_TOOL = _KeepTableTool()


def make_error(
    code: str,
    message: str,
    *,
    backend: str | None = None,
    plugin: BackendPlugin | None = None,
    retry_after_ms: int | None = None,
    temporary: bool | None = None,
    repair_next_step: str | None = None,
    repair_tool: str | _KeepTableTool | None = KEEP_TABLE_TOOL,
    repair_arguments: dict[str, Any] | None = None,
    repair_alternative: str | None = None,
    details: ErrorDetail | None = None,
    invalid_arguments: list[InvalidArgument] | None = None,
    limit_bytes: int | None = None,
    actual_bytes: int | None = None,
    candidate_roots: list[str] | None = None,
) -> ErrorInfo:
    """Build the envelope for `code`, deriving the symbolic repair from the table.
    `repair_tool` has three states: omitted keeps the table's tool, a string overrides
    it, explicit None clears it. An `invalid_arguments` envelope must carry the list and
    `details` is always derived from its first entry."""
    if code == "invalid_arguments":
        if not invalid_arguments:
            raise ValueError("make_error: an invalid_arguments envelope must carry a non-empty invalid_arguments list")
        if details is not None:
            raise ValueError("make_error: `details` is derived from invalid_arguments[0]; do not supply it")
        first = invalid_arguments[0]
        details = ErrorDetail(
            field=first.field,
            reason=first.reason,
            allowed_values=first.allowed_values,
            field_withheld=first.field_withheld,
        )
    rule = repair_table(plugin)[code]
    next_step = repair_next_step or rule.next_step
    tool = rule.tool if isinstance(repair_tool, _KeepTableTool) else repair_tool
    is_temp = rule.temporary if temporary is None else temporary
    backend_id = backend if backend is not None else (plugin.backend_id if plugin else None)
    return ErrorInfo(
        code=code,  # type: ignore[arg-type]  # validated by pydantic against the catalog
        message=message,
        backend=backend_id,
        temporary=is_temp,
        retry_after_ms=retry_after_ms if is_temp else None,
        repair=Repair(
            next_step=next_step,  # type: ignore[arg-type]
            tool=tool,
            arguments=repair_arguments,
            alternative=repair_alternative or rule.alternative,
        ),
        details=details,
        invalid_arguments=invalid_arguments,
        limit_bytes=limit_bytes,
        actual_bytes=actual_bytes,
        candidate_roots=candidate_roots,
    )


def serialize_error_info(error: ErrorInfo) -> dict[str, Any]:
    """Strip absent optionals but ALWAYS keep `retry_after_ms` (§6 wants the key)."""
    payload = error.model_dump(mode="json", exclude_none=True)
    payload.setdefault("retry_after_ms", None)
    return payload


def serialize_error(result: ErrorResult) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude_none=True)
    payload["error"] = serialize_error_info(result.error)
    return payload


def error_envelope(code: str, message: str, meta: Meta, **kwargs: Any) -> dict[str, Any]:
    return serialize_error(ErrorResult(error=make_error(code, message, **kwargs), meta=meta))


def _detail_from(raw: dict[str, Any] | None) -> ErrorDetail | None:
    if not raw:
        return None
    try:
        return ErrorDetail.model_validate(raw)
    except ValidationError:
        return ErrorDetail(reason=" ".join(f"{k}={v}" for k, v in raw.items())[:300])


def render_failure(plugin: BackendPlugin, failure: ClassifiedFailure, meta: Meta) -> dict[str, Any]:
    """The wire envelope for a backend's classified failure. Minted codes are
    generalized; an uncataloged code is reported as internal_error with the original
    code and detail in the message; `retryable` overrides the rule's `temporary`; a
    backend-supplied repair wins over the table; usage from a failed run is kept."""
    table = repair_table(plugin)
    code = generalize_code(failure.code, plugin.backend_id)
    message = failure.detail
    if code not in table or code not in ERROR_CODES:
        message = f"{failure.code}: {failure.detail}"
        code = "internal_error"
    rule = table[code]
    temporary = rule.temporary if failure.retryable is None else failure.retryable
    if failure.repair is not None:
        repair = Repair(
            next_step=failure.repair.next_step,  # type: ignore[arg-type]
            tool=failure.repair.tool,
            arguments=failure.repair.arguments,
            alternative=failure.repair.alternative or rule.alternative,
        )
    else:
        repair = Repair(next_step=rule.next_step, tool=rule.tool, alternative=rule.alternative)  # type: ignore[arg-type]
    if failure.usage is not None:
        meta = meta.model_copy(update={"usage": Usage(**dataclasses.asdict(failure.usage))})
    info = ErrorInfo(
        code=code,  # type: ignore[arg-type]
        message=message,
        backend=plugin.backend_id,
        temporary=temporary,
        retry_after_ms=failure.retry_after_ms if temporary else None,
        repair=repair,
        details=_detail_from(failure.details),
    )
    return serialize_error(ErrorResult(error=info, meta=meta))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -v --no-cov`
Expected: all PASS. If `test_repair_table_covers_the_whole_catalog_and_no_more` fails because `repair_rules` mints a code the catalog lacks (or vice versa), the catalog in `codes.py` is wrong — fix `codes.py`, never the table.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/errors.py tests/test_errors.py
git commit -m "feat(errors): render failures with backend-aware repair precedence

pontonier's repair rules are the defaults (minted with a neutral
vocabulary so the four per-backend codes generalize to backend_*), a
plugin's local codes are added and its overrides win per code, and
render_failure honors the 0.9.0 machine fields on ClassifiedFailure
(ADR 0005)."
```

---

### Task 11: Middlewares, capability suppression, `create_app`, logging, `main`

**Files:**
- Create: `src/amicus/middleware.py`, `src/amicus/obs.py`, `src/amicus/server.py`, `src/amicus/tools/__init__.py` (stub for this task; Task 12 fills it), `src/amicus/tools/_meta.py`
- Test: `tests/test_middleware.py`, `tests/test_server.py`, `tests/test_obs.py`

**Interfaces:**
- Produces (`middleware`): `InputSchemaDialectMiddleware()`, `SemanticErrorMiddleware()`, `ValidationEnvelopeMiddleware(app, settings)`, `ResourceErrorMiddleware()`, `invalid_arguments_envelope(tool_name, *, param_names, property_schemas, errors, meta) -> dict | None`, `format_loc(loc) -> str`, `WITHHELD_FIELD = "<withheld>"`, `resource_not_found_code(context) -> int`.
- Produces (`tools._meta`): `SERVER_STABILITY = "alpha"`, `TOOL_STABILITY: dict[str, str]`, `lifecycle_meta(name) -> dict`, `effects_for(settings) -> AnnotationEffects`, `annotations_for(kind, settings) -> dict[str, bool]` with `kind in {"active", "free", "job_read", "job_consume", "job_cancel"}`, `base_meta(settings, *, backend=None, **fields) -> Meta`, `tool_stability(name) -> str`.
- Produces (`obs`): `configure(settings, *, force=False) -> logging.Logger`, `get_logger(name)`.
- Produces (`server`): `CAPABILITY_SUMMARY: str`, `UI_EXTENSION_ID`, `AppState(settings, registry)`, `create_app(settings=None, registry=None) -> FastMCP`, `state_of(app) -> AppState`, `main()`.
- Produces (`tools.__init__` stub): `register_all(app, settings, registry) -> None` (no-op in this task; `TOOL_ORDER = ()`).

- [ ] **Step 1: Write the failing tests**

`tests/test_middleware.py`:

```python
"""The four middlewares, driven through an in-memory client against a scratch app."""

from __future__ import annotations

from typing import Literal

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ResourceError
from mcp import MCPError

from amicus import config, middleware
from amicus.schemas.envelope import Meta


def _scratch_app() -> FastMCP:
    settings = config.settings({})
    app = FastMCP(name="scratch")
    app.add_middleware(middleware.InputSchemaDialectMiddleware())
    app.add_middleware(middleware.SemanticErrorMiddleware())
    app.add_middleware(middleware.ValidationEnvelopeMiddleware(app, settings))
    app.add_middleware(middleware.ResourceErrorMiddleware())

    @app.tool(name="probe")
    async def probe(mode: Literal["ok", "fail"], paths: list[str] | None = None) -> dict:
        if mode == "fail":
            return {"ok": False, "error": {"code": "internal_error"}}
        return {"ok": True}

    @app.resource("scratch://boom")
    def boom() -> str:
        raise ResourceError("nope")

    return app


async def test_input_schema_dialect_is_stamped():
    async with Client(_scratch_app()) as c:
        [tool] = await c.list_tools()
    assert tool.input_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


async def test_semantic_error_flips_is_error():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "fail"}, raise_on_error=False)
        ok = await c.call_tool("probe", {"mode": "ok"}, raise_on_error=False)
    assert res.is_error is True and res.structured_content["ok"] is False
    assert ok.is_error is False


async def test_validation_envelope_for_an_enum_failure():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "nope"}, raise_on_error=False)
    assert res.is_error
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "mode"
    assert err["details"]["allowed_values"] == ["ok", "fail"]
    assert err["repair"]["tool"] == "probe"
    assert "use one of the field's allowed_values" in err["repair"]["alternative"]
    assert res.structured_content["meta"]["timeout_seconds"] == 300
    assert "nope" not in err["message"]


async def test_validation_envelope_for_unknown_and_missing_arguments():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "ok", "extra": 1}, raise_on_error=False)
        missing = await c.call_tool("probe", {}, raise_on_error=False)
    assert res.structured_content["error"]["details"]["field"] == "extra"
    assert "remove the unknown argument" in res.structured_content["error"]["repair"]["alternative"]
    assert missing.structured_content["error"]["details"]["field"] == "mode"


async def test_validation_envelope_indexed_loc_and_withheld_name():
    async with Client(_scratch_app()) as c:
        res = await c.call_tool("probe", {"mode": "ok", "paths": [1]}, raise_on_error=False)
        bad = await c.call_tool("probe", {"mode": "ok", "a\x07b": 1}, raise_on_error=False)
    assert res.structured_content["error"]["details"]["field"] == "paths[0]"
    detail = bad.structured_content["error"]["details"]
    assert detail["field"] == middleware.WITHHELD_FIELD and detail["field_withheld"] is True


def test_format_loc_bounds_and_withholds():
    assert middleware.format_loc(("paths", 0)) == "paths[0]"
    assert middleware.format_loc(()) == "<arguments>"
    assert middleware.format_loc(("x" * 200,)).endswith("…")
    assert middleware.format_loc(("a\x1bb",)) == middleware.WITHHELD_FIELD


def test_invalid_arguments_envelope_returns_none_for_non_argument_errors():
    out = middleware.invalid_arguments_envelope(
        "probe",
        param_names={"mode"},
        property_schemas={},
        errors=[{"loc": ("something_else",), "msg": "m", "type": "value_error"}],
        meta=Meta(),
    )
    assert out is None


async def test_resource_errors_carry_the_envelope_per_era():
    app = _scratch_app()
    async with Client(app, mode="legacy") as legacy:
        with pytest.raises(MCPError) as exc:
            await legacy.read_resource("scratch://missing")
    assert exc.value.error.code == -32002
    data = exc.value.error.data
    assert data["machine_code"] == "resource_not_found"
    assert data["human_message"] == "Resource not found."
    assert data["resource_uri"] == "scratch://missing"
    assert "code" not in data and "message" not in data
    async with Client(app) as modern:
        assert modern.protocol_version == "2026-07-28"
        with pytest.raises(MCPError) as exc:
            await modern.read_resource("scratch://missing")
        assert exc.value.error.code == -32602
        with pytest.raises(MCPError) as exc:
            await modern.read_resource("scratch://boom")
        assert exc.value.error.code == -32603
        assert exc.value.error.data["machine_code"] == "internal_error"


def test_resource_not_found_code_defaults_to_handshake_without_evidence():
    assert middleware.resource_not_found_code(object()) == -32002
```

`tests/test_server.py`:

```python
"""create_app: capability suppression on both eras, instructions, main()."""

from __future__ import annotations

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.registry import BackendRegistry


def _app():
    return server.create_app(config.settings({}), BackendRegistry({}, {}))


async def test_initialize_does_not_advertise_prompts_or_the_ui_extension():
    async with Client(_app(), mode="legacy") as c:
        caps = c.initialize_result.capabilities
        assert c.initialize_result.instructions == server.CAPABILITY_SUMMARY
    wire = caps.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert "prompts" not in wire and "extensions" not in wire
    assert caps.tools is not None and caps.resources is not None


async def test_discover_does_not_advertise_prompts_or_the_ui_extension():
    async with Client(_app()) as c:
        assert c.protocol_version == "2026-07-28"
        caps = c.server_capabilities
    wire = caps.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert "prompts" not in wire and "extensions" not in wire


async def test_ui_filter_preserves_other_extensions(monkeypatch):
    app = _app()
    original = app._mcp_server.get_capabilities

    def fake(*args, **kwargs):
        caps = original(*args, **kwargs)
        return caps.model_copy(update={"extensions": {server.UI_EXTENSION_ID: {}, "io.example/x": {"a": 1}}})

    monkeypatch.setattr(app._mcp_server, "get_capabilities", server._filter_capabilities(fake))
    async with Client(app) as c:
        wire = c.server_capabilities.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert wire["extensions"] == {"io.example/x": {"a": 1}}


def test_state_is_attached_and_summary_is_rules_then_context():
    app = _app()
    state = server.state_of(app)
    assert state.settings.enabled_backends == ("codex", "kimi", "claude")
    lead = server.CAPABILITY_SUMMARY.split(". ")[0]
    assert "second opinion" in lead
    assert "does not" in server.CAPABILITY_SUMMARY[:400]
    assert server.CAPABILITY_SUMMARY.index("Use amicus_backends") < server.CAPABILITY_SUMMARY.index("Background:")
    assert "isError: true" in server.CAPABILITY_SUMMARY
    assert "completed" in server.CAPABILITY_SUMMARY and "delivery statement" in server.CAPABILITY_SUMMARY


def test_create_app_defaults_to_process_settings(clean_env):
    clean_env.setenv("AMICUS_BACKENDS", "codex")
    app = server.create_app()
    assert server.state_of(app).settings.enabled_backends == ("codex",)


def test_tasks_flag_without_the_extension_is_a_config_error(clean_env, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastmcp_tasks"):
            raise ImportError("no fastmcp_tasks")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    app = server.create_app(config.settings({"AMICUS_TASKS": "1"}), BackendRegistry({}, {}))
    state = server.state_of(app)
    assert state.tasks_active is False
    assert any("fastmcp[tasks]" in e for e in state.config_errors)


def test_main_handles_disconnects_and_crashes(monkeypatch, clean_env):
    calls = []

    class FakeApp:
        def __init__(self, exc):
            self.exc = exc

        def run(self):
            calls.append("run")
            if self.exc:
                raise self.exc

    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(KeyboardInterrupt()))
    server.main()
    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(None))
    server.main()
    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(RuntimeError("boom")))
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 1
    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(SystemExit(3)))
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 3
    assert calls == ["run"] * 4


def test_main_refuses_non_posix(monkeypatch, clean_env):
    with pytest.raises(SystemExit):
        server._enforce_posix_platform("nt")
    server._enforce_posix_platform("posix")
    clean_env.setenv("AMICUS_ALLOW_UNSUPPORTED_PLATFORM", "1")
    server._enforce_posix_platform("nt")  # downgraded to a warning
```

`tests/test_obs.py`:

```python
"""Logging goes to stderr (and optionally a file), never stdout."""

from __future__ import annotations

import logging
import sys

from amicus import config, obs


def test_configure_attaches_stderr_and_optional_file(tmp_path, clean_env):
    log_file = tmp_path / "amicus.log"
    settings = config.settings({"AMICUS_LOG_LEVEL": "DEBUG", "AMICUS_LOG_FILE": str(log_file)})
    logger = obs.configure(settings, force=True)
    assert logger.level == logging.DEBUG
    streams = [getattr(h, "stream", None) for h in logger.handlers]
    assert sys.stderr in streams and sys.stdout not in streams
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    assert logging.getLogger("pontonier").propagate is False
    obs.get_logger("amicus.x").debug("hello")
    for h in logger.handlers:
        h.flush()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_configure_is_idempotent_and_survives_a_bad_file(tmp_path, clean_env):
    settings = config.settings({"AMICUS_LOG_FILE": str(tmp_path / "missing" / "x.log")})
    logger = obs.configure(settings, force=True)
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    again = obs.configure(config.settings({"AMICUS_LOG_LEVEL": "ERROR"}))
    assert again is logger and logger.level != logging.ERROR
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_middleware.py tests/test_server.py tests/test_obs.py -v --no-cov`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `src/amicus/tools/_meta.py` and the tools stub**

`src/amicus/tools/__init__.py` (stub; Task 12 replaces it):

```python
"""Tool registration in a fixed order (filled in by the tool modules)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

TOOL_ORDER: tuple[str, ...] = ()


def register_all(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    """Register every tool in TOOL_ORDER (no tools yet in this task)."""
```

`src/amicus/tools/_meta.py`:

```python
"""Per-tool metadata shared by every tool module: annotations (worst enabled backend,
ADR 0001), lifecycle _meta, stability tiers, and the base Meta for an envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pontonier.conventions import annotations as ann
from pontonier.conventions.annotations import AnnotationEffects

from amicus.backends import KNOWN_EFFECTS
from amicus.schemas.envelope import Meta
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings

SERVER_STABILITY = "alpha"
# Tools more experimental than the server-wide tier; anything absent inherits it.
TOOL_STABILITY: dict[str, str] = {
    "amicus_consult_async": "experimental",
    "amicus_review_changes_async": "experimental",
    "amicus_adversarial_review_async": "experimental",
    "amicus_delegate_async": "experimental",
    "amicus_job_status": "experimental",
    "amicus_job_result": "experimental",
    "amicus_job_consume_result": "experimental",
    "amicus_job_cancel": "experimental",
    "amicus_job_list": "experimental",
}
# An enabled id the in-tree table does not know (a third-party plugin) is annotated for
# the worst case until its plugin declares otherwise.
_UNKNOWN_EFFECTS = AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True)

AnnotationKind = Literal["active", "free", "job_read", "job_consume", "job_cancel"]


def tool_stability(name: str) -> str:
    return TOOL_STABILITY.get(name, SERVER_STABILITY)


def lifecycle_meta(name: str) -> dict[str, Any]:
    """The `<reverse-dns>/lifecycle` _meta block ([9.tier-metadata]); the deprecation
    marker is absent, which is the not-deprecated signal."""
    return {LIFECYCLE_META_KEY: {"stability": tool_stability(name)}}


def effects_for(settings: Settings) -> AnnotationEffects:
    destructive = any(
        KNOWN_EFFECTS.get(b, _UNKNOWN_EFFECTS).paid_calls_destructive
        for b in settings.enabled_backends
    )
    return AnnotationEffects(paid_calls_destructive=destructive, job_reads_read_only=True)


def annotations_for(kind: AnnotationKind, settings: Settings) -> dict[str, bool]:
    effects = effects_for(settings)
    if kind == "active":
        return ann.active(effects)
    if kind == "free":
        return ann.free_read()
    if kind == "job_read":
        return ann.job_read(effects)
    if kind == "job_consume":
        return ann.job_mutate(idempotent=False)
    return ann.job_mutate(idempotent=True)


def base_meta(settings: Settings, *, backend: str | None = None, **fields: Any) -> Meta:
    return Meta(backend=backend, timeout_seconds=settings.timeout_seconds, **fields)
```

- [ ] **Step 4: Write `src/amicus/middleware.py`**

```python
"""FastMCP middlewares: schema dialect, semantic isError, the invalid_arguments envelope
at the call boundary, and the JSON-RPC error.data envelope for resource reads."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastmcp.exceptions import DisabledError, NotFoundError, ResourceError
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from pontonier.core import redaction
from pydantic import ValidationError

from amicus.errors import make_error, serialize_error, serialize_error_info
from amicus.schemas.envelope import ErrorResult, InvalidArgument, Meta
from amicus.schemas.fingerprint import JSON_SCHEMA_DIALECT

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings

MAX_INVALID_ARGS = 25
MAX_ARG_REASON_LEN = 300
MAX_ARG_FIELD_LEN = 128
WITHHELD_FIELD = "<withheld>"
_MISSING_TYPES = frozenset({"missing", "missing_argument"})
RESOURCE_NOT_FOUND_HANDSHAKE = -32002
RESOURCE_NOT_FOUND_MODERN = INVALID_PARAMS


def _has_control_char(text: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in text)


def _loc_is_withheld(loc: tuple[object, ...]) -> bool:
    return any(isinstance(c, str) and _has_control_char(c) for c in loc)


def format_loc(loc: tuple[object, ...]) -> str:
    """A stable accessor path for a pydantic loc; withheld when it carries a control char."""
    if _loc_is_withheld(loc):
        return WITHHELD_FIELD
    out = ""
    for component in loc:
        if isinstance(component, int):
            out += f"[{component}]"
        elif out:
            out += f".{component}"
        else:
            out = str(component)
    if len(out) > MAX_ARG_FIELD_LEN:
        out = out[:MAX_ARG_FIELD_LEN] + "…"
    return out or "<arguments>"


def _enum_for_property(prop: Any, *, element: bool = False) -> list[str] | None:
    if not isinstance(prop, dict):
        return None
    branches = [prop, *(b for b in prop.get("anyOf", []) if isinstance(b, dict))]
    for branch in branches:
        node = branch.get("items") if element else branch
        if not isinstance(node, dict):
            continue
        enum = node.get("enum")
        if isinstance(enum, list):
            return [str(v) for v in enum]
    return None


def invalid_arguments_envelope(
    tool_name: str,
    *,
    param_names: set[str],
    property_schemas: dict[str, Any],
    errors: list[Any],
    meta: Meta,
) -> dict[str, Any] | None:
    """The `invalid_arguments` envelope for a pydantic argument ValidationError, or None
    when the errors are not request-argument failures (re-raise those untouched)."""
    for err in errors:
        loc = err.get("loc") or ()
        is_extra = err.get("type") == "unexpected_keyword_argument"
        if not is_extra and not (loc and str(loc[0]) in param_names):
            return None
    total = len(errors)
    items: list[InvalidArgument] = []
    for err in errors[:MAX_INVALID_ARGS]:
        loc = tuple(err.get("loc") or ())
        indexed = len(loc) > 1 and isinstance(loc[1], int)
        allowed = (
            _enum_for_property(property_schemas.get(str(loc[0])), element=indexed) if loc else None
        )
        items.append(
            InvalidArgument(
                field=format_loc(loc),
                reason=str(err.get("msg", ""))[:MAX_ARG_REASON_LEN],
                allowed_values=allowed,
                field_withheld=_loc_is_withheld(loc),
            )
        )
    first = items[0]
    shown = f" (showing {len(items)} of {total})" if total > len(items) else ""
    safe_field = redaction.sanitize_echo(first.field)
    message = f"{tool_name}: {total} invalid argument(s){shown}: {safe_field} — {first.reason}"
    types = {err.get("type") for err in errors}
    hints: list[str] = []
    if "unexpected_keyword_argument" in types:
        hints.append("remove the unknown argument(s)")
    if types & _MISSING_TYPES:
        hints.append("provide the required argument(s)")
    if "literal_error" in types:
        hints.append("use one of the field's allowed_values")
    detail = f" — {'; '.join(hints)}" if hints else ""
    alternative = (
        f"Correct the argument(s) first{detail}. Consult each tool's inputSchema "
        "(tools/list) or call amicus_capabilities for the parameters and accepted values, "
        "then retry."
    )
    return serialize_error(
        ErrorResult(
            error=make_error(
                "invalid_arguments",
                message[:300],
                repair_tool=tool_name,
                repair_alternative=alternative,
                invalid_arguments=items,
            ),
            meta=meta,
        )
    )


class InputSchemaDialectMiddleware(Middleware):
    """Stamp the JSON Schema dialect onto every tool's input schema ([3.dialect])."""

    async def on_list_tools(self, context, call_next):  # type: ignore[no-untyped-def]
        tools = await call_next(context)
        for tool in tools:
            if tool.parameters is not None:
                tool.parameters["$schema"] = JSON_SCHEMA_DIALECT
        return tools


class SemanticErrorMiddleware(Middleware):
    """An `ok: false` envelope is an MCP `isError: true` result ([6.tool-errors])."""

    async def on_call_tool(self, context, call_next):  # type: ignore[no-untyped-def]
        result = await call_next(context)
        sc = result.structured_content
        if isinstance(sc, dict) and sc.get("ok") is False:
            result.is_error = True
        return result


class ValidationEnvelopeMiddleware(Middleware):
    """Re-emit a call-boundary argument ValidationError as the documented envelope."""

    def __init__(self, app: FastMCP, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def on_call_tool(self, context, call_next):  # type: ignore[no-untyped-def]
        try:
            return await call_next(context)
        except (ValidationError, FastMCPValidationError) as exc:
            cause = exc if isinstance(exc, ValidationError) else exc.__cause__
            if not isinstance(cause, ValidationError):
                raise
            name = context.message.name
            try:
                tool = await self._app.get_tool(name)
                params = tool.parameters if tool is not None else None
                props = params.get("properties", {}) if params else {}
            except Exception:
                raise exc from None
            envelope = invalid_arguments_envelope(
                name,
                param_names=set(props),
                property_schemas=props,
                errors=cause.errors(),
                meta=Meta(timeout_seconds=self._settings.timeout_seconds),
            )
            if envelope is None:
                raise
            return ToolResult(structured_content=envelope, is_error=True)


def resource_not_found_code(context: object) -> int:
    """-32002 on a handshake-era connection, -32602 on a modern one (SEP-2164); the
    handshake value without positive evidence of a modern connection."""
    fastmcp_context = getattr(context, "fastmcp_context", None)
    request_context = getattr(fastmcp_context, "request_context", None)
    version = getattr(request_context, "protocol_version", None)
    if version in MODERN_PROTOCOL_VERSIONS:
        return RESOURCE_NOT_FOUND_MODERN
    return RESOURCE_NOT_FOUND_HANDSHAKE


class ResourceErrorMiddleware(Middleware):
    """Carry the §6 envelope in a resource-read failure's JSON-RPC error.data, with
    code/message renamed machine_code/human_message ([6.rename])."""

    async def on_read_resource(self, context, call_next):  # type: ignore[no-untyped-def]
        message = getattr(context, "message", None)
        uri = str(getattr(message, "uri", "") or "") or None
        try:
            return await call_next(context)
        except (NotFoundError, DisabledError) as exc:
            raise self._envelope_error(
                "resource_not_found", resource_not_found_code(context), "Resource not found.", uri
            ) from exc
        except ResourceError as exc:
            raise self._envelope_error(
                "internal_error", INTERNAL_ERROR, "Resource read failed.", uri
            ) from exc

    @staticmethod
    def _envelope_error(code: str, mcp_code: int, message: str, uri: str | None) -> MCPError:
        info = make_error(code, message)
        info.resource_uri = uri
        info.request_id = uuid4().hex
        data = serialize_error_info(info)
        data["machine_code"] = data.pop("code")
        data["human_message"] = data.pop("message")
        return MCPError(code=mcp_code, message=message, data=data)
```

- [ ] **Step 5: Write `src/amicus/obs.py`**

```python
"""Diagnostic logging: stderr (plus an optional file), never stdout."""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings

ROOT_LOGGER_NAME = "amicus"
LIBRARY_LOGGER_NAME = "pontonier"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def configure(settings: Settings, *, force: bool = False) -> logging.Logger:
    """Configure the amicus and pontonier loggers once (idempotent unless ``force``)."""
    global _configured  # noqa: PLW0603
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if _configured and not force:
        return logger
    formatter = logging.Formatter(_LOG_FORMAT)
    for name in (ROOT_LOGGER_NAME, LIBRARY_LOGGER_NAME):
        target = logging.getLogger(name)
        target.setLevel(settings.log_level)
        target.propagate = False
        for handler in target.handlers[:]:
            target.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        target.addHandler(stderr_handler)
        if settings.log_file:
            try:
                file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
                file_handler.setFormatter(formatter)
                target.addHandler(file_handler)
            except OSError:
                target.warning(
                    "could not open AMICUS_LOG_FILE %r; logging to stderr only", settings.log_file
                )
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

- [ ] **Step 6: Write `src/amicus/server.py`**

```python
"""create_app(settings, registry) -> FastMCP, and the stdio console entrypoint."""

from __future__ import annotations

import contextlib
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from amicus import SERVER_NAME, __version__, config, obs, tools
from amicus.middleware import (
    InputSchemaDialectMiddleware,
    ResourceErrorMiddleware,
    SemanticErrorMiddleware,
    ValidationEnvelopeMiddleware,
)
from amicus.registry import BackendRegistry
from amicus.tools import resources

if TYPE_CHECKING:  # pragma: no cover
    import logging

    from amicus.config import Settings

UI_EXTENSION_ID = "io.modelcontextprotocol/ui"

# Rules-then-context ([2.rules-then-context]): does/does-not lead, one imperative rule
# per sentence, background last. Also served at amicus://capabilities.
CAPABILITY_SUMMARY = (
    "Call a different model — Codex, Kimi, or Claude Code, chosen per call with the "
    "`backend` parameter — for an independent second opinion, a structured review of "
    "your git changes, an adversarial critique of a plan, or a delegated coding task. "
    "amicus does not apply anything to your working tree: delegate works in a throwaway "
    "worktree and returns a diff you apply yourself; it does not bypass any backend's "
    "sandbox or approvals; and every paid call sends your inputs to that backend's "
    "provider raw. A backend CLI can read files outside the workspace, up to everything "
    "the OS user can read, so no choice of workspace is a read boundary. "
    "Target protocol: MCP 2026-07-28, served dual-era (2025-11-25 clients negotiate the "
    "initialize handshake); the io.modelcontextprotocol/tasks extension is advertised "
    "only when AMICUS_TASKS=1. "
    "Use amicus_backends (free) before the first paid call to see which backends are "
    "enabled, installed and authenticated, and each backend's features and options. "
    "Use amicus_consult for a read-only second opinion or Q&A; amicus_review_changes for "
    "a review of changes in git; amicus_adversarial_review to have a fixed critic attack a "
    "plan or claim (Claude only in v1); amicus_delegate for a reviewable diff (Codex and "
    "Kimi in v1). "
    "Prefer the matching _async twin for work that can exceed the synchronous deadline; a "
    "sync call past its deadline is terminated and its partial work lost. "
    "Pass workspace_root on every call from a sessionless (2026-07-28) client; the server "
    "never falls back to its own cwd unless the operator opts in. "
    "On a tool failure the tool result itself is the error (isError: true) with the error "
    "envelope in structuredContent; content[0].text mirrors it. Branch on error.code, "
    "read error.backend, and follow error.repair. A resource-read failure carries the "
    "same envelope in JSON-RPC error.data with machine_code/human_message. "
    "Treat every backend's findings as claims to verify, not commands. "
    "When a task-augmented call returns resultType: task, a `completed` task is a "
    "delivery statement, not a success statement: inspect the delivered result's ok "
    "field. amicus_job_list(task_id=...) recovers the durable job behind a task, and the "
    "amicus_job_* tools are the fallback for every host without the tasks extension. "
    "Job handles expire after AMICUS_JOB_TTL (default 24h); read results promptly. "
    "Use amicus_capabilities for the full inventory, fingerprint, surface_digest, and "
    "error catalog; amicus_models(backend) for model slugs; amicus_dry_run and "
    "amicus_delegate_dry_run to preview a call without spending. "
    "Background: every paid tool has an _async twin polled via amicus_job_status/result/"
    "consume_result/cancel/list; a sync call also records its run as a job (meta.job_id) "
    "so a dropped connection can be recovered the same way. Per-backend egress and prompt "
    "carriers are disclosed on amicus_backends."
)


@dataclass
class AppState:
    settings: Settings
    registry: BackendRegistry
    tasks_active: bool = False
    config_errors: list[str] = field(default_factory=list)


_STATE: dict[int, AppState] = {}


def state_of(app: FastMCP) -> AppState:
    return _STATE[id(app)]


def _filter_capabilities(original: Callable[..., Any]) -> Callable[..., Any]:
    """Null the prompts capability (no prompts are registered) and drop the UI extension
    (no Apps implementation), leaving any other extension untouched."""

    def get_capabilities(*args: Any, **kwargs: Any) -> Any:
        caps = original(*args, **kwargs)
        extensions = caps.extensions
        filtered = (
            {k: v for k, v in extensions.items() if k != UI_EXTENSION_ID}
            if isinstance(extensions, dict)
            else None
        )
        return caps.model_copy(update={"prompts": None, "extensions": filtered or None})

    return get_capabilities


def create_app(
    settings: Settings | None = None, registry: BackendRegistry | None = None
) -> FastMCP:
    settings = config.settings() if settings is None else settings
    registry = BackendRegistry.load(settings.enabled_backends) if registry is None else registry
    app = FastMCP(name=SERVER_NAME, instructions=CAPABILITY_SUMMARY, version=__version__)
    state = AppState(settings=settings, registry=registry, config_errors=list(settings.config_errors))
    _STATE[id(app)] = state
    lowlevel = app._mcp_server
    lowlevel.get_capabilities = _filter_capabilities(lowlevel.get_capabilities)  # ty: ignore[invalid-assignment]
    app.add_middleware(InputSchemaDialectMiddleware())
    app.add_middleware(SemanticErrorMiddleware())
    app.add_middleware(ValidationEnvelopeMiddleware(app, settings))
    app.add_middleware(ResourceErrorMiddleware())
    if settings.tasks_enabled:
        try:
            from fastmcp_tasks import TasksExtension

            app.add_extension(TasksExtension(url=settings.tasks_backend_url))
            state.tasks_active = True
        except ImportError as exc:
            state.config_errors.append(
                f"AMICUS_TASKS=1 but the tasks extension is not installed "
                f"(install the fastmcp[tasks] extra): {exc}"
            )
    tools.register_all(app, settings, registry)
    resources.register_resources(app, settings, registry)
    return app


def _make_signal_handler(log: logging.Logger, previous: Any) -> Callable[[int, object], None]:
    def handler(signum: int, frame: object) -> None:
        name = signal.Signals(signum).name
        log.info("amicus %s: received %s, shutting down", __version__, name)
        if callable(previous):
            previous(signum, frame)
        else:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    return handler


def _install_signal_logging(log: logging.Logger) -> None:
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError, AttributeError):
            previous = signal.getsignal(signum)
            if previous == signal.SIG_IGN:
                continue
            signal.signal(signum, _make_signal_handler(log, previous))


def _enforce_posix_platform(os_name: str | None = None) -> None:
    platform_name = os.name if os_name is None else os_name
    if platform_name == "posix":
        return
    if os.environ.get("AMICUS_ALLOW_UNSUPPORTED_PLATFORM") == "1":
        sys.stderr.write(
            "WARNING: AMICUS_ALLOW_UNSUPPORTED_PLATFORM=1 on a non-POSIX platform; the "
            "async-job safety layer cannot hold. Unsupported.\n"
        )
        return
    sys.stderr.write(
        f"amicus requires a POSIX platform (macOS or Linux); got os.name={platform_name}. "
        "Set AMICUS_ALLOW_UNSUPPORTED_PLATFORM=1 to override (unsupported).\n"
    )
    raise SystemExit(1)


def main() -> None:
    """Console-script entrypoint: run the MCP server over stdio, failing legibly."""
    _enforce_posix_platform()
    settings = config.settings()
    log = obs.configure(settings)
    _install_signal_logging(log)
    log.info("amicus %s starting (stdio)", __version__)
    app = create_app(settings)
    try:
        app.run()
    except (KeyboardInterrupt, EOFError, BrokenPipeError) as exc:
        log.info("amicus %s: clean shutdown (%s)", __version__, type(exc).__name__)
    except SystemExit:
        raise
    except Exception as exc:
        log.exception(
            "amicus %s crashed out of the stdio transport loop; reconnect with /mcp or "
            "restart the client.",
            __version__,
        )
        raise SystemExit(1) from exc
    else:
        log.info("amicus %s: stdio transport closed, shutting down", __version__)


if __name__ == "__main__":  # pragma: no cover
    main()
```

Also create `src/amicus/tools/resources.py` as a stub for this task (Task 13 fills it):

```python
"""Resource registration (filled in by Task 13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry


def register_resources(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    """No resources yet in this task."""
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py tests/test_server.py tests/test_obs.py -v --no-cov`
Expected: all PASS. Two likely adjustments:
- If the modern-era `read_resource` of an unknown URI surfaces as a different exception type than `MCPError` in fastmcp 4.0, read the raised type from the traceback and assert on `exc.value.error` accordingly; the numeric codes and `error.data` shape are the contract, the exception class is not.
- If `test_ui_filter_preserves_other_extensions` fails because the client strips `extensions` on the modern era too, assert via `c.session.discover_result.capabilities` instead.

- [ ] **Step 8: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/middleware.py src/amicus/obs.py src/amicus/server.py src/amicus/tools tests/test_middleware.py tests/test_server.py tests/test_obs.py
git commit -m "feat(server): add create_app with the four middlewares and capability suppression

The dialect stamp, semantic isError flip, call-boundary invalid_arguments
envelope and JSON-RPC error.data resource envelope (with the
machine_code/human_message rename) are ported from codex-in-claude; the
prompts capability and the UI extension are suppressed on both eras;
AMICUS_TASKS=1 registers the tasks extension when installed and records
a config error otherwise."
```

---

### Task 12: The eight paid tools, schema-only, with real pre-spend validation

**Files:**
- Create: `src/amicus/tools/_guard.py`, `src/amicus/tools/_resolve.py`, `src/amicus/tools/consult.py`, `src/amicus/tools/review.py`, `src/amicus/tools/delegate.py`
- Modify: `src/amicus/tools/__init__.py` (replace the stub)
- Test: `tests/test_paid_tools.py`

**Interfaces:**
- Consumes: `params.*` aliases, `results.*_SCHEMA`, `options.{option_violations, resolved_options}`, `errors.{error_envelope, make_error, serialize_error}`, `tools._meta.*`, `registry.BackendRegistry`, `plugin.BackendPlugin`.
- Produces (`tools`): `TOOL_ORDER` (18 names, Step 4), `ACTIVE_TOOLS`, `FREE_TOOLS`, `JOB_TOOLS`, `PAIRS`, `register_all(app, settings, registry)`.
- Produces (`_guard`): `GUARD_MARKER`, `guard(tool_name, settings)` decorator for async tools.
- Produces (`_resolve`): `PAID_MARKER`, `FREE_MARKER`, `FEATURE_FOR_VERB`, `blank_input_error(value, field, tool_name, settings, backend) -> dict | None`, `resolve_paid_call(*, registry, settings, tool_name, verb, backend, backend_options) -> tuple[BackendPlugin, dict[str, Any]] | dict[str, Any]`, `not_implemented(tool_name, settings, backend) -> dict`.
- Produces (each tool module): `register(app, settings, registry) -> tuple[str, ...]` returning the names it registered, in order.

- [ ] **Step 1: Write the failing test**

`tests/test_paid_tools.py`:

```python
"""The eight paid tools: schemas from the matrix, pre-spend validation, forced errors."""

from __future__ import annotations

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server, tools
from amicus.registry import BackendRegistry
from amicus.schemas import params
from amicus.tools import _resolve
from tests.support import fakeplugin

VALID = {
    "amicus_consult": {"backend": "codex", "question": "q"},
    "amicus_consult_async": {"backend": "codex", "question": "q"},
    "amicus_review_changes": {"backend": "codex"},
    "amicus_review_changes_async": {"backend": "codex"},
    "amicus_adversarial_review": {"backend": "claude", "target": "t"},
    "amicus_adversarial_review_async": {"backend": "claude", "target": "t"},
    "amicus_delegate": {"backend": "codex", "task": "t"},
    "amicus_delegate_async": {"backend": "codex", "task": "t"},
}


def _app(env: dict | None = None, registry: BackendRegistry | None = None):
    return server.create_app(config.settings(env or {}), registry or BackendRegistry({}, {}))


def _fake_registry() -> BackendRegistry:
    return BackendRegistry(
        {
            "codex": fakeplugin.make_plugin("codex", features=frozenset({"delegate"})),
            "claude": fakeplugin.make_plugin("claude", features=frozenset({"adversarial_review"})),
        },
        {},
    )


async def _tools(app):
    async with Client(app) as c:
        return {t.name: t for t in await c.list_tools()}


async def test_eight_paid_tools_exist_with_matrix_params_and_closed_schemas():
    by_name = await _tools(_app())
    assert set(params.TOOL_VERB) <= set(by_name)
    for name in params.TOOL_VERB:
        schema = by_name[name].input_schema
        assert set(schema["properties"]) == params.expected_params(name), name
        assert set(schema.get("required", [])) == params.expected_required(name), name
        assert schema["additionalProperties"] is False
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert by_name[name].output_schema is not None
        desc = by_name[name].description or ""
        assert desc.startswith(_resolve.PAID_MARKER), name


async def test_backend_enum_is_the_v1_set():
    by_name = await _tools(_app())
    prop = by_name["amicus_consult"].input_schema["properties"]["backend"]
    assert prop["enum"] == ["codex", "kimi", "claude"]


@pytest.mark.parametrize("name", sorted(VALID))
async def test_without_a_loaded_backend_every_paid_tool_reports_backend_unavailable(name):
    app = _app()
    async with Client(app) as c:
        res = await c.call_tool(name, VALID[name], raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == name)
    assert res.is_error
    err = res.structured_content["error"]
    assert err["code"] == "backend_unavailable"
    assert err["backend"] == VALID[name]["backend"]
    assert err["repair"]["tool"] == "amicus_backends"
    assert "import_failed" in err["message"]
    assert res.structured_content["meta"]["backend"] == VALID[name]["backend"]
    Draft202012Validator(tool.output_schema).validate(res.structured_content)


@pytest.mark.parametrize("name", sorted(VALID))
async def test_with_a_loaded_backend_every_paid_tool_is_not_implemented_yet(name):
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool(name, VALID[name], raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == name)
    err = res.structured_content["error"]
    assert err["code"] == "not_implemented", err
    assert err["temporary"] is False and err["repair"]["tool"] == "amicus_capabilities"
    Draft202012Validator(tool.output_schema).validate(res.structured_content)


async def test_feature_gating():
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool("amicus_delegate", {"backend": "claude", "task": "t"}, raise_on_error=False)
        adv = await c.call_tool("amicus_adversarial_review", {"backend": "codex", "target": "t"}, raise_on_error=False)
    assert res.structured_content["error"]["code"] == "feature_unsupported"
    assert "delegate" in res.structured_content["error"]["message"]
    assert adv.structured_content["error"]["code"] == "feature_unsupported"


async def test_backend_options_are_validated_before_availability():
    app = _app()  # no backends loaded: options still fail first, zero spend, honest order
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q", "backend_options": {"config_mode": "safe"}},
            raise_on_error=False,
        )
        bad_value = await c.call_tool(
            "amicus_review_changes",
            {"backend": "kimi", "backend_options": {"isolation": "ignore-rules"}},
            raise_on_error=False,
        )
        unknown_key = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q", "backend_options": {"sandbox": "x"}},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "backend_options.config_mode"
    assert err["repair"]["tool"] == "amicus_consult"
    err = bad_value.structured_content["error"]
    assert err["details"]["allowed_values"] == ["inherit", "ignore-skills"]
    err = unknown_key.structured_content["error"]
    assert err["code"] == "invalid_arguments" and err["details"]["field"] == "backend_options.sandbox"


async def test_blank_inputs_are_refused_pre_spend():
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        q = await c.call_tool("amicus_consult", {"backend": "codex", "question": "  "}, raise_on_error=False)
        t = await c.call_tool("amicus_delegate_async", {"backend": "codex", "task": "\n"}, raise_on_error=False)
    assert q.structured_content["error"]["details"]["field"] == "question"
    assert q.structured_content["error"]["repair"]["tool"] == "amicus_consult"
    assert t.structured_content["error"]["details"]["field"] == "task"
    assert t.structured_content["error"]["repair"]["tool"] == "amicus_delegate_async"


async def test_unknown_backend_is_a_boundary_invalid_arguments():
    async with Client(_app()) as c:
        res = await c.call_tool("amicus_consult", {"backend": "gemini", "question": "q"}, raise_on_error=False)
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments"
    assert err["details"]["field"] == "backend"
    assert err["details"]["allowed_values"] == ["codex", "kimi", "claude"]


@pytest.mark.parametrize(
    ("env", "destructive"),
    [({}, True), ({"AMICUS_BACKENDS": "codex,kimi"}, False), ({"AMICUS_BACKENDS": "claude"}, True)],
)
async def test_paid_annotations_follow_the_worst_enabled_backend(env, destructive):
    by_name = await _tools(_app(env))
    for name in params.TOOL_VERB:
        ann = by_name[name].annotations
        assert ann is not None
        assert ann.read_only_hint is False and ann.open_world_hint is True
        assert ann.destructive_hint is destructive, name
        assert ann.idempotent_hint is False


async def test_pair_parity_sync_minus_sync_only_equals_async_minus_async_only():
    by_name = await _tools(_app())
    for sync_name, async_name in tools.PAIRS:
        s = by_name[sync_name].input_schema
        a = by_name[async_name].input_schema
        s_props = {k: v for k, v in s["properties"].items() if k not in params.SYNC_ONLY_PARAMS}
        a_props = {k: v for k, v in a["properties"].items() if k not in params.ASYNC_ONLY_PARAMS}
        assert s_props == a_props, (sync_name, async_name)
        assert set(s.get("required", [])) == set(a.get("required", []))


async def test_guard_turns_an_unexpected_exception_into_internal_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(_resolve, "resolve_paid_call", boom)
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool("amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False)
    err = res.structured_content["error"]
    assert err["code"] == "internal_error" and "kaboom" not in err["message"]
    assert "RuntimeError" in err["message"]


async def test_lifecycle_meta_on_every_paid_tool():
    by_name = await _tools(_app())
    assert by_name["amicus_consult"].meta["dev.bconnelly.amicus/lifecycle"] == {"stability": "alpha"}
    assert by_name["amicus_consult_async"].meta["dev.bconnelly.amicus/lifecycle"] == {"stability": "experimental"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_paid_tools.py -v --no-cov`
Expected: FAIL (`ImportError: cannot import name '_resolve'` and no tools registered).

- [ ] **Step 3: Write `_guard.py` and `_resolve.py`**

`src/amicus/tools/_guard.py`:

```python
"""Wrap a tool so an unexpected exception becomes an internal_error envelope."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pontonier.core.redaction import exc_summary

from amicus import obs
from amicus.errors import error_envelope
from amicus.tools._meta import base_meta

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings

GUARD_MARKER = "_amicus_guarded"


def guard(
    tool_name: str, settings: Settings
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Cancellation is a BaseException and propagates; only `Exception` is enveloped."""

    def decorator(fn: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                obs.get_logger(__name__).exception("%s failed unexpectedly", tool_name)
                return error_envelope(
                    "internal_error",
                    f"{tool_name} failed: {exc_summary(exc)}",
                    base_meta(settings, backend=kwargs.get("backend")),
                )

        setattr(wrapper, GUARD_MARKER, True)
        return wrapper

    return decorator
```

`src/amicus/tools/_resolve.py`:

```python
"""Pre-spend resolution shared by every paid tool: blank input, backend_options
applicability, backend availability, feature gating. Zero spend; cheapest check first."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.errors import error_envelope
from amicus.schemas.envelope import InvalidArgument
from amicus.schemas.options import BackendOptions, option_violations, resolved_options
from amicus.tools._meta import base_meta

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings
    from amicus.plugin import BackendPlugin
    from amicus.registry import BackendRegistry

PAID_MARKER = "PAID — spends the selected backend's quota on every new call."
FREE_MARKER = "Free — no model call."
FEATURE_FOR_VERB: dict[str, str] = {"delegate": "delegate", "adversarial_review": "adversarial_review"}


def blank_input_error(
    value: str, field: str, tool_name: str, settings: Settings, backend: str
) -> dict[str, Any] | None:
    if value.strip():
        return None
    reason = f"{field} must not be empty or whitespace-only."
    return error_envelope(
        "invalid_arguments",
        f"{tool_name}: 1 invalid argument(s): {field} — {reason}",
        base_meta(settings, backend=backend),
        repair_tool=tool_name,
        repair_alternative=f"Supply a {field} with actual content, then retry.",
        invalid_arguments=[InvalidArgument(field=field, reason=reason)],
    )


def resolve_paid_call(
    *,
    registry: BackendRegistry,
    settings: Settings,
    tool_name: str,
    verb: str,
    backend: str,
    backend_options: BackendOptions | None,
) -> tuple[BackendPlugin, dict[str, Any]] | dict[str, Any]:
    """The plugin and resolved options for a paid call, or a ready error envelope."""
    meta = base_meta(settings, backend=backend)
    violations = option_violations(backend, backend_options)
    if violations:
        first = violations[0]
        return error_envelope(
            "invalid_arguments",
            f"{tool_name}: {len(violations)} invalid argument(s): {first.field} — {first.reason}",
            meta,
            repair_tool=tool_name,
            invalid_arguments=violations,
        )
    plugin = registry.get(backend)
    if plugin is None:
        why = registry.unavailable_for(backend)
        detail = f"{why.reason}: {why.detail}" if why else "not enabled in AMICUS_BACKENDS"
        return error_envelope(
            "backend_unavailable", f"backend {backend!r} is unavailable ({detail})", meta
        )
    feature = FEATURE_FOR_VERB.get(verb)
    if feature is not None and feature not in plugin.contract.supported_features:
        return error_envelope(
            "feature_unsupported",
            f"backend {backend!r} does not support {feature}",
            meta,
            plugin=plugin,
            repair_arguments={"backend": backend},
        )
    return plugin, resolved_options(backend, backend_options)


def not_implemented(tool_name: str, settings: Settings, backend: str) -> dict[str, Any]:
    return error_envelope(
        "not_implemented",
        f"{tool_name} is registered but backend {backend!r} has not landed in this release",
        base_meta(settings, backend=backend),
    )
```

- [ ] **Step 4: Write `tools/__init__.py` (replace the stub)**

```python
"""Tool registration in a FIXED order: the wire order is contract ([9.deterministic-order])."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

ACTIVE_TOOLS: tuple[str, ...] = (
    "amicus_consult",
    "amicus_consult_async",
    "amicus_review_changes",
    "amicus_review_changes_async",
    "amicus_delegate",
    "amicus_delegate_async",
    "amicus_adversarial_review",
    "amicus_adversarial_review_async",
)
FREE_TOOLS: tuple[str, ...] = (
    "amicus_dry_run",
    "amicus_delegate_dry_run",
    "amicus_backends",
    "amicus_models",
    "amicus_capabilities",
)
JOB_TOOLS: tuple[str, ...] = (
    "amicus_job_status",
    "amicus_job_result",
    "amicus_job_consume_result",
    "amicus_job_cancel",
    "amicus_job_list",
)
TOOL_ORDER: tuple[str, ...] = ACTIVE_TOOLS + FREE_TOOLS + JOB_TOOLS
PAIRS: tuple[tuple[str, str], ...] = (
    ("amicus_consult", "amicus_consult_async"),
    ("amicus_review_changes", "amicus_review_changes_async"),
    ("amicus_delegate", "amicus_delegate_async"),
    ("amicus_adversarial_review", "amicus_adversarial_review_async"),
)


def register_all(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    from amicus.tools import consult, delegate, discovery, dry_run, jobs, review

    registered: tuple[str, ...] = ()
    registered += consult.register(app, settings, registry)
    registered += review.register_review_changes(app, settings, registry)
    registered += delegate.register(app, settings, registry)
    registered += review.register_adversarial(app, settings, registry)
    registered += dry_run.register(app, settings, registry)
    registered += discovery.register(app, settings, registry)
    registered += jobs.register(app, settings, registry)
    if registered != TOOL_ORDER:
        raise RuntimeError(f"tool registration order drifted: {registered} != {TOOL_ORDER}")
```

For this task, `dry_run`, `discovery`, and `jobs` do not exist yet: create each as a one-function stub returning `()` so `register_all` runs, and temporarily make the `TOOL_ORDER` comparison tolerate the missing groups by comparing `registered == TOOL_ORDER[: len(registered)]`. Task 13 restores strict equality. (Create `src/amicus/tools/dry_run.py`, `discovery.py`, `jobs.py` each containing only `def register(app, settings, registry): return ()` with the same TYPE_CHECKING imports as `resources.py`.)

- [ ] **Step 5: Write the three paid-tool modules**

`src/amicus/tools/consult.py`:

```python
"""amicus_consult and amicus_consult_async."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    DetailParam,
    ExtraContextParam,
    IdempotencyKeyParam,
    InstructionsAppendParam,
    ModelParam,
    QuestionParam,
    ReasoningEffortParam,
    TimeoutSecondsParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import CONSULT_RESULT_SCHEMA, JOB_STARTED_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._resolve import PAID_MARKER, blank_input_error, not_implemented, resolve_paid_call

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_EGRESS = (
    "Egress: sends question, extra_context and instructions_append raw to the backend's "
    "provider; the backend can read files outside the workspace."
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    @app.tool(
        name="amicus_consult",
        annotations=annotations_for("active", settings),
        output_schema=CONSULT_RESULT_SCHEMA,
        title="Consult a backend model (paid)",
        meta=lifecycle_meta("amicus_consult"),
        task=settings.tasks_enabled,
    )
    @guard("amicus_consult", settings)
    async def amicus_consult(
        backend: BackendParam,
        question: QuestionParam,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        f"""{PAID_MARKER} Read-only second opinion or Q&A from `backend` on a question, design,
        or a diff you paste inline; use amicus_review_changes when the diff is in git.
        {_EGRESS} Recorded as a job (meta.job_id). Prefer amicus_consult_async for a
        high-effort or broad repo-grounded consult that can exceed the deadline."""
        return await _run("amicus_consult", backend, question, backend_options)

    @app.tool(
        name="amicus_consult_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background consult (paid)",
        meta=lifecycle_meta("amicus_consult_async"),
    )
    @guard("amicus_consult_async", settings)
    async def amicus_consult_async(
        backend: BackendParam,
        question: QuestionParam,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        f"""{PAID_MARKER} Async twin of amicus_consult: returns a job handle immediately;
        poll amicus_job_status, read amicus_job_result. {_EGRESS} Starting a job commits
        to spend."""
        return await _run("amicus_consult_async", backend, question, backend_options)

    async def _run(tool_name: str, backend: str, question: str, options: Any) -> dict[str, Any]:
        err = blank_input_error(question, "question", tool_name, settings, backend)
        if err is not None:
            return err
        resolved = resolve_paid_call(
            registry=registry, settings=settings, tool_name=tool_name, verb="consult",
            backend=backend, backend_options=options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented(tool_name, settings, backend)

    return ("amicus_consult", "amicus_consult_async")
```

An f-string docstring is NOT a docstring (Python only treats a literal as `__doc__`). Write each description as a module-level constant and pass it via `description=` in `@app.tool(...)`, i.e. `description=f"{PAID_MARKER} Read-only second opinion ... {_EGRESS} ..."`, and give the function a one-line plain docstring. Apply this rule to every tool in this task and Task 13; the code blocks show the text, the `description=` argument is where it goes.

`src/amicus/tools/review.py`:

```python
"""amicus_review_changes(_async) and amicus_adversarial_review(_async)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    BaseParam,
    CommitParam,
    DetailParam,
    EvidenceParam,
    ExtraContextParam,
    FocusParam,
    IdempotencyKeyParam,
    InstructionsAppendParam,
    ModelParam,
    OptionalScopeParam,
    PathsParam,
    ReasoningEffortParam,
    ScopeParam,
    TargetParam,
    TimeoutSecondsParam,
    UntrackedParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import ADVERSARIAL_RESULT_SCHEMA, JOB_STARTED_SCHEMA, REVIEW_RESULT_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._resolve import PAID_MARKER, blank_input_error, not_implemented, resolve_paid_call

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_REVIEW_DESC = (
    f"{PAID_MARKER} Structured review by `backend` of changes gathered from git — "
    "working_tree, branch, or commit — with verdict, confidence and findings. Egress: "
    "sends the bounded, secret-redacted diff plus raw extra_context and "
    "instructions_append to the backend's provider. An empty scope returns "
    "review_status=not_run with no spend. Recorded as a job (meta.job_id)."
)
_REVIEW_ASYNC_DESC = (
    f"{PAID_MARKER} Async twin of amicus_review_changes: returns a job handle; poll "
    "amicus_job_status, read amicus_job_result. Same egress. Starting a job commits to spend."
)
_ADV_DESC = (
    f"{PAID_MARKER} A fixed adversarial critic on `backend` attacks `target` (a plan, claim "
    "or decision) using `evidence` and an optionally attached git diff; the critic stance is "
    "the product, so there is no instructions_append. Claude only in v1 (feature "
    "adversarial_review). Egress: sends target, evidence, extra_context and the redacted "
    "diff raw to the backend's provider."
)
_ADV_ASYNC_DESC = (
    f"{PAID_MARKER} Async twin of amicus_adversarial_review: returns a job handle; poll "
    "amicus_job_status, read amicus_job_result. Same egress and feature gate."
)


def register_review_changes(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    async def _run(tool_name: str, backend: str, options: Any) -> dict[str, Any]:
        resolved = resolve_paid_call(
            registry=registry, settings=settings, tool_name=tool_name, verb="review_changes",
            backend=backend, backend_options=options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented(tool_name, settings, backend)

    @app.tool(
        name="amicus_review_changes",
        annotations=annotations_for("active", settings),
        output_schema=REVIEW_RESULT_SCHEMA,
        title="Review git changes (paid)",
        meta=lifecycle_meta("amicus_review_changes"),
        description=_REVIEW_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_review_changes", settings)
    async def amicus_review_changes(
        backend: BackendParam,
        scope: ScopeParam = "working_tree",
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Review changes from git with the selected backend."""
        return await _run("amicus_review_changes", backend, backend_options)

    @app.tool(
        name="amicus_review_changes_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background review (paid)",
        meta=lifecycle_meta("amicus_review_changes_async"),
        description=_REVIEW_ASYNC_DESC,
    )
    @guard("amicus_review_changes_async", settings)
    async def amicus_review_changes_async(
        backend: BackendParam,
        scope: ScopeParam = "working_tree",
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background review with the selected backend."""
        return await _run("amicus_review_changes_async", backend, backend_options)

    return ("amicus_review_changes", "amicus_review_changes_async")


def register_adversarial(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    async def _run(tool_name: str, backend: str, target: str, options: Any) -> dict[str, Any]:
        err = blank_input_error(target, "target", tool_name, settings, backend)
        if err is not None:
            return err
        resolved = resolve_paid_call(
            registry=registry, settings=settings, tool_name=tool_name, verb="adversarial_review",
            backend=backend, backend_options=options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented(tool_name, settings, backend)

    @app.tool(
        name="amicus_adversarial_review",
        annotations=annotations_for("active", settings),
        output_schema=ADVERSARIAL_RESULT_SCHEMA,
        title="Adversarial critique of a plan or claim (paid)",
        meta=lifecycle_meta("amicus_adversarial_review"),
        description=_ADV_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_adversarial_review", settings)
    async def amicus_adversarial_review(
        backend: BackendParam,
        target: TargetParam,
        evidence: EvidenceParam = None,
        scope: OptionalScopeParam = None,
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Attack a target with a fixed adversarial critic on the selected backend."""
        return await _run("amicus_adversarial_review", backend, target, backend_options)

    @app.tool(
        name="amicus_adversarial_review_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background adversarial critique (paid)",
        meta=lifecycle_meta("amicus_adversarial_review_async"),
        description=_ADV_ASYNC_DESC,
    )
    @guard("amicus_adversarial_review_async", settings)
    async def amicus_adversarial_review_async(
        backend: BackendParam,
        target: TargetParam,
        evidence: EvidenceParam = None,
        scope: OptionalScopeParam = None,
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        focus: FocusParam = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background adversarial critique on the selected backend."""
        return await _run("amicus_adversarial_review_async", backend, target, backend_options)

    return ("amicus_adversarial_review", "amicus_adversarial_review_async")
```

`src/amicus/tools/delegate.py`:

```python
"""amicus_delegate and amicus_delegate_async."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    DetailParam,
    IdempotencyKeyParam,
    ModelParam,
    ReasoningEffortParam,
    TaskParam,
    TimeoutSecondsParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import DELEGATE_RESULT_SCHEMA, JOB_STARTED_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._resolve import PAID_MARKER, blank_input_error, not_implemented, resolve_paid_call

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_DESC = (
    f"{PAID_MARKER} `backend` implements `task` in a throwaway git worktree seeded from "
    "tracked state and returns the diff — never applied to your working tree. Codex and "
    "Kimi in v1 (feature delegate); Claude stays review-only. Egress: sends task raw to the "
    "backend's provider; a backend sandbox may also write the OS temp roots, which are "
    "neither in the diff nor cleaned up. Recorded as a job (meta.job_id)."
)
_ASYNC_DESC = (
    f"{PAID_MARKER} Async twin of amicus_delegate: returns a job handle; poll "
    "amicus_job_status, read amicus_job_result. Same egress and feature gate. Starting a "
    "job commits to spend."
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    async def _run(tool_name: str, backend: str, task: str, options: Any) -> dict[str, Any]:
        err = blank_input_error(task, "task", tool_name, settings, backend)
        if err is not None:
            return err
        resolved = resolve_paid_call(
            registry=registry, settings=settings, tool_name=tool_name, verb="delegate",
            backend=backend, backend_options=options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented(tool_name, settings, backend)

    @app.tool(
        name="amicus_delegate",
        annotations=annotations_for("active", settings),
        output_schema=DELEGATE_RESULT_SCHEMA,
        title="Delegate a coding task for a reviewable diff (paid)",
        meta=lifecycle_meta("amicus_delegate"),
        description=_DESC,
        task=settings.tasks_enabled,
    )
    @guard("amicus_delegate", settings)
    async def amicus_delegate(
        backend: BackendParam,
        task: TaskParam,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        timeout_seconds: TimeoutSecondsParam = None,
        detail: DetailParam = "summary",
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Delegate a task to the selected backend in a throwaway worktree."""
        return await _run("amicus_delegate", backend, task, backend_options)

    @app.tool(
        name="amicus_delegate_async",
        annotations=annotations_for("active", settings),
        output_schema=JOB_STARTED_SCHEMA,
        title="Start a background delegate (paid)",
        meta=lifecycle_meta("amicus_delegate_async"),
        description=_ASYNC_DESC,
    )
    @guard("amicus_delegate_async", settings)
    async def amicus_delegate_async(
        backend: BackendParam,
        task: TaskParam,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background delegate on the selected backend."""
        return await _run("amicus_delegate_async", backend, task, backend_options)

    return ("amicus_delegate", "amicus_delegate_async")
```

Rewrite `consult.py`'s two tools in this same `description=` style (constants `_DESC`/`_ASYNC_DESC`, one-line docstrings) before running the tests.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_paid_tools.py tests/test_server.py -v --no-cov`
Expected: all PASS. Likely adjustments: if FastMCP rejects `task=False` on a tool without the extension registered, pass `task=True if settings.tasks_enabled else None`; if the `annotations` object on the client is a dict rather than a model, index it (`ann["destructiveHint"]`).

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/tools tests/test_paid_tools.py
git commit -m "feat(tools): register the eight paid tools schema-only with pre-spend checks

Each paid tool is built from the parameter matrix aliases and its
published output schema, validates blank input, backend_options
applicability, backend availability and feature support before any
spend, and returns not_implemented until its backend lands. Annotations
follow the worst enabled backend (ADR 0001)."
```

---

### Task 13: Dry runs, job tools, discovery tools, resources, completion

**Files:**
- Create: `src/amicus/surface.py`, `src/amicus/tools/dry_run.py`, `src/amicus/tools/jobs.py`, `src/amicus/tools/discovery.py`
- Modify: `src/amicus/tools/resources.py` (replace the stub), `src/amicus/tools/__init__.py` (restore strict `TOOL_ORDER` equality)
- Test: `tests/test_discovery.py`, `tests/test_resources.py`, `tests/test_surface.py`

**Interfaces:**
- Produces (`surface`): `async surface_records(app) -> dict`, `async surface_digest(app) -> str` (sha256 hex over the server-side tool, resource and template records plus the instructions, via `pontonier.conventions.fingerprint.canonical_digest`).
- Produces (`discovery`): `register(app, settings, registry) -> tuple[str, ...]`, `backends_payload(settings, registry, config_errors, backend=None) -> dict`, `models_payload(registry, backend) -> dict`, `async capabilities_payload(app, settings, registry, config_errors, tasks_active, detail="summary", include_schemas=None) -> dict`, `TOOL_DETAILS: dict[str, dict]`.
- Produces (`resources`): `register_resources(app, settings, registry)`, `STATIC_RESOURCE_URIS`, `TEMPLATE_URIS`, `complete_backend(ref, argument, context) -> list[str] | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_surface.py`:

```python
"""surface_digest: a sha256 over the server-side records, stable and profile-sensitive."""

from __future__ import annotations

from amicus import config, server, surface
from amicus.registry import BackendRegistry


async def test_digest_is_hex_deterministic_and_profile_sensitive():
    a = server.create_app(config.settings({}), BackendRegistry({}, {}))
    b = server.create_app(config.settings({}), BackendRegistry({}, {}))
    c = server.create_app(config.settings({"AMICUS_BACKENDS": "codex"}), BackendRegistry({}, {}))
    da, db, dc = await surface.surface_digest(a), await surface.surface_digest(b), await surface.surface_digest(c)
    assert len(da) == 64 and da == db and da != dc
    records = await surface.surface_records(a)
    assert [t["name"] for t in records["tools"]] == sorted(t["name"] for t in records["tools"])
    assert records["instructions"] == server.CAPABILITY_SUMMARY
    assert {r["uri"] for r in records["resources"]} >= {"amicus://capabilities"}
    assert {t["uriTemplate"] for t in records["resource_templates"]} == {
        "amicus://backends/{backend}", "amicus://models/{backend}"
    }
```

`tests/test_discovery.py`:

```python
"""The 18-tool surface, the free discovery tools, and job tools (schema-only)."""

from __future__ import annotations

import json
from typing import get_args

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server, tools
from amicus.registry import BackendRegistry, UnavailableBackend
from amicus.schemas import field_policy
from amicus.schemas.codes import ERROR_CODES
from amicus.schemas.envelope import Meta
from amicus.schemas.results import CapabilitiesDetail
from amicus.tools import _resolve
from tests.support import fakeplugin


def _app(env=None, registry=None):
    return server.create_app(config.settings(env or {}), registry or BackendRegistry({}, {}))


def _mixed_registry():
    return BackendRegistry(
        {"codex": fakeplugin.make_plugin("codex", egress="sends to OpenAI", carriers="argv")},
        {"kimi": UnavailableBackend("kimi", "import_failed", "no module amicus.backends.kimi")},
    )


async def _tools(app):
    async with Client(app) as c:
        return await c.list_tools()


async def test_exactly_eighteen_tools_in_the_fixed_order():
    listed = [t.name for t in await _tools(_app())]
    assert len(listed) == 18
    assert listed == list(tools.TOOL_ORDER)


async def test_free_and_job_tool_markers_and_annotations():
    by_name = {t.name: t for t in await _tools(_app())}
    for name in tools.FREE_TOOLS:
        assert (by_name[name].description or "").startswith(_resolve.FREE_MARKER), name
        ann = by_name[name].annotations
        assert ann.read_only_hint is True and ann.open_world_hint is False
        assert ann.destructive_hint is None and ann.idempotent_hint is None
    for name in ("amicus_job_status", "amicus_job_result", "amicus_job_list"):
        assert by_name[name].annotations.read_only_hint is True
    consume = by_name["amicus_job_consume_result"].annotations
    cancel = by_name["amicus_job_cancel"].annotations
    assert consume.read_only_hint is False and consume.idempotent_hint is False
    assert cancel.read_only_hint is False and cancel.idempotent_hint is True
    for name in tools.JOB_TOOLS:
        assert by_name[name].meta["dev.bconnelly.amicus/lifecycle"]["stability"] == "experimental"


async def test_advertised_control_char_patterns_are_complete():
    app = _app()
    patterns = await field_policy.advertised_patterns(app)
    for name in field_policy.REJECT_PARAMS:
        assert patterns.get(name) == field_policy.CONTROL_CHAR_FREE_PATTERN, name


async def test_every_tool_output_schema_is_valid_and_every_error_envelope_validates():
    app = _app()
    async with Client(app) as c:
        listed = await c.list_tools()
        args = {
            "amicus_dry_run": {"backend": "codex"},
            "amicus_delegate_dry_run": {"backend": "codex", "task": "t"},
            "amicus_models": {"backend": "codex"},
            "amicus_job_status": {"job_id": "a" * 32},
            "amicus_job_result": {"job_id": "a" * 32},
            "amicus_job_consume_result": {"job_id": "a" * 32},
            "amicus_job_cancel": {"job_id": "a" * 32},
            "amicus_job_list": {},
        }
        for tool in listed:
            Draft202012Validator.check_schema(tool.output_schema)
            if tool.name in args:
                res = await c.call_tool(tool.name, args[tool.name], raise_on_error=False)
                Draft202012Validator(tool.output_schema).validate(res.structured_content)
                if tool.name != "amicus_models":
                    assert res.structured_content["error"]["code"] in {"not_implemented", "backend_unavailable"}


async def test_dry_runs_validate_options_then_report_backend_state():
    async with Client(_app(registry=_mixed_registry())) as c:
        bad = await c.call_tool("amicus_dry_run", {"backend": "codex", "backend_options": {"access": "readonly"}}, raise_on_error=False)
        ok = await c.call_tool("amicus_dry_run", {"backend": "codex"}, raise_on_error=False)
        kimi = await c.call_tool("amicus_delegate_dry_run", {"backend": "kimi", "task": "t"}, raise_on_error=False)
    assert bad.structured_content["error"]["details"]["field"] == "backend_options.access"
    assert ok.structured_content["error"]["code"] == "not_implemented"
    assert kimi.structured_content["error"]["code"] == "backend_unavailable"


async def test_backends_catalog_reports_enabled_available_and_unavailable():
    app = _app(env={"AMICUS_BACKENDS": "codex,kimi", "MOONBRIDGE_TIMEOUT_SECONDS": "60"}, registry=_mixed_registry())
    async with Client(app) as c:
        res = await c.call_tool("amicus_backends", {})
        tool = next(t for t in await c.list_tools() if t.name == "amicus_backends")
        only = await c.call_tool("amicus_backends", {"backend": "kimi"})
    payload = res.structured_content
    Draft202012Validator(tool.output_schema).validate(payload)
    by_id = {b["id"]: b for b in payload["backends"]}
    assert set(by_id) == {"codex", "kimi", "claude"}
    assert by_id["codex"]["enabled"] and by_id["codex"]["available"]
    assert by_id["codex"]["status"] == {"installed": True, "version": "fake 1.0", "authenticated": True, "warnings": []}
    assert by_id["codex"]["features"] == ["delegate"]
    assert by_id["codex"]["egress"] == "sends to OpenAI" and by_id["codex"]["carriers"] == "argv"
    assert {o["name"] for o in by_id["codex"]["options"]} == {"isolation"}
    assert by_id["codex"]["options"][0]["allowed_values"] == ["inherit", "ignore-config", "ignore-rules"]
    assert by_id["codex"]["effects"] == {"paid_calls_destructive": False, "job_reads_read_only": True}
    assert by_id["kimi"]["enabled"] and not by_id["kimi"]["available"]
    assert not by_id["claude"]["enabled"]
    assert by_id["claude"]["effects"]["paid_calls_destructive"] is True
    assert payload["unavailable"] == [{"id": "kimi", "reason": "import_failed", "detail": "no module amicus.backends.kimi"}]
    assert any("MOONBRIDGE_TIMEOUT_SECONDS" in w for w in payload["env_warnings"])
    assert [b["id"] for b in only.structured_content["backends"]] == ["kimi"]


async def test_backends_status_probe_failure_is_a_warning_not_a_crash():
    class Boom:
        def probe(self):
            raise RuntimeError("probe died")

    reg = BackendRegistry({"codex": fakeplugin.make_plugin("codex", status=Boom())}, {})
    async with Client(_app(registry=reg)) as c:
        res = await c.call_tool("amicus_backends", {"backend": "codex"})
    [entry] = res.structured_content["backends"]
    assert entry["status"]["installed"] is False
    assert any("RuntimeError" in w for w in entry["status"]["warnings"])


async def test_models_for_available_and_unavailable_backends():
    async with Client(_app(registry=_mixed_registry())) as c:
        codex = await c.call_tool("amicus_models", {"backend": "codex"})
        kimi = await c.call_tool("amicus_models", {"backend": "kimi"})
        tool = next(t for t in await c.list_tools() if t.name == "amicus_models")
    Draft202012Validator(tool.output_schema).validate(codex.structured_content)
    assert codex.structured_content["models"] == [{"slug": "fake-1", "display_name": None, "default_reasoning_effort": None, "supported_reasoning_efforts": None}]
    assert codex.structured_content["source"] == "static"
    assert kimi.structured_content["available"] is False and kimi.structured_content["models"] == []


async def test_capabilities_summary_full_contracts_and_include_schemas():
    app = _app()
    async with Client(app) as c:
        tool = next(t for t in await c.list_tools() if t.name == "amicus_capabilities")
        summary = (await c.call_tool("amicus_capabilities", {})).structured_content
        full = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
        contracts = (await c.call_tool("amicus_capabilities", {"detail": "contracts"})).structured_content
        with_schemas = (await c.call_tool("amicus_capabilities", {"include_schemas": ["error-envelope", "parameter-contracts"]})).structured_content
    Draft202012Validator(tool.output_schema).validate(summary)
    assert set(summary["active_tools"]) == set(tools.ACTIVE_TOOLS)
    assert set(summary["free_tools"]) == set(tools.FREE_TOOLS)
    assert set(summary["job_tools"]) == set(tools.JOB_TOOLS)
    assert set(summary["error_codes"]) == set(ERROR_CODES)
    assert summary["meta_fields"] == list(Meta.model_fields)
    assert len(summary["surface_digest"]) == 64
    assert summary["tasks"]["enabled"] is False and summary["tasks"]["task_tools"] == []
    assert summary["enabled_backends"] == ["codex", "kimi", "claude"]
    assert {d["name"] for d in summary["tool_details"]} == set(tools.TOOL_ORDER)
    entry = next(d for d in summary["tool_details"] if d["name"] == "amicus_consult")
    assert set(entry) == {"name", "cost", "stability", "backends", "error_codes"}
    assert entry["stability"] is None
    entry_full = next(d for d in full["tool_details"] if d["name"] == "amicus_consult")
    assert entry_full["required_params"] == ["backend", "question"]
    assert "use_when" in entry_full and entry_full["returns"]
    assert contracts["tool_details"] == []
    assert set(with_schemas["schemas"]) == {"error-envelope", "parameter-contracts"}
    assert with_schemas["schemas"]["error-envelope"]["$schema"]
    assert "surface_digest" in summary and summary["fingerprint"] == "amicus/0.1/schema-1"
    assert "delivery statement" in summary["tasks"]["fallback"]
    assert set(get_args(CapabilitiesDetail)) == {"summary", "full", "contracts"}


async def test_capabilities_reports_unknown_include_schemas_as_invalid_arguments():
    async with Client(_app()) as c:
        res = await c.call_tool("amicus_capabilities", {"include_schemas": ["nope"]}, raise_on_error=False)
    err = res.structured_content["error"]
    assert err["code"] == "invalid_arguments" and err["details"]["field"] == "include_schemas[0]"
    assert err["details"]["allowed_values"] == ["error-envelope", "result-meta", "capabilities-result", "parameter-contracts"]


async def test_job_list_filters_are_advertised():
    by_name = {t.name: t for t in await _tools(_app())}
    props = by_name["amicus_job_list"].input_schema["properties"]
    assert set(props) == {"workspace_root", "limit", "status", "backend", "task_id"}
    assert set(by_name["amicus_job_result"].input_schema["properties"]) == {"job_id", "workspace_root", "detail"}
    assert set(by_name["amicus_job_cancel"].input_schema["properties"]) == {"job_id", "workspace_root"}


@pytest.mark.parametrize("name", ["amicus_backends", "amicus_capabilities"])
async def test_free_tool_payloads_are_json_serializable(name):
    async with Client(_app()) as c:
        res = await c.call_tool(name, {})
    json.dumps(res.structured_content)
```

`tests/test_resources.py`:

```python
"""Six resources: four static bodies, two templates with completion."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp import MCPError
from mcp_types import ResourceTemplateReference

from amicus import config, server
from amicus.registry import BackendRegistry
from amicus.tools import resources
from tests.support import fakeplugin


def _app(registry=None):
    return server.create_app(config.settings({}), registry or BackendRegistry({}, {}))


async def test_static_resources_list_and_read_as_json_with_triage_and_lifecycle_meta():
    async with Client(_app()) as c:
        listed = {str(r.uri): r for r in await c.list_resources()}
        assert set(listed) == set(resources.STATIC_RESOURCE_URIS) == {
            "amicus://capabilities", "amicus://error-envelope", "amicus://result-meta", "amicus://params",
        }
        for uri, rec in listed.items():
            meta = rec.meta or {}
            assert "dev.bconnelly.amicus/lifecycle" in meta, uri
            assert meta["dev.bconnelly.amicus/triage"]["size_bytes"] > 0 or meta["dev.bconnelly.amicus/triage"].get("volatile")
            [block] = await c.read_resource(uri)
            body = json.loads(block.text)
            assert isinstance(body, dict)
        assert listed["amicus://error-envelope"].mime_type == "application/schema+json"
        assert listed["amicus://params"].mime_type == "application/json"


async def test_templates_are_listed_and_readable():
    reg = BackendRegistry({"codex": fakeplugin.make_plugin("codex")}, {})
    async with Client(_app(reg)) as c:
        templates = {t.uri_template for t in await c.list_resource_templates()}
        assert templates == set(resources.TEMPLATE_URIS)
        [entry] = await c.read_resource("amicus://backends/codex")
        assert json.loads(entry.text)["available"] is True
        [models] = await c.read_resource("amicus://models/codex")
        assert json.loads(models.text)["models"][0]["slug"] == "fake-1"
        [kimi] = await c.read_resource("amicus://backends/kimi")
        assert json.loads(kimi.text)["available"] is False
        with pytest.raises(MCPError) as exc:
            await c.read_resource("amicus://backends/gemini")
        assert exc.value.error.data["machine_code"] == "resource_not_found"


async def test_completion_for_the_backend_template_variable():
    async with Client(_app()) as c:
        ref = ResourceTemplateReference(uri="amicus://backends/{backend}")
        assert (await c.complete(ref, {"name": "backend", "value": "c"})).values == ["codex", "claude"]
        ref = ResourceTemplateReference(uri="amicus://models/{backend}")
        assert (await c.complete(ref, {"name": "backend", "value": ""})).values == ["codex", "kimi", "claude"]
        assert (await c.complete(ref, {"name": "other", "value": ""})).values == []
    assert resources.complete_backend(object(), None, None) is None


async def test_capabilities_resource_matches_the_tool():
    async with Client(_app()) as c:
        via_tool = (await c.call_tool("amicus_capabilities", {})).structured_content
        [block] = await c.read_resource("amicus://capabilities")
    via_resource = json.loads(block.text)
    assert via_resource["surface_digest"] == via_tool["surface_digest"]
    assert via_resource["error_codes"] == via_tool["error_codes"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_surface.py tests/test_discovery.py tests/test_resources.py -v --no-cov`
Expected: FAIL (`ImportError: cannot import name 'surface'`; tool count is 8).

- [ ] **Step 3: Write `src/amicus/surface.py`**

```python
"""The server-side surface records and their digest (ADR 0006)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from pontonier.conventions.fingerprint import canonical_digest

_FASTMCP_META_KEY = "fastmcp"


def _clean(record: dict[str, Any]) -> dict[str, Any]:
    meta = record.get("_meta")
    if isinstance(meta, dict):
        meta = {k: v for k, v in meta.items() if k != _FASTMCP_META_KEY}
        if meta:
            record["_meta"] = meta
        else:
            record.pop("_meta", None)
    return record


def _dump(model: Any) -> dict[str, Any]:
    return _clean(model.model_dump(mode="json", by_alias=True, exclude_none=True))


async def surface_records(app: FastMCP) -> dict[str, Any]:
    """Tool, resource and template records as the server holds them (middleware not run),
    sorted by identity, plus the instructions text."""
    tools = [_dump(t.to_mcp_tool()) for t in await app.list_tools(run_middleware=False)]
    resources = [_dump(r.to_mcp_resource()) for r in await app.list_resources(run_middleware=False)]
    templates = [
        _dump(t.to_mcp_template()) for t in await app.list_resource_templates(run_middleware=False)
    ]
    return {
        "tools": sorted(tools, key=lambda t: t["name"]),
        "resources": sorted(resources, key=lambda r: r["uri"]),
        "resource_templates": sorted(templates, key=lambda t: t["uriTemplate"]),
        "instructions": app.instructions,
    }


async def surface_digest(app: FastMCP) -> str:
    return canonical_digest(await surface_records(app))
```

- [ ] **Step 4: Write `src/amicus/tools/dry_run.py` and `src/amicus/tools/jobs.py`**

`src/amicus/tools/dry_run.py`:

```python
"""amicus_dry_run and amicus_delegate_dry_run (free previews; bodies land in M1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.schemas.params import (
    BackendOptionsParam,
    BackendParam,
    BaseParam,
    CommitParam,
    ExtraContextParam,
    InstructionsAppendParam,
    ModelParam,
    PathsParam,
    ReasoningEffortParam,
    ScopeParam,
    TaskParam,
    UntrackedParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import DELEGATE_DRY_RUN_SCHEMA, DRY_RUN_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
from amicus.tools._resolve import FREE_MARKER, blank_input_error, not_implemented, resolve_paid_call

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_PREVIEW_FACT = (
    "A dry run reports metadata about the input amicus would assemble; it does not invoke "
    "the backend, and it neither enumerates nor bounds the files the model itself reads "
    "during the paid call."
)
_DRY_RUN_DESC = (
    f"{FREE_MARKER} Preview an amicus_review_changes call: the diff scope, its byte size and "
    "summary, the resolved model, effort and backend_options, and whether the paid call "
    f"would run the model at all. {_PREVIEW_FACT}"
)
_DELEGATE_DRY_RUN_DESC = (
    f"{FREE_MARKER} Preview an amicus_delegate call: the worktree baseline and prefix, task "
    f"bytes, and the resolved model, effort and backend_options. {_PREVIEW_FACT}"
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    @app.tool(
        name="amicus_dry_run",
        annotations=annotations_for("free", settings),
        output_schema=DRY_RUN_SCHEMA,
        title="Preview a review (free)",
        meta=lifecycle_meta("amicus_dry_run"),
        description=_DRY_RUN_DESC,
    )
    @guard("amicus_dry_run", settings)
    async def amicus_dry_run(
        backend: BackendParam,
        scope: ScopeParam = "working_tree",
        base: BaseParam = None,
        commit: CommitParam = None,
        paths: PathsParam = None,
        untracked: UntrackedParam = "explicit_only",
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Preview a review call without spending."""
        resolved = resolve_paid_call(
            registry=registry, settings=settings, tool_name="amicus_dry_run",
            verb="review_changes", backend=backend, backend_options=backend_options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented("amicus_dry_run", settings, backend)

    @app.tool(
        name="amicus_delegate_dry_run",
        annotations=annotations_for("free", settings),
        output_schema=DELEGATE_DRY_RUN_SCHEMA,
        title="Preview a delegate (free)",
        meta=lifecycle_meta("amicus_delegate_dry_run"),
        description=_DELEGATE_DRY_RUN_DESC,
    )
    @guard("amicus_delegate_dry_run", settings)
    async def amicus_delegate_dry_run(
        backend: BackendParam,
        task: TaskParam,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Preview a delegate call without spending."""
        err = blank_input_error(task, "task", "amicus_delegate_dry_run", settings, backend)
        if err is not None:
            return err
        resolved = resolve_paid_call(
            registry=registry, settings=settings, tool_name="amicus_delegate_dry_run",
            verb="delegate", backend=backend, backend_options=backend_options,
        )
        if isinstance(resolved, dict):
            return resolved
        return not_implemented("amicus_delegate_dry_run", settings, backend)

    return ("amicus_dry_run", "amicus_delegate_dry_run")
```

`src/amicus/tools/jobs.py`:

```python
"""The five amicus_job_* tools (schema-only until M2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.errors import error_envelope
from amicus.schemas.params import (
    DetailParam,
    JobIdParam,
    JobLimitParam,
    JobStatusFilterParam,
    OptionalBackendParam,
    TaskIdParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import JOB_LIST_SCHEMA, JOB_RESULT_SCHEMA, JOB_STATUS_SCHEMA
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, base_meta, lifecycle_meta
from amicus.tools._resolve import FREE_MARKER

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

_RETENTION = (
    "Records expire after AMICUS_JOB_TTL (default 24h) and a per-workspace cap evicts the "
    "oldest terminal records; read results promptly."
)


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    def pending(tool_name: str) -> dict[str, Any]:
        return error_envelope(
            "not_implemented", f"{tool_name} lands with the jobs surface (M2)", base_meta(settings)
        )

    @app.tool(
        name="amicus_job_status",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Poll a background job (free)",
        meta=lifecycle_meta("amicus_job_status"),
        description=(
            f"{FREE_MARKER} Poll a job's state without fetching its result: status, elapsed "
            "time, result_available, result_ok, and poll_after_ms to honor before the next "
            f"poll. {_RETENTION}"
        ),
    )
    @guard("amicus_job_status", settings)
    async def amicus_job_status(job_id: JobIdParam, workspace_root: WorkspaceRootParam = None) -> dict[str, Any]:
        """Poll a background job."""
        return pending("amicus_job_status")

    @app.tool(
        name="amicus_job_result",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch a background job's result (free)",
        meta=lifecycle_meta("amicus_job_result"),
        description=(
            f"{FREE_MARKER} Return the originating paid tool's envelope once result_available; "
            "branch on `tool`. The record is retained, so a re-read is free. A still-running "
            f"job is job_running with retry_after_ms. {_RETENTION}"
        ),
    )
    @guard("amicus_job_result", settings)
    async def amicus_job_result(job_id: JobIdParam, workspace_root: WorkspaceRootParam = None, detail: DetailParam = "summary") -> dict[str, Any]:
        """Fetch a background job's result."""
        return pending("amicus_job_result")

    @app.tool(
        name="amicus_job_consume_result",
        annotations=annotations_for("job_consume", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch and delete a background job's result (free)",
        meta=lifecycle_meta("amicus_job_consume_result"),
        description=(
            f"{FREE_MARKER} Like amicus_job_result, then delete the record: a repeat call "
            "returns job_not_found, so this is not idempotent."
        ),
    )
    @guard("amicus_job_consume_result", settings)
    async def amicus_job_consume_result(job_id: JobIdParam, workspace_root: WorkspaceRootParam = None, detail: DetailParam = "summary") -> dict[str, Any]:
        """Fetch and delete a background job's result."""
        return pending("amicus_job_consume_result")

    @app.tool(
        name="amicus_job_cancel",
        annotations=annotations_for("job_cancel", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Cancel a background job (free)",
        meta=lifecycle_meta("amicus_job_cancel"),
        description=(
            f"{FREE_MARKER} Ask the worker to stop and mark the job cancelled; a terminal job "
            "is returned unchanged, so cancel is idempotent. An unkeyed task-augmented call "
            "cancels its job; a keyed job survives and the result names its job_id."
        ),
    )
    @guard("amicus_job_cancel", settings)
    async def amicus_job_cancel(job_id: JobIdParam, workspace_root: WorkspaceRootParam = None) -> dict[str, Any]:
        """Cancel a background job."""
        return pending("amicus_job_cancel")

    @app.tool(
        name="amicus_job_list",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_LIST_SCHEMA,
        title="List background jobs (free)",
        meta=lifecycle_meta("amicus_job_list"),
        description=(
            f"{FREE_MARKER} List the jobs known for this workspace, newest first, across all "
            "backends; narrow with `backend`, `status`, or `task_id` (the tasks-extension id "
            "recorded at task creation). Only an explicit `limit` truncates (truncated: true, "
            f"no cursor). {_RETENTION}"
        ),
    )
    @guard("amicus_job_list", settings)
    async def amicus_job_list(
        workspace_root: WorkspaceRootParam = None,
        limit: JobLimitParam = None,
        status: JobStatusFilterParam = None,
        backend: OptionalBackendParam = None,
        task_id: TaskIdParam = None,
    ) -> dict[str, Any]:
        """List background jobs."""
        return pending("amicus_job_list")

    return (
        "amicus_job_status",
        "amicus_job_result",
        "amicus_job_consume_result",
        "amicus_job_cancel",
        "amicus_job_list",
    )
```

- [ ] **Step 5: Write `src/amicus/tools/discovery.py`**

```python
"""amicus_backends, amicus_models, amicus_capabilities (free discovery)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pontonier.core.redaction import exc_summary

from amicus import SERVER_NAME, __version__, surface
from amicus.backends import KNOWN_DISPLAY_NAMES, KNOWN_EFFECTS
from amicus.errors import error_envelope
from amicus.schemas.codes import BACKEND_IDS, ERROR_CODES
from amicus.schemas.envelope import ERROR_ENVELOPE_SCHEMA, RESULT_META_SCHEMA, InvalidArgument, Meta
from amicus.schemas.options import OPTION_ALLOWED_VALUES
from amicus.schemas.params import (
    PARAMS_RESOURCE_URI,
    BackendParam,
    CapabilitiesDetailParam,
    IncludeSchemasParam,
    OptionalBackendParam,
    expected_params,
    expected_required,
    params_resource_body,
)
from amicus.schemas.results import (
    BACKENDS_SCHEMA,
    CAPABILITIES_RESULT_SCHEMA,
    CAPABILITIES_SCHEMA,
    MODEL_CATALOG_SCHEMA,
    PAID_TOOLS,
    BackendEntry,
    BackendOptionInfo,
    BackendsResult,
    BackendStatus,
    CapabilitiesResult,
    EffectsInfo,
    ModelCatalogResult,
    ModelInfo,
    TaskSupport,
    ToolCapability,
    UnavailableEntry,
)
from amicus.tools import ACTIVE_TOOLS, FREE_TOOLS, JOB_TOOLS, TOOL_ORDER
from amicus.tools._guard import guard
from amicus.tools._meta import SERVER_STABILITY, TOOL_STABILITY, annotations_for, base_meta, effects_for, lifecycle_meta
from amicus.tools._resolve import FREE_MARKER

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.plugin import BackendPlugin
    from amicus.registry import BackendRegistry

INCLUDE_SCHEMAS_VALUES: tuple[str, ...] = (
    "error-envelope", "result-meta", "capabilities-result", "parameter-contracts",
)
_SUMMARY_FIELDS = ("name", "cost", "stability", "backends", "error_codes")

# Per-tool inventory facts tools/list does not carry. required/key params are derived
# from the matrix for the paid tools so this table cannot disagree with the schemas.
_COMMON_PAID_CODES = [
    "backend_unavailable", "feature_unsupported", "invalid_arguments", "invalid_workspace_root",
    "workspace_outside_roots", "input_too_large", "timeout", "nonzero_exit",
    "backend_auth_required", "backend_rate_limited", "not_implemented",
]
_REVIEW_CODES = ["invalid_base", "invalid_commit", "invalid_paths", "not_a_git_repo", "context_too_large"]
TOOL_DETAILS: dict[str, dict[str, Any]] = {
    "amicus_consult": {"cost": "active", "backends": list(BACKEND_IDS), "use_when": "A read-only second opinion or Q&A from another model, including on a diff pasted inline.", "returns": "summary, findings, questions, next_steps, raw_response (detail=full) and meta.", "error_codes": _COMMON_PAID_CODES},
    "amicus_consult_async": {"cost": "active", "backends": list(BACKEND_IDS), "use_when": "The same consult when it may exceed the sync deadline; returns a job handle.", "returns": "job_id, poll_after_ms, expires_at, follow_up; result via amicus_job_result.", "error_codes": _COMMON_PAID_CODES + ["idempotency_conflict", "idempotency_in_progress"]},
    "amicus_review_changes": {"cost": "active", "backends": list(BACKEND_IDS), "use_when": "A structured review of changes that live in git.", "returns": "verdict, confidence, findings, review_status, context_summary and meta.", "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES},
    "amicus_review_changes_async": {"cost": "active", "backends": list(BACKEND_IDS), "use_when": "A multi-file or whole-branch review that may exceed the sync deadline.", "returns": "a job handle; result via amicus_job_result.", "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES + ["idempotency_conflict", "idempotency_in_progress"]},
    "amicus_delegate": {"cost": "active", "backends": ["codex", "kimi"], "use_when": "A coding task implemented in a throwaway worktree, returned as a diff you apply yourself.", "returns": "diff, diffstat, summary and meta.", "error_codes": _COMMON_PAID_CODES + ["not_a_git_repo", "git_unavailable", "worktree_error"]},
    "amicus_delegate_async": {"cost": "active", "backends": ["codex", "kimi"], "use_when": "A substantial delegate that may exceed the sync deadline.", "returns": "a job handle; result via amicus_job_result.", "error_codes": _COMMON_PAID_CODES + ["not_a_git_repo", "git_unavailable", "worktree_error", "idempotency_conflict", "idempotency_in_progress"]},
    "amicus_adversarial_review": {"cost": "active", "backends": ["claude"], "use_when": "A fixed critic attacking a plan, claim or decision before you commit to it.", "returns": "verdict, confidence, findings and meta.", "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES},
    "amicus_adversarial_review_async": {"cost": "active", "backends": ["claude"], "use_when": "The same critique when it may exceed the sync deadline.", "returns": "a job handle; result via amicus_job_result.", "error_codes": _COMMON_PAID_CODES + _REVIEW_CODES + ["idempotency_conflict", "idempotency_in_progress"]},
    "amicus_dry_run": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Preview a review's scope, size and resolved options before spending.", "returns": "would_call_model, scope, prompt_bytes, context_summary, resolved backend_options.", "error_codes": ["backend_unavailable", "invalid_arguments", "invalid_workspace_root", "not_a_git_repo", "not_implemented"]},
    "amicus_delegate_dry_run": {"cost": "free", "backends": ["codex", "kimi"], "use_when": "Preview a delegate's worktree baseline before spending.", "returns": "worktree plan, task_bytes, resolved backend_options.", "error_codes": ["backend_unavailable", "feature_unsupported", "invalid_arguments", "not_a_git_repo", "not_implemented"]},
    "amicus_backends": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Before the first paid call: which backends are enabled, installed, authenticated, and what each supports.", "returns": "per-backend entries, unavailable reasons, env warnings, config errors.", "error_codes": ["invalid_arguments"]},
    "amicus_models": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Before overriding model or reasoning_effort.", "returns": "advisory model slugs with effort sets and the catalog source.", "error_codes": ["invalid_arguments"]},
    "amicus_capabilities": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "The full inventory, fingerprint, surface_digest and error catalog.", "returns": "this payload.", "error_codes": ["invalid_arguments"]},
    "amicus_job_status": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Poll a job without fetching its result.", "returns": "status, result_available, result_ok, poll_after_ms.", "error_codes": ["job_not_found", "invalid_workspace_root", "not_implemented"]},
    "amicus_job_result": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Fetch a finished job's envelope.", "returns": "the originating tool's envelope.", "error_codes": ["job_not_found", "job_running", "job_failed", "job_cancelled", "job_timeout", "job_result_incompatible", "not_implemented"]},
    "amicus_job_consume_result": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Fetch a finished job's envelope and delete the record.", "returns": "the originating tool's envelope.", "error_codes": ["job_not_found", "job_running", "job_failed", "job_cancelled", "job_timeout", "job_result_incompatible", "not_implemented"]},
    "amicus_job_cancel": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Stop a running job.", "returns": "the job's status after cancellation.", "error_codes": ["job_not_found", "not_implemented"]},
    "amicus_job_list": {"cost": "free", "backends": list(BACKEND_IDS), "use_when": "Recover job_ids, including the job behind a task_id.", "returns": "job summaries, truncated flag.", "error_codes": ["invalid_workspace_root", "not_implemented"]},
}
_JOB_PARAMS: dict[str, tuple[list[str], list[str]]] = {
    "amicus_dry_run": (["backend"], ["scope", "base", "commit", "paths", "workspace_root", "backend_options"]),
    "amicus_delegate_dry_run": (["backend", "task"], ["workspace_root", "backend_options"]),
    "amicus_backends": ([], ["backend"]),
    "amicus_models": (["backend"], []),
    "amicus_capabilities": ([], ["detail", "include_schemas"]),
    "amicus_job_status": (["job_id"], ["workspace_root"]),
    "amicus_job_result": (["job_id"], ["workspace_root", "detail"]),
    "amicus_job_consume_result": (["job_id"], ["workspace_root", "detail"]),
    "amicus_job_cancel": (["job_id"], ["workspace_root"]),
    "amicus_job_list": ([], ["workspace_root", "limit", "status", "backend", "task_id"]),
}


def _params_for(name: str) -> tuple[list[str], list[str]]:
    if name in _JOB_PARAMS:
        return _JOB_PARAMS[name]
    required = sorted(expected_required(name))
    optional = sorted(expected_params(name) - set(required))
    return required, optional


def _status_of(plugin: BackendPlugin) -> BackendStatus:
    try:
        rep = plugin.status.probe()
    except Exception as exc:  # noqa: BLE001 - a probe failure is a warning, not a crash
        return BackendStatus(installed=False, warnings=[f"status probe failed: {exc_summary(exc)}"])
    return BackendStatus(
        installed=rep.installed, version=rep.version, authenticated=rep.authenticated,
        warnings=list(rep.warnings),
    )


def _options_for(backend_id: str, plugin: BackendPlugin | None) -> list[BackendOptionInfo]:
    defaults = {o.name: o.default for o in plugin.options} if plugin else {}
    out: list[BackendOptionInfo] = []
    for name, per_backend in OPTION_ALLOWED_VALUES.items():
        if backend_id in per_backend:
            allowed = per_backend[backend_id]
            out.append(BackendOptionInfo(
                name=name, allowed_values=list(allowed) if allowed else None, default=defaults.get(name),
            ))
    return out


def backends_payload(
    settings: Settings, registry: BackendRegistry, config_errors: list[str], backend: str | None = None
) -> dict[str, Any]:
    ids = list(dict.fromkeys([*BACKEND_IDS, *settings.enabled_backends]))
    entries: list[BackendEntry] = []
    for backend_id in ids:
        if backend is not None and backend_id != backend:
            continue
        plugin = registry.get(backend_id)
        contract = plugin.contract if plugin else None
        effects = plugin.effects if plugin else KNOWN_EFFECTS.get(backend_id)
        entries.append(BackendEntry(
            id=backend_id,
            display_name=contract.display_name if contract else KNOWN_DISPLAY_NAMES.get(backend_id, backend_id),
            enabled=backend_id in settings.enabled_backends,
            available=plugin is not None,
            status=_status_of(plugin) if plugin else None,
            features=sorted(contract.supported_features) if contract else [],
            effects=EffectsInfo(
                paid_calls_destructive=effects.paid_calls_destructive if effects else True,
                job_reads_read_only=True,
            ),
            options=_options_for(backend_id, plugin),
            egress=plugin.egress or None if plugin else None,
            carriers=plugin.carriers or None if plugin else None,
            readonly_honesty=contract.readonly_honesty_statement if contract else None,
            implicit_context=contract.implicit_context_disclosure if contract else None,
        ))
    unavailable = [
        UnavailableEntry(id=u.backend_id, reason=u.reason, detail=u.detail)
        for u in registry.unavailable.values()
        if backend is None or u.backend_id == backend
    ]
    return BackendsResult(
        backends=entries,
        unavailable=unavailable,
        env_warnings=[*settings.env_warnings, *(f"{p} is an unexpanded ${{...}} placeholder" for p in settings.placeholders)],
        config_errors=list(config_errors),
    ).model_dump(mode="json")


def models_payload(registry: BackendRegistry, backend: str) -> dict[str, Any]:
    plugin = registry.get(backend)
    if plugin is None:
        return ModelCatalogResult(backend=backend, available=False, models=[], source="none").model_dump(mode="json")
    listing = plugin.models.read()
    return ModelCatalogResult(
        backend=backend,
        available=True,
        models=[ModelInfo(
            slug=m.slug, display_name=m.display_name, default_reasoning_effort=m.default_reasoning_effort,
            supported_reasoning_efforts=list(m.supported_reasoning_efforts) if m.supported_reasoning_efforts is not None else None,
        ) for m in listing.models],
        source=listing.source,
        fetched_at=listing.fetched_at,
    ).model_dump(mode="json")


async def capabilities_payload(
    app: FastMCP,
    settings: Settings,
    registry: BackendRegistry,
    config_errors: list[str],
    tasks_active: bool,
    detail: str = "summary",
    include_schemas: list[str] | None = None,
) -> dict[str, Any]:
    effects = effects_for(settings)
    details = [
        ToolCapability(
            name=name,
            cost=TOOL_DETAILS[name]["cost"],
            stability=TOOL_STABILITY.get(name),
            backends=TOOL_DETAILS[name]["backends"],
            use_when=TOOL_DETAILS[name]["use_when"],
            required_params=_params_for(name)[0],
            key_optional_params=_params_for(name)[1],
            returns=TOOL_DETAILS[name]["returns"],
            error_codes=TOOL_DETAILS[name]["error_codes"],
        )
        for name in TOOL_ORDER
    ]
    schemas: dict[str, Any] | None = None
    if include_schemas:
        bodies = {
            "error-envelope": ERROR_ENVELOPE_SCHEMA,
            "result-meta": RESULT_META_SCHEMA,
            "capabilities-result": CAPABILITIES_RESULT_SCHEMA,
            "parameter-contracts": params_resource_body(),
        }
        schemas = {k: bodies[k] for k in include_schemas}
    caps = CapabilitiesResult(
        name=SERVER_NAME,
        version=__version__,
        surface_digest=await surface.surface_digest(app),
        transport="stdio",
        stability=SERVER_STABILITY,
        enabled_backends=list(settings.enabled_backends),
        active_tools=list(ACTIVE_TOOLS),
        free_tools=list(FREE_TOOLS),
        job_tools=list(JOB_TOOLS),
        tool_details=details,
        error_codes=list(ERROR_CODES),
        scope=[
            "Second opinions, git-change reviews, adversarial critiques and delegated diffs "
            "from Codex, Kimi or Claude Code, selected per call.",
            "Durable background jobs for every paid verb, plus the tasks extension when enabled.",
        ],
        negative_scope=[
            "Never applies a diff to your working tree.",
            "Never bypasses a backend's sandbox or approvals.",
            "Does not bound what a backend CLI reads: the workspace selects where it works, not what it can read.",
            "No session transfer in v1.",
        ],
        prerequisites=[
            "At least one backend CLI installed and authenticated (amicus_backends reports which).",
            "workspace_root on every call from a sessionless (2026-07-28) client.",
        ],
        deprecation_policy=(
            "A deprecated tool, parameter or code stays discoverable for two minor releases "
            "with a deprecation marker in its lifecycle _meta naming the replacement."
        ),
        tool_error_carrier=(
            "tool result with isError: true; the error envelope is in structuredContent, and "
            "content[0].text mirrors it as JSON"
        ),
        resource_error_carrier=(
            "JSON-RPC error; the envelope (machine_code/human_message/backend/temporary/"
            "retry_after_ms/repair/resource_uri/request_id) is in error.data. Classify by "
            "error.data.machine_code: the numeric is era-bound (-32002 on a 2025-11-25 "
            "connection, -32602 on 2026-07-28; -32603 for a read failure on both)."
        ),
        annotations_reading=(
            "Annotations describe the worst ENABLED backend, not the backend selected per "
            f"call: paid tools are destructiveHint {str(effects.paid_calls_destructive).lower()} "
            "for this profile because "
            + ("Claude Code is enabled and its config modes may run workspace hooks. " if effects.paid_calls_destructive else "every enabled backend confines writes to a throwaway worktree. ")
            + "readOnlyHint tracks whether a call changes observable state that outlives the "
            "response (a job record, committed spend), so paid tools are readOnlyHint false "
            "even when the run writes nothing, and job reads stay readOnlyHint true under the "
            "observable-scope reading. Per-backend effects are published on amicus_backends."
        ),
        tasks=TaskSupport(
            enabled=tasks_active,
            task_tools=list(PAID_TOOLS) if tasks_active else [],
            fallback=(
                "A `completed` task is a delivery statement, not a success statement: inspect "
                "the delivered result's ok field. Every host can use the amicus_job_* tools "
                "instead; amicus_job_list(task_id=...) recovers the job behind a task."
            ),
        ),
        meta_fields=list(Meta.model_fields),
        schemas=schemas,
    ).model_dump(mode="json", exclude_none=True)
    if detail == "contracts":
        caps["tool_details"] = []
    elif detail == "summary":
        caps["tool_details"] = [
            {k: d.get(k) for k in _SUMMARY_FIELDS} for d in caps["tool_details"]
        ]
    else:
        for entry in caps["tool_details"]:
            entry.setdefault("stability", None)
    return caps


def register(app: FastMCP, settings: Settings, registry: BackendRegistry) -> tuple[str, ...]:
    from amicus.server import state_of

    @app.tool(
        name="amicus_backends",
        annotations=annotations_for("free", settings),
        output_schema=BACKENDS_SCHEMA,
        title="List backends and their readiness (free)",
        meta=lifecycle_meta("amicus_backends"),
        description=(
            f"{FREE_MARKER} Every known backend with enabled/available state, an installed/"
            "authenticated probe for the available ones, declared features, the backend_options "
            "each accepts with allowed values, annotation effects, egress and prompt carriers; "
            "plus why an enabled backend is unavailable, legacy-env warnings and config errors. "
            "Run it before the first paid call."
        ),
    )
    @guard("amicus_backends", settings)
    async def amicus_backends(backend: OptionalBackendParam = None) -> dict[str, Any]:
        """List backends."""
        return backends_payload(settings, registry, state_of(app).config_errors, backend)

    @app.tool(
        name="amicus_models",
        annotations=annotations_for("free", settings),
        output_schema=MODEL_CATALOG_SCHEMA,
        title="List a backend's models (free)",
        meta=lifecycle_meta("amicus_models"),
        description=(
            f"{FREE_MARKER} Advisory model slugs for `backend` (pass as `model`) with each "
            "model's advertised reasoning-effort set; the backend validates the real values. "
            "Not fingerprint-stable; same payload as amicus://models/{backend}."
        ),
    )
    @guard("amicus_models", settings)
    async def amicus_models(backend: BackendParam) -> dict[str, Any]:
        """List a backend's models."""
        return models_payload(registry, backend)

    @app.tool(
        name="amicus_capabilities",
        annotations=annotations_for("free", settings),
        output_schema=CAPABILITIES_SCHEMA,
        title="List server capabilities (free)",
        meta=lifecycle_meta("amicus_capabilities"),
        description=(
            f"{FREE_MARKER} The tool inventory, fingerprint and surface_digest (cache by them), "
            "the full error-code catalog, the annotation policy, the tasks/jobs contract, and "
            "meta's field list. detail=summary (default) | full | contracts; include_schemas "
            "embeds error-envelope, result-meta, capabilities-result and/or "
            "parameter-contracts for resource-blind clients."
        ),
    )
    @guard("amicus_capabilities", settings)
    async def amicus_capabilities(
        detail: CapabilitiesDetailParam = "summary", include_schemas: IncludeSchemasParam = None
    ) -> dict[str, Any]:
        """List capabilities."""
        if include_schemas:
            bad = [(i, v) for i, v in enumerate(include_schemas) if v not in INCLUDE_SCHEMAS_VALUES]
            if bad:
                items = [InvalidArgument(
                    field=f"include_schemas[{i}]", reason="unknown schema name",
                    allowed_values=list(INCLUDE_SCHEMAS_VALUES),
                ) for i, _ in bad]
                return error_envelope(
                    "invalid_arguments",
                    f"amicus_capabilities: {len(items)} invalid argument(s): {items[0].field} — unknown schema name",
                    base_meta(settings), repair_tool="amicus_capabilities", invalid_arguments=items,
                )
        state = state_of(app)
        return await capabilities_payload(
            app, settings, registry, state.config_errors, state.tasks_active, detail, include_schemas
        )

    return ("amicus_backends", "amicus_models", "amicus_capabilities")
```

`PARAMS_RESOURCE_URI` is imported for the resources module's use; if ruff reports it unused here, drop it from this import list.

- [ ] **Step 6: Write `src/amicus/tools/resources.py` (replace the stub)**

```python
"""Four static resources, two templates with completion, one lifecycle _meta each."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import NotFoundError
from mcp_types import ResourceTemplateReference

from amicus.schemas.codes import BACKEND_IDS
from amicus.schemas.envelope import ERROR_ENVELOPE_SCHEMA, RESULT_META_SCHEMA
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY, TRIAGE_META_KEY
from amicus.schemas.params import PARAMS_RESOURCE_URI, params_resource_body
from amicus.tools import discovery
from amicus.tools._meta import SERVER_STABILITY

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

STATIC_RESOURCE_URIS: tuple[str, ...] = (
    "amicus://capabilities",
    "amicus://error-envelope",
    "amicus://result-meta",
    PARAMS_RESOURCE_URI,
)
TEMPLATE_URIS: tuple[str, ...] = ("amicus://backends/{backend}", "amicus://models/{backend}")


def _meta(payload: dict[str, Any] | None = None, *, volatile: bool = False) -> dict[str, Any]:
    triage: dict[str, Any] = {"volatile": True} if volatile else {"size_bytes": len(json.dumps(payload).encode())}
    return {LIFECYCLE_META_KEY: {"stability": SERVER_STABILITY}, TRIAGE_META_KEY: triage}


def complete_backend(ref: Any, argument: Any, context: Any) -> list[str] | None:
    if not isinstance(ref, ResourceTemplateReference) or ref.uri not in TEMPLATE_URIS:
        return None
    if getattr(argument, "name", None) != "backend":
        return []
    prefix = getattr(argument, "value", "") or ""
    return [b for b in BACKEND_IDS if b.startswith(prefix)]


def register_resources(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    from amicus.server import state_of

    @app.resource(
        "amicus://capabilities", name="amicus-capabilities", title="amicus capability summary",
        mime_type="application/json", meta=_meta(volatile=True),
    )
    async def capabilities_resource() -> dict[str, Any]:
        """The amicus_capabilities payload (detail=summary) as a resource."""
        state = state_of(app)
        return await discovery.capabilities_payload(app, settings, registry, state.config_errors, state.tasks_active)

    @app.resource(
        "amicus://error-envelope", name="amicus-error-envelope", title="amicus error envelope schema",
        mime_type="application/schema+json", meta=_meta(ERROR_ENVELOPE_SCHEMA),
    )
    def error_envelope_resource() -> dict[str, Any]:
        """The full ErrorResult schema; tool outputSchemas carry only an opaque error branch."""
        return ERROR_ENVELOPE_SCHEMA

    @app.resource(
        "amicus://result-meta", name="amicus-result-meta", title="amicus result metadata schema",
        mime_type="application/schema+json", meta=_meta(RESULT_META_SCHEMA),
    )
    def result_meta_resource() -> dict[str, Any]:
        """The full Meta schema every success envelope's opaque `meta` points at."""
        return RESULT_META_SCHEMA

    @app.resource(
        PARAMS_RESOURCE_URI, name="amicus-params", title="amicus parameter contracts",
        mime_type="application/json", meta=_meta(params_resource_body()),
    )
    def params_resource() -> dict[str, Any]:
        """Full semantics for parameters whose inline description is a compressed summary."""
        return params_resource_body()

    @app.resource(
        "amicus://backends/{backend}", name="amicus-backend", title="One backend's catalog entry",
        mime_type="application/json", meta=_meta(volatile=True),
    )
    def backend_resource(backend: str) -> dict[str, Any]:
        """The amicus_backends entry for one backend."""
        payload = discovery.backends_payload(settings, registry, state_of(app).config_errors, backend)
        if not payload["backends"]:
            raise NotFoundError(f"unknown backend {backend!r}")
        return {**payload["backends"][0], "unavailable": payload["unavailable"]}

    @app.resource(
        "amicus://models/{backend}", name="amicus-models", title="One backend's model catalog",
        mime_type="application/json", meta=_meta(volatile=True),
    )
    def models_resource(backend: str) -> dict[str, Any]:
        """The amicus_models payload for one backend."""
        if backend not in BACKEND_IDS and registry.get(backend) is None:
            raise NotFoundError(f"unknown backend {backend!r}")
        return discovery.models_payload(registry, backend)

    app.completion(complete_backend)
```

Then restore strict equality in `tools/__init__.py::register_all` (`if registered != TOOL_ORDER: raise RuntimeError(...)`) and delete the temporary stubs' bodies (they are now the real modules).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_surface.py tests/test_discovery.py tests/test_resources.py tests/test_paid_tools.py tests/test_server.py -v --no-cov`
Expected: all PASS. Likely adjustments:
- If `Resource` records expose `_meta` as `.meta` on the client model, read `rec.meta`; if under `model_extra`, use `rec.model_dump(by_alias=True)["_meta"]`.
- If FastMCP's completion handler signature must be `(ref, argument, context)` positional, keep it as written; if it rejects a sync handler, make `complete_backend` async and update the direct-call test to `await`.
- If `app.instructions` is not an attribute, use `app._mcp_server.instructions`.
- If the client wraps a resource `dict` return as JSON text with `mime_type` overridden to `application/json`, keep the schema resources' mime as declared but assert on the declared record (`listed[...].mime_type`) rather than the read block.

- [ ] **Step 8: Run the whole suite with coverage**

Run: `uv run pytest`
Expected: PASS at ≥95% branch coverage. If coverage is short, the uncovered lines the report names are the ones to test next (typically `discovery._params_for` for a job tool, `backends_payload` with a filter, `models_payload` with an effort set) — add the missing case to `tests/test_discovery.py` rather than excluding lines.

- [ ] **Step 9: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/surface.py src/amicus/tools tests/test_surface.py tests/test_discovery.py tests/test_resources.py
git commit -m "feat(tools): complete the 18-tool surface with discovery, jobs and resources

amicus_backends (catalog, readiness probe, option applicability, legacy
env warnings), amicus_models, amicus_capabilities (fingerprint,
surface_digest, error catalog, tasks contract, opt-in schemas), the two
free previews and five job tools schema-only, four static resources and
two templates with completion, each carrying lifecycle _meta."
```

---

### Task 14: Manifest snapshot per profile, surface honesty, digest pins

**Files:**
- Create: `src/amicus/manifest.py`, `tests/test_manifest.py`, `tests/test_surface_honesty.py`, `tests/test_fingerprint.py`, `tests/fixtures/manifest_snapshot.all.json`, `tests/fixtures/manifest_snapshot.codex-kimi.json`, `tests/fixtures/manifest_snapshot.claude.json`

**Interfaces:**
- Produces (`manifest`): `PROFILES: dict[str, dict[str, str]]` (`"all"`, `"codex-kimi"`, `"claude"` → env overrides), `app_for_profile(profile) -> FastMCP`, `async build_manifest(app) -> dict`, `manifest_json(manifest) -> str`, `async manifest_hash(app) -> str`, `render(profile) -> str`, `main(argv=None)` (`python -m amicus.manifest --profile all [--measure]`), `STATIC_RESOURCE_URIS`, `DYNAMIC_RESOURCE_URIS`, `RESULT_ENVELOPE_FIELDS`, `RELEASE_VARIABLE_EXCLUDE`, `SELF_REFERENTIAL_EXCLUDE`.

- [ ] **Step 1: Write `src/amicus/manifest.py`**

```python
"""Canonical manifest of the agent-visible surface, per profile (ADR 0006).

Ported from codex-in-claude: both protocol eras are captured (legacy `initialize`, modern
`server/discover` and the modern result envelopes), every static resource body is read
and parsed, and the capabilities payload is captured minus release-variable and
self-referential fields. A committed snapshot per profile plus a pinned hash guard
FINGERPRINT; regeneration is always its own commit.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import sys
from typing import Any

from fastmcp import Client, FastMCP

from amicus import config, server
from amicus.registry import BackendRegistry

PROFILES: dict[str, dict[str, str]] = {
    "all": {},
    "codex-kimi": {"AMICUS_BACKENDS": "codex,kimi"},
    "claude": {"AMICUS_BACKENDS": "claude"},
}
_FASTMCP_META_KEY = "fastmcp"
_SETLIKE_ARRAY_KEYS = frozenset({"enum", "required"})
RELEASE_VARIABLE_EXCLUDE = frozenset({"version", "server_version"})
SELF_REFERENTIAL_EXCLUDE = frozenset({"fingerprint", "surface_digest"})
_DISCOVER_SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
_MODERN_ERA = "2026-07-28"
RESULT_ENVELOPE_FIELDS = ("resultType", "ttlMs", "cacheScope")
STATIC_RESOURCE_URIS = ("amicus://error-envelope", "amicus://result-meta", "amicus://params")
# Content never read: it embeds surface_digest (self-referential) and the live env report.
DYNAMIC_RESOURCE_URIS = ("amicus://capabilities",)
_SECTION_BY_STATIC_URI = {
    "amicus://error-envelope": "error_envelope",
    "amicus://result-meta": "result_meta",
    "amicus://params": "params",
}
_ENVELOPE_PROBE_TOOL = "amicus_capabilities"
_ENVELOPE_PROBE_ARGS: dict[str, Any] = {"detail": "summary"}


def app_for_profile(profile: str) -> FastMCP:
    """An app for a profile with NO backend loaded: the manifest guards the schema-only
    surface, which must not depend on which CLIs this machine has installed."""
    return server.create_app(config.settings(PROFILES[profile]), BackendRegistry({}, {}))


def _sorted_by_json(items: list[Any]) -> list[Any]:
    return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, raw in obj.items():
            value = raw
            if key == "_meta" and isinstance(raw, dict):
                value = {k: v for k, v in raw.items() if k != _FASTMCP_META_KEY}
                if not value:
                    continue
            cval = _canonicalize(value)
            if isinstance(cval, list) and (key in _SETLIKE_ARRAY_KEYS or key == "type"):
                cval = _sorted_by_json(cval)
            out[key] = cval
        return out
    if isinstance(obj, list):
        return [_canonicalize(v) for v in obj]
    return obj


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def _envelope_fields(result: Any) -> dict[str, Any]:
    wire = _dump(result)
    return {k: wire[k] for k in RESULT_ENVELOPE_FIELDS if k in wire}


def _envelope_block(content: Any) -> dict[str, Any]:
    block = _canonicalize(_dump(content))
    text = block.get("text")
    if isinstance(text, str):
        with contextlib.suppress(json.JSONDecodeError):
            block["text"] = _canonicalize(json.loads(text))
    return block


async def build_manifest(app: FastMCP) -> dict[str, Any]:
    async with Client(app, mode="legacy") as client:
        tools = [_canonicalize(_dump(t)) for t in await client.list_tools()]
        resources = [_canonicalize(_dump(r)) for r in await client.list_resources()]
        templates = [_canonicalize(_dump(t)) for t in await client.list_resource_templates()]
        prompts = [_canonicalize(_dump(p)) for p in await client.list_prompts()]
        initialize = _canonicalize(_dump(client.initialize_result))
        server_info = initialize.get("serverInfo")
        if isinstance(server_info, dict):
            server_info.pop("version", None)
        static_sections = {
            _SECTION_BY_STATIC_URI[uri]: [_envelope_block(c) for c in await client.read_resource(uri)]
            for uri in STATIC_RESOURCE_URIS
        }
        caps_result = await client.call_tool(_ENVELOPE_PROBE_TOOL, {"detail": "full"})
    caps = {
        k: v
        for k, v in caps_result.structured_content.items()
        if k not in RELEASE_VARIABLE_EXCLUDE | SELF_REFERENTIAL_EXCLUDE
    }
    async with Client(app) as modern:
        if modern.protocol_version != _MODERN_ERA:  # pragma: no cover - guard
            raise RuntimeError(f"default client negotiated {modern.protocol_version!r}")
        discover = _canonicalize(_dump(modern.session.discover_result))
        envelopes: dict[str, Any] = {
            "tools/list": _envelope_fields(await modern.list_tools_mcp()),
            "resources/list": _envelope_fields(await modern.list_resources_mcp()),
            "resources/templates/list": _envelope_fields(await modern.list_resource_templates_mcp()),
            "prompts/list": _envelope_fields(await modern.list_prompts_mcp()),
            "resources/read": {
                uri: _envelope_fields(await modern.read_resource_mcp(uri)) for uri in STATIC_RESOURCE_URIS
            },
            "tools/call": _envelope_fields(
                await modern.call_tool_mcp(_ENVELOPE_PROBE_TOOL, _ENVELOPE_PROBE_ARGS)
            ),
        }
    meta = discover.get("_meta")
    if isinstance(meta, dict) and isinstance(meta.get(_DISCOVER_SERVER_INFO_META), dict):
        meta[_DISCOVER_SERVER_INFO_META].pop("version", None)
    return {
        "tools": sorted(tools, key=lambda t: t["name"]),
        "resources": sorted(resources, key=lambda r: r["uri"]),
        "resource_templates": sorted(templates, key=lambda t: t["uriTemplate"]),
        "prompts": sorted(prompts, key=lambda p: p["name"]),
        "initialize": initialize,
        "discover": discover,
        "modern_result_envelopes": envelopes,
        **static_sections,
        "capabilities": _canonicalize(caps),
    }


def manifest_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


async def manifest_hash(app: FastMCP) -> str:
    return hashlib.sha256(manifest_json(await build_manifest(app)).encode("utf-8")).hexdigest()


def render(profile: str) -> str:
    return manifest_json(asyncio.run(build_manifest(app_for_profile(profile))))


async def tools_list_bytes(app: FastMCP) -> int:
    """The serialized tools/list a client receives (the discovery-cost measurement)."""
    async with Client(app) as c:
        tools = await c.list_tools()
    payload = [t.model_dump(mode="json", exclude_none=True, by_alias=True) for t in tools]
    return len(json.dumps(payload, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description="Render the manifest or measure tools/list.")
    parser.add_argument("--profile", default="all", choices=sorted(PROFILES))
    parser.add_argument("--measure", action="store_true", help="print tools/list bytes per profile")
    args = parser.parse_args(argv)
    if args.measure:
        for profile in PROFILES:
            size = asyncio.run(tools_list_bytes(app_for_profile(profile)))
            sys.stdout.write(f"{profile}\t{size}\n")
        return 0
    sys.stdout.write(render(args.profile))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 2: Write the tests**

`tests/test_manifest.py`:

```python
"""Guard: the manifest snapshot covers the full agent-visible surface, per profile."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastmcp import Client

from amicus import manifest
from amicus.schemas.fingerprint import FINGERPRINT_COVERS, FINGERPRINT_COVERS_DESC

FIXTURES = Path(__file__).parent / "fixtures"

# sha256 of each profile's canonical manifest JSON; regenerate per the failure message.
EXPECTED_MANIFEST_HASH: dict[str, str] = {
    "all": "",
    "codex-kimi": "",
    "claude": "",
}

_CACHING_SPEC_LIST_METHODS = ("tools/list", "resources/list", "resources/templates/list", "prompts/list")


def test_canonicalize():
    assert manifest._canonicalize({"_meta": {"fastmcp": {"tags": []}, "app": {"k": 1}}}) == {"_meta": {"app": {"k": 1}}}
    assert manifest._canonicalize({"_meta": {"fastmcp": {"tags": []}}}) == {}
    canon = manifest._canonicalize({"enum": ["c", "a"], "required": ["z", "a"], "type": ["string", "null"]})
    assert canon == {"enum": ["a", "c"], "required": ["a", "z"], "type": ["null", "string"]}
    src = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert manifest._canonicalize(src)["anyOf"] == src["anyOf"]


async def test_build_manifest_covers_full_surface():
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    assert {t["name"] for t in m["tools"]} == set(m["capabilities"]["active_tools"]) | set(
        m["capabilities"]["free_tools"]
    ) | set(m["capabilities"]["job_tools"])
    assert len(m["tools"]) == 18
    for section in ("resources", "resource_templates", "initialize", "discover", "error_envelope", "result_meta", "params", "capabilities"):
        assert m[section], section
    assert m["prompts"] == []


async def test_fingerprint_covers_accounts_for_every_section():
    section_tokens = {
        "tools": {"tool_names", "tool_input_schemas", "tool_output_schemas", "tool_descriptions", "tool_annotations", "tool_lifecycle_meta", "error_codes", "value_enums"},
        "resources": {"resource_metadata"},
        "resource_templates": {"resource_templates"},
        "prompts": {"prompts"},
        "initialize": {"initialize_response"},
        "discover": {"discover_response"},
        "modern_result_envelopes": {"modern_result_envelopes"},
        "error_envelope": {"error_envelope_schema"},
        "result_meta": {"result_meta_schema"},
        "params": {"parameter_contracts"},
        "capabilities": {"capabilities_payload", "capability_guarantees", "capabilities_result_schema"},
    }
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    assert set(section_tokens) == set(m)
    assert set().union(*section_tokens.values()) == set(FINGERPRINT_COVERS)


async def test_manifest_drops_exactly_the_declared_capability_fields():
    app = manifest.app_for_profile("all")
    m = await manifest.build_manifest(app)
    async with Client(app) as c:
        live = (await c.call_tool("amicus_capabilities", {"detail": "full"})).structured_content
    dropped = set(live) - set(m["capabilities"])
    assert dropped == manifest.RELEASE_VARIABLE_EXCLUDE | manifest.SELF_REFERENTIAL_EXCLUDE
    assert set(live) >= manifest.RELEASE_VARIABLE_EXCLUDE | manifest.SELF_REFERENTIAL_EXCLUDE


def test_release_variable_exclusions_are_disclosed():
    clause = re.search(r"Release identity is excluded: (.+?) change every release", FINGERPRINT_COVERS_DESC)
    assert clause
    disclosed = {n.strip() for n in clause.group(1).split(",")}
    assert disclosed == manifest.RELEASE_VARIABLE_EXCLUDE | {"serverInfo.version"}
    assert "surface_digest" in FINGERPRINT_COVERS_DESC


async def test_static_resource_bodies_are_parsed():
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    for section in ("error_envelope", "result_meta", "params"):
        parsed = [b["text"] for b in m[section] if isinstance(b.get("text"), dict)]
        assert parsed, section
    assert any("backend" in b.get("properties", {}) for b in [x["text"] for x in m["result_meta"]])


async def test_initialize_and_discover_are_captured_without_versions():
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    assert m["initialize"]["serverInfo"]["name"] == "amicus"
    assert "version" not in m["initialize"]["serverInfo"]
    assert m["discover"]["supportedVersions"] == ["2026-07-28"]
    assert "version" not in m["discover"]["_meta"]["io.modelcontextprotocol/serverInfo"]
    assert m["initialize"]["capabilities"] != m["discover"]["capabilities"]


async def test_modern_result_envelopes_are_pinned_at_the_sdk_default():
    """ttlMs/cacheScope are deliberately left at the SDK default (ADR 0006); the manifest
    pins the emitted values so a framework change is reviewed, not silent."""
    m = await manifest.build_manifest(manifest.app_for_profile("all"))
    env = m["modern_result_envelopes"]
    assert set(env) == set(_CACHING_SPEC_LIST_METHODS) | {"resources/read", "tools/call"}
    for method in _CACHING_SPEC_LIST_METHODS:
        assert env[method] == {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}, method
    assert set(env["resources/read"]) == set(manifest.STATIC_RESOURCE_URIS)
    for uri, fields in env["resources/read"].items():
        assert fields == {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}, uri
    assert env["tools/call"]["resultType"] == "complete"
    listed = {r["uri"] for r in m["resources"]}
    assert listed == set(manifest.STATIC_RESOURCE_URIS) | set(manifest.DYNAMIC_RESOURCE_URIS)


async def test_list_items_are_era_neutral():
    app = manifest.app_for_profile("all")
    async with Client(app, mode="legacy") as legacy, Client(app) as modern:
        for lister in ("list_tools", "list_resources", "list_resource_templates"):
            a = [manifest._canonicalize(manifest._dump(x)) for x in await getattr(legacy, lister)()]
            b = [manifest._canonicalize(manifest._dump(x)) for x in await getattr(modern, lister)()]
            assert a == b, lister
        assert await modern.list_tools()


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
async def test_manifest_matches_golden(profile):
    app = manifest.app_for_profile(profile)
    current = manifest.manifest_json(await manifest.build_manifest(app))
    fixture = FIXTURES / f"manifest_snapshot.{profile}.json"
    assert fixture.exists(), (
        f"no snapshot for profile {profile!r}: `uv run python -m amicus.manifest --profile "
        f"{profile} > tests/fixtures/manifest_snapshot.{profile}.json` in its own commit"
    )
    assert current == fixture.read_text(encoding="utf-8"), (
        "agent-visible surface changed — review the snapshot diff, then in a DEDICATED "
        "commit: bump FINGERPRINT (schema-N) in schemas/fingerprint.py, regenerate every "
        "profile's fixture, and re-pin EXPECTED_MANIFEST_HASH and the surface digests."
    )
    assert await manifest.manifest_hash(app) == EXPECTED_MANIFEST_HASH[profile]


async def test_profiles_differ_where_annotations_differ():
    a = await manifest.build_manifest(manifest.app_for_profile("codex-kimi"))
    b = await manifest.build_manifest(manifest.app_for_profile("claude"))
    consult_a = next(t for t in a["tools"] if t["name"] == "amicus_consult")
    consult_b = next(t for t in b["tools"] if t["name"] == "amicus_consult")
    assert consult_a["annotations"]["destructiveHint"] is False
    assert consult_b["annotations"]["destructiveHint"] is True


def test_render_returns_canonical_json():
    out = manifest.render("all")
    assert out.startswith("{") and out.endswith("\n")


async def test_tools_list_bytes_is_positive():
    assert await manifest.tools_list_bytes(manifest.app_for_profile("all")) > 10_000
```

`tests/test_surface_honesty.py`:

```python
"""Wire prose must not contradict what amicus does: a shared union of bans in M0, refined
per backend when each plugin's contract lands (its forbidden_surface_phrases join here)."""

from __future__ import annotations

import json

import pytest
from pontonier.testing import surface_honesty

from amicus import manifest

# Cross-backend vocabulary that would teach an agent a mechanism amicus lacks.
FORBIDDEN_SURFACE_PHRASES: tuple[str, ...] = (
    "applies the diff to your working tree",
    "--dangerously-bypass",
    "codex exec",
    "kimi exec",
    "codex_consult",
    "claude_consult",
    "kimi_consult",
    "codex-in-claude",
    "moonbridge",
    "claude-in-codex",
)


@pytest.fixture(scope="module")
def wire_text() -> str:
    import asyncio

    return json.dumps(asyncio.run(manifest.build_manifest(manifest.app_for_profile("all"))), ensure_ascii=False)


@pytest.mark.parametrize("phrase", FORBIDDEN_SURFACE_PHRASES)
def test_wire_prose_does_not_carry_sibling_vocabulary(wire_text, phrase):
    assert surface_honesty.find_forbidden_phrases(wire_text, (phrase,)) == []


def test_the_instrument_can_fail(wire_text):
    assert surface_honesty.find_forbidden_phrases(wire_text, ("amicus_consult",))
```

`tests/test_fingerprint.py`:

```python
"""surface_digest per profile is pinned beside the manifest hash; a bump is deliberate."""

from __future__ import annotations

import pytest

from amicus import manifest, surface
from amicus.schemas.fingerprint import FINGERPRINT

EXPECTED_SURFACE_DIGEST: dict[str, str] = {"all": "", "codex-kimi": "", "claude": ""}


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
async def test_surface_digest_is_pinned(profile):
    actual = await surface.surface_digest(manifest.app_for_profile(profile))
    assert actual == EXPECTED_SURFACE_DIGEST[profile], (
        f"surface_digest moved for {profile!r}: {actual}. If intentional, bump FINGERPRINT "
        "(currently {FINGERPRINT}) and re-pin in a dedicated commit."
    )


async def test_digest_moves_when_a_description_changes():
    app = manifest.app_for_profile("all")
    before = await surface.surface_digest(app)
    tool = await app.get_tool("amicus_consult")
    original = tool.description
    tool.description = (original or "") + " probe"
    try:
        after = await surface.surface_digest(app)
    finally:
        tool.description = original
    assert after != before
    assert await surface.surface_digest(app) == before
```

- [ ] **Step 3: Run the tests to verify the golden tests fail for want of fixtures**

Run: `uv run pytest tests/test_manifest.py tests/test_surface_honesty.py tests/test_fingerprint.py -v --no-cov`
Expected: every test PASSES except `test_manifest_matches_golden[*]` (no snapshot yet) and `test_surface_digest_is_pinned[*]` (empty pins). If `test_wire_prose_does_not_carry_sibling_vocabulary` fails, a description carries sibling vocabulary — fix the description (Tasks 12/13), never the ban.

- [ ] **Step 4: Commit the module and tests (without fixtures)**

```bash
git add src/amicus/manifest.py tests/test_manifest.py tests/test_surface_honesty.py tests/test_fingerprint.py
git commit -m "feat(manifest): capture the agent-visible surface per profile

Both eras are captured (initialize, server/discover, the modern result
envelopes pinned at the SDK default ttlMs/cacheScope per ADR 0006), the
static resource bodies are parsed, and the capabilities payload is kept
minus release-variable and self-referential fields. Fixtures follow in
their own commit."
```

- [ ] **Step 5: Generate the fixtures and pin the hashes (dedicated commit)**

```bash
for p in all codex-kimi claude; do
  uv run python -m amicus.manifest --profile "$p" > "tests/fixtures/manifest_snapshot.$p.json"
done
uv run python - <<'PY'
import asyncio, json
from amicus import manifest, surface
for p in manifest.PROFILES:
    app = manifest.app_for_profile(p)
    print(p, asyncio.run(manifest.manifest_hash(app)), asyncio.run(surface.surface_digest(app)))
PY
```

Copy each printed manifest hash into `EXPECTED_MANIFEST_HASH[profile]` in `tests/test_manifest.py` and each surface digest into `EXPECTED_SURFACE_DIGEST[profile]` in `tests/test_fingerprint.py`.

Run: `uv run pytest tests/test_manifest.py tests/test_fingerprint.py -q --no-cov`
Expected: all PASS.

```bash
git add tests/fixtures tests/test_manifest.py tests/test_fingerprint.py
git commit -m "test(manifest): commit the M0 manifest snapshots and pin the digests

schema-1: the first snapshot of every profile (all, codex-kimi, claude)
and the surface digests they carry. No surface change; this is the
initial acknowledgment."
```

---

### Task 15: Discovery-cost ratchet per profile

**Files:**
- Create: `tests/test_discovery_cost.py`

- [ ] **Step 1: Measure**

Run: `uv run python -m amicus.manifest --measure`
Expected: three lines `profile<TAB>bytes`. Record them; they are the targets below.

- [ ] **Step 2: Write the test with the measured numbers**

`tests/test_discovery_cost.py` — replace each `0` in `MEASURED` with the printed value for that profile; `BUDGET` is the next multiple of 1,000 above the measured value:

```python
"""Wire-size ratchet for tools/list, per profile.

The least-capable realistic client preloads every tool definition, so the serialized
catalog is a per-session token tax. The budget is a ceiling; the target is the last
deliberate measurement so a failure message shows the drift. Raising a budget is a
reviewed decision — say why in the PR body.

Measured 2026-09-04 at schema-1 (18 tools, schema-only): see MEASURED.
"""

from __future__ import annotations

import pytest

from amicus import manifest

MEASURED: dict[str, int] = {"all": 0, "codex-kimi": 0, "claude": 0}
BUDGET: dict[str, int] = {p: ((n // 1000) + 1) * 1000 for p, n in MEASURED.items()}
# ceil(bytes/4): a dependency-free, conservative token proxy (~4.13 bytes per token).
TOKEN_PROXY_BUDGET: dict[str, int] = {p: -(-b // 4) for p, b in BUDGET.items()}


def _token_proxy(wire_bytes: int) -> int:
    return -(-wire_bytes // 4)


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
async def test_tools_list_wire_size_budget(profile):
    size = await manifest.tools_list_bytes(manifest.app_for_profile(profile))
    assert size <= BUDGET[profile], (
        f"[{profile}] tools/list is {size} bytes (target {MEASURED[profile]}), over the "
        f"{BUDGET[profile]} budget. Compact a description or schema, or raise the budget "
        "deliberately."
    )
    assert _token_proxy(size) <= TOKEN_PROXY_BUDGET[profile]


def test_measured_values_are_real():
    assert all(n > 0 for n in MEASURED.values())
    assert MEASURED["codex-kimi"] != MEASURED["claude"] or MEASURED["all"] == MEASURED["claude"]
```

- [ ] **Step 3: Run, then prove the ratchet can fail**

Run: `uv run pytest tests/test_discovery_cost.py -v --no-cov`
Expected: PASS.

Temporarily set `BUDGET = {p: 1 for p in MEASURED}` and rerun; expected: three FAILs whose messages show the measured sizes. Revert.

- [ ] **Step 4: Commit**

```bash
git add tests/test_discovery_cost.py
git commit -m "test(schemas): ratchet the tools/list discovery cost per profile

Measured on the 18 real schemas for the all, codex-kimi and claude
profiles; the budget is the next 1,000 above each measurement and the
token proxy is ceil(bytes/4)."
```

---

### Task 16: Task↔job map and the tasks-extension spike

**Files:**
- Create: `src/amicus/jobs/__init__.py`, `src/amicus/jobs/taskmap.py`, `src/amicus/orchestration/__init__.py`, `tests/test_taskmap.py`, `tests/test_tasks_spike.py`
- Modify: `docs/adr/0004-tasks-and-jobs.md` (spike report)

**Interfaces:**
- Produces (`jobs.taskmap`): `TaskJobMap(path)` with `.record(task_id, job_id) -> None`, `.job_for(task_id) -> str | None`, `.task_for(job_id) -> str | None`, `.entries() -> dict[str, str]`; atomic writes; a missing or corrupt file reads as empty.

- [ ] **Step 1: Write the failing tests**

`tests/test_taskmap.py`:

```python
"""The persisted task_id -> job_id map (ADR 0004)."""

from __future__ import annotations

from amicus.jobs.taskmap import TaskJobMap


def test_record_and_lookup_survive_a_reopen(tmp_path):
    path = tmp_path / "tasks.json"
    m = TaskJobMap(path)
    assert m.job_for("t1") is None and m.entries() == {}
    m.record("t1", "j1")
    m.record("t2", "j2")
    again = TaskJobMap(path)
    assert again.job_for("t1") == "j1" and again.task_for("j2") == "t2"
    assert again.task_for("nope") is None
    assert again.entries() == {"t1": "j1", "t2": "j2"}


def test_corrupt_or_missing_file_reads_as_empty(tmp_path):
    path = tmp_path / "nested" / "tasks.json"
    assert TaskJobMap(path).entries() == {}
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    assert TaskJobMap(path).entries() == {}
    TaskJobMap(path).record("t", "j")
    assert TaskJobMap(path).job_for("t") == "j"
    assert not list(path.parent.glob("*.tmp"))
```

`tests/test_tasks_spike.py`:

```python
"""Tasks-extension spike (M0): prove the real `fastmcp[tasks]` extension runs in-process
against this server, that a task-augmented paid call delivers the same envelope, that the
task id is reachable inside the tool (for the task→job map), and record what a legacy-
era client gets. Findings are copied into docs/adr/0004-tasks-and-jobs.md."""

from __future__ import annotations

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs.taskmap import TaskJobMap
from amicus.registry import BackendRegistry
from amicus.schemas.results import PAID_TOOLS
from tests.support import fakeplugin

pytest.importorskip("fastmcp_tasks")
from fastmcp_tasks import call_tool_task  # noqa: E402
from fastmcp_tasks.context import get_task_context  # noqa: E402


def _app():
    settings = config.settings({"AMICUS_TASKS": "1", "AMICUS_TASKS_BACKEND_URL": "memory://"})
    reg = BackendRegistry({"codex": fakeplugin.make_plugin("codex")}, {})
    return server.create_app(settings, reg)


async def test_extension_is_advertised_and_capabilities_report_it():
    app = _app()
    assert server.state_of(app).tasks_active is True
    async with Client(app) as c:
        caps = c.server_capabilities.model_dump(by_alias=True, mode="json", exclude_none=True)
        assert "io.modelcontextprotocol/tasks" in caps["extensions"]
        assert "io.modelcontextprotocol/ui" not in caps["extensions"]
        payload = (await c.call_tool("amicus_capabilities", {})).structured_content
    assert payload["tasks"]["enabled"] is True
    assert payload["tasks"]["task_tools"] == list(PAID_TOOLS)


async def test_task_augmented_paid_call_delivers_the_same_envelope():
    app = _app()
    async with Client(app) as c:
        plain = await c.call_tool("amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False)
        task = await call_tool_task(c, "amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False)
        status = await task.status()
        result = await task.result()
    assert plain.structured_content["error"]["code"] == "not_implemented"
    assert result.structured_content["error"]["code"] == "not_implemented"
    # Spike finding: does the semantic isError flip survive task delivery?
    assert result.is_error is True
    assert task.task_id and task.create_result.ttl_ms is not None
    assert status.status in {"working", "completed"}


async def test_task_id_is_reachable_inside_the_tool_and_persisted(tmp_path):
    app = _app()
    mapping = TaskJobMap(tmp_path / "tasks.json")

    @app.tool(name="spike_probe", task=True)
    async def spike_probe() -> dict:
        info = get_task_context()
        task_id = getattr(info, "task_id", None) if info is not None else None
        if task_id:
            mapping.record(task_id, "job-for-" + task_id)
        return {"ok": True, "task_id": task_id}

    async with Client(app) as c:
        task = await call_tool_task(c, "spike_probe", {})
        result = await task.result()
    seen = result.structured_content["task_id"]
    assert seen == task.task_id
    assert TaskJobMap(tmp_path / "tasks.json").job_for(task.task_id) == "job-for-" + task.task_id


async def test_legacy_era_client_still_gets_a_plain_result():
    app = _app()
    async with Client(app, mode="legacy") as c:
        res = await c.call_tool("amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False)
    assert res.structured_content["error"]["code"] == "not_implemented"


async def test_free_tools_are_unaffected_by_the_extension():
    async with Client(_app()) as c:
        res = await c.call_tool("amicus_backends", {})
    assert res.structured_content["ok"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_taskmap.py tests/test_tasks_spike.py -v --no-cov`
Expected: `ImportError` for `amicus.jobs.taskmap`.

- [ ] **Step 3: Write the modules**

`src/amicus/jobs/__init__.py`: `"""Job lifecycle (M2) and the task↔job map (M0 spike)."""`

`src/amicus/orchestration/__init__.py`: `"""The one run loop (M1)."""` (exists so the import-linter contract can name it).

`src/amicus/jobs/taskmap.py`:

```python
"""A persisted task_id -> job_id map, written atomically (ADR 0004)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class TaskJobMap:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def entries(self) -> dict[str, str]:
        return self._read()

    def job_for(self, task_id: str) -> str | None:
        return self._read().get(task_id)

    def task_for(self, job_id: str) -> str | None:
        for task_id, job in self._read().items():
            if job == job_id:
                return task_id
        return None

    def record(self, task_id: str, job_id: str) -> None:
        data = self._read()
        data[task_id] = job_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, sort_keys=True)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
```

- [ ] **Step 4: Run the tests and read the spike findings**

Run: `uv run pytest tests/test_taskmap.py tests/test_tasks_spike.py -v --no-cov -s`
Expected: `test_taskmap.py` PASSES. For the spike, each assertion is a MEASUREMENT: where one fails, that is a finding, not a defect in this plan — change the assertion to pin the observed behaviour (e.g. `assert result.is_error is False  # finding: the flip does not survive`) and record it in Step 5. Do not weaken `test_task_id_is_reachable_inside_the_tool_and_persisted` without recording how the id IS reachable (`get_task_context()` fields; print `info` with `-s` to see them).

- [ ] **Step 5: Record the spike report in ADR 0004**

Replace the line `Filled in by Task 16 of the M0 plan.` in `docs/adr/0004-tasks-and-jobs.md` with the measured facts, one sentence per line, covering exactly these points (fill each from the test run, no guesses):

```markdown
- Extension: `fastmcp-tasks` 4.0.0 (`fastmcp[tasks]`), Docket backend `memory://`, no Redis needed in-process; it pulls `pydocket` and `cryptography`.
- Registration: `app.add_extension(TasksExtension(url=...))` before any `task=True` tool; a `task=True` tool without the extension raises at registration.
- Advertisement: `server/discover` lists `io.modelcontextprotocol/tasks`; the UI-extension filter leaves it intact.
- Delivery: a task-augmented `amicus_consult` delivers the same envelope as the plain call; `isError` on the delivered result is <true|false as observed>.
- Task id: reachable inside the tool via `fastmcp_tasks.context.get_task_context()` (<field name as observed>); persisted through `TaskJobMap` at task creation.
- TTL: `create_result.ttl_ms` observed = <value>; the 60 s default must be raised to at least the job deadline in M5.
- Legacy era: a `mode="legacy"` client calling a `task=True` tool gets <a plain result | an error> (observed).
- Cancellation, keyed replay, and `amicus_job_list(task_id=...)` are M2/M5 work; M0 only proves the seam.
```

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add src/amicus/jobs src/amicus/orchestration tests/test_taskmap.py tests/test_tasks_spike.py docs/adr/0004-tasks-and-jobs.md
git commit -m "feat(tasks): add the task-to-job map and record the tasks-extension spike

The real fastmcp[tasks] extension runs in-process against the server
with the memory:// backend; a task-augmented paid call delivers the same
envelope, the task id is reachable inside the tool and persisted via
TaskJobMap, and the findings (TTL, isError propagation, legacy-era
behaviour) are recorded in ADR 0004."
```

---

### Task 17: Import contracts, the full gate, perturbation checks, draft PR

**Files:**
- Create: `tests/test_import_contracts.py`

- [ ] **Step 1: Write the import-contract test**

```python
"""The import rules from the spec, enforced by import-linter inside the gate."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_import_linter_contracts_hold():
    exe = shutil.which("lint-imports")
    assert exe, "import-linter is a dev dependency; run under `uv run`"
    proc = subprocess.run([exe], cwd=ROOT, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Contracts: 2 kept, 0 broken" in proc.stdout
```

Run: `uv run pytest tests/test_import_contracts.py -v --no-cov`
Expected: PASS. If import-linter reports a contract naming a module that does not exist, that module's package is missing its `__init__.py` (Task 16 created `orchestration` and `jobs`).

Perturbation: add `from amicus import server  # noqa: F401` to `src/amicus/backends/__init__.py`, rerun; expected FAIL naming the broken contract. Revert.

```bash
git add tests/test_import_contracts.py
git commit -m "test(packaging): enforce the import rules with import-linter"
```

- [ ] **Step 2: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && uv run prek run --all-files`
Expected: every step clean; pytest reports total branch coverage ≥ 95%. Record the coverage percentage and the test count for the PR body.

- [ ] **Step 3: Perturbation checks (negative-result rule)**

1. Manifest: append ` probe` to `_DRY_RUN_DESC` in `src/amicus/tools/dry_run.py`; run `uv run pytest tests/test_manifest.py tests/test_fingerprint.py -q --no-cov`; expected: `test_manifest_matches_golden[*]` and `test_surface_digest_is_pinned[*]` FAIL for every profile. Revert with `git checkout -- src/amicus/tools/dry_run.py`.
2. Parameter matrix: add `extra: str | None = None` to `amicus_delegate`'s signature; run `uv run pytest tests/test_paid_tools.py -q --no-cov -k matrix`; expected: FAIL naming `amicus_delegate`. Revert.
3. Discovery cost: done in Task 15 Step 3.
4. Import contracts: done in Step 1.

Re-run the full gate after the reverts; expected: green.

- [ ] **Step 4: Push and open the draft PR**

Run: `git remote -v`

If a remote exists:

```bash
git push -u origin feat/m0-scaffold
gh pr create --draft --title "feat: M0 scaffold, schema-only surface, plugin seam, tasks spike" --body-file /private/tmp/claude-501/-Users-bdc-projects-amicus/fea72b63-6ec0-453a-98c1-c1464d373167/scratchpad/m0-pr-body.md
```

If no remote exists (the GitHub repository has not been created), STOP after writing the PR body to the scratchpad path above and report that the human must create `briandconnelly/amicus` and push; do not create the repository.

PR body (write it to the path above, filling every angle-bracket placeholder from the measured outputs):

```markdown
## Summary

Milestone M0 of amicus (spec: `docs/superpowers/specs/2026-09-04-amicus-design.md`; plan: `docs/superpowers/plans/2026-09-04-amicus-M0-scaffold-and-surface.md`).

- Repository scaffold: tooling copied from codex-in-claude, vendored dev skills, ADRs 0001–0006 (0003/0004 proposed).
- `schemas/`: closed code catalog derived from pontonier, envelope + Meta, result models and published schemas, the verb × backend parameter matrix, the closed `backend_options` object, field policy.
- `plugin.py`, `registry.py` (never raises; in-tree ids reserved; entry-point loading proven with a FakePlugin), `config/` with the legacy env shim, `errors.py` with backend-aware repair precedence, the four middlewares, `server.create_app`.
- All 18 tools registered schema-only in a fixed order with real pre-spend validation; 4 static resources + 2 templates with completion; capability suppression on both eras.
- Manifest snapshot + pinned hash + surface digest per profile; discovery-cost ratchet per profile; tasks-extension spike recorded in ADR 0004.

## Verification

- Gate: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && uv run prek run --all-files` — passed; <N> tests, coverage <X>% (branch).
- tools/list measured: all <bytes>, codex-kimi <bytes>, claude <bytes>; budgets set to the next 1,000 above each.
- `ttlMs`/`cacheScope` pinned at the SDK default (0 / private) in every profile's manifest (ADR 0006).
- Perturbation checks: manifest snapshot and surface digest fail on a description change (all profiles); the parameter-matrix test fails on an added parameter; the discovery-cost ratchet fails on a lowered budget; import-linter fails on a backends→server import. All reverted, gate green.
- Tasks spike: see `docs/adr/0004-tasks-and-jobs.md`.

## Out of scope (separate PRs per the execution model)

- `.github/workflows/**`, `CODEOWNERS`, `AGENTS.md`/`CLAUDE.md`.
- Trademark clearance before any PyPI publish.

🤖 Generated with Claude Code
```

- [ ] **Step 5: Stop**

Do not merge, approve, tag, or release. The human reviews and merges.

---

## Self-review (writing-plans checklist)

- **Spec coverage (M0 row):** scaffold with copied tooling → Task 1; ADR skeleton, vendored skills, spec copy (already at `docs/superpowers/specs/` in this repo) → Task 2; `plugin.py`, `registry.py` → Task 9; `schemas/` incl. the parameter matrix (Task 6) and closed `BackendOptions` (Task 7), codes/fingerprint (3), envelope (4), results (5); `errors.py` → Task 10; `middleware.py`, `server.create_app` → Task 11; `config/` → Task 8; discovery tools + resources → Task 13; `FakePlugin` via the entry-point path → Task 9; all 18 tools schema-only → Tasks 12–13; tasks spike with real `fastmcp[tasks]` and the persisted task-id → job-id mapping → Task 16. Gate items: manifest snapshot + digest → Task 14; discovery cost measured per profile with ratchet → Task 15; tasks spike report → Task 16 Step 5; `ttlMs`/`cacheScope` pinned → Task 14 (`test_modern_result_envelopes_are_pinned_at_the_sdk_default`) and ADR 0006.
- **Deliberate deviations from the spec text, to be surfaced in the PR:** (1) `surface_digest` is a sha256 over the server-side tool/resource/template records plus instructions, not over the full manifest, because the full manifest needs an in-memory client that cannot safely be opened from inside a tool call of the same app; the full manifest hash is pinned in tests beside it. (2) `wire_shape_snapshot.py` and `result_format_snapshot.py` are deferred to M2, where the delivery chokepoint and persisted results they guard exist. (3) The `capabilities-result` schema is reachable via `amicus_capabilities(include_schemas=[...])`, not a seventh resource, keeping the spec's six resources. (4) Result-side `backend` fields are an open lowercase identifier (third-party plugin ids), while the `backend` parameter is the v1 enum.
- **Placeholder scan:** the only angle-bracket placeholders are in Task 16 Step 5 (spike findings) and Task 17 Step 4 (PR body), both filled from measured output by instruction; `EXPECTED_MANIFEST_HASH`/`EXPECTED_SURFACE_DIGEST`/`MEASURED` start empty/zero and are pinned from printed values in Tasks 14–15 (TDD: the pin test fails until pinned).
- **Type consistency:** `BackendRef` (Task 4) is used by every result `backend`/`id` field (Task 5) and by `Meta`; `option_violations`/`resolved_options` (Task 7) are consumed by `_resolve.resolve_paid_call` (Task 12) and `discovery._options_for` (Task 13); `expected_params`/`expected_required`/`TOOL_VERB` (Task 6) drive `tests/test_paid_tools.py` (12) and `discovery._params_for` (13); `BackendRegistry.get`/`.unavailable_for`/`.unavailable` (Task 9) are read by `_resolve` and `discovery`; `AppState.config_errors`/`.tasks_active` (Task 11) are read by `discovery.register`/`resources.register_resources` (13); `annotations_for` kinds match between `_meta` (11) and every tool module (12–13); `error_envelope`/`make_error`/`render_failure` (10) signatures match their call sites in `_guard`, `_resolve`, `middleware`, `jobs`, `discovery`.
