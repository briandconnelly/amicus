# amicus M6 Implementation Plan: packaging, docs, evals and the review walk

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make amicus installable and migratable — both host manifests with `env_vars` generated from the declarations, a router skill and per-verb commands, a test-asserted `docs/MIGRATION.md`, a third-party backend proven to load from a real wheel, install smoke captured from both hosts, and the agent-friendly-mcp review walk answered with real cold-start and first-repair probe evidence.

**Architecture:** No new runtime subsystem.
Everything either generates from an existing declaration (`.mcp.json` `env_vars` and the `MIGRATION.md` env table both derive from `config/envspec.py`, and a test asserts the committed file equals the generated one) or exercises an existing seam from outside for the first time (the `amicus.backends` entry-point group, which `registry.py` has always read but which no out-of-tree distribution has ever populated).
The host-facing surface — skill, commands, manifests — is new content, not new code paths.
The review walk runs last and is expected to produce a fix wave; if that wave changes any tool description, it moves the fingerprint, and the plan budgets for that.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `prek`.
Runtime unchanged: `fastmcp>=4.0,<4.1`, `mcp>=2.1,<2.2`, `pontonier==0.9.0`, `pydantic>=2`, `anyio>=4`.
Build backend `hatchling`.
This plan adds no runtime dependency.
Hosts: Claude Code and Codex CLI on the maintainer's machine (versions recorded at capture time, not assumed — M5 found the two hosts negotiate different protocol eras).

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — "Milestones" row M6 (scope: packaging, docs, eval fixtures, migration doc, annotation-friction capture; gate: install smoke from both manifests, FakePlugin as a wheel, agent-friendly-mcp review walk); "Config" (`.mcp.json` `env_vars` generated from declarations plus vendor auth variables; `docs/MIGRATION.md` asserted equal to declarations by a test; `${VAR}` placeholder check kept); "Testing architecture" (`FakePlugin` via a test-only entry point; eval fixtures in `skills/collaborating-with-amicus/tests/`).
ADR 0001 (annotations follow the worst enabled backend — the friction this milestone captures), ADR 0002 (closed `BackendOptions`), ADR 0006 (fingerprint and surface digest).
Checklist the walk is run against: `.agents/skills/agent-friendly-mcp/` — `references/review-workflow.md` is the binding protocol, `references/contract-checklist.md` holds the rule ids.
Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`; binding repo rules: `AGENTS.md`.

## Global Constraints

- Repo: `/Users/bdc/projects/amicus`.
  Work on branch `feat/m6-packaging` in the sibling git worktree `/Users/bdc/projects/amicus-wt-m6` (created from `main` at `de5c582`; baseline 976 tests green, 96.97% branch coverage, `FINGERPRINT = "amicus/0.1/schema-6"`, `RESULT_FORMAT = 2`).
  Never commit to `main`.
- Dependencies exactly as `pyproject.toml` has them; this plan adds none.
  `uv build` is invoked from the existing `hatchling` config; no new build tooling.
- Gate (AGENTS.md rule 2): `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest` at ≥95% branch coverage.
  Coverage floor never lowered.
- Tool surface starts and is expected to end at 18 tools, 6 resources, no prompts.
  Tasks 0–9 MUST NOT move the surface: no tool gains, loses or renames a parameter, and no tool description text changes.
  Task 10's fix wave MAY move it — that is the one place a surface change is permitted, and if it happens `FINGERPRINT` moves `amicus/0.1/schema-6` → `amicus/0.1/schema-7` and every pin is regenerated in its own commit (rule 10).
  `RESULT_FORMAT` stays `2`: no stored job result changes shape in this milestone (rule 11 does not fire).
- The plugin manifests are NOT part of `FINGERPRINT_COVERS`.
  A manifest version bump must never invalidate a stored job result.
  They get their own snapshot test instead (Task 2), so they cannot drift from the declarations silently.
- Prompt inputs (`question`, `task`, `extra_context`, `instructions_append`, `focus`, `target`, `evidence`) never land on disk, on a worker's argv or in a log (rule 18).
  Rule 18 prohibits WRITING them, not merely committing them, so post-hoc elision is too late:
  by then the value has already been on disk in a scratch file or a host transcript.
  Tasks 8 and 9 therefore capture to an **allowlist** from the first keystroke — tool name,
  protocol facts, selected backend, `ok`/`error.code`, and the assertion verdict.
  Raw host output and prompt text are read transiently and never saved; what is written is a
  scrubbed summary composed by hand.
  The probe prompts themselves are fixed, non-sensitive strings authored in the plan, so the
  scenario file may quote those; nothing typed during a live session is transcribed verbatim.
- Spend: Task 8 spends **one paid consult per enabled backend per host — six calls total**
  (codex, kimi, claude × Claude Code, Codex CLI), authorized by the maintainer in the
  2026-09-07 planning session after the Codex review showed three could not cover both hosts.
  No other task spends.
  The `-m integration` live gates stay unrun (rule 5); do not run them without an in-session ask.
  `tests/conftest.py`'s guard making the real backend binaries unreachable is never weakened (rule 6).
- Commit messages: Conventional Commits `type(scope): subject`; scopes from `scripts/check_commit_message.py`.
  Task 0 adds the `skills` scope (rule 13); until it lands, no commit may use it.
  Imperative lowercase subject, no trailing period.
  End every commit body with the attribution trailer given in the session.
- Markdown under `docs/`: one sentence per line (rule 16).
  Every task that authors a file under `docs/` ends with this check on the files IT created,
  before its commit:
  ```sh
  uv run python - <<'EOF'
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
  EOF
  ```
  Scoped to files the milestone creates; existing plans are not retrofitted here.
  This applies to `docs/MIGRATION.md` and every capture note.
  It does NOT apply to `skills/` or `commands/`, which are outside `docs/`.
- Off limits (rules 9, 17): `.github/**`, `AGENTS.md`, `CLAUDE.md`; any sibling checkout (read-only for porting); releasing; merging or approving the PR.
  **The publish workflow is written in Task 10 but committed on a separate branch and shipped as its own PR** — it must never appear in a commit on `feat/m6-packaging`.

## Decisions made here (surface in ADR 0012 and the PR body)

The maintainer approved decisions 1–5 in the planning session (2026-09-07); 6–10 are the planner's rulings on questions the spec leaves open.

1. **Packaging goes as far as release automation, unpublished — but the workflow is a separate plan.**
   Manifests, wheel and install smoke land here.
   The publish workflow and its TestPyPI dry run are `docs/superpowers/plans/2026-09-07-amicus-publish-workflow.md`, executed after M6 merges, because the execution model's rules 5 and 6 forbid a milestone plan producing a second PR or touching `.github/workflows/**`.
   No PyPI publish in either; the trademark clearance the README names is still open and is maintainer-only.
2. **Commands are per-verb with the backend as an argument.** `/amicus:consult`, not `/amicus:codex:consult`.
   The tool surface's whole premise is the backend being a parameter; the command surface says the same thing and stays fixed-size as backends are added.
3. **Eval fixtures are a scenario file plus a harness protocol, with a subset hand-run.** Ported from the sibling's `scenarios.md` format.
   Scenarios that are specified but not executed are marked unrun in the file — never quietly counted as passing.
4. **`docs/MIGRATION.md` carries three things per sibling:** the env-var mapping (generated, test-asserted), the tool-name map, and the behavior deltas a migrating user actually hits.
5. **The cold-start and first-repair probes are captured from the real host installs in Task 8**, not simulated.
   `review-workflow.md:31` permits simulated evidence; the maintainer chose captured.
6. **The cold-start probe and the authorized paid consult are the same event.**
   A fresh host context meeting the installed server, asked a natural-language task, choosing a tool and calling it, is simultaneously the install smoke and the cold-start evidence.
   The budget is six calls: one per backend per host.
   A cold-start probe measures a specific host's agent, so the two hosts cannot share calls.
   Each run enables exactly one backend via `AMICUS_BACKENDS`, which is what makes the routing assertion gradable.
7. **Task 2's manifest smoke is a hard precondition for Task 8.**
   Task 8 is the only task that cannot be cheaply re-run.
   The precondition is the subprocess smoke of the manifest's own command line (Task 2 Step 8), NOT the in-process boot check (Step 7) — an in-process `create_app()` reads no manifest and so cannot fail for a bad command, a missing console script or malformed JSON.
   Both must pass, plus the full gate at Task 7 Step 7, before a paid call is made.
8. **The annotation-friction capture is a probe inside Task 8, not a separate exercise.** ADR 0001's consequence (Claude enabled ⇒ codex-only calls carry mutation-grade annotations) is observable as host approval behavior in the same session that runs the other probes.
9. **The wheel fixture lives in `tests/fixtures/fakebackend/` and is built at test time**, not committed as a `.whl`.
   A committed binary would rot against the `hatchling` config and could not prove the current build path works.
10. **The wheel test asserts a negative control.** A wrong `api_version` in the installed wheel must produce `UnavailableBackend(reason="api_version")`.
    Without it, an entry-point group that silently scanned nothing would look exactly like success.

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `src/amicus/packaging.py` | Pure functions deriving the `env_vars` list and the migration env table from the declared namespaces. No I/O; the single source both the manifest and the doc are generated from. |
| `.mcp.json` | The one MCP server definition both host manifests point at. Generated, test-asserted. |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Claude Code install path. |
| `.codex-plugin/plugin.json` | Codex install path. |
| `skills/collaborating-with-amicus/SKILL.md` + `references/` | The router skill. |
| `skills/collaborating-with-amicus/tests/scenarios.md` | Eval fixtures: scenarios, harness protocol, recorded baselines, run/unrun status. |
| `commands/amicus/*.md` | Seven per-verb slash commands. |
| `docs/MIGRATION.md` | Migration from all three siblings. |
| `tests/fixtures/fakebackend/` | A minimal standalone distribution declaring an `amicus.backends` entry point. |
| `tests/test_packaging.py` | Generation equality, manifest snapshot, `${VAR}` placeholder check. |
| `tests/test_wheel_seam.py` | Out-of-tree entry-point loading, positive and negative control. |
| `tests/test_migration_doc.py` | `MIGRATION.md` env table equals the declarations. |
| `docs/adr/0012-m6-packaging-decisions.md` | The decisions above. |
| `docs/host-captures/install-smoke/` | Task 8 evidence. |
| `docs/reviews/2026-09-XX-agent-friendly-mcp-walk.md` | Task 10 findings, probes, inapplicability reasons. |

**Modified:** `scripts/check_commit_message.py` (add `skills` scope), `README.md` (the "Where things are" table), `pyproject.toml` (only if the wheel fixture needs an exclusion so `hatchling` does not ship test fixtures).

---

### Task 0: The `skills` commit scope

**Files:**
- Modify: `scripts/check_commit_message.py:38-58`
- Test: `tests/test_check_commit_message.py`

**Interfaces:**
- Produces: `ALLOWED_SCOPES` containing `"skills"`, so every later task may use `feat(skills):`.

Rule 13 requires the checker to be extended in the same change that needs the new scope; this task exists so that change is not smuggled into a content commit.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_check_commit_message.py`:

```python
def test_skills_scope_is_allowed():
    from scripts.check_commit_message import ALLOWED_SCOPES

    assert "skills" in ALLOWED_SCOPES
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_check_commit_message.py::test_skills_scope_is_allowed -v`
Expected: FAIL, `AssertionError`.

- [ ] **Step 3: Add the scope**

In `scripts/check_commit_message.py`, add `"skills",` to `ALLOWED_SCOPES` immediately after `"resources",` (the surface-adjacent group), keeping the tuple's existing ordering logic.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/test_check_commit_message.py -v`
Expected: PASS, and the pre-existing scope tests still pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_commit_message.py tests/test_check_commit_message.py
git commit -m "chore(ci): allow the skills commit scope"
```

---

### Task 1: Generate `env_vars` from the declarations

**Files:**
- Create: `src/amicus/packaging.py`
- Create: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `amicus.config.GLOBAL_ENV` (`EnvNamespace`, 16 vars); each backend's `ENV` namespace via `amicus.registry`; `amicus.backends.claude.contract.LOGIN_CREDENTIAL_ENV_VARS`.
- Produces:
  - `declared_env_names() -> tuple[str, ...]` — every `AMICUS_*` name across the global namespace and all in-tree backends, sorted.
  - `vendor_auth_env_names() -> tuple[str, ...]` — vendor credential names contributed by backends, sorted.
  - `env_vars_list() -> list[str]` — the two above concatenated, sorted, deduplicated.
    This is exactly what `.mcp.json` `env_vars` must contain.

The generator reads `LOGIN_CREDENTIAL_ENV_VARS` off each backend's contract module **defensively** — codex and kimi do not define it (they rely on their CLI's own login), so absence is normal and must not raise.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_packaging.py`:

```python
"""env_vars and the migration table are generated from the declarations, never typed by hand."""

from __future__ import annotations

from amicus import packaging
from amicus.config import GLOBAL_ENV


def test_declared_names_cover_the_global_namespace():
    names = packaging.declared_env_names()
    for name in GLOBAL_ENV.names():
        assert name in names


def test_declared_names_cover_every_in_tree_backend():
    names = packaging.declared_env_names()
    for expected in ("AMICUS_CODEX_BIN", "AMICUS_KIMI_BIN", "AMICUS_CLAUDE_BIN"):
        assert expected in names


def test_declared_names_are_sorted_and_unique():
    names = packaging.declared_env_names()
    assert list(names) == sorted(set(names))


def test_vendor_auth_includes_the_claude_credentials():
    assert packaging.vendor_auth_env_names() == ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


EXPECTED_ENV_VARS = [
    # Pinned by review, not derived: comparing a generated file to its own generator is not an
    # oracle. This list is the independent expectation; the generator must reproduce it exactly.
    # 35 declared (16 global + 6 codex + 6 kimi + 7 claude) + 2 vendor = 37.
    "AMICUS_ALLOW_CWD_WORKSPACE", "AMICUS_BACKENDS", "AMICUS_CLAUDE_ACCESS", "AMICUS_CLAUDE_BIN",
    "AMICUS_CLAUDE_CONFIG_MODE", "AMICUS_CLAUDE_MAX_BUDGET_USD", "AMICUS_CLAUDE_MODEL",
    "AMICUS_CLAUDE_REASONING_EFFORT", "AMICUS_CLAUDE_SUPPORTED_MAJORS", "AMICUS_CODEX_BIN",
    "AMICUS_CODEX_EXTRA_ARGS", "AMICUS_CODEX_ISOLATION", "AMICUS_CODEX_MODEL",
    "AMICUS_CODEX_REASONING_EFFORT", "AMICUS_CODEX_SUPPORTED_VERSIONS", "AMICUS_GIT_TIMEOUT_SECONDS",
    "AMICUS_HOST_NAME", "AMICUS_JOB_MAX_COUNT", "AMICUS_JOB_MAX_SECONDS", "AMICUS_JOB_TTL",
    "AMICUS_KIMI_BIN", "AMICUS_KIMI_EXTRA_ARGS", "AMICUS_KIMI_ISOLATION", "AMICUS_KIMI_MODEL",
    "AMICUS_KIMI_REASONING_EFFORT", "AMICUS_KIMI_SUPPORTED_VERSIONS", "AMICUS_LOG_FILE",
    "AMICUS_LOG_LEVEL", "AMICUS_MAX_DELEGATE_DIFF_BYTES", "AMICUS_MAX_INPUT_BYTES",
    "AMICUS_MAX_OUTPUT_BYTES", "AMICUS_STATE_DIR", "AMICUS_TASKS", "AMICUS_TASKS_BACKEND_URL",
    "AMICUS_TIMEOUT_SECONDS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
]


def test_env_vars_list_matches_the_pinned_expectation():
    """The independent oracle. If this fails, a declaration changed: review the diff and
    update the pin deliberately — never regenerate the pin from the generator."""
    assert packaging.env_vars_list() == EXPECTED_ENV_VARS


def test_env_vars_list_is_declared_plus_vendor():
    combined = set(packaging.declared_env_names()) | set(packaging.vendor_auth_env_names())
    assert set(packaging.env_vars_list()) == combined
    assert packaging.env_vars_list() == sorted(combined)


def test_declared_names_are_all_amicus_namespaced():
    """Declared names are AMICUS_*; vendor credentials are a separate, deliberate list.

    Keeping the two apart is the point: a vendor name silently entering `declared_env_names()`
    would put a credential in the migration table as if amicus declared it."""
    assert all(name.startswith("AMICUS_") for name in packaging.declared_env_names())
    assert not any(n.startswith("AMICUS_") for n in packaging.vendor_auth_env_names())
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'amicus.packaging'`.

- [ ] **Step 3: Write the module**

Create `src/amicus/packaging.py`:

```python
"""Derive packaging artifacts from the env declarations.

`.mcp.json`'s `env_vars` and `docs/MIGRATION.md`'s env table are both generated here so
neither can drift from `config/envspec.py`. Pure functions, no I/O: the tests compare a
committed file against what these return."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from amicus.config import GLOBAL_ENV
from amicus.schemas.codes import BACKEND_IDS

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config.envspec import EnvNamespace, EnvVar


def _backend_namespaces() -> list[EnvNamespace]:
    namespaces: list[EnvNamespace] = []
    for backend_id in BACKEND_IDS:
        module = importlib.import_module(f"amicus.backends.{backend_id}.config")
        namespaces.append(module.ENV)
    return namespaces


def declared_env_names() -> tuple[str, ...]:
    """Every AMICUS_* name this server reads, across the global and per-backend namespaces."""
    names = set(GLOBAL_ENV.names())
    for namespace in _backend_namespaces():
        names.update(namespace.names())
    return tuple(sorted(names))


def vendor_auth_env_names() -> tuple[str, ...]:
    """Vendor credential names a backend needs passed through.

    Read defensively: codex and kimi authenticate through their own CLI login and declare
    no credential env vars, so a missing attribute is normal, not an error."""
    names: set[str] = set()
    for backend_id in BACKEND_IDS:
        try:
            contract = importlib.import_module(f"amicus.backends.{backend_id}.contract")
        except ModuleNotFoundError:  # pragma: no cover - every in-tree backend has one
            continue
        names.update(getattr(contract, "LOGIN_CREDENTIAL_ENV_VARS", ()))
    return tuple(sorted(names))


def env_vars_list() -> list[str]:
    """The `env_vars` passthrough list for `.mcp.json`."""
    return sorted(set(declared_env_names()) | set(vendor_auth_env_names()))


def declared_vars() -> tuple[EnvVar, ...]:
    """Every declared EnvVar, global first then per backend, for the migration table."""
    collected = list(GLOBAL_ENV.vars)
    for namespace in _backend_namespaces():
        collected.extend(namespace.vars)
    return tuple(collected)
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Verify the instrument can fail**

Temporarily add `EnvVar("AMICUS_ZZZ_PROBE", "probe")` to `GLOBAL_ENV.vars`, rerun `test_declared_names_cover_the_global_namespace`, and confirm it still passes but `env_vars_list()` now contains `AMICUS_ZZZ_PROBE` — proving the generator tracks the declarations rather than a frozen copy.
Then revert the probe.

Run: `uv run python -c "from amicus import packaging; print(len(packaging.env_vars_list()))"`
Expected after revert: `37` — verified against `main` at de5c582: 35 declared
(16 global + 6 codex + 6 kimi + 7 claude) plus 2 vendor (`ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`; codex and kimi declare none).
If this number differs, a declaration changed — update the count, do not loosen the test.

- [ ] **Step 6: Commit**

```bash
git add src/amicus/packaging.py tests/test_packaging.py
git commit -m "feat(packaging): derive env_vars from the env declarations"
```

---

### Task 2: Both host manifests, with a boot check

**Files:**
- Create: `.mcp.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `packaging.env_vars_list()` from Task 1.
- Produces: `.mcp.json` at the repo root — the single server definition both plugin manifests reference.
  Task 8 installs from these files.

This task ends with **decision 7's precondition**: an in-process `fastmcp` client proves the server starts from the manifest's own command line before any host sees it.

Publish form: `.mcp.json` names `uvx --from git+https://github.com/briandconnelly/amicus.git@v0.1.0 amicus-mcp`, matching the pre-PyPI shape moonbridge and claude-in-codex use.
The install smoke in Task 8 overrides this with a local path; that override is recorded in the capture and never committed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_packaging.py`:

```python
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> dict:
    return json.loads((REPO_ROOT / relative).read_text())


def test_mcp_json_env_vars_equal_the_generated_list():
    server = _read(".mcp.json")["mcpServers"]["amicus"]
    assert server["env_vars"] == packaging.env_vars_list()


def test_mcp_json_invokes_the_console_script():
    server = _read(".mcp.json")["mcpServers"]["amicus"]
    assert server["command"] == "uvx"
    assert server["args"][-1] == "amicus-mcp"


def test_mcp_json_has_no_unexpanded_placeholders():
    """The ${VAR} check the spec keeps: env_vars is a passthrough list, not a value map."""
    raw = (REPO_ROOT / ".mcp.json").read_text()
    assert "${" not in raw


def test_both_plugin_manifests_point_at_the_one_mcp_json():
    assert _read(".claude-plugin/plugin.json")["mcpServers"] == "./.mcp.json"
    assert _read(".codex-plugin/plugin.json")["mcpServers"] == "./.mcp.json"


def test_plugin_manifest_version_matches_the_package():
    from importlib.metadata import version

    package_version = version("amicus")
    assert _read(".claude-plugin/plugin.json")["version"] == package_version
    assert _read(".codex-plugin/plugin.json")["version"] == package_version


def test_claude_manifest_declares_skills_and_commands():
    manifest = _read(".claude-plugin/plugin.json")
    assert manifest["skills"] == "./skills/"
    assert manifest["commands"] == "./commands/"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_packaging.py -v -k "mcp_json or manifest"`
Expected: FAIL, `FileNotFoundError: .mcp.json`.

- [ ] **Step 3: Write `.mcp.json`**

Generate the `env_vars` array rather than typing it:

```bash
uv run python - <<'PY'
import json, pathlib
from amicus import packaging

doc = {
    "mcpServers": {
        "amicus": {
            "command": "uvx",
            "args": [
                "--from",
                "git+https://github.com/briandconnelly/amicus.git@v0.1.0",
                "amicus-mcp",
            ],
            "env_vars": packaging.env_vars_list(),
        }
    }
}
pathlib.Path(".mcp.json").write_text(json.dumps(doc, indent=2) + "\n")
PY
```

- [ ] **Step 4: Write `.claude-plugin/plugin.json`**

```json
{
  "name": "amicus",
  "version": "0.1.0",
  "description": "One MCP server for every second-opinion model: consult, review, and delegate with the backend as a parameter.",
  "author": { "name": "Brian Connelly" },
  "homepage": "https://github.com/briandconnelly/amicus",
  "repository": "https://github.com/briandconnelly/amicus",
  "license": "MIT",
  "keywords": ["mcp", "codex", "kimi", "claude-code", "code-review", "delegation", "second-opinion"],
  "skills": "./skills/",
  "commands": "./commands/",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "amicus",
    "shortDescription": "Consult, review, and delegate to Codex, Kimi, or Claude — one server, backend as a parameter.",
    "longDescription": "amicus gives Claude Code one tool surface for every second-opinion model. Pick the backend as a parameter instead of installing a server per model. Delegation runs in a throwaway git worktree and returns a reviewable diff that is never applied to your working tree. Long jobs run asynchronously with a job id you can poll, cancel, and recover. Enabling a backend that can write makes every tool carry that backend's approval annotations — see docs/MIGRATION.md.",
    "developerName": "Brian Connelly",
    "category": "Developer Tools",
    "capabilities": ["MCP", "Skills"],
    "websiteURL": "https://github.com/briandconnelly/amicus",
    "defaultPrompt": [
      "Get a second opinion on this approach from another model.",
      "Have another model review my current changes.",
      "Delegate this task to another model and show me the proposed diff."
    ]
  }
}
```

- [ ] **Step 5: Write `.claude-plugin/marketplace.json` and `.codex-plugin/plugin.json`**

`marketplace.json` follows codex-in-claude's committed shape (read `~/projects/codex-in-claude/.claude-plugin/marketplace.json` and mirror its field set, substituting amicus's name, description and source).
`.codex-plugin/plugin.json` is the Claude manifest minus `commands` (Codex has no slash-command surface), with `displayName` `"amicus (for Codex)"`.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 7: In-process boot check (necessary, NOT sufficient)**

No async marker: `pyproject.toml` sets `asyncio_mode = "auto"`, and `addopts` carries
`--strict-markers` with only `integration` registered, so an unregistered `@pytest.mark.anyio`
would error rather than skip.
`create_app()` takes no arguments here on purpose — both parameters default to `None`
(`src/amicus/server.py:124-128`), so it resolves real settings and loads the real registry,
which is what a boot check should exercise.

Add to `tests/test_packaging.py`:

```python
from fastmcp import Client

from amicus.server import create_app


async def test_server_boots_in_process_with_no_amicus_env_set(monkeypatch):
    """A server-unit boot test: the app comes up and lists 18 tools with no AMICUS_* set.

    This does NOT test the manifest. It reads no `.mcp.json`, starts no `uvx`, and applies no
    `env_vars` list. Step 8 is the test that covers the manifest; this one only rules out an
    in-process regression first, because it is the cheaper of the two to diagnose."""
    for name in packaging.declared_env_names():
        monkeypatch.delenv(name, raising=False)
    async with Client(create_app()) as client:
        tools = await client.list_tools()
    assert len(tools) == 18
```

- [ ] **Step 8: The real manifest smoke — decision 7's actual precondition**

The in-process check above cannot fail for a bad `command`, a bad `--from`, a missing console
script, or a malformed `.mcp.json`, because it never reads the file.
This test does: it parses the committed manifest, substitutes ONLY the `--from` source with a
locally built wheel, and speaks MCP to the resulting subprocess over stdio.

Add to `tests/test_packaging.py`:

```python
import subprocess

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest.mark.slow
async def test_the_committed_manifest_command_starts_a_real_server(tmp_path):
    """Smoke the manifest's own command line, not an in-process app.

    The committed `--from` names a git tag that does not exist until release, so this
    substitutes a locally built wheel for that ONE field and asserts every other field —
    command, console script, arg order — exactly as committed. What stays unproven until
    release is the tag's resolvability; that is the release workflow's gate, and Task 10's
    ADR records it as a known limit of the M6 claim."""
    server = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["amicus"]
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(REPO_ROOT)],
                   check=True, capture_output=True)
    wheel = next(tmp_path.glob("*.whl"))
    args = [str(wheel) if a.startswith("git+") else a for a in server["args"]]
    assert args[-1] == "amicus-mcp", "the console script name must survive substitution"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    transport = StdioTransport(command=server["command"], args=args, env=env)
    async with Client(transport) as client:
        tools = await client.list_tools()
    assert len(tools) == 18
```

Confirm the transport class and its keyword names against the installed FastMCP before
writing this — `uv run python -c "from fastmcp.client.transports import StdioTransport;
help(StdioTransport.__init__)"` — and use whatever the installed version actually exposes.

Run: `uv run pytest tests/test_packaging.py -v -k manifest_command`
Expected: PASS.

Then confirm it can fail: change `.mcp.json`'s `args` last element to `amicus-mcpp`, rerun, see
it FAIL at startup, and restore.
A manifest smoke that passes against a wrong console-script name is not a smoke.

**If this test does not pass on the current commit, Task 8 does not start.**

- [ ] **Step 9: Full gate, then commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`

```bash
git add .mcp.json .claude-plugin/ .codex-plugin/ tests/test_packaging.py
git commit -m "feat(packaging): add both host manifests with generated env_vars"
```

---

### Task 3: The `collaborating-with-amicus` router skill

**Files:**
- Create: `skills/collaborating-with-amicus/SKILL.md`
- Create: `skills/collaborating-with-amicus/references/choosing-a-backend.md`
- Create: `skills/collaborating-with-amicus/references/sync-vs-async.md`
- Create: `skills/collaborating-with-amicus/references/reviewing-a-returned-diff.md`

**Interfaces:**
- Produces: the skill directory `.claude-plugin/plugin.json` already points at, and the treatment text Task 5's scenarios measure.

Read `~/projects/codex-in-claude/skills/collaborating-with-codex/SKILL.md` for the house voice before writing (read-only; rule 17).
The router's job is different from the sibling's: the sibling routes between *verbs* for one model, amicus must also route between *backends*.

The skill's binding rules — apply `separating-context-from-constraints` (vendored in `.agents/skills/`) while writing, since this document is instructions an agent consumes:

1. Pick the backend from the task, not from habit; `amicus_backends` says which are enabled and authenticated.
2. Use `_async` when the work can exceed the sync deadline; a sync call that times out has still spent the quota.
3. Never call a paid tool to find out whether a backend is available — `amicus_backends` and `amicus_dry_run` are free.
4. A returned diff is never applied; review it before applying.
5. Prompt inputs travel over stdin — never paste a secret into `question`, `task`, or `extra_context`.

- [ ] **Step 1: Write `SKILL.md` with frontmatter**

```markdown
---
name: collaborating-with-amicus
description: Use whenever this agent should call another model through amicus — a second opinion, a code review, an adversarial review, or a delegated implementation. Trigger on "ask another model", "get a second opinion", "have Codex/Kimi/Claude review this", "delegate this", and at decision points: choosing a hard-to-reverse approach, after two failed fixes, before declaring risky work complete.
---
```

Then the rules above as a Rules section, followed by a Context section explaining the backend-as-parameter model, the free-vs-paid split, and the job lifecycle.
Rules bind; context explains — the same split `AGENTS.md` uses.

- [ ] **Step 2: Write the three reference files**

- `choosing-a-backend.md` — what each backend is good at, what `amicus_backends` reports, and the honest statement that the choice is a judgment call.
- `sync-vs-async.md` — the deadline, what `_async` returns, how to poll, and that a task-augmented call maps to a job recoverable via `amicus_job_list(task_id=...)`.
- `reviewing-a-returned-diff.md` — `amicus_delegate` returns a diff in a throwaway worktree; it is never applied; how to read and apply it.

- [ ] **Step 3: Self-review with the vendored skill**

Run the `separating-context-from-constraints` checklist over `SKILL.md`: every binding rule testable, no hedged "generally/try to", no rule buried in narrative.
Fix findings inline.

- [ ] **Step 4: Verify the skill is well-formed**

Run: `uv run python -c "
import pathlib, re
text = pathlib.Path('skills/collaborating-with-amicus/SKILL.md').read_text()
assert text.startswith('---'), 'missing frontmatter'
front = text.split('---')[1]
assert re.search(r'^name: collaborating-with-amicus$', front, re.M)
assert re.search(r'^description: ', front, re.M)
print('ok')
"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add skills/collaborating-with-amicus/
git commit -m "feat(skills): add the collaborating-with-amicus router skill"
```

---

### Task 4: Per-verb slash commands

**Files:**
- Create: `commands/amicus/consult.md`, `review.md`, `delegate.md`, `adversarial.md`, `dry-run.md`, `status.md`, `jobs.md`

**Interfaces:**
- Consumes: the tool names in `amicus.tools.TOOL_ORDER`.
- Produces: the `commands/` directory `.claude-plugin/plugin.json` points at.

Each command takes the backend as a **required** argument (decision 2, corrected).
`backend: BackendParam` has no default on any tool (`src/amicus/tools/consult.py:64-65`), and
`AMICUS_BACKENDS` selects which backends are *enabled*, not a default one.
A command that implies a default would teach an invalid first call — the exact failure the
cold-start probe measures.
When the user does not name a backend, the command directs the agent to `amicus_backends` to choose.
Read `~/projects/codex-in-claude/commands/codex/consult.md` for the house format first.

The mapping, so no command invents a tool that does not exist:

| Command | Tool |
| --- | --- |
| `consult.md` | `amicus_consult` / `amicus_consult_async` |
| `review.md` | `amicus_review_changes` / `amicus_review_changes_async` |
| `delegate.md` | `amicus_delegate` / `amicus_delegate_async` |
| `adversarial.md` | `amicus_adversarial_review` / `amicus_adversarial_review_async` |
| `dry-run.md` | `amicus_dry_run`, `amicus_delegate_dry_run` |
| `status.md` | `amicus_backends`, `amicus_capabilities`, `amicus_models` |
| `jobs.md` | `amicus_job_list`, `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_cancel` |

- [ ] **Step 1: Write the failing test**

Add `tests/test_commands.py`:

```python
"""Every command file names only tools that exist, and every paid verb has a command."""

from __future__ import annotations

import re
from pathlib import Path

from amicus.tools import TOOL_ORDER

COMMANDS = Path(__file__).resolve().parents[1] / "commands" / "amicus"


def test_every_referenced_tool_exists():
    referenced = set()
    for path in COMMANDS.glob("*.md"):
        referenced.update(re.findall(r"\bamicus_[a-z_]+\b", path.read_text()))
    unknown = referenced - set(TOOL_ORDER)
    assert not unknown, f"commands name tools that do not exist: {sorted(unknown)}"


def test_every_tool_is_reachable_from_some_command():
    referenced = set()
    for path in COMMANDS.glob("*.md"):
        referenced.update(re.findall(r"\bamicus_[a-z_]+\b", path.read_text()))
    assert set(TOOL_ORDER) - referenced == set()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_commands.py -v`
Expected: FAIL — the directory does not exist, so `referenced` is empty and the second test reports all 18 tools missing.

- [ ] **Step 3: Write the seven command files**

Each with frontmatter (`description`, `argument-hint`) and a body that names its tools, states the backend argument, and says what the command does *not* do (delegate does not apply the diff).

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/test_commands.py -v`
Expected: PASS, 2 tests.
The second test is the one that catches a forgotten verb — confirm it fails if you delete `jobs.md`, then restore it.

- [ ] **Step 5: Commit**

```bash
git add commands/ tests/test_commands.py
git commit -m "feat(skills): add per-verb slash commands with the backend as an argument"
```

---

### Task 5: Eval fixtures — scenarios and harness protocol

**Files:**
- Create: `skills/collaborating-with-amicus/tests/scenarios.md`

**Interfaces:**
- Produces: the scenario ids and harness protocol Task 8's probes and Task 9's hand-run subset both record against.
  The cold-start and first-repair probes live here (decision 5) so there is one evidence format, not two.

Read `~/projects/codex-in-claude/skills/collaborating-with-codex/tests/scenarios.md` for the format: reproducible baseline by git blob, harness protocol, per-scenario assertions.

- [ ] **Step 1: Write the file skeleton with the harness protocol**

Sections: **Reproducible baseline** (this is a new skill, so the baseline is "no skill installed" — state that explicitly rather than citing a blob that does not exist), **Harness protocol** (record prompt, model, harness version, full answer, assertion evidence for every run), **Scenarios**, **Run log**.

- [ ] **Step 2: Write the scenarios**

At minimum these, each with a prompt, an assertion, and a `status:` field of `unrun` until executed:

| Id | Tests | Assertion |
| --- | --- | --- |
| S1 | Cold start | A fresh agent with no amicus history reaches a valid first call for "get a second opinion on this design". |
| S2 | First repair | Given a deliberately invalid call, the returned `repair` object gets the agent to a valid retry without guessing. |
| S3 | Backend routing | "Have Codex review this" reaches `amicus_review_changes` with `backend="codex"`, not a consult. |
| S4 | Sync vs async | A task described as long-running reaches an `_async` twin, not the sync tool. |
| S5 | Don't-spend | "Is Kimi available?" reaches `amicus_backends`, never a paid consult. |
| S6 | Diff safety | After `amicus_delegate` returns, the agent reviews the diff and does not claim it was applied. |
| S7 | Annotation friction | With Claude enabled, a codex-only call surfaces the mutation-grade approval; the agent explains rather than retrying blindly. |

- [ ] **Step 3: Mark honestly**

Every scenario starts `status: unrun`.
Nothing is marked `pass` in this task — Tasks 8 and 9 do that, and only for runs actually executed (decision 3).

- [ ] **Step 4: Verify the file's own claims**

Run: `uv run python -c "
import pathlib
text = pathlib.Path('skills/collaborating-with-amicus/tests/scenarios.md').read_text()
ids = [l for l in text.splitlines() if l.startswith('### S')]
assert len(ids) >= 7, ids
assert text.count('status:') == len(ids), 'every scenario needs a status'
assert 'status: pass' not in text, 'nothing may be marked pass before it is run'
print('ok', len(ids))
"`
Expected: `ok 7`.

- [ ] **Step 5: Commit**

```bash
git add skills/collaborating-with-amicus/tests/scenarios.md
git commit -m "test(skills): specify the amicus routing eval scenarios"
```

---

### Task 6: `docs/MIGRATION.md`

**Files:**
- Create: `docs/MIGRATION.md`
- Create: `tests/test_migration_doc.py`

**Interfaces:**
- Consumes: `packaging.declared_vars()` from Task 1; `EnvVar.legacy` tuples, which already carry the sibling prefixes (`CODEX_IN_CLAUDE_`, `MOONBRIDGE_`, `CLAUDE_IN_CODEX_`); `LEGACY_REMOVAL_VERSION = "0.3.0"`.
- Produces: the migration doc the README links and M7's deprecation depends on.

Three sections per decision 4. One sentence per line (rule 16).

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_doc.py`:

```python
"""The migration doc's env table is asserted equal to the declarations (spec: Config)."""

from __future__ import annotations

import re
from pathlib import Path

from amicus import packaging
from amicus.config.envspec import LEGACY_REMOVAL_VERSION

DOC = Path(__file__).resolve().parents[1] / "docs" / "MIGRATION.md"


def _table_rows() -> dict[str, set[str]]:
    """Parse the env table: amicus name -> the legacy names it lists."""
    rows: dict[str, set[str]] = {}
    for line in DOC.read_text().splitlines():
        match = re.match(r"^\|\s*`(AMICUS_[A-Z0-9_]+)`\s*\|([^|]*)\|", line)
        if match:
            legacy = set(re.findall(r"`([A-Z0-9_]+)`", match.group(2)))
            rows[match.group(1)] = legacy
    return rows


def test_every_declared_var_appears_in_the_table():
    rows = _table_rows()
    for var in packaging.declared_vars():
        assert var.name in rows, f"{var.name} is declared but missing from MIGRATION.md"


def test_no_invented_vars_in_the_table():
    declared = {v.name for v in packaging.declared_vars()}
    assert set(_table_rows()) <= declared


def test_legacy_names_match_the_declarations_exactly():
    rows = _table_rows()
    for var in packaging.declared_vars():
        assert rows[var.name] == set(var.legacy), (
            f"{var.name}: doc lists {rows[var.name]}, declarations say {set(var.legacy)}"
        )


def test_removal_version_is_stated():
    assert LEGACY_REMOVAL_VERSION in DOC.read_text()


def test_every_sibling_tool_prefix_is_mapped():
    text = DOC.read_text()
    for prefix in ("codex_", "kimi_", "claude_"):
        assert prefix in text, f"no tool map for {prefix}*"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_migration_doc.py -v`
Expected: FAIL, `FileNotFoundError`.

- [ ] **Step 3: Generate the env table**

```bash
uv run python - <<'PY'
from amicus import packaging
lines = ["| amicus name | legacy names | default |", "| --- | --- | --- |"]
for var in packaging.declared_vars():
    legacy = ", ".join(f"`{n}`" for n in var.legacy) or "—"
    default = f"`{var.default}`" if var.default is not None else "—"
    lines.append(f"| `{var.name}` | {legacy} | {default} |")
print("\n".join(lines))
PY
```

Paste the output into the doc's "Environment variables" section.

- [ ] **Step 4: Write the tool map and behavior deltas**

Tool map — one table per sibling, e.g.
`codex_consult` → `amicus_consult` with `backend="codex"`; `codex_job_status` → `amicus_job_status`.
Behavior deltas — at minimum:

- **Approval friction (ADR 0001).** Enabling Claude gives *every* tool mutation-grade annotations, so a codex-only call now prompts where it did not before.
  This is deliberate; disable the Claude backend to get the old friction back.
- **One server, one job store.** Jobs from all backends share `AMICUS_STATE_DIR`; `AMICUS_JOB_MAX_COUNT` is per workspace while the task map is one file per state dir.
- **Closed options (ADR 0002).** `backend_options` is a closed superset; a key the chosen backend does not support is an error, not a silent ignore.
- **Legacy env names warn and are removed in `0.3.0`;** setting both an amicus name and a legacy name with different values is an error.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/test_migration_doc.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Verify the instrument can fail**

Delete one row from the env table, rerun, confirm `test_every_declared_var_appears_in_the_table` FAILS naming that variable, then restore it.
A doc test that passes against a truncated table is worthless.

- [ ] **Step 7: Commit**

```bash
git add docs/MIGRATION.md tests/test_migration_doc.py
git commit -m "docs(packaging): add the migration guide with a test-asserted env table"
```

---

### Task 7: The third-party backend wheel

**Files:**
- Create: `tests/fixtures/fakebackend/pyproject.toml`
- Create: `tests/fixtures/fakebackend/src/fakebackend/__init__.py`
- Create: `tests/test_wheel_seam.py`
- Modify: `pyproject.toml` (exclude the fixture from the amicus wheel if `hatchling` picks it up)

**Interfaces:**
- Consumes: `amicus.plugin.BackendPlugin`, `PLUGIN_API_VERSION`, `ENTRY_POINT_GROUP = "amicus.backends"`; `amicus.registry` loading.
- Produces: proof that `registry.py`'s entry-point path — never exercised from outside this repo — actually works for a third party.

This is the gate item "FakePlugin as a wheel".
`tests/support/fakeplugin.py` already registers under a test-only entry point, but that is a same-repo import path; it cannot fail the way a real installed distribution can.

- [ ] **Step 0: Register the `slow` marker first**

`addopts` carries `--strict-markers` and `markers` currently registers only `integration`
(`pyproject.toml:99-107`), so an unregistered `slow` marker is a collection ERROR, not a skip.
Add to the `markers` list:

```toml
    "slow: builds and installs a wheel into a throwaway venv; minutes, not seconds",
```

Note this keeps the test in the default gate run — `addopts` deselects only `integration`.
That is deliberate: the seam is a gate item, so it must run in the gate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wheel_seam.py`:

```python
"""A third-party backend, built as a real wheel and installed out of tree, is discoverable.

The entry-point group is the plugin seam's whole promise. An in-repo import path cannot
prove it: a group that scanned nothing would look identical to success. Hence the negative
control below."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fakebackend"
REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.slow  # registered in pyproject.toml by Step 0 below


def _build_and_install(tmp_path: Path, api_version: int) -> Path:
    """Build the fixture wheel with a given api_version and install it beside amicus."""
    src = tmp_path / "src"
    subprocess.run(["cp", "-R", str(FIXTURE), str(src)], check=True)
    init = src / "src" / "fakebackend" / "__init__.py"
    init.write_text(init.read_text().replace("API_VERSION_PLACEHOLDER", str(api_version)))
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist"), str(src)],
                   check=True, capture_output=True)
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True)
    wheel = next((tmp_path / "dist").glob("*.whl"))
    subprocess.run(["uv", "pip", "install", "--python", str(venv / "bin" / "python"),
                    str(REPO_ROOT), str(wheel)], check=True, capture_output=True)
    return venv / "bin" / "python"


def _probe(python: Path) -> dict:
    """Ask the installed amicus what it thinks of the installed third-party backend."""
    code = (
        "import json;"
        "from amicus.registry import BackendRegistry;"
        "r = BackendRegistry.load(('fakebackend',));"
        "print(json.dumps({'available': sorted(r.available), "
        "'unavailable': {k: v.reason for k, v in r.unavailable.items()}}))"
    )
    out = subprocess.run([str(python), "-c", code], check=True, capture_output=True, text=True)
    return json.loads(out.stdout)


def test_a_wheel_declaring_the_entry_point_is_loaded(tmp_path):
    from amicus.plugin import PLUGIN_API_VERSION

    result = _probe(_build_and_install(tmp_path, PLUGIN_API_VERSION))
    assert result["available"] == ["fakebackend"]
    assert result["unavailable"] == {}


def test_a_wheel_with_a_wrong_api_version_is_rejected_by_reason(tmp_path):
    """The negative control: an empty scan and a rejection must not look the same."""
    from amicus.plugin import PLUGIN_API_VERSION

    result = _probe(_build_and_install(tmp_path, PLUGIN_API_VERSION + 1))
    assert result["available"] == []
    assert result["unavailable"] == {"fakebackend": "api_version"}
```

The `BackendRegistry` API above was traced against `src/amicus/registry.py:96-104` on `main`:
`load(enabled: Iterable[str], *, in_tree=None, entry_points=None)` is a classmethod, and
`available` / `unavailable` are plain dicts keyed by backend id, so the probe code is correct as written.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_wheel_seam.py -v`
Expected: FAIL — the fixture does not exist.

- [ ] **Step 3: Write the fixture distribution**

`tests/fixtures/fakebackend/pyproject.toml`:

```toml
[project]
name = "fakebackend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.entry-points."amicus.backends"]
fakebackend = "fakebackend:plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/fakebackend"]
```

`tests/fixtures/fakebackend/src/fakebackend/__init__.py` builds a minimal conforming `BackendPlugin` with `api_version = API_VERSION_PLACEHOLDER` (the test substitutes it) — model it on `tests/support/fakeplugin.py`, which already constructs a conforming plugin; import the same pontonier pieces.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/test_wheel_seam.py -v`
Expected: PASS, 2 tests.
This is slow (two venvs, two builds) — that is why it carries `pytest.mark.slow`.

- [ ] **Step 5: Confirm the negative control actually discriminates**

Temporarily change the fixture's entry-point group to `amicus.backends.typo`, rerun the positive test, and confirm it FAILS with an empty `available` — proving the test observes the group and not something incidental.
Restore.

- [ ] **Step 6: Check the fixture does not ship in the amicus wheel**

Run: `uv build --wheel --out-dir /tmp/amicus-build . && uv run python -c "
import zipfile, glob
names = zipfile.ZipFile(glob.glob('/tmp/amicus-build/*.whl')[0]).namelist()
assert not [n for n in names if 'fakebackend' in n], 'fixture leaked into the wheel'
print('clean')
"`
Expected: `clean`.
If not, add an exclusion under `[tool.hatch.build.targets.wheel]`.

- [ ] **Step 7: Run the full gate, then commit**

This is the last gate before Task 8 spends, so it must be the current one, not Task 2's.

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`
Expected: green, coverage ≥95%.
**Task 8 does not start unless this exact command passed on this commit.**

```bash
git add tests/fixtures/fakebackend/ tests/test_wheel_seam.py pyproject.toml
git commit -m "test(plugin): prove the entry-point seam with a real out-of-tree wheel"
```

---

### Task 8: Install smoke and probe capture — the one task that spends

**Files:**
- Create: `docs/host-captures/install-smoke/claude-code/<version>/{notes.md,transcript.md,server.log}`
- Create: `docs/host-captures/install-smoke/codex/<version>/{notes.md,transcript.md,server.log}`
- Modify: `skills/collaborating-with-amicus/tests/scenarios.md` (run log for S1, S2, S7)

**Interfaces:**
- Consumes: the manifests from Task 2 (and **its Step 8 boot check must have passed** — decision 7).
- Produces: the install-smoke evidence for the M6 gate, and the cold-start (S1), first-repair (S2) and annotation-friction (S7) probe evidence Task 10's walk requires.

**Precondition — do not start until all are true:** Task 2 Step 8 passed; the full gate is green; the backends are authenticated (`amicus_backends` reports so); the maintainer has confirmed in-session that the three paid calls should be spent now.

**Budget: six paid calls total.** One cold-start consult per backend per host (3 × 2).
Everything else in this task is free.
If a probe fails and you want to re-run it, STOP and ask — a retry is spend the maintainer has not authorized.

- [ ] **Step 1: Install into Claude Code from `.claude-plugin/`**

Install from the local worktree path, overriding `.mcp.json`'s git ref with a local `--from` pointing at the worktree.
Record the exact override in `notes.md`; do not commit a modified `.mcp.json`.

- [ ] **Step 2: Record the negotiated handshake**

With `AMICUS_LOG_LEVEL=DEBUG` and `AMICUS_LOG_FILE` set, capture the connection line: protocol version, `client_info` name and version, whether the tasks extension was declared.
M5 found the two hosts negotiate different protocol eras — record what is observed, never what is expected.

- [ ] **Step 3: S1, the cold-start probe (spends one call per backend)**

In a fresh host context with no amicus history, give a natural-language task: *"Get a second opinion from another model on whether this function's error handling is right."*
Record: which tool the agent reached for first, whether the call was valid on the first attempt, and the answer.
Repeat once per backend (three calls on this host; three more on the second host in Step 7).

**Name the expected backend before running.** S1's prompt says "another model", which does not
determine a correct answer, so the probe is ungradable as written.
Fix it by running each repetition with exactly ONE backend enabled via `AMICUS_BACKENDS`:
the expected backend is then the enabled one, and a call naming any other backend is a fail.
Record `AMICUS_BACKENDS` in the capture for every run.

Assertion: a valid first call to a paid verb naming the one enabled backend.

- [ ] **Step 4: S2, the first-repair probe (free)**

Induce an invalid call — an unsupported `backend_options` key for the chosen backend (ADR 0002 makes this a structured error, not a silent ignore).
Record the error envelope's `repair` object and whether the agent's next call is valid.
Assertion: the agent repairs from the `repair` hint without guessing.
This costs nothing: the call is rejected before dispatch.

- [ ] **Step 5: S7, the annotation-friction probe (free)**

With Claude enabled, invoke a codex-only call and record the host's approval prompt verbatim — this is ADR 0001's disclosed regression as a user actually meets it (decision 8).
Assertion: the prompt appears, and the capability summary explains why.

- [ ] **Step 6: Three further probes (free)**

Per `review-workflow.md:41`, at least three more applicable probes: discovery cost (`tools/list` size against the M0 ratchet), annotation honesty (do declared effects match observed ones), and version/upgrade behavior (`amicus_capabilities` fingerprint).
For any probe skipped, write the inapplicability reason — the checklist requires a recorded reason, not silence.

- [ ] **Step 7: Repeat Steps 1–6 for Codex from `.codex-plugin/`**

Codex has no slash-command surface, so the command-discovery probe is inapplicable there — record that reason explicitly.
This host gets its own three paid cold-start calls, one per backend, under the six-call budget —
the Claude host's three do not transfer, because a cold-start probe measures THIS host's agent
meeting the server.
Six calls is the cap; a seventh needs a fresh ask.

- [ ] **Step 8: Strip telemetry, check rule 18, commit**

Follow M5's capture hygiene: strip cost and token telemetry from both captures before commit.
Then re-read every transcript for prompt inputs (rule 18) and elide any that appear.

Run: `uv run python -c "
import pathlib
bad = []
for p in pathlib.Path('docs/host-captures/install-smoke').rglob('*.md'):
    t = p.read_text()
    for marker in ('cost_usd', 'total_tokens', 'input_tokens'):
        if marker in t: bad.append((str(p), marker))
assert not bad, bad
print('clean')
"`
Expected: `clean`.

- [ ] **Step 9: Update the run log honestly**

In `scenarios.md`, set `status: pass` or `status: fail` for S1, S2 and S7 **only** for runs actually executed, with prompt, model, harness version and evidence recorded.
Everything else stays `unrun`.

- [ ] **Step 10: Commit**

```bash
git add docs/host-captures/install-smoke/ skills/collaborating-with-amicus/tests/scenarios.md
git commit -m "docs(packaging): capture the install smoke and cold-start probes from both hosts"
```

---

### Task 9: Hand-run the remaining eval subset

**Files:**
- Modify: `skills/collaborating-with-amicus/tests/scenarios.md`

**Interfaces:**
- Consumes: the scenario ids from Task 5 not already run in Task 8 (S3, S4, S5, S6).
- Produces: the run log entries that make the eval fixtures evidence rather than aspiration.

Free: these test routing, and the assertions are about which tool the agent *reaches for*, observable without completing a paid call (use `amicus_dry_run` or stop at the tool-call boundary).

- [ ] **Step 1: Run S3, S4, S5, S6 in fresh contexts**

One fresh context per scenario, per the harness protocol.
Record prompt, model, harness version, full answer, assertion evidence.

- [ ] **Step 2: Record results honestly, including failures**

A failing scenario is a finding for Task 10's fix wave, not something to re-run until it passes.
If a scenario fails, write what the agent did instead — that is the input the skill wording needs.

- [ ] **Step 3: Verify nothing is over-claimed**

Run: `uv run python -c "
import pathlib, re
text = pathlib.Path('skills/collaborating-with-amicus/tests/scenarios.md').read_text()
for block in text.split('### S')[1:]:
    sid = block.split()[0]
    status = re.search(r'status: (\w+)', block).group(1)
    if status in ('pass','fail'):
        assert 'harness version' in block.lower(), f'S{sid} claims {status} with no run record'
print('ok')
"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add skills/collaborating-with-amicus/tests/scenarios.md
git commit -m "test(skills): record the hand-run routing eval results"
```

---

### Task 10: The agent-friendly-mcp review walk, ADR, README, and the publish workflow

**Files:**
- Create: `docs/reviews/2026-09-XX-agent-friendly-mcp-walk.md`
- Create: `docs/adr/0012-m6-packaging-decisions.md`
- Modify: `README.md` (the "Where things are" table, the "Resuming the work" section)
- Create **on a separate branch**: `.github/workflows/publish.yml`

**Interfaces:**
- Consumes: the probe evidence from Tasks 8 and 9; the checklist at `.agents/skills/agent-friendly-mcp/references/`.
- Produces: the walk findings, the fix wave, and the milestone's closing documentation.

- [ ] **Step 1: Run the walk**

Follow `references/review-workflow.md` as written — it is the binding protocol, not a suggestion.
Severity comes from demonstrated cost to an agent, scaled by catalog breadth and cold-start evidence (`review-workflow.md:27`), not from a fixed default.
Cite rule ids from `contract-checklist.md` for every finding.

- [ ] **Step 2: Write the findings doc with the probe evidence attached**

The checklist's completion criteria (`review-workflow.md:126`) require: cold-start and first-repair probes answered with concrete evidence, at least three other applicable probes, and a recorded inapplicability reason for every skipped probe.
Link each to the Task 8 capture.
A findings doc that cannot point at its probes has not completed the walk.

- [ ] **Step 3: Verify the walk against the checklist's real Done Criteria**

A substring grep is not this checklist's bar.
`review-workflow.md:123-128` requires: every section §1–§9 accounted for in a coverage table
(covered by a finding, `OK` with evidence, or `not-checked` with a reason); cold-start and
first-repair probes run with concrete evidence plus at least three other applicable probes, each
skipped probe carrying its inapplicability reason; every finding carrying all five labeled lines
(severity, section, summary, evidence, remediation); and an explicit statement naming residual
risks when no Critical or Major findings exist.

Write `tests/test_review_artifact.py` so omission is mechanically detectable rather than trusted:

```python
"""The agent-friendly-mcp walk artifact must satisfy the checklist's Done Criteria.

The walk is an M6 gate item, so a token document must not be able to pass for it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = next((Path(__file__).resolve().parents[1] / "docs" / "reviews").glob("*agent-friendly-mcp-walk.md"))
TEXT = DOC.read_text()
SECTIONS = [f"§{n}" for n in range(1, 10)]
FINDING_FIELDS = ("severity:", "section:", "summary:", "evidence:", "remediation:")


@pytest.mark.parametrize("section", SECTIONS)
def test_every_checklist_section_is_accounted_for(section):
    row = re.search(rf"^\|\s*{re.escape(section)}\s*\|([^|]*)\|", TEXT, re.M)
    assert row, f"{section} has no coverage-table row"
    status = row.group(1).strip().lower()
    assert status in {"covered", "ok", "not-checked"}, f"{section}: bad status {status!r}"
    if status == "not-checked":
        assert len(row.group(0).split("|")[3].strip()) > 10, f"{section}: not-checked needs a reason"


def test_the_two_mandatory_probes_carry_evidence():
    for probe in ("cold-start", "first-repair"):
        block = re.search(rf"### Probe: {probe}(.+?)(?=\n### |\Z)", TEXT, re.S | re.I)
        assert block, f"no {probe} probe section"
        assert "docs/host-captures/" in block.group(1), f"{probe} probe cites no captured evidence"


def test_at_least_three_further_probes_are_applicable_or_excused():
    probes = re.findall(r"### Probe: (.+)", TEXT)
    further = [p for p in probes if p.strip().lower() not in {"cold-start", "first-repair"}]
    assert len(further) >= 3, f"only {len(further)} further probes: {further}"


def test_every_finding_carries_all_five_labeled_lines():
    for finding in re.findall(r"#### Finding \d+(.+?)(?=\n#### |\n## |\Z)", TEXT, re.S):
        missing = [f for f in FINDING_FIELDS if f not in finding.lower()]
        assert not missing, f"finding missing {missing}"


def test_a_clean_report_names_residual_risks():
    if not re.search(r"severity:\s*(critical|major)", TEXT, re.I):
        assert "residual risk" in TEXT.lower(), "a clean report must name residual risks"
```

Run: `uv run pytest tests/test_review_artifact.py -v`
Expected: PASS once the walk document is written to the required shape.

Then confirm the instrument discriminates: delete the §5 coverage row, rerun, see that
parametrized case FAIL; restore it.

- [ ] **Step 4: The fix wave**

Apply the findings.
Expect this to be real work — M4 and M5 both needed one.
**If any fix changes a tool description, parameter, or the capability summary, the surface moves:** bump `FINGERPRINT` `amicus/0.1/schema-6` → `amicus/0.1/schema-7` and regenerate every pin (manifest snapshots, surface digests, wire-shape and result-format snapshots, the tools/list ratchet) **in its own commit** (rule 10).
`RESULT_FORMAT` stays `2` unless a stored result's shape changes (rule 11).

- [ ] **Step 5: Write ADR 0012**

Record decisions 1–10 above, following the format of `docs/adr/0011-m5-tasks-decisions.md`.
State the known gap plainly: the walk is a checklist review, and while M6 captures cold-start and first-repair evidence, it does not build the standing regression gate `design-workflow.md` Step 9 describes.
`tests/test_discovery_cost.py` ratchets the token cost of discovery, which is a different measure from first-call success — say so, so the existing ratchet is not mistaken for coverage it does not provide.

- [ ] **Step 6: Update the README**

Add rows for the M6 plan, `docs/MIGRATION.md`, the skill, and the walk findings.
Update "Resuming the work" to say `main` carries M6 and the next milestone is M7.

- [ ] **Step 7: Full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`
Expected: green, coverage ≥95%, floor unchanged.

- [ ] **Step 8: Commit the milestone work**

```bash
git add docs/reviews/ docs/adr/0012-m6-packaging-decisions.md README.md
git commit -m "docs(packaging): record the agent-friendly-mcp walk and the M6 decisions"
```

- [ ] **Step 9: Open ONE draft PR**

The execution model is stricter than rule 9 alone: rule 5 is "One plan produces one draft PR",
and rule 6 says `.github/workflows/**` changes are separate reviewed PRs, not a side effect of a
milestone plan.
Putting the publish workflow on a second branch inside this plan would have satisfied rule 9's
letter and broken rule 5.
It is therefore **out of this plan entirely** and has its own plan,
`docs/superpowers/plans/2026-09-07-amicus-publish-workflow.md`, executed after M6 merges.

```bash
gh pr create --draft --title "feat(packaging): M6 — packaging, docs, evals and the review walk"
```

Rule 8: never merge, never approve.
The PR body carries the residuals, the known gaps from Step 5, and the paid-call ledger from Task 8
(six calls, what each bought).

---

## Self-Review

**Spec coverage.** M6's scope row maps as: packaging → Tasks 1, 2, 7 and the separate workflow PR; docs → Tasks 3, 4, 6, 10; eval fixtures → Tasks 5, 9; migration doc → Task 6; annotation-friction capture → Task 8 Step 5.
The gate row maps as: install smoke from both manifests → Task 8; FakePlugin as a wheel → Task 7; agent-friendly-mcp review walk → Task 10.
The Config section's three requirements — generated `env_vars`, test-asserted `MIGRATION.md`, `${VAR}` placeholder check — are Tasks 1, 6 and Task 2's `test_mcp_json_has_no_unexpanded_placeholders` respectively.

**Known gaps, stated rather than hidden.**
The standing cold-start regression gate (`design-workflow.md` Step 9) is not built.
M6 captures the evidence but does not pin a baseline that future changes are measured against.
The committed manifest's `--from` names a git tag that will not exist until release, so Task 2 Step 8 substitutes a locally built wheel for that one field.
Tag resolvability is therefore NOT proven by M6; it is the publish workflow's gate.
Both gaps are recorded in ADR 0012 and carried to M7.

**Type consistency.** `packaging.declared_env_names()`, `vendor_auth_env_names()`, `env_vars_list()` and `declared_vars()` are defined in Task 1 and used under those exact names in Tasks 2 and 6. `BackendRegistry.load` in Task 7 is flagged for verification against `src/amicus/registry.py` before use rather than assumed.

**Ordering.** Task 0 unblocks the `skills` scope before Tasks 3–5 need it.
Task 1 precedes Tasks 2 and 6, which consume it.
Task 2's boot check precedes Task 8's spend.
Task 7 precedes Task 8 so the seam fails cheaply.
Task 10 is last so the fix wave sees everything.
