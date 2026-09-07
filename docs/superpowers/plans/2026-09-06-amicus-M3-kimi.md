# amicus M3 Implementation Plan: the Kimi backend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every paid verb, both dry runs, `amicus_backends` and `amicus_models` real for `backend="kimi"`: a ported Kimi plugin with the adapter fixes the spec names, a worktree (or, for a consult outside a repo, an empty temp dir) for every tier, the orphan sweep, pre-spend effort validation, the moonbridge differentials, and the live gate.

**Architecture:** moonbridge's CLI contract, handshake staging, argv builder, stream-json normalizer, live model catalog, classifier and status probe are ported into `src/amicus/backends/kimi/` behind the M0 `BackendPlugin` seam, in the same file-per-responsibility layout as `backends/codex/`.
The orchestration loop (`orchestration/run.py`) is unchanged in shape: it already selects a `WorktreeSite` when the contract says `WORKTREE_ALL_TIERS`, sweeps orphans when the contract asks, runs `validate_request` before spawning, and calls `inspect_outcome` on every completed process.
M3 adds one site (`EmptyDirSite`, for a consult outside a git repository) and hardens the artifact reader; everything else Kimi-specific lives in the plugin.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `prek`.
Runtime: `pontonier==0.9.0` (`OutcomeInspector`, `ClassifiedFailure.details/repair`, `Usage.cached_input_tokens`, `runtime.sweep_orphans`, `worktree.is_git_repo`), `fastmcp>=4.0,<4.1`, `mcp>=2.1,<2.2`, `pydantic>=2`, `anyio>=4`.
No new dependency.
Live gate: the installed `kimi` CLI (`kimi-code 0.41.0` on the maintainer's machine, one configured provider).

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — "Milestones" row M3 (scope: Kimi with adapter fixes, `WorktreeSite` all tiers, orphan sweep, pre-spend effort validation; gate: hot-path differential vs moonbridge incl. sanitize-before-truncate, `check_backend` positive and perturbed, `integration_kimi`); "Verified constraints" (the Kimi adapter gaps); "Orchestration: one loop, isolation as a strategy"; "Plugin interface"; "Testing architecture".
ADR 0001 (annotations), ADR 0002 (options), ADR 0003 (workspace), ADR 0005 (envelope), ADR 0007 (M1 port decisions), ADR 0008 (M2).
Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`; binding repo rules: `AGENTS.md`.
Sibling read for porting (never edited): `/Users/bdc/projects/moonbridge` at `f6df12d` (v0.3.0; its venv runs pontonier 0.7.0 on Python 3.14), files `src/moonbridge/{cli_contract,kimi,backend,normalize,kimi_models,config,runspace,orchestration,preflight}.py` and `docs/kimi-help/0.39.1/`.

## Global Constraints

- Repo: `/Users/bdc/projects/amicus`.
  Work on branch `feat/m3-kimi` in the sibling git worktree `/Users/bdc/projects/amicus-wt-m3` (created from `main` at `f3c1cbc`; baseline 612 tests green, 97.18% branch coverage).
  Never commit to `main`.
- Dependencies exactly as `pyproject.toml` has them; this plan adds none.
- Gate (AGENTS.md rule 2): `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest` at ≥95% branch coverage.
  Coverage floor never lowered.
  Every `uv run` assumes `uv sync` ran once; `uv run --no-sync` is fine while iterating.
- Import rules (import-linter, `pyproject.toml`): `amicus.backends.*` never imports `amicus.tools`/`server`/`orchestration`/`jobs`/`middleware`/`errors`/`registry`/`manifest`.
  The Kimi package imports only `amicus.plugin`, `amicus.config` (envspec and `settings`), `amicus.schemas.*` and pontonier, like the Codex package.
- Tool surface stays exactly 18 tools in `amicus.tools.TOOL_ORDER`; 6 resources; no prompts; no tool gains or loses a parameter; no description changes.
  `FINGERPRINT` stays `amicus/0.1/schema-3` and `RESULT_FORMAT` stays `1`; every Kimi error code is already in the catalog (`empty_response`, `invalid_model`, `cli_contract_changed`, `kimi_*` generalized to `backend_*`).
  Task 9 verifies the manifest, digest, wire-shape and result-format pins are byte-identical; if any moved, stop and explain in the PR body.
- `backend="claude"` keeps returning `backend_unavailable`; `amicus_adversarial_review(_async)` keeps returning `not_implemented`; `task=True` wiring stays M5.
- Prompt inputs never land in `spec.json`, on the worker's argv, or in a log.
  Kimi's own carrier is a handshake file under a private temp dir OUTSIDE the workspace; argv carries only a pointer to that file's path (AGENTS.md rule 18 is about amicus-side persistence and argv, and the pointer carries no input text).
- Spend guard: `tests/conftest.py` keeps `AMICUS_CODEX_BIN` unusable (autouse) and, from Task 2 on, `AMICUS_KIMI_BIN` too; every unit test drives `tests/support/fake_kimi.py` or a scripted runtime.
  The live suite `tests/test_kimi_live.py` (`-m integration`) runs exactly once, in Task 9, because the maintainer authorized it in the planning session (AGENTS.md rule 5); record the outcome in the PR body.
- Commit messages: Conventional Commits `type(scope): subject`; scopes from `scripts/check_commit_message.py` (`schemas`, `plugin`, `registry`, `config`, `errors`, `middleware`, `server`, `tools`, `resources`, `manifest`, `orchestration`, `jobs`, `tasks`, `backends`, `packaging`, `docs`, `ci`, `deps`, `release`).
  Imperative lowercase subject, no trailing period.
  End every commit body with the attribution trailer given in the session.
- Markdown under `docs/`: one sentence per line.
- Off limits (AGENTS.md rules 9, 17): `.github/**`, `AGENTS.md`, `CLAUDE.md`; any sibling checkout (moonbridge is read, and its venv runs the capture script, never modified); releasing; merging or approving the PR.

## Decisions made here (surface in ADR 0009 and the PR body)

1. **Consult outside a git repository runs in an empty temp dir**, never in the workspace: `orchestration.isolation.EmptyDirSite` (prefix `amicus-wt-`) is selected only for kind `consult` under `IsolationPolicy.WORKTREE_ALL_TIERS` when `workspace_root` is not a repo, and stamps `NO_REPO_WARNING` on `meta.security_warnings`.
   Review still fails `not_a_git_repo` at gather; delegate still fails at the pre-spend preflight.
2. **`empty_response` is an outcome inspection**: `KimiBackend` implements pontonier's `OutcomeInspector`; a zero-exit run with no answer file and no assistant text in the stream is `empty_response`.
   The loop needs no Kimi branch.
3. **Pre-spend effort validation lives in `KimiBackend.validate_request`** (the loop runs it before spawning): shape first, then the live catalog decides alone when it names the alias, the fallback vocabulary `{minimal, low, medium, high, xhigh, max}` decides only when the catalog is silent, and an unlisted alias fails open.
   The refusal carries `details.allowed_values` and a repair pointing at `amicus_models`.
4. **`instructions_append` rides the handshake prompt file** as a leading section composed by `schemas.instructions.compose` (Kimi has no developer-turn carrier); it is accepted for consult and review only, like Codex.
   `amicus_backends.carriers` says so.
5. **The answer file is read through a hardened reader** in `orchestration.run._read_artifacts` (O_NOFOLLOW, O_NONBLOCK, regular files only, 1 MB cap), because a delegate's answer file is written by a full-tool agent.
   Codex's last-message artifact goes through the same reader.
6. **Kimi 0.41.0 is supported on captured evidence**: `docs/kimi-help/0.41.0/` holds `kimi --version`, `kimi --help` and the redacted shape of `kimi provider list --json`; a test asserts every flag the contract sends or refuses appears in that capture; `SUPPORTED_VERSIONS = {(0, 35), (0, 39), (0, 41)}`.
   The behavioural probes (read-only agent profile, orphan survival, silently ignored effort) are inherited from moonbridge's 0.39.1 findings and re-checked only where the live gate can (Task 9's read-only tool-list probe).
7. **Names**: env namespace `AMICUS_KIMI_*` (`BIN`, `EXTRA_ARGS`, `MODEL`, `REASONING_EFFORT`, `ISOLATION`, `SUPPORTED_VERSIONS`; legacy `MOONBRIDGE_` twins for all but `BIN`), read-only agent `amicus-readonly`, handshake dir prefix `amicus-kimi-handshake-`.
   `AMICUS_KIMI_EXTRA_ARGS` is declared and always refused with the reason (kimi exposes no option amicus can pass safely: `-p` is its prompt flag, `-c` is `--continue`).
8. **Not ported**: moonbridge's tiers/sandbox defaults (`TIER_DEFAULT`, `SANDBOX_DEFAULT`), `WORKTREE_BASE`, the handshake-dir diff exclusion (the dir is outside the tree), `reconcile_dropped_model` (amicus's `finalize.stamp_run` already clears `meta.model` when `--model` is help-gated away), and the `extra_args_rejected` branch of the classifier (no passthrough exists).
9. **The model catalog is probed live with a 300 s in-process cache** (`KimiModels.read()`), so a worker validates and lists models with one `kimi provider list --json` spawn; provider names, base URLs and API keys are never parsed.
10. **Differentials against moonbridge are compared on a projection** (argv modulo the temp paths, the binary token and the agent name; envelope codes after `backend_*` generalization, `temporary`, `retry_after_ms`, usage, session id, summary/verdict/findings, and four boolean leak checks), captured by `scripts/capture_kimi_differentials.py` inside moonbridge's venv.

## File map

Created in this milestone (responsibility in one line each):

- `src/amicus/backends/kimi/__init__.py` — `plugin(environ=None) -> BackendPlugin`, the zero-argument factory the registry calls; vocabulary, egress and carrier disclosures.
- `src/amicus/backends/kimi/contract.py` — the Kimi CLI facts (flags, handshake names, read-only agent tools, stream-json event surface, failure signatures, disclosures) and the pontonier `BackendContract`.
- `src/amicus/backends/kimi/config.py` — the `AMICUS_KIMI_*` namespace with the legacy shim, `KimiConfig`, the refuse-all extra-args parser, `skills_dir_for`, version parsing.
- `src/amicus/backends/kimi/binary.py` — the `kimi` binary resolver (override, PATH, bare literal).
- `src/amicus/backends/kimi/normalize.py` — tolerant stream-json parsing: final message, error message, usage, session id, structured answer.
- `src/amicus/backends/kimi/models.py` — the live, allowlist-shaped model catalog reader and `supported_efforts_for`.
- `src/amicus/backends/kimi/cli.py` — the read-only agent document, handshake staging, prompt pointer, `build_exec_command`, run env, the hardened answer-file reader, the free probes, `classify_failure -> ClassifiedFailure`.
- `src/amicus/backends/kimi/adapter.py` — `KimiBackend` on the pontonier `AgentBackend` lifecycle plus `OutcomeInspector`.
- `src/amicus/backends/kimi/status.py` — the readiness probe.
- `src/amicus/backends/kimi/options.py` — the `OptionSpec` table.
- `docs/kimi-help/0.41.0/{kimi-version.txt,kimi-help.txt,provider-list-shape.json,FINDINGS.md}` — the 0.41.0 evidence.
- `scripts/capture_kimi_differentials.py` — run inside moonbridge's venv to capture the sibling's argv, prompts and envelope projections into `tests/fixtures/kimi_differentials.json`.
- `tests/support/kimifixtures.py` — pinned flag support, a backend built from an explicit environ, argv normalization, the scripted runtime for Kimi.
- `tests/support/fake_kimi.py` — a stand-in `kimi` executable for end-to-end tests without spend.
- `docs/adr/0009-m3-kimi-port-decisions.md` — the decisions above.
- Tests: `tests/test_kimi_contract.py`, `test_kimi_config.py`, `test_kimi_binary.py`, `test_kimi_normalize.py`, `test_kimi_models.py`, `test_kimi_cli.py`, `test_kimi_adapter.py`, `test_kimi_status.py`, `test_kimi_plugin.py`, `test_kimi_argv_differential.py`, `test_kimi_result_differential.py`, `test_kimi_sync_tools.py`, `test_kimi_live.py`.

Modified: `src/amicus/orchestration/isolation.py` (EmptyDirSite, select_site), `src/amicus/orchestration/run.py` (hardened artifact reads), `tests/conftest.py` (Kimi spend guard and fixtures), `tests/test_conftest_guards.py`, `tests/test_isolation.py`, `tests/test_run.py`, `tests/test_registry.py`, `tests/test_async_tools.py`, `tests/test_dry_run.py`, `tests/test_paid_tools.py` (comment), `tests/test_surface_honesty.py`, `README.md`.

---

### Task 0: Worktree and baseline

**Files:** none modified.

- [ ] **Step 1: Use the worktree**

The worktree already exists (created while this plan was written):

```bash
cd /Users/bdc/projects/amicus-wt-m3
git status --short          # expected: only this plan file, untracked
git branch --show-current   # expected: feat/m3-kimi
```

If it does not exist: `cd /Users/bdc/projects/amicus && git worktree add ../amicus-wt-m3 -b feat/m3-kimi main && cd ../amicus-wt-m3 && uv sync`.

- [ ] **Step 2: Confirm the prerequisites**

Run: `uv run --no-sync python -c "import importlib.metadata as m; print(m.version('pontonier'), m.version('fastmcp'))"`
Expected: `0.9.0 4.0.x`.

Run: `(cd /Users/bdc/projects/moonbridge && git log -1 --format=%h && uv run --no-sync python -c "import importlib.metadata as m; print(m.version('pontonier'))")`
Expected: `f6df12d` and `0.7.0`. A different commit is fine but record it in the PR body; the capture script in Task 7 records the commit it ran against.

Run: `which kimi && kimi --version`
Expected: `/Users/bdc/.kimi-code/bin/kimi` and `0.41.0`. If kimi is missing, every task up to 8 still runs (they never spawn the real CLI); Task 1's evidence capture and Task 9's live tests will fail and must be reported, not skipped.

- [ ] **Step 3: Baseline gate**

Run: `uv run --no-sync pytest -q`
Expected: `612 passed`, coverage ≥ 95%.

- [ ] **Step 4: Commit the plan**

```bash
git add docs/superpowers/plans/2026-09-06-amicus-M3-kimi.md
git commit -m "docs: add the M3 implementation plan"
```

---

### Task 1: The Kimi CLI contract and the 0.41.0 evidence

**Files:**
- Create: `src/amicus/backends/kimi/__init__.py` (package marker only for now; the factory lands in Task 5)
- Create: `src/amicus/backends/kimi/contract.py`
- Create: `docs/kimi-help/0.41.0/kimi-version.txt`, `docs/kimi-help/0.41.0/kimi-help.txt`, `docs/kimi-help/0.41.0/provider-list-shape.json`, `docs/kimi-help/0.41.0/FINDINGS.md`
- Test: `tests/test_kimi_contract.py`
- Modify: `tests/test_surface_honesty.py` (add `"read-only sandbox"` to the union)

**Interfaces:**
- Produces: every constant named in the code below; `contract.CONTRACT: BackendContract` with `backend_id="kimi"`, `env_prefix="AMICUS_KIMI_"`, `isolation_policy=WORKTREE_ALL_TIERS`, `needs_orphan_sweep=True`, `effort_silently_ignored_upstream=True`, `effort_validation="token_floor_plus_catalog"`, `supported_features={"delegate", "model_validation", "empty_response_detection"}`; the signature helpers `is_auth_failure`, `is_contract_drift`, `is_invalid_model`, `is_unresolved_default_model`, `is_rate_limited`, `parse_retry_after_ms` (all `*texts: str | None`).

- [ ] **Step 1: Capture the 0.41.0 evidence (free probes only)**

```bash
mkdir -p docs/kimi-help/0.41.0
kimi --version > docs/kimi-help/0.41.0/kimi-version.txt
kimi --help > docs/kimi-help/0.41.0/kimi-help.txt 2>&1
kimi provider list --json | uv run --no-sync python -c '
import json, sys
d = json.load(sys.stdin)
models = d.get("models") if isinstance(d.get("models"), dict) else {}
shape = {
    "top_level_keys": sorted(d) if isinstance(d, dict) else type(d).__name__,
    "providers_type": type(d.get("providers")).__name__ if isinstance(d, dict) else None,
    "models_type": type(d.get("models")).__name__ if isinstance(d, dict) else None,
    "model_entry_keys": sorted({k for m in models.values() if isinstance(m, dict) for k in m}),
    "model_count": len(models),
}
print(json.dumps(shape, indent=2))
' > docs/kimi-help/0.41.0/provider-list-shape.json
cat docs/kimi-help/0.41.0/kimi-version.txt docs/kimi-help/0.41.0/provider-list-shape.json
grep -c "apiKey\|baseUrl\|sk-" docs/kimi-help/0.41.0/provider-list-shape.json   # expected: 0
```

Expected: `0.41.0`; `top_level_keys` containing `models` and `providers`; `model_entry_keys` containing `supportEfforts` (if `defaultEffort`/`displayName` are absent on this machine's alias, say so in FINDINGS.md — `parse_catalog` treats them as optional); the grep prints `0`.

Write `docs/kimi-help/0.41.0/FINDINGS.md`:

```markdown
# kimi-code 0.41.0 — amicus M3 evidence

Captured 2026-09-06 on the maintainer's machine by running the binary (`kimi --version`, `kimi --help`, `kimi provider list --json`).
No model call was made for this capture.

## What the captures show

- `kimi-version.txt`: `0.41.0`.
- `kimi-help.txt`: every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still advertised.
  `tests/test_kimi_contract.py` asserts this against the file, after first proving a known-absent control flag is not matched.
- `provider-list-shape.json`: the payload is an object with `models` and `providers` maps; a model entry carries `supportEfforts` (the shape `models.parse_catalog` reads).
  Only key names were captured; provider details (API keys, base URLs) were never written to disk.

## What is inherited, not re-verified here

The behavioural findings in moonbridge's `docs/kimi-help/0.39.1/M0-FINDINGS.md` (the read-only `--agent-file` profile removes Bash and Write; a worktree does not contain kimi; an unrecognized `KIMI_MODEL_THINKING_EFFORT` is silently ignored; a SIGKILLed run leaves orphaned Bash children; the argv ceiling near 950k chars) are carried into the amicus contract unchanged.
They were not re-run as standalone probes on 0.41.0.
The live gate (`tests/test_kimi_live.py`, run once in this milestone) re-checks the one guarantee it can observe from the answer: a read-only consult asked to list its tools names no Bash, Write or Edit tool.
Its outcome is recorded below after the run.

## Live gate outcome

(filled in by Task 9)
```

- [ ] **Step 2: Write the failing contract tests**

`tests/test_kimi_contract.py`:

```python
"""The Kimi CLI contract: derivations from the constants, the failure signatures, and the
0.41.0 evidence rule (a flag the contract sends or refuses must appear in the capture)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pontonier.backend.contract import IsolationPolicy
from pontonier.testing import conformance

from amicus.backends.kimi import contract

HELP = (Path(__file__).parent.parent / "docs" / "kimi-help" / "0.41.0" / "kimi-help.txt").read_text()
VERSION = (
    (Path(__file__).parent.parent / "docs" / "kimi-help" / "0.41.0" / "kimi-version.txt")
    .read_text()
    .strip()
)


def test_contract_is_derived_from_the_constants_and_self_consistent():
    c = contract.CONTRACT
    assert c.backend_id == "kimi" and c.env_prefix == "AMICUS_KIMI_" and c.bin_name == "kimi"
    assert c.exec_argv_prefix == () and c.always_send_flags == contract.ALWAYS_SEND_FLAGS
    assert c.help_gated_flags == tuple(sorted(contract.HELP_GATED_FLAGS))
    assert c.isolation_policy is IsolationPolicy.WORKTREE_ALL_TIERS and c.needs_orphan_sweep
    assert c.effort_silently_ignored_upstream and c.effort_validation == "token_floor_plus_catalog"
    assert c.structured_output == "prompt_append" and c.model_catalog.strategy == "live_probe"
    assert c.supported_features == {"delegate", "model_validation", "empty_response_detection"}
    assert c.limits.max_argv_prompt_chars == contract.MAX_ARGV_PROMPT_CHARS
    assert c.limits.answer_file_name == contract.ANSWER_FILE_NAME
    assert c.readonly_honesty_statement == contract.READ_ONLY_CONFIDENTIALITY_LIMIT
    assert conformance.check_contract(c) == []


def test_read_only_tools_carry_no_shell_or_write():
    assert "Bash" not in contract.READ_ONLY_AGENT_TOOLS
    assert "Write" not in contract.READ_ONLY_AGENT_TOOLS
    assert contract.READ_ONLY_AGENT_NAME == "amicus-readonly"


def test_evidence_the_instrument_can_fail():
    assert "--definitely-not-a-kimi-flag" not in HELP


@pytest.mark.parametrize(
    "flag",
    [
        *contract.ALWAYS_SEND_FLAGS,
        *contract.HELP_GATED_FLAGS,
        contract.ADD_DIR_FLAG,
        *contract.PROMPT_MODE_INCOMPATIBLE_FLAGS,
    ],
)
def test_every_sent_or_refused_flag_is_in_the_captured_help(flag):
    assert flag in HELP


def test_captured_version_is_a_supported_version():
    major, minor, _patch = VERSION.split(".")
    assert (int(major), int(minor)) in contract.SUPPORTED_VERSIONS
    assert contract.SUPPORTED_VERSIONS == frozenset({(0, 35), (0, 39), (0, 41)})


@pytest.mark.parametrize(
    "text, auth, drift, model, unresolved, rate",
    [
        ("Error: 401 Unauthorized", True, False, False, False, False),
        ("invalid api key", True, False, False, False, False),
        ("error: unknown option '--zap'", False, True, False, False, False),
        ("Cannot combine --prompt with --yolo.", False, True, False, False, False),
        ('error: failed to run prompt: Model "x" is not configured in config.toml.', False, False, True, False, False),
        (
            "error: failed to run prompt: model foo does not resolve to a configured provider",
            False,
            False,
            True,
            True,
            False,
        ),
        ("this alias does not resolve to a configured provider, said the docs", False, False, False, False, False),
        ("429 Too Many Requests", False, False, False, False, True),
        ("quota exhausted", False, False, False, False, True),
        ("all good", False, False, False, False, False),
    ],
)
def test_failure_signatures(text, auth, drift, model, unresolved, rate):
    assert contract.is_auth_failure(text) is auth
    assert contract.is_contract_drift(text) is drift
    assert contract.is_invalid_model(text) is model
    assert contract.is_unresolved_default_model(text) is unresolved
    assert contract.is_rate_limited(text) is rate


def test_retry_after_parsing():
    assert contract.parse_retry_after_ms("Retry-After: 5") == 5000
    assert contract.parse_retry_after_ms("retry_after=250ms") == 250
    assert contract.parse_retry_after_ms("try again in 2 minutes") == 120_000
    assert contract.parse_retry_after_ms("retry-after: 0") == 0
    assert contract.parse_retry_after_ms("nothing here") is None
    assert contract.parse_retry_after_ms(None, "") is None


def test_effort_token_pattern_is_shape_only():
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch("xhigh")
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch("future-level.2")
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch("") is None
    assert contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch(" high ") is None
    assert "xhigh" in contract.REASONING_EFFORT_FALLBACK_VOCABULARY
```

Also append `"read-only sandbox"` to `FORBIDDEN_SURFACE_PHRASES` in `tests/test_surface_honesty.py` (the Kimi contract bans it; the amicus manifest must not carry it either).

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_kimi_contract.py tests/test_surface_honesty.py -q --no-cov`
Expected: `test_kimi_contract.py` errors at import (`No module named 'amicus.backends.kimi'`); `test_surface_honesty.py` passes (the manifest already lacks the phrase; the union entry is the guard).

- [ ] **Step 4: Write the contract**

`src/amicus/backends/kimi/__init__.py` (Task 5 replaces it):

```python
"""The Kimi backend plugin (M3). `plugin()` lands in a later task of the M3 plan."""
```

`src/amicus/backends/kimi/contract.py`:

```python
"""Single source of truth for the external `kimi` (Kimi Code) CLI contract, ported from
moonbridge `cli_contract.py` (verified by the sibling against 0.35.0 and 0.39.1) and
re-verified against 0.41.0 by the captures in docs/kimi-help/0.41.0/.

`kimi -p` is NOT `codex exec`. Three differences drive the whole design:

1. There is no sandbox and there are no approvals. Prompt mode runs Bash and writes files
   with zero gating, and a worktree changes kimi's cwd, not its reach. The read-only
   control is READ_ONLY_AGENT_TOOLS, delivered per run via --agent-file.
2. The prompt is argv-only: stdin is ignored, and argv past ~950k chars crashes kimi with a
   Node RangeError. So the real prompt travels in a handshake file OUTSIDE the workspace
   and argv carries a short pointer to it.
3. There is no --output-last-message. The answer is recovered from the stream-json
   assistant lines or, when the tier has a Write tool, from an answer file the prompt asks
   kimi to produce.
"""

from __future__ import annotations

import re

from pontonier.backend import contract as _pc

KIMI_BIN = "kimi"

# kimi has no `exec` subcommand; headless runs ride the top-level `-p/--prompt` flag.
EXEC_SUBCOMMAND: tuple[str, ...] = ()
# Long forms only: the help probe parses long flags out of `kimi --help`.
PROMPT_FLAG = "--prompt"
OUTPUT_FORMAT_FLAG = "--output-format"
OUTPUT_FORMAT_JSON = "stream-json"
MODEL_FLAG = "--model"  # takes a config.toml ALIAS, not a raw provider model id
AGENT_FILE_FLAG = "--agent-file"  # the read-only guarantee; incompatible with --session
SKILLS_DIR_FLAG = "--skills-dir"  # replaces auto-discovered skill dirs (built-ins still load)
ADD_DIR_FLAG = "--add-dir"  # never sent: it would punch through worktree isolation
PROMPT_MODE_INCOMPATIBLE_FLAGS = (
    "-y",
    "--yolo",
    "--auto",
    "--plan",
    "-S",
    "--session",
    "-c",
    "--continue",
)

# Free probes (no model call).
VERSION_ARGS = ("--version",)
HELP_ARGS = ("--help",)
PROVIDER_LIST_ARGS = ("provider", "list", "--json")
HELP_CACHE_TTL_SECONDS = 300

# --- The read-only guarantee -------------------------------------------------------------
# Bash is deliberately absent: it can write. Verified on 0.35.0/0.39.1 that an agent file
# declaring exactly these three reports exactly these three.
READ_ONLY_AGENT_TOOLS = ("Read", "Glob", "Grep")
READ_ONLY_AGENT_NAME = "amicus-readonly"
READ_ONLY_CONFIDENTIALITY_LIMIT = (
    "Read-only means Kimi cannot MODIFY anything — it has no shell or write tool. It does "
    "NOT mean Kimi can only see the workspace: its Read tool accepts absolute paths, so a "
    "prompt-injected repository could make it read other files on this machine and send "
    "them to your configured Kimi provider. Do not point it at a workspace whose contents "
    "you would not hand to that provider."
)
# Wire prose that would teach a mechanism kimi lacks.
FORBIDDEN_SURFACE_PHRASES = ("kimi exec", "read-only sandbox")

# --- The file handshake -------------------------------------------------------------------
# Written OUTSIDE the workspace (a mkdtemp dir; symlink defense in cli.create_handshake_dir).
HANDSHAKE_DIR_PREFIX = "amicus-kimi-handshake-"
PROMPT_FILE_NAME = "prompt.md"
AGENT_FILE_NAME = "readonly-agent.md"
ANSWER_FILE_NAME = "answer.md"  # only a write-capable (delegate) run can produce it
MAX_ARGV_PROMPT_CHARS = 8_000  # far below the ~950k crash edge
MAX_ANSWER_BYTES = 1_000_000

# --- Reasoning effort ----------------------------------------------------------------------
# kimi has no effort FLAG; effort rides an env var and the accepted values are per model.
REASONING_EFFORT_ENV = "KIMI_MODEL_THINKING_EFFORT"
MODEL_OUTPUT_FORMAT_ENV = "KIMI_MODEL_OUTPUT_FORMAT"
# Shape of an effort token (our policy, not a kimi claim): anything that could be a level.
REASONING_EFFORT_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,31}")
# Used ONLY when the catalog is silent: kimi silently ignores an unrecognized effort, so
# refusing on a closed set is safer than spending on a guess.
REASONING_EFFORT_FALLBACK_VOCABULARY = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "max"}
)

# --- Flag classes ---------------------------------------------------------------------------
ALWAYS_SEND_FLAGS = (PROMPT_FLAG, OUTPUT_FORMAT_FLAG, AGENT_FILE_FLAG)
HELP_GATED_FLAGS: dict[str, bool] = {MODEL_FLAG: True, SKILLS_DIR_FLAG: True}

# --- Posture labels (NOT kimi flags) ------------------------------------------------------
SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"

# Advisory: a mismatch warns on amicus_backends, never blocks. (0, 41) is supported on the
# evidence in docs/kimi-help/0.41.0/.
SUPPORTED_VERSIONS = frozenset({(0, 35), (0, 39), (0, 41)})

# --- Models --------------------------------------------------------------------------------
MODEL_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
MODELS_CACHE_MAX_BYTES = 1_000_000
MODELS_CACHE_MAX_ENTRIES = 256
SUPPORTED_EFFORTS_MAX_ENTRIES = 16

# --- stream-json event surface --------------------------------------------------------------
# Verified line shapes on stdout (stderr carries raw tool output and warnings):
#   {"role":"meta","type":"system.version","version":"0.41.0"}          <- first
#   {"role":"assistant","content":"...","tool_calls":[...]}
#   {"role":"tool","tool_call_id":"...","content":"..."}
#   {"role":"meta","type":"session.resume_hint","session_id":"..."}     <- last
#   {"type":"goal.summary",...}                                        <- goal mode only
# `tool_call_id` is NOT unique within a run; `goal.summary` carries no "role".
ROLE_KEY = "role"
TYPE_KEY = "type"
ROLE_ASSISTANT = "assistant"
CONTENT_KEY = "content"
# kimi emits no per-turn token accounting outside goal mode; meta.usage stays null then.
USAGE_EVENT_MARKERS = ("tokensUsed", "turnsUsed")

# --- Disclosure -----------------------------------------------------------------------------
SKILLS_DISCOVERY_FACT = (
    "Kimi auto-loads the resolved workspace's AGENTS.md and discovers skills from its own "
    "config (including `extra_skill_dirs`, which may point outside the workspace)."
)
SKILLS_DISCOVERY_FACT_FULL = (
    SKILLS_DISCOVERY_FACT
    + " Skill names and descriptions are exposed to the model up front, so that content can "
    "be sent even if your prompt never mentions it. The isolation option does not suppress "
    "any of it: kimi's built-in skills always load, and AGENTS.md is read regardless."
)
REDACTION_LIMIT_FACT = (
    "Your inputs are sent raw and unredacted. Secret redaction is best-effort and covers "
    "the gathered diff and Kimi's returned output — not what you type, and not the files "
    "Kimi reads for itself."
)
SKILLS_ISOLATION_NOTE = (
    "backend_options.isolation='ignore-skills' replaces the auto-discovered user/project "
    "skill directories via --skills-dir, but kimi's BUILT-IN skills still load. It is a "
    "reduction in exposure, not an elimination."
)

# --- Failure signatures -----------------------------------------------------------------------
# Auth failures come from the user-configured provider, so these stay generic.
_AUTH_PATTERNS = (
    re.compile(r"\b401\b|\bunauthorized\b", re.I),
    re.compile(r"\binvalid[_ -]?api[_ -]?key\b", re.I),
    re.compile(r"\bauthentication (failed|error|required)\b", re.I),
    re.compile(r"\bno api key\b|\bapi[_ -]?key (is )?(missing|not set)\b", re.I),
    re.compile(r"\brun `?kimi login`?", re.I),
)
# kimi/commander rejecting a flag or value the plugin sent.
_DRIFT_PATTERNS = (
    re.compile(r"error: unknown option", re.I),
    re.compile(r"error: option .* argument missing", re.I),
    re.compile(r"\ballowed choices are\b|\binvalid argument\b", re.I),
    re.compile(r"Output format is only supported in prompt mode", re.I),
    re.compile(r"Cannot combine --prompt with", re.I),
    re.compile(r"Cannot use --session without an id", re.I),
    re.compile(r"unknown command", re.I),
)
# Two captured phrasings for an alias kimi cannot resolve. The second is anchored on the
# `failed to run prompt:` prefix because its tail is ordinary English that the MODEL's own
# prose (searched too) could contain; a false negative beats blaming a fine `model`.
_INVALID_MODEL_PATTERNS = (
    re.compile(r'Model ".*?" is not configured in config\.toml', re.I),
    re.compile(r"failed to run prompt: model \S+ does not resolve to a configured provider", re.I),
)
_RATE_LIMIT_PATTERNS = (
    re.compile(r"\b429\b", re.I),
    re.compile(r"\brate[ _-]?limit(ed|_reached)?\b", re.I),
    re.compile(r"\btoo many requests\b", re.I),
    re.compile(r"\bquota (exceeded|exhausted)\b", re.I),
)
RATE_LIMIT_DEFAULT_BACKOFF_MS = 60_000
_RETRY_AFTER_PATTERNS = (
    re.compile(r"retry[- _]?after[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)\s*(ms|s|seconds?)?", re.I),
    re.compile(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s|seconds?|minutes?)", re.I),
)


def _any(patterns: tuple[re.Pattern[str], ...], texts: tuple[str | None, ...]) -> bool:
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return False
    return any(p.search(blob) for p in patterns)


def is_auth_failure(*texts: str | None) -> bool:
    return _any(_AUTH_PATTERNS, texts)


def is_contract_drift(*texts: str | None) -> bool:
    return _any(_DRIFT_PATTERNS, texts)


def is_invalid_model(*texts: str | None) -> bool:
    return _any(_INVALID_MODEL_PATTERNS, texts)


def is_unresolved_default_model(*texts: str | None) -> bool:
    """The unresolvable alias is config.toml's `default_model`, not the caller's `model`."""
    return _any((_INVALID_MODEL_PATTERNS[1],), texts)


def is_rate_limited(*texts: str | None) -> bool:
    return _any(_RATE_LIMIT_PATTERNS, texts)


def parse_retry_after_ms(*texts: str | None) -> int | None:
    """A retry delay in ms, or None when the text carries none. Returns 0 faithfully."""
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return None
    for pattern in _RETRY_AFTER_PATTERNS:
        m = pattern.search(blob)
        if not m:
            continue
        value = float(m.group(1))
        unit = (m.group(2) or "s").lower()
        if unit == "ms":
            return int(value)
        if unit.startswith("minute"):
            return int(value * 60_000)
        return int(value * 1000)
    return None


# --- The pontonier contract -----------------------------------------------------------------
CONTRACT = _pc.BackendContract(
    backend_id="kimi",
    display_name="Kimi",
    bin_name=KIMI_BIN,
    env_prefix="AMICUS_KIMI_",
    exec_argv_prefix=EXEC_SUBCOMMAND,
    always_send_flags=ALWAYS_SEND_FLAGS,
    help_gated_flags=tuple(sorted(HELP_GATED_FLAGS)),
    forbidden_surface_phrases=FORBIDDEN_SURFACE_PHRASES,
    supported_features=frozenset({"delegate", "model_validation", "empty_response_detection"}),
    readonly_honesty_statement=READ_ONLY_CONFIDENTIALITY_LIMIT,
    implicit_context_disclosure=SKILLS_DISCOVERY_FACT_FULL,
    structured_output="prompt_append",
    model_catalog=_pc.ModelCatalog(
        strategy="live_probe",
        # kimi rejects an unknown alias outright, but only ADVISES on efforts.
        model_identifier_authority="authoritative",
        effort_metadata_authority="advisory",
    ),
    isolation_policy=_pc.IsolationPolicy.WORKTREE_ALL_TIERS,
    needs_orphan_sweep=True,
    # Verified: kimi SILENTLY IGNORES an unrecognized effort (exit 0, default effort), so
    # pre-spend validation is the only protection (adapter.validate_request).
    effort_silently_ignored_upstream=True,
    effort_validation="token_floor_plus_catalog",
    usage_event_markers=USAGE_EVENT_MARKERS,
    failure_signatures=_pc.FailureSignatures(
        auth=tuple(f"(?i){p.pattern}" for p in _AUTH_PATTERNS),
        contract_drift=tuple(f"(?i){p.pattern}" for p in _DRIFT_PATTERNS),
        invalid_model=tuple(f"(?i){p.pattern}" for p in _INVALID_MODEL_PATTERNS),
        rate_limited=tuple(f"(?i){p.pattern}" for p in _RATE_LIMIT_PATTERNS),
    ),
    limits=_pc.Limits(
        max_argv_prompt_chars=MAX_ARGV_PROMPT_CHARS,
        handshake_dir_name=HANDSHAKE_DIR_PREFIX,
        answer_file_name=ANSWER_FILE_NAME,
    ),
)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_kimi_contract.py tests/test_surface_honesty.py -q --no-cov`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests
git add src/amicus/backends/kimi docs/kimi-help tests/test_kimi_contract.py tests/test_surface_honesty.py
git commit -m "feat(backends): add the kimi CLI contract with 0.41.0 evidence"
```

---

### Task 2: Config, the binary resolver, and the Kimi spend guard

**Files:**
- Create: `src/amicus/backends/kimi/config.py`, `src/amicus/backends/kimi/binary.py`
- Modify: `tests/conftest.py` (Kimi guard, `clean_env`, `pinned_kimi_bin`)
- Test: `tests/test_kimi_config.py`, `tests/test_kimi_binary.py`, `tests/test_conftest_guards.py` (append)

**Interfaces:**
- Consumes: `contract.SUPPORTED_VERSIONS`, `contract.KIMI_BIN` (Task 1); `amicus.config.envspec.{EnvNamespace, EnvVar, EnvConflictError, is_env_placeholder}`; `amicus.config.settings(environ)` for `state_dir`.
- Produces: `config.PREFIX = "AMICUS_KIMI_"`, `config.ENV: EnvNamespace`, `config.VALID_ISOLATIONS = ("inherit", "ignore-skills")`, `config.ExtraArgs(tokens, option_count, configured, error)` with `.valid`, `config.parse_extra_args(raw) -> ExtraArgs`, `config.KimiConfig(bin_override, extra_args, model, reasoning_effort, isolation, supported_versions, state_dir, warnings, errors)`, `config.load_config(environ=None) -> KimiConfig`, `config.skills_dir_for(isolation, state_dir) -> str | None`, `config.parse_version(text) -> tuple[int, int] | None`, `config.version_supported(version, config) -> bool | None`; `binary.BinaryNotFoundError`, `binary.ENV_VAR = "AMICUS_KIMI_BIN"`, `binary.kimi_bin(config) -> str`, `binary.KimiBinary(config)` with `.resolve() -> str | None` and `.override_error() -> str | None`; conftest `NEVER_SPAWN_KIMI`, fixture `pinned_kimi_bin`.

- [ ] **Step 1: Write the failing tests**

`tests/test_kimi_config.py`:

```python
"""AMICUS_KIMI_* resolution: legacy shim, isolation default, refused extra args, versions."""

from __future__ import annotations

from pathlib import Path

from amicus.backends.kimi import config as kc
from amicus.backends.kimi import contract


def test_namespace_declares_the_six_settings_with_legacy_twins():
    names = kc.ENV.names()
    assert names == (
        "AMICUS_KIMI_BIN",
        "AMICUS_KIMI_EXTRA_ARGS",
        "AMICUS_KIMI_MODEL",
        "AMICUS_KIMI_REASONING_EFFORT",
        "AMICUS_KIMI_ISOLATION",
        "AMICUS_KIMI_SUPPORTED_VERSIONS",
    )
    assert kc.ENV.var("AMICUS_KIMI_BIN").legacy == ()
    assert kc.ENV.var("AMICUS_KIMI_MODEL").legacy == ("MOONBRIDGE_MODEL",)
    assert kc.ENV.prefix == contract.CONTRACT.env_prefix


def test_defaults_and_state_dir(tmp_path):
    cfg = kc.load_config({"AMICUS_STATE_DIR": str(tmp_path / "state")})
    assert cfg.bin_override is None and cfg.model is None and cfg.reasoning_effort is None
    assert cfg.isolation == "inherit" and cfg.supported_versions == contract.SUPPORTED_VERSIONS
    assert cfg.state_dir == tmp_path / "state" and cfg.warnings == () and cfg.errors == ()
    assert not cfg.extra_args.configured and cfg.extra_args.valid


def test_legacy_names_are_read_with_a_warning_and_conflicts_are_errors():
    cfg = kc.load_config({"MOONBRIDGE_MODEL": "k3", "MOONBRIDGE_ISOLATION": "ignore-skills"})
    assert cfg.model == "k3" and cfg.isolation == "ignore-skills"
    assert any("read from legacy MOONBRIDGE_MODEL" in w for w in cfg.warnings)
    conflict = kc.load_config({"AMICUS_KIMI_MODEL": "a", "MOONBRIDGE_MODEL": "b"})
    assert conflict.model == "a" and any("different values" in e for e in conflict.errors)


def test_bad_isolation_warns_and_falls_back():
    cfg = kc.load_config({"AMICUS_KIMI_ISOLATION": "ignore-config"})
    assert cfg.isolation == "inherit"
    assert any("AMICUS_KIMI_ISOLATION" in w and "ignore-skills" in w for w in cfg.warnings)


def test_extra_args_are_always_refused_with_the_reason():
    refused = kc.parse_extra_args("-p secret-prompt")
    assert refused.configured and not refused.valid and refused.tokens == ()
    assert refused.error is not None
    assert "unsupported argument: -p" in refused.error and "prompt flag" in refused.error
    assert "secret-prompt" not in refused.error
    assert kc.parse_extra_args("'unbalanced").error == "could not tokenize (unbalanced quotes?)"
    assert kc.parse_extra_args("   ").error == "no options found"
    assert kc.load_config({"AMICUS_KIMI_EXTRA_ARGS": "--model x"}).extra_args.valid is False
    assert kc.load_config({"AMICUS_KIMI_EXTRA_ARGS": ""}).extra_args.configured is False


def test_supported_versions_and_version_parsing():
    cfg = kc.load_config({"AMICUS_KIMI_SUPPORTED_VERSIONS": "0.41, 1.0"})
    assert cfg.supported_versions == frozenset({(0, 41), (1, 0)})
    assert kc.load_config({"AMICUS_KIMI_SUPPORTED_VERSIONS": "x"}).supported_versions == (
        contract.SUPPORTED_VERSIONS
    )
    assert kc.parse_version("0.41.0") == (0, 41) and kc.parse_version("kimi 1.2.3\n") == (1, 2)
    assert kc.parse_version("nope") is None and kc.parse_version(None) is None
    assert kc.version_supported("0.41.0", cfg) is True
    assert kc.version_supported("0.30.0", cfg) is False
    assert kc.version_supported(None, cfg) is None


def test_skills_dir_for_creates_an_empty_dir_only_for_ignore_skills(tmp_path):
    assert kc.skills_dir_for("inherit", tmp_path) is None
    path = kc.skills_dir_for("ignore-skills", tmp_path)
    assert path == str(tmp_path / "empty-skills") and Path(path).is_dir()
    assert list(Path(path).iterdir()) == []
```

`tests/test_kimi_binary.py`:

```python
"""The kimi binary resolver: override wins and fails loudly; PATH; bare literal."""

from __future__ import annotations

import os
import stat

import pytest

from amicus.backends.kimi import binary
from amicus.backends.kimi import config as kc


def _exe(tmp_path, name="kimi"):
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_usable_override_is_used_exactly_as_given(tmp_path):
    exe = _exe(tmp_path)
    cfg = kc.load_config({"AMICUS_KIMI_BIN": str(exe)})
    assert binary.kimi_bin(cfg) == str(exe)
    resolver = binary.KimiBinary(cfg)
    assert resolver.resolve() == str(exe) and resolver.override_error() is None


def test_unusable_override_is_loud_and_never_echoes_its_value(tmp_path):
    cfg = kc.load_config({"AMICUS_KIMI_BIN": str(tmp_path / "missing-secret-name")})
    with pytest.raises(binary.BinaryNotFoundError) as exc:
        binary.kimi_bin(cfg)
    assert "AMICUS_KIMI_BIN" in str(exc.value) and "missing-secret-name" not in str(exc.value)
    resolver = binary.KimiBinary(cfg)
    assert resolver.resolve() is None and "AMICUS_KIMI_BIN" in (resolver.override_error() or "")
    directory = kc.load_config({"AMICUS_KIMI_BIN": str(tmp_path)})
    assert binary.KimiBinary(directory).resolve() is None


def test_path_search_then_bare_literal(tmp_path, monkeypatch, clean_env):
    monkeypatch.delenv("AMICUS_KIMI_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    cfg = kc.load_config({})
    assert binary.kimi_bin(cfg) == "kimi"
    exe = _exe(tmp_path)
    assert binary.kimi_bin(cfg) == str(exe)
    assert os.access(exe, os.X_OK)
```

Append to `tests/test_conftest_guards.py`:

```python
def test_never_spawn_kimi_env_is_set_to_the_unusable_path():
    from tests.conftest import NEVER_SPAWN_KIMI

    assert os.environ["AMICUS_KIMI_BIN"] == NEVER_SPAWN_KIMI
    assert not Path(NEVER_SPAWN_KIMI).exists()


def test_the_real_kimi_plugin_config_does_not_resolve_a_binary():
    from amicus.backends.kimi import binary, config

    assert binary.KimiBinary(config.load_config()).resolve() is None


def test_positive_control_a_usable_kimi_override_does_resolve(monkeypatch, tmp_path):
    from amicus.backends.kimi import binary, config

    exe = tmp_path / "kimi"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    monkeypatch.setenv("AMICUS_KIMI_BIN", str(exe))
    assert binary.KimiBinary(config.load_config()).resolve() == str(exe)
```

(`os` and `Path` are already imported at the top of that file; if not, add `import os` and `from pathlib import Path`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_kimi_config.py tests/test_kimi_binary.py tests/test_conftest_guards.py -q --no-cov`
Expected: import errors for `amicus.backends.kimi.config` / `.binary`; the conftest tests fail on `NEVER_SPAWN_KIMI`.

- [ ] **Step 3: Write config.py**

```python
"""Kimi-side configuration: the AMICUS_KIMI_* namespace (legacy MOONBRIDGE_ shim), the
resolved KimiConfig, the refuse-all extra-args parser, isolation → skills dir, and version
parsing. Ported from moonbridge `config.py`; tiers, sandbox defaults and WORKTREE_BASE are
not ported (amicus has kinds, not tiers, and one worktree policy)."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.core import redaction

from amicus.backends.kimi import contract
from amicus.config import settings as global_settings
from amicus.config.envspec import EnvConflictError, EnvNamespace, EnvVar, is_env_placeholder

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

PREFIX = "AMICUS_KIMI_"
_LEGACY = "MOONBRIDGE_"

ENV = EnvNamespace(
    prefix=PREFIX,
    vars=(
        EnvVar(
            f"{PREFIX}BIN",
            "Explicit path to the kimi executable; used exactly as given.",
            None,
            (),
        ),
        EnvVar(
            f"{PREFIX}EXTRA_ARGS",
            "Operator passthrough of extra kimi options. kimi exposes no option amicus can "
            "pass safely, so any value is refused and reported by amicus_backends.",
            None,
            (f"{_LEGACY}EXTRA_ARGS",),
        ),
        EnvVar(
            f"{PREFIX}MODEL",
            "Default model ALIAS (from kimi's config.toml) when a call omits `model`.",
            None,
            (f"{_LEGACY}MODEL",),
        ),
        EnvVar(
            f"{PREFIX}REASONING_EFFORT",
            "Default reasoning effort when a call omits `reasoning_effort`.",
            None,
            (f"{_LEGACY}REASONING_EFFORT",),
        ),
        EnvVar(
            f"{PREFIX}ISOLATION",
            "Default backend_options.isolation: inherit | ignore-skills.",
            "inherit",
            (f"{_LEGACY}ISOLATION",),
        ),
        EnvVar(
            f"{PREFIX}SUPPORTED_VERSIONS",
            "Comma-separated kimi major.minor versions treated as supported (advisory).",
            None,
            (f"{_LEGACY}SUPPORTED_VERSIONS",),
        ),
    ),
)

VALID_ISOLATIONS = ("inherit", "ignore-skills")
DEFAULT_ISOLATION = "inherit"

# There is no safe passthrough: kimi reuses the short flags a Codex-style allowlist would
# accept for different things (`-p` is the PROMPT flag, `-c` is --continue), and
# `--add-dir` would punch through worktree isolation.
NO_PASSTHROUGH_REASON = (
    "kimi exposes no option amicus can pass through safely (-p is its prompt flag, -c is "
    "--continue, --add-dir defeats isolation); unset this variable"
)


@dataclass(frozen=True)
class ExtraArgs:
    """Parsed AMICUS_KIMI_EXTRA_ARGS. `tokens` is always empty: the allowlist is empty and
    a configured value only yields a value-free `error` naming the first token."""

    tokens: tuple[str, ...] = ()
    option_count: int = 0
    configured: bool = False
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None


def _safe_token(token: str) -> str:
    return redaction.sanitize_echo(token)[:60]


def parse_extra_args(raw: str) -> ExtraArgs:
    """Tokenize a non-blank value; every token is refused with the reason. Never raises."""
    try:
        toks = shlex.split(raw)
    except ValueError:
        return ExtraArgs(configured=True, error="could not tokenize (unbalanced quotes?)")
    if not toks:
        return ExtraArgs(configured=True, error="no options found")
    return ExtraArgs(
        configured=True,
        option_count=len(toks),
        error=f"unsupported argument: {_safe_token(toks[0])} — {NO_PASSTHROUGH_REASON}",
    )


@dataclass(frozen=True)
class KimiConfig:
    bin_override: str | None
    extra_args: ExtraArgs
    model: str | None
    reasoning_effort: str | None
    isolation: str
    supported_versions: frozenset[tuple[int, int]]
    state_dir: Path
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _parse_supported_versions(raw: str | None) -> frozenset[tuple[int, int]]:
    if not raw:
        return contract.SUPPORTED_VERSIONS
    parsed: set[tuple[int, int]] = set()
    for part in raw.split(","):
        bits = part.strip().split(".")
        if len(bits) < 2:
            continue
        try:
            parsed.add((int(bits[0]), int(bits[1])))
        except ValueError:
            return contract.SUPPORTED_VERSIONS
    return frozenset(parsed) or contract.SUPPORTED_VERSIONS


def load_config(environ: Mapping[str, str] | None = None) -> KimiConfig:
    """Resolve every AMICUS_KIMI_* setting once. Never raises: conflicts and bad values ride
    `warnings`/`errors` so amicus_backends can report them."""
    report = ENV.report(environ)
    warnings = list(report.warnings)
    errors = list(report.errors)

    def get(name: str) -> str | None:
        try:
            return ENV.resolve(name, environ).value
        except EnvConflictError:
            import os  # noqa: PLC0415

            env = os.environ if environ is None else environ
            own = env.get(name)
            if is_env_placeholder(own):
                own = None
            return own if own is not None else ENV.var(name).default

    isolation = get(f"{PREFIX}ISOLATION") or DEFAULT_ISOLATION
    if isolation not in VALID_ISOLATIONS:
        warnings.append(
            f"{PREFIX}ISOLATION={isolation!r} is not one of {', '.join(VALID_ISOLATIONS)}; "
            f"using {DEFAULT_ISOLATION}"
        )
        isolation = DEFAULT_ISOLATION
    raw_extra = get(f"{PREFIX}EXTRA_ARGS")
    extra = parse_extra_args(raw_extra) if raw_extra and raw_extra.strip() else ExtraArgs()
    return KimiConfig(
        bin_override=get(f"{PREFIX}BIN") or None,
        extra_args=extra,
        model=get(f"{PREFIX}MODEL") or None,
        reasoning_effort=get(f"{PREFIX}REASONING_EFFORT") or None,
        isolation=isolation,
        supported_versions=_parse_supported_versions(get(f"{PREFIX}SUPPORTED_VERSIONS")),
        state_dir=global_settings(environ).state_dir,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def skills_dir_for(isolation: str, state_dir: Path) -> str | None:
    """Directory for --skills-dir under `isolation`, or None to leave discovery alone.
    'ignore-skills' points kimi at a stable empty directory; built-in skills still load."""
    if isolation != "ignore-skills":
        return None
    path = Path(state_dir) / "empty-skills"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def parse_version(version: str | None) -> tuple[int, int] | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.(\d+)\.\d+", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def version_supported(version: str | None, config: KimiConfig) -> bool | None:
    parsed = parse_version(version)
    if parsed is None:
        return None
    return parsed in config.supported_versions
```

- [ ] **Step 4: Write binary.py**

```python
"""Resolve the `kimi` executable. Precedence: AMICUS_KIMI_BIN (used exactly as given; an
unusable value is a loud BinaryNotFoundError, never a fallthrough) → shutil.which → the bare
literal "kimi" so a spawn fails as binary-missing rather than "no invocation possible"."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.backends.kimi import contract

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.kimi.config import KimiConfig

ENV_VAR = "AMICUS_KIMI_BIN"


class BinaryNotFoundError(RuntimeError):
    """AMICUS_KIMI_BIN names something that is not an executable file."""


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def kimi_bin(config: KimiConfig) -> str:
    """The token to spawn. Raises BinaryNotFoundError for an unusable override; the message
    names the env var and never its value (operator-controlled, unbounded)."""
    if config.bin_override:
        if not _is_executable_file(Path(config.bin_override)):
            raise BinaryNotFoundError(
                f"{ENV_VAR} is set, but it does not name an executable file on disk "
                "(missing path, a directory, or no execute bit)."
            )
        return config.bin_override
    return shutil.which(contract.KIMI_BIN) or contract.KIMI_BIN


class KimiBinary:
    """The plugin's BinaryResolver: None only when the override is unusable."""

    def __init__(self, config: KimiConfig) -> None:
        self._config = config

    def resolve(self) -> str | None:
        try:
            return kimi_bin(self._config)
        except BinaryNotFoundError:
            return None

    def override_error(self) -> str | None:
        try:
            kimi_bin(self._config)
        except BinaryNotFoundError as exc:
            return str(exc)
        return None
```

- [ ] **Step 5: Extend conftest.py**

Add beside `NEVER_SPAWN_CODEX`:

```python
NEVER_SPAWN_KIMI = "/nonexistent/amicus-test-kimi"
```

Add a second autouse guard after `_never_spawn_real_codex`, and set the same variable in `clean_env`:

```python
@pytest.fixture(autouse=True)
def _never_spawn_real_kimi(monkeypatch):
    """No unit test may run the real kimi CLI: an unusable AMICUS_KIMI_BIN makes every kimi
    run, probe and catalog read short-circuit. Tests that want a run point the override at
    the `fake_kimi` fixture; the live suite (tests/test_kimi_live.py) deletes it."""
    monkeypatch.setenv("AMICUS_KIMI_BIN", NEVER_SPAWN_KIMI)
```

In `clean_env`, after the codex line: `monkeypatch.setenv("AMICUS_KIMI_BIN", NEVER_SPAWN_KIMI)`.

Add the pinned-binary fixture after `pinned_codex_bin`:

```python
@pytest.fixture
def pinned_kimi_bin(monkeypatch):
    """Let AMICUS_KIMI_BIN=/KIMI resolve without a file on disk (argv tests only)."""
    from amicus.backends.kimi import binary

    monkeypatch.setattr(
        binary, "_is_executable_file", lambda path: str(path) == "/KIMI" or path.is_file()
    )
    return monkeypatch
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_kimi_config.py tests/test_kimi_binary.py tests/test_conftest_guards.py tests/test_config.py -q --no-cov`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests && uv run --no-sync ty check
git add src/amicus/backends/kimi tests/conftest.py tests/test_kimi_config.py tests/test_kimi_binary.py tests/test_conftest_guards.py
git commit -m "feat(backends): add the AMICUS_KIMI_* namespace, binary resolver and spend guard"
```

---

### Task 3: The stream-json normalizer and the live model catalog

**Files:**
- Create: `src/amicus/backends/kimi/normalize.py`, `src/amicus/backends/kimi/models.py`
- Test: `tests/test_kimi_normalize.py`, `tests/test_kimi_models.py`

**Interfaces:**
- Consumes: `contract.*` (Task 1), `config.KimiConfig`, `binary.KimiBinary` (Task 2), `amicus.schemas.structured.classify_structured`, `amicus.plugin.{ModelEntry, ModelListing}`, `pontonier.backend.protocol.Usage`.
- Produces: `normalize.parse_event_metadata(events: str) -> tuple[Usage | None, str | None]`, `normalize.extract_final_message(events) -> str | None`, `normalize.extract_error_message(events) -> str | None`, `normalize.parse_structured(text: str | None) -> dict | None`; `models.parse_catalog(payload: object) -> list[ModelEntry] | None`, `models.probe_catalog(binary: str, timeout_seconds=10) -> object | None`, `models.KimiModels(config, binary)` with `.read(force: bool = False) -> ModelListing` (`source` is `"live"` or `"none"`, cached `contract.HELP_CACHE_TTL_SECONDS`), `models.supported_efforts_for(model: str | None, listing: ModelListing) -> tuple[str, ...] | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_kimi_normalize.py`:

```python
"""Tolerant stream-json parsing: final message, error text, usage, session id, structured."""

from __future__ import annotations

from amicus.backends.kimi import normalize

VERSION = '{"role":"meta","type":"system.version","version":"0.41.0"}\n'
RESUME = '{"role":"meta","type":"session.resume_hint","session_id":"session_abc"}\n'


def test_last_assistant_text_wins_and_tool_call_only_lines_are_skipped():
    events = (
        VERSION
        + '{"role":"assistant","tool_calls":[{"id":"Read:0"}]}\n'
        + '{"role":"tool","tool_call_id":"Read:0","content":"file body"}\n'
        + '{"role":"assistant","content":"first"}\n'
        + '{"role":"assistant","content":"  final  "}\n'
        + '{"role":"assistant","content":"","tool_calls":[]}\n'
        + '{"type":"goal.summary","tokensUsed":5}\n'
        + RESUME
    )
    assert normalize.extract_final_message(events) == "final"


def test_no_assistant_text_returns_none_and_garbage_is_skipped():
    assert normalize.extract_final_message(VERSION + RESUME) is None
    assert normalize.extract_final_message("{not json\n[1,2]\nplain text\n") is None
    assert normalize.extract_final_message("") is None


def test_session_id_and_usage_are_read_tolerantly():
    events = (
        VERSION
        + '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":80}}\n'
        + RESUME
    )
    usage, session_id = normalize.parse_event_metadata(events)
    assert session_id == "session_abc"
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == (100, 20, 80)
    assert usage.total_tokens == 120  # derived: kimi emits no total
    explicit = '{"type":"x","usage":{"input_tokens":1,"output_tokens":1,"total_tokens":9}}\n'
    assert normalize.parse_event_metadata(explicit)[0].total_tokens == 9
    assert normalize.parse_event_metadata(VERSION + RESUME) == (None, "session_abc")
    assert normalize.parse_event_metadata("") == (None, None)


def test_error_message_is_unwrapped_from_error_events():
    events = (
        '{"type":"turn.failed","message":"{\\"error\\": {\\"message\\": \\"inner text\\"}}"}\n'
    )
    assert normalize.extract_error_message(events) == "inner text"
    plain = '{"type":"error","error":{"message":"plain"}}\n'
    assert normalize.extract_error_message(plain) == "plain"
    assert normalize.extract_error_message(VERSION) is None
    assert normalize.extract_error_message('{"type":"error","message":"{broken"}\n') == "{broken"


def test_parse_structured_accepts_fenced_objects_only():
    assert normalize.parse_structured('```json\n{"summary": "s"}\n```') == {"summary": "s"}
    assert normalize.parse_structured("[1, 2]") is None
    assert normalize.parse_structured("prose") is None
    assert normalize.parse_structured(None) is None
```

`tests/test_kimi_models.py`:

```python
"""The live model catalog: allowlist-shaped parsing, shape-only effort tokens, the probe."""

from __future__ import annotations

import json

from pontonier.core.runtime import BINARY_NOT_FOUND, CommandRun

from amicus.backends.kimi import binary as kb
from amicus.backends.kimi import config as kc
from amicus.backends.kimi import models

PAYLOAD = {
    "providers": {"p1": {"apiKey": "sk-" + "s" * 40, "baseUrl": "https://private.example"}},
    "models": {
        "k3": {
            "displayName": "Kimi K3",
            "defaultEffort": "medium",
            "supportEfforts": ["low", "medium", "high", "xhigh", "not valid!"],
            "provider": "p1",
        },
        "bare": {},
        "bad alias!": {"supportEfforts": ["low"]},
        "empty": {"supportEfforts": []},
    },
}


def test_parse_catalog_reads_only_named_model_fields():
    entries = models.parse_catalog(PAYLOAD)
    assert entries is not None
    by_slug = {e.slug: e for e in entries}
    assert set(by_slug) == {"k3", "bare", "empty"}
    assert by_slug["k3"].display_name == "Kimi K3"
    assert by_slug["k3"].default_reasoning_effort == "medium"
    assert by_slug["k3"].supported_reasoning_efforts == ("low", "medium", "high", "xhigh")
    assert by_slug["bare"].supported_reasoning_efforts is None
    assert by_slug["empty"].supported_reasoning_efforts == ()
    assert "sk-" not in repr(entries) and "private.example" not in repr(entries)


def test_parse_catalog_returns_none_on_drift():
    assert models.parse_catalog([]) is None
    assert models.parse_catalog({"models": []}) is None
    assert models.parse_catalog({"models": {}}) is None
    assert models.parse_catalog({"models": {"k": {"supportEfforts": ["!!"]}}})[0].supported_reasoning_efforts is None


def test_supported_efforts_for_none_means_cannot_tell():
    listing = models.ModelListing(models=tuple(models.parse_catalog(PAYLOAD) or ()), source="live")
    assert models.supported_efforts_for("k3", listing) == ("low", "medium", "high", "xhigh")
    assert models.supported_efforts_for("bare", listing) is None
    assert models.supported_efforts_for("unlisted", listing) is None
    assert models.supported_efforts_for(None, listing) is None
    assert models.supported_efforts_for("empty", listing) == ()


def _reader(monkeypatch, stdout, exit_code=0, binary_missing=False):
    calls = []

    def fake(cmd, timeout_seconds, **k):
        calls.append(cmd)
        if binary_missing:
            return CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
        return CommandRun(stdout, "", exit_code, 1, False)

    monkeypatch.setattr(models.runtime, "run_sync_capture", fake)
    cfg = kc.load_config({"AMICUS_KIMI_BIN": "/KIMI"})
    return models.KimiModels(cfg, kb.KimiBinary(cfg)), calls


def test_read_probes_live_and_caches(pinned_kimi_bin, monkeypatch):
    reader, calls = _reader(monkeypatch, json.dumps(PAYLOAD))
    listing = reader.read()
    assert listing.source == "live" and [m.slug for m in listing.models] == ["k3", "bare", "empty"]
    assert calls == [["/KIMI", "provider", "list", "--json"]]
    assert reader.read().source == "live" and len(calls) == 1
    assert reader.read(force=True).source == "live" and len(calls) == 2


def test_read_reports_none_when_the_probe_fails(pinned_kimi_bin, monkeypatch):
    assert _reader(monkeypatch, "", exit_code=1)[0].read().source == "none"
    assert _reader(monkeypatch, "not json")[0].read().source == "none"
    assert _reader(monkeypatch, "x" * 2_000_000)[0].read().source == "none"
    assert _reader(monkeypatch, "", binary_missing=True)[0].read().source == "none"
    unresolved = models.KimiModels(kc.load_config({}), kb.KimiBinary(kc.load_config({})))
    assert unresolved.read().source == "none"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_kimi_normalize.py tests/test_kimi_models.py -q --no-cov`
Expected: import errors.

- [ ] **Step 3: Write normalize.py**

```python
"""Parse a `kimi -p` stream-json outcome tolerantly (ported from moonbridge `normalize.py`).
kimi has no --output-last-message: the final answer is the last assistant line with text (or,
for a write-capable run, the answer file the adapter reads). An event-schema change degrades
metadata rather than breaking a run."""

from __future__ import annotations

import json

from pontonier.backend.protocol import Usage

from amicus.backends.kimi import contract
from amicus.schemas.structured import classify_structured


def _events(events: str):
    for raw_line in events.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(event, dict):
            yield event


def parse_event_metadata(events: str) -> tuple[Usage | None, str | None]:
    """(usage, session_id), either None when the stream did not carry it. Never raises."""
    usage: Usage | None = None
    session_id: str | None = None
    for event in _events(events):
        session_id = session_id or _find_session_id(event)
        found = _find_usage(event)
        if found is not None:
            usage = found
    return usage, session_id


def extract_final_message(events: str) -> str | None:
    """The last `{"role":"assistant","content":...}` line with text; tool-call-only lines
    are the model calling a tool, not answering. None when nothing answered."""
    found: str | None = None
    for event in _events(events):
        # `goal.summary` lines carry no "role" at all, so read it tolerantly.
        if event.get(contract.ROLE_KEY) != contract.ROLE_ASSISTANT:
            continue
        content = event.get(contract.CONTENT_KEY)
        if isinstance(content, str) and content.strip():
            found = content.strip()
    return found


def extract_error_message(events: str) -> str | None:
    """A human-readable error from `error`/`*.failed` events on stdout; the message is
    sometimes itself a JSON blob ({"error": {"message": ...}}), unwrapped one level."""
    found: str | None = None
    for event in _events(events):
        marker = str(event.get(contract.TYPE_KEY) or "").lower()
        if "error" not in marker and "failed" not in marker:
            continue
        message = event.get("message")
        if isinstance(event.get("error"), dict):
            message = event["error"].get("message", message)
        if isinstance(message, str) and message:
            found = _unwrap_json_message(message)
    return found


def _unwrap_json_message(message: str) -> str:
    text = message.strip()
    if not text.startswith("{"):
        return text
    try:
        blob = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(blob, dict) and isinstance(blob.get("error"), dict):
        inner = blob["error"].get("message")
        if isinstance(inner, str) and inner:
            return inner
    return text


def _find_session_id(event: dict) -> str | None:
    for key in ("session_id", "sessionId", "thread_id", "threadId", "conversation_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    for nest in ("msg", "payload", "data"):
        inner = event.get(nest)
        if isinstance(inner, dict):
            found = _find_session_id(inner)
            if found:
                return found
    return None


def _find_usage(event: dict) -> Usage | None:
    marker = str(event.get(contract.TYPE_KEY) or event.get("msg") or "").lower()
    candidates: list[dict] = []
    if any(m.lower() in marker for m in contract.USAGE_EVENT_MARKERS):
        candidates.append(event)
    for key in ("usage", "token_usage", "tokens", "info"):
        inner = event.get(key)
        if isinstance(inner, dict):
            candidates.append(inner)
    for nest in ("msg", "payload", "data"):
        inner = event.get(nest)
        if isinstance(inner, dict):
            for key in ("usage", "token_usage", "tokens"):
                deep = inner.get(key)
                if isinstance(deep, dict):
                    candidates.append(deep)
    for blob in candidates:
        usage = _usage_from(blob)
        if usage is not None:
            return usage
    return None


def _usage_from(blob: dict) -> Usage | None:
    def _int(*names: str) -> int | None:
        for name in names:
            value = blob.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    input_tokens = _int("input_tokens", "prompt_tokens", "input")
    output_tokens = _int("output_tokens", "completion_tokens", "output")
    cached = _int("cached_input_tokens", "cache_read_input_tokens", "cached_tokens")
    total = _int("total_tokens", "total")
    if input_tokens is None and output_tokens is None and total is None:
        return None
    # kimi emits token_count without a total: derive it (cached is a subset of input).
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cached_input_tokens=cached,
    )


def parse_structured(text: str | None) -> dict | None:
    """The answer as a JSON object (code fence tolerated), else None (prose)."""
    status, parsed = classify_structured(text)
    return parsed if status == "ok" else None
```

- [ ] **Step 4: Write models.py**

```python
"""Read Kimi's configured model aliases for `model` and `reasoning_effort` discovery
(ported from moonbridge `kimi_models.py`). `-m` takes an ALIAS from the user's config.toml,
so the catalog is `kimi provider list --json`, read live and cached briefly in-process.

**The source contains secrets**: its `providers` block carries `apiKey` and `baseUrl`.
`parse_catalog` is allowlist-shaped — it reads named fields off `models` only — so a new
secret-bearing field upstream cannot leak by default. Authoritative for the alias set
(kimi rejects an unknown alias); advisory for efforts (see `supported_efforts_for`)."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from pontonier.core import redaction, runtime

from amicus.backends.kimi import contract
from amicus.plugin import ModelEntry, ModelListing

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.kimi.binary import KimiBinary
    from amicus.backends.kimi.config import KimiConfig

PROBE_TIMEOUT_SECONDS = 10


def _effort_token(value: object) -> str | None:
    """SHAPE only, never vocabulary: the catalog is what the model DECLARES."""
    if not isinstance(value, str) or not contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch(value):
        return None
    return value


def _supported_efforts(raw: object) -> tuple[str, ...] | None:
    """None = absent or unusable; () = an explicitly empty advertised set."""
    if not isinstance(raw, list):
        return None
    efforts: list[str] = []
    for entry in raw[: contract.SUPPORTED_EFFORTS_MAX_ENTRIES]:
        token = _effort_token(entry)
        if token is not None and token not in efforts:
            efforts.append(token)
    if raw and not efforts:
        return None
    return tuple(efforts)


def _label(value: object, cap: int) -> str | None:
    if not isinstance(value, str) or len(value) > cap:
        return None
    return redaction.sanitize_echo(value) or None


def parse_catalog(payload: object) -> list[ModelEntry] | None:
    """Model aliases from a `kimi provider list --json` payload, or None if it drifted.
    Reads ONLY the `models` map; the sibling `providers` map is never touched."""
    if not isinstance(payload, dict):
        return None
    entries = payload.get("models")
    if not isinstance(entries, dict):
        return None
    models: list[ModelEntry] = []
    for alias, entry in list(entries.items())[: contract.MODELS_CACHE_MAX_ENTRIES]:
        if not isinstance(alias, str) or not contract.MODEL_SLUG_PATTERN.match(alias):
            continue
        fields = entry if isinstance(entry, dict) else {}
        models.append(
            ModelEntry(
                slug=alias,
                display_name=_label(fields.get("displayName"), 128),
                default_reasoning_effort=_effort_token(fields.get("defaultEffort")),
                supported_reasoning_efforts=_supported_efforts(fields.get("supportEfforts")),
            )
        )
    return models or None


def probe_catalog(binary: str, timeout_seconds: int = PROBE_TIMEOUT_SECONDS) -> object | None:
    """The free provider-list probe's parsed payload, or None."""
    run = runtime.run_sync_capture(
        [binary, *contract.PROVIDER_LIST_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.timed_out or run.exit_code != 0:
        return None
    if len(run.stdout.encode("utf-8", "replace")) > contract.MODELS_CACHE_MAX_BYTES:
        return None
    try:
        return json.loads(run.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


class KimiModels:
    """The plugin's ModelCatalogReader: live probe, cached for HELP_CACHE_TTL_SECONDS so a
    worker validates an effort and lists models with one spawn."""

    def __init__(self, config: KimiConfig, binary: KimiBinary) -> None:
        self._config = config
        self._binary = binary
        self._cache: tuple[float, ModelListing] | None = None

    def read(self, force: bool = False) -> ModelListing:
        now = time.monotonic()
        if not force and self._cache is not None:
            stamped, listing = self._cache
            if now - stamped < contract.HELP_CACHE_TTL_SECONDS:
                return listing
        binary = self._binary.resolve()
        parsed = parse_catalog(probe_catalog(binary)) if binary is not None else None
        listing = (
            ModelListing(models=tuple(parsed), source="live")
            if parsed
            else ModelListing(models=(), source="none")
        )
        self._cache = (now, listing)
        return listing


def supported_efforts_for(model: str | None, listing: ModelListing) -> tuple[str, ...] | None:
    """Efforts the named alias declares, or None for "cannot tell" (no model, absent
    catalog, unlisted alias, or an alias declaring nothing). Callers MUST treat None as
    "do not reject": kimi ignores an unrecognized effort, so refusing on a guess blocks a
    valid run while accepting on a guess only risks the effort being ignored."""
    if not model:
        return None
    for entry in listing.models:
        if entry.slug == model:
            return entry.supported_reasoning_efforts
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_kimi_normalize.py tests/test_kimi_models.py -q --no-cov`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests && uv run --no-sync ty check
git add src/amicus/backends/kimi tests/test_kimi_normalize.py tests/test_kimi_models.py
git commit -m "feat(backends): add the kimi stream-json normalizer and live model catalog"
```

---

### Task 4: The CLI layer: handshake, argv, probes, classifier

**Files:**
- Create: `src/amicus/backends/kimi/cli.py`
- Test: `tests/test_kimi_cli.py`

**Interfaces:**
- Consumes: `contract.*` (Task 1), `normalize.extract_error_message` (Task 3), `pontonier.conventions.preflight.{FlagSupport, is_supported}`, `pontonier.core.{redaction, runtime}`, `pontonier.backend.protocol.{ClassifiedFailure, RepairHint}`.
- Produces: `cli.read_only_agent_document() -> str`; `cli.schema_instruction(schema: dict) -> str`; `cli.build_exec_command(*, kimi_bin, read_only, prompt_pointer, model=None, agent_file_path=None, skills_dir=None, flag_support) -> tuple[list[str], list[str]]` (raises `ValueError` for a read-only run without an agent file or an oversized pointer); `cli.build_run_env(base: dict[str, str], reasoning_effort: str | None) -> dict[str, str]`; `cli.create_handshake_dir() -> str`; `cli.write_handshake(run_dir, prompt_text, *, read_only) -> dict[str, str]` (keys `prompt`, and `agent` or `answer`); `cli.build_prompt_pointer(paths, *, read_only) -> str`; `cli.read_answer_file(path) -> str`; `cli.kimi_version(binary, timeout_seconds=10) -> str | None`; `cli.login_status(binary, timeout_seconds=10) -> tuple[bool | None, str | None]`; `cli.version_display(version) -> str | None`; `cli.classify_failure(run, *, last_message, events, reasoning_effort, sanitize) -> ClassifiedFailure`.

- [ ] **Step 1: Write the failing tests**

`tests/test_kimi_cli.py`:

```python
"""kimi -p staging and classification: the read-only guarantee, the handshake, the pointer,
the answer-file reader, the free probes, and the classifier's precedence and sanitization."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pontonier.conventions.preflight import FlagSupport
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun

from amicus.backends.kimi import cli, contract

ALL = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)
RO = {"prompt": "/T/prompt.md", "agent": "/T/readonly-agent.md"}
RW = {"prompt": "/T/prompt.md", "answer": "/T/answer.md"}


def _cmd(**kw):
    base = dict(
        kimi_bin="/KIMI",
        read_only=True,
        prompt_pointer=cli.build_prompt_pointer(RO, read_only=True),
        agent_file_path=RO["agent"],
        flag_support=ALL,
    )
    base.update(kw)
    return cli.build_exec_command(**base)


# --- argv --------------------------------------------------------------------------------


def test_read_only_without_an_agent_file_raises_rather_than_degrading():
    with pytest.raises(ValueError, match="agent file"):
        _cmd(agent_file_path=None)


def test_read_only_sends_the_agent_file_and_it_is_never_help_gated():
    cmd, dropped = _cmd(flag_support=FlagSupport(supported=frozenset(), help_parsed=True))
    assert cmd[cmd.index("--agent-file") + 1] == RO["agent"] and dropped == []
    assert "--agent-file" not in contract.HELP_GATED_FLAGS


def test_argv_shape_and_never_sent_flags():
    cmd, dropped = _cmd(model="k3", skills_dir="/T/empty-skills")
    assert cmd[0] == "/KIMI" and cmd[1] == "--prompt" and cmd[3:5] == ["--output-format", "stream-json"]
    assert cmd[cmd.index("--model") + 1] == "k3" and cmd[cmd.index("--skills-dir") + 1] == "/T/empty-skills"
    assert dropped == []
    assert contract.ADD_DIR_FLAG not in cmd
    assert not set(contract.PROMPT_MODE_INCOMPATIBLE_FLAGS) & set(cmd)


def test_model_and_skills_dir_are_help_gated_with_their_values():
    cmd, dropped = _cmd(model="k3", skills_dir="/T/s", flag_support=NO_MODEL)
    assert "--model" not in cmd and "k3" not in cmd and "/T/s" not in cmd
    assert dropped == ["--model", "--skills-dir"]
    fail_open, dropped2 = _cmd(model="k3", flag_support=FlagSupport(frozenset(), help_parsed=False))
    assert "--model" in fail_open and dropped2 == []


def test_an_oversized_pointer_is_refused():
    with pytest.raises(ValueError, match="argv prompt exceeds"):
        _cmd(prompt_pointer="x" * (contract.MAX_ARGV_PROMPT_CHARS + 1))


def test_delegate_argv_has_no_agent_file():
    cmd, _ = _cmd(read_only=False, prompt_pointer=cli.build_prompt_pointer(RW, read_only=False), agent_file_path=None)
    assert "--agent-file" not in cmd and "/T/answer.md" in cmd[2]


# --- env ---------------------------------------------------------------------------------


def test_run_env_pins_the_output_format_and_sets_effort_only_when_given():
    env = cli.build_run_env({"HOME": "/h", "KIMI_MODEL_OUTPUT_FORMAT": "text"}, "high")
    assert env["KIMI_MODEL_THINKING_EFFORT"] == "high" and env["HOME"] == "/h"
    assert env["KIMI_MODEL_OUTPUT_FORMAT"] == "stream-json"
    assert "KIMI_MODEL_THINKING_EFFORT" not in cli.build_run_env({}, None)


# --- the read-only agent and the handshake ------------------------------------------------


def test_the_read_only_agent_document_grants_only_the_three_tools():
    doc = cli.read_only_agent_document()
    assert doc.startswith("---\nname: amicus-readonly\n")
    tools_block = doc.split("tools:\n", 1)[1].split("---", 1)[0]
    assert [line.strip("- ").strip() for line in tools_block.strip().splitlines()] == list(
        contract.READ_ONLY_AGENT_TOOLS
    )
    assert "Bash" not in doc and "Write" not in doc


def test_handshake_files_for_each_tier_are_private_and_outside_the_repo(tmp_path):
    run_dir = cli.create_handshake_dir()
    try:
        assert Path(run_dir).name.startswith(contract.HANDSHAKE_DIR_PREFIX)
        assert not (Path(run_dir) / ".git").exists() and str(tmp_path) not in run_dir
        ro = cli.write_handshake(run_dir, "PROMPT", read_only=True)
        assert set(ro) == {"prompt", "agent"}
        assert Path(ro["prompt"]).read_text() == "PROMPT"
        assert Path(ro["agent"]).read_text() == cli.read_only_agent_document()
        assert stat.S_IMODE(os.stat(ro["prompt"]).st_mode) == 0o600
        rw = cli.write_handshake(cli.create_handshake_dir(), "P", read_only=False)
        assert set(rw) == {"prompt", "answer"} and not Path(rw["answer"]).exists()
    finally:
        import shutil

        shutil.rmtree(run_dir, ignore_errors=True)


def test_handshake_refuses_to_follow_a_planted_symlink(tmp_path):
    run_dir = tmp_path / "hs"
    run_dir.mkdir()
    target = tmp_path / "elsewhere.md"
    (run_dir / contract.PROMPT_FILE_NAME).symlink_to(target)
    with pytest.raises(FileExistsError):
        cli.write_handshake(str(run_dir), "PROMPT", read_only=True)
    assert not target.exists()


def test_prompt_pointers_stay_small_and_name_the_files():
    ro = cli.build_prompt_pointer(RO, read_only=True)
    rw = cli.build_prompt_pointer(RW, read_only=False)
    assert RO["prompt"] in ro and RW["answer"] not in ro
    assert RW["prompt"] in rw and RW["answer"] in rw
    assert len(ro) < 300 and len(rw) < 300


def test_schema_instruction_names_the_schema():
    text = cli.schema_instruction({"type": "object"})
    assert text.startswith("\n\n# Required output format") and '"type": "object"' in text


# --- the answer file ------------------------------------------------------------------------


def test_answer_file_reader_is_bounded_and_refuses_symlinks_and_fifos(tmp_path):
    normal = tmp_path / "a.md"
    normal.write_text("  answer  \n")
    assert cli.read_answer_file(str(normal)) == "answer"
    link = tmp_path / "link.md"
    link.symlink_to(normal)
    assert cli.read_answer_file(str(link)) == ""
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * (contract.MAX_ANSWER_BYTES + 1))
    assert cli.read_answer_file(str(big)) == ""
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    assert cli.read_answer_file(str(fifo)) == ""
    assert cli.read_answer_file(str(tmp_path / "missing")) == ""
    binary = tmp_path / "b.md"
    binary.write_bytes(b"\xff\xfeok")
    assert cli.read_answer_file(str(binary)).endswith("ok")


# --- probes ------------------------------------------------------------------------------


def _probe(monkeypatch, stdout="", stderr="", exit_code=0, timed_out=False, missing=False):
    def fake(cmd, timeout_seconds, **k):
        if missing:
            return CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
        return CommandRun(stdout, stderr, exit_code, 1, timed_out)

    monkeypatch.setattr(cli.runtime, "run_sync_capture", fake)


def test_version_probe(monkeypatch):
    _probe(monkeypatch, stdout="0.41.0\n")
    assert cli.kimi_version("/KIMI") == "0.41.0"
    _probe(monkeypatch, missing=True)
    assert cli.kimi_version("/KIMI") is None
    assert cli.version_display("0.41.0\x1b[0m") == "0.41.0"


def test_login_status_counts_providers_and_never_echoes_them(monkeypatch):
    payload = '{"providers": {"p": {"apiKey": "sk-secret", "baseUrl": "https://x"}}, "models": {}}'
    _probe(monkeypatch, stdout=payload)
    ok, detail = cli.login_status("/KIMI")
    assert ok is True and detail == "Kimi reports 1 configured provider(s)."
    _probe(monkeypatch, stdout='{"providers": {}}')
    assert cli.login_status("/KIMI") == (False, "Kimi has no configured provider; run `kimi login`.")
    _probe(monkeypatch, stdout="garbage")
    assert cli.login_status("/KIMI") == (None, None)
    _probe(monkeypatch, exit_code=1)
    assert cli.login_status("/KIMI")[0] is False
    _probe(monkeypatch, missing=True)
    assert cli.login_status("/KIMI") == (None, None)
    _probe(monkeypatch, stdout="[1, 2]")
    assert cli.login_status("/KIMI")[0] is True


# --- classification ------------------------------------------------------------------------


def _run(stdout="", stderr="", exit_code=1, timed_out=False):
    return CommandRun(stdout, stderr, exit_code, 12, timed_out)


def _classify(run, **kw):
    base = dict(last_message=None, events=None, reasoning_effort=None, sanitize=None)
    base.update(kw)
    return cli.classify_failure(run, **base)


def test_missing_binary_and_timeout():
    assert _classify(_run(stderr=BINARY_NOT_FOUND, exit_code=127)).code == "kimi_not_found"
    assert _classify(_run(stderr=TIMED_OUT, exit_code=-9, timed_out=True)).code == "timeout"


def test_invalid_model_blames_the_argument_but_an_unresolved_default_does_not():
    f = _classify(_run(stderr='error: failed to run prompt: Model "x" is not configured in config.toml.'))
    assert f.code == "invalid_model" and f.details == {"field": "model"}
    assert f.repair is not None and f.repair.tool == "amicus_models"
    g = _classify(_run(stderr="error: failed to run prompt: model foo does not resolve to a configured provider"))
    assert g.code == "invalid_model" and g.details is None
    assert g.repair is not None and g.repair.next_step == "correct_config" and "default_model" in (g.repair.alternative or "")


def test_model_prose_discussing_the_failure_is_not_invalid_model():
    events = '{"role":"assistant","content":"the alias does not resolve to a configured provider"}\n'
    f = _classify(_run(stdout=events, exit_code=3), events=events, last_message="x")
    assert f.code == "nonzero_exit"


def test_drift_auth_and_rate_limit_precedence():
    assert _classify(_run(stderr="error: unknown option '--zap'")).code == "cli_contract_changed"
    assert _classify(_run(stderr="Cannot combine --prompt with --yolo.")).code == "cli_contract_changed"
    assert _classify(_run(stderr="401 Unauthorized")).code == "kimi_auth_required"
    rate = _classify(_run(stderr="429 Too Many Requests; retry-after: 5"))
    assert rate.code == "kimi_rate_limited" and rate.retry_after_ms == 5000
    assert _classify(_run(stderr="rate limit reached")).retry_after_ms == contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
    assert _classify(_run(stderr="rate limit; retry-after: 0")).retry_after_ms == 0
    both = _classify(_run(stderr="error: unknown option '--x' (429 rate limit)"))
    assert both.code == "cli_contract_changed"
    assert _classify(_run(stderr='error: unknown option; Model "x" is not configured in config.toml')).code == "cli_contract_changed"
    from_events = '{"type":"turn.failed","message":"rate limit reached; try again in 2 seconds"}\n'
    assert _classify(_run(stdout=from_events), events=from_events).retry_after_ms == 2000


def test_auth_is_also_detected_in_the_last_message():
    assert _classify(_run(exit_code=2), last_message="invalid api key").code == "kimi_auth_required"


def test_generic_failures_are_bounded_and_sanitized_before_truncation():
    secret = "sk-" + "c" * 32
    f = _classify(_run(stderr=f"boom token={secret}", exit_code=3))
    assert f.code == "nonzero_exit" and secret not in f.detail and "kimi exited 3" in f.detail
    straddling = "x" * 290 + f" token={secret}"
    g = _classify(_run(stderr=straddling, exit_code=2))
    assert "sk-c" not in g.detail and len(g.detail) <= 320
    h = _classify(_run(stderr="failed at /wt/abc/src/a.py", exit_code=2), sanitize=lambda t: t.replace("/wt/abc/", "./"))
    assert "/wt/abc" not in h.detail and "./src/a.py" in h.detail
    assert _classify(_run(stderr="\x1b[31mred\x1b[0m", exit_code=2)).detail.endswith("red")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_kimi_cli.py -q --no-cov`
Expected: import error for `amicus.backends.kimi.cli`.

- [ ] **Step 3: Write cli.py**

```python
"""Build the `kimi -p` invocation, stage the handshake files, run the free probes, and
classify a failed run into a pontonier ClassifiedFailure (ported from moonbridge `kimi.py`).

Two guarantees live here:

* Read-only runs really are read-only: a read-only run is given an --agent-file whose
  `tools:` list omits Bash and Write. That file is generated per run and is the ONLY thing
  standing between a consult and an unrestricted agent (the worktree is not a boundary),
  so `build_exec_command` refuses to build a read-only command without it.
* Gathered context never rides argv: the prompt is written to a handshake file OUTSIDE the
  workspace and argv carries a short pointer, because kimi ignores stdin and crashes past
  ~950k argv chars.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from stat import S_ISREG
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, RepairHint
from pontonier.conventions import preflight
from pontonier.core import redaction, runtime

from amicus.backends.kimi import contract, normalize

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from pontonier.conventions.preflight import FlagSupport
    from pontonier.core.runtime import CommandRun


def read_only_agent_document() -> str:
    """The generated agent profile that makes a run read-only. Its `tools:` list is
    guarantee-bearing (contract.READ_ONLY_AGENT_TOOLS): Bash and Write are absent."""
    tools = "\n".join(f"  - {t}" for t in contract.READ_ONLY_AGENT_TOOLS)
    return (
        "---\n"
        f"name: {contract.READ_ONLY_AGENT_NAME}\n"
        "description: Read-only consultant with no shell or write tools.\n"
        "tools:\n"
        f"{tools}\n"
        "---\n"
        "You are a read-only consultant. Answer using only the tools you have. "
        "You cannot modify files, and you must not ask for permission to do so.\n"
    )


def schema_instruction(output_schema: dict) -> str:
    """The prompt-appended structured-output instruction (kimi has no --output-schema)."""
    return (
        "\n\n# Required output format\n"
        "Reply with a single JSON object and nothing else — no prose, no code fence. "
        "It must validate against this JSON Schema:\n\n"
        f"{json.dumps(output_schema, indent=2)}\n"
    )


def _gate_optional(tokens: list[str], fs: FlagSupport) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        takes_value = contract.HELP_GATED_FLAGS.get(token)
        if takes_value is not None and not preflight.is_supported(token, fs):
            dropped.append(token)
            i += 2 if takes_value else 1
            continue
        kept.append(token)
        i += 1
    return kept, dropped


def build_exec_command(
    *,
    kimi_bin: str,
    read_only: bool,
    prompt_pointer: str,
    model: str | None = None,
    agent_file_path: str | None = None,
    skills_dir: str | None = None,
    flag_support: FlagSupport,
) -> tuple[list[str], list[str]]:
    """The `kimi -p` invocation. Returns (argv, dropped_help_gated_flags). cwd is not a kimi
    flag; the runner sets it on the subprocess. --add-dir and the prompt-mode-incompatible
    flags are never sent."""
    if read_only and not agent_file_path:
        raise ValueError(
            "read-only runs require an agent file: the tools allowlist is the only thing "
            "enforcing read-only, and a worktree does not contain kimi"
        )
    if len(prompt_pointer) > contract.MAX_ARGV_PROMPT_CHARS:
        raise ValueError(
            f"argv prompt exceeds {contract.MAX_ARGV_PROMPT_CHARS} chars; "
            "write it to the handshake prompt file instead"
        )
    tokens = [kimi_bin, *contract.EXEC_SUBCOMMAND, contract.PROMPT_FLAG, prompt_pointer]
    tokens += [contract.OUTPUT_FORMAT_FLAG, contract.OUTPUT_FORMAT_JSON]
    if agent_file_path:
        tokens += [contract.AGENT_FILE_FLAG, agent_file_path]
    if skills_dir:
        tokens += [contract.SKILLS_DIR_FLAG, skills_dir]
    if model:
        tokens += [contract.MODEL_FLAG, model]
    return _gate_optional(tokens, flag_support)


def build_run_env(base: dict[str, str], reasoning_effort: str | None) -> dict[str, str]:
    """Child environment: effort rides an env var (no flag), and the output format is
    pinned so a user's KIMI_MODEL_OUTPUT_FORMAT=text cannot strip the event stream."""
    env = dict(base)
    if reasoning_effort is not None:
        env[contract.REASONING_EFFORT_ENV] = reasoning_effort
    env[contract.MODEL_OUTPUT_FORMAT_ENV] = contract.OUTPUT_FORMAT_JSON
    return env


def _write_exclusive(path: Path, text: str) -> None:
    """Create and write, refusing to follow a symlink or reuse an existing file: the dir is
    created fresh by this process, so anything already at the target is a plant."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def create_handshake_dir() -> str:
    """A fresh, private, server-owned directory for one run's handshake files, deliberately
    NOT inside the worktree (a repo tracking a symlink at the handshake path would redirect
    the writes). kimi reads the files by absolute path."""
    return tempfile.mkdtemp(prefix=contract.HANDSHAKE_DIR_PREFIX)


def write_handshake(run_dir: str, prompt_text: str, *, read_only: bool) -> dict[str, str]:
    """Write one run's handshake files and return their ABSOLUTE paths: `prompt` always,
    `agent` for a read-only run, `answer` (not yet existing) for a write-capable run."""
    base = Path(run_dir)
    base.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    prompt_path = base / contract.PROMPT_FILE_NAME
    _write_exclusive(prompt_path, prompt_text)
    paths["prompt"] = str(prompt_path)
    if read_only:
        agent_path = base / contract.AGENT_FILE_NAME
        _write_exclusive(agent_path, read_only_agent_document())
        # The agent file is the ONLY thing enforcing read-only: confirm its bytes.
        if agent_path.read_text(encoding="utf-8") != read_only_agent_document():
            raise ValueError("read-only agent file did not read back as written")
        paths["agent"] = str(agent_path)
    else:
        paths["answer"] = str(base / contract.ANSWER_FILE_NAME)
    return paths


def build_prompt_pointer(paths: dict[str, str], *, read_only: bool) -> str:
    prompt = paths["prompt"]
    if read_only:
        return (
            f"Read the file {prompt} and follow it exactly. "
            "Reply with your answer as your final message."
        )
    return (
        f"Read the file {prompt} and follow it exactly. "
        f"When you are done, write your final answer to {paths['answer']}."
    )


def read_answer_file(answer_path: str) -> str:
    """The answer file, or "" if it is anything but a plain small regular file. The file is
    written by a full-tool agent, so its path is model-controlled at read time: O_NOFOLLOW
    rejects a substituted symlink, O_NONBLOCK keeps a FIFO from blocking before fstat can
    reject it, and the size cap bounds memory."""
    try:
        fd = os.open(answer_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        st = os.fstat(fd)
        if not S_ISREG(st.st_mode) or st.st_size > contract.MAX_ANSWER_BYTES:
            return ""
        raw = os.read(fd, contract.MAX_ANSWER_BYTES)
    except OSError:
        return ""
    finally:
        os.close(fd)
    return raw.decode("utf-8", "replace").strip()


# --- free probes ------------------------------------------------------------------------------


def kimi_version(binary: str, timeout_seconds: int = 10) -> str | None:
    run = runtime.run_sync_capture([binary, *contract.VERSION_ARGS], timeout_seconds=timeout_seconds)
    if run.binary_missing or run.exit_code != 0:
        return None
    return run.stdout.strip() or None


def login_status(binary: str, timeout_seconds: int = 10) -> tuple[bool | None, str | None]:
    """kimi has no `login status`; readiness is "at least one provider is configured", read
    from `kimi provider list --json`. The detail derives from the COUNT only — never the
    payload, which carries base URLs and may carry an API key."""
    run = runtime.run_sync_capture(
        [binary, *contract.PROVIDER_LIST_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.timed_out:
        return None, None
    if run.exit_code != 0:
        return False, "Kimi reports no usable provider configuration; run `kimi login`."
    count = _provider_count(run.stdout)
    if count is None:
        return None, None
    if count == 0:
        return False, "Kimi has no configured provider; run `kimi login`."
    return True, f"Kimi reports {count} configured provider(s)."


def _provider_count(stdout: str) -> int | None:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("providers", "items", "data"):
            value = data.get(key)
            if isinstance(value, (list, dict)):
                return len(value)
    return None


_ECHO_MAX_CHARS = 200


def version_display(version: str | None) -> str | None:
    """The bounded, sanitized DISPLAY copy of a version string; None when nothing survives."""
    return redaction.sanitize_echo(version)[:_ECHO_MAX_CHARS] or None


# --- classification --------------------------------------------------------------------------

_UNRESOLVED_DEFAULT_MODEL_DETAIL = (
    "Kimi could not resolve the `default_model` in its config.toml — the alias names no "
    '`[models."..."]` section. This is the CONFIGURED DEFAULT, not the `model` you passed, '
    "so overriding or omitting `model` will not help."
)


def classify_failure(
    run: CommandRun,
    *,
    last_message: str | None,
    events: str | None,
    reasoning_effort: str | None,
    sanitize: Callable[[str], str] | None,
) -> ClassifiedFailure:
    """Map a non-success run into the shared taxonomy. Order (pontonier's shared one):
    binary missing → timeout → drift → auth → rate limit → invalid model → nonzero_exit.
    There is no effort branch: kimi silently ignores an unrecognized effort, so a rejection
    never reaches here (the adapter refuses pre-spend). `sanitize` replaces the generic
    branch's sanitizer and runs BEFORE the 300-char cut, so a secret or worktree path that
    straddles the cut cannot leak a prefix."""
    if run.binary_missing:
        return ClassifiedFailure(
            code="kimi_not_found",
            detail="The `kimi` CLI was not found; run amicus_backends for the resolution detail.",
        )
    if run.timed_out:
        return ClassifiedFailure(code="timeout", detail="kimi exceeded the timeout.")
    _ = reasoning_effort
    event_error = normalize.extract_error_message(events) if events else None
    if contract.is_contract_drift(run.stderr, run.stdout, event_error):
        return ClassifiedFailure(
            code="cli_contract_changed",
            detail=(
                "kimi rejected a flag or value amicus sent — its CLI contract likely changed "
                "for your installed version."
            ),
        )
    if contract.is_auth_failure(run.stderr, run.stdout, last_message, event_error):
        return ClassifiedFailure(
            code="kimi_auth_required",
            detail="kimi is not authenticated: the configured provider rejected the credentials.",
        )
    if contract.is_rate_limited(run.stderr, run.stdout, last_message, event_error):
        retry_after = contract.parse_retry_after_ms(
            run.stderr, run.stdout, last_message, event_error
        )
        if retry_after is None:
            retry_after = contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
        return ClassifiedFailure(
            code="kimi_rate_limited",
            detail="kimi hit a usage/rate limit.",
            retry_after_ms=retry_after,
        )
    if contract.is_invalid_model(run.stderr, run.stdout, last_message, event_error):
        if contract.is_unresolved_default_model(
            run.stderr, run.stdout, last_message, event_error
        ):
            return ClassifiedFailure(
                code="invalid_model",
                detail=_UNRESOLVED_DEFAULT_MODEL_DETAIL,
                repair=RepairHint(
                    next_step="correct_config",
                    tool=None,
                    alternative=(
                        "Correct `default_model` in kimi's config.toml (or add the matching "
                        '`[models."..."]` section), then retry.'
                    ),
                ),
            )
        return ClassifiedFailure(
            code="invalid_model",
            detail=(
                "Kimi does not have that model alias configured. `model` takes an alias "
                "defined in kimi's config.toml, not a raw provider model id."
            ),
            details={"field": "model"},
            repair=RepairHint(
                next_step="correct_arguments",
                tool="amicus_models",
                alternative=(
                    "Pass one of the aliases amicus_models lists for kimi, or omit model to "
                    "use the configured default_model."
                ),
            ),
        )
    raw = (event_error or run.stderr or run.stdout).strip()
    detail = (sanitize(raw) if sanitize is not None else redaction.sanitize_echo_prose(raw))[:300]
    return ClassifiedFailure(code="nonzero_exit", detail=f"kimi exited {run.exit_code}: {detail}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_kimi_cli.py -q --no-cov`
Expected: all PASS.
If `test_generic_failures_are_bounded_and_sanitized_before_truncation` fails on the straddling case, the cut is happening before the sanitizer — fix the order, never the test.

- [ ] **Step 5: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests && uv run --no-sync ty check
git add src/amicus/backends/kimi/cli.py tests/test_kimi_cli.py
git commit -m "feat(backends): add the kimi handshake, argv builder, probes and classifier"
```

---

### Task 5: The adapter, status probe, options and plugin factory

**Files:**
- Create: `src/amicus/backends/kimi/adapter.py`, `src/amicus/backends/kimi/status.py`, `src/amicus/backends/kimi/options.py`
- Modify: `src/amicus/backends/kimi/__init__.py` (the factory)
- Create: `tests/support/kimifixtures.py`
- Test: `tests/test_kimi_adapter.py`, `tests/test_kimi_status.py`, `tests/test_kimi_plugin.py`
- Modify: `tests/test_registry.py:28-31`, `tests/test_async_tools.py:187-198`, `tests/test_dry_run.py:87-92`, `tests/test_paid_tools.py:31` (comment)

**Interfaces:**
- Consumes: everything from Tasks 1–4; `amicus.plugin.{BackendPlugin, OptionSpec, StatusReport}`, `amicus.schemas.instructions`, `amicus.schemas.params.reasoning_effort_shape_error`, `pontonier.conventions.preflight.HelpProbe`, `pontonier.core.{worktree, runtime}`.
- Produces: `adapter.KimiBackend(config, binary, help_probe, models)` implementing `AgentBackend` and `OutcomeInspector` (`validate_request`, `prepare`, `finalize`, `classify_failure`, `inspect_outcome`, `list_models`, `auth_probe`, `scrub_env`); `status.KimiStatus(config, binary, help_probe).probe() -> StatusReport`, `status.VERSION_WARNING`; `options.options_for(config) -> tuple[OptionSpec, ...]` (`isolation`, `model`, `reasoning_effort`, each applying to `{consult, review_changes, delegate}`); `amicus.backends.kimi.plugin(environ=None) -> BackendPlugin` with `VOCABULARY`, `EGRESS`, `CARRIERS`; `tests.support.kimifixtures.{ALL_FLAGS, NO_MODEL, make_backend(environ=None, flags=ALL_FLAGS, catalog=None) -> (plugin, backend), normalize_argv(argv) -> list[str], scripted_run_async(...), load_fixture()}`.

- [ ] **Step 1: Write the fixtures helper**

`tests/support/kimifixtures.py`:

```python
"""Shared helpers for the kimi plugin tests: pinned flag support, a backend built from an
explicit environ (binary pinned to /KIMI, catalog optionally pinned), argv normalization
against the sibling capture, and a scripted runtime that honours the handshake pointer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pontonier.conventions.preflight import FlagSupport, HelpProbe
from pontonier.core.runtime import CommandRun

from amicus.backends import kimi as kimi_pkg
from amicus.backends.kimi import contract
from amicus.backends.kimi.adapter import KimiBackend
from amicus.plugin import ModelEntry, ModelListing

ALL_FLAGS = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)
K3 = ModelListing(
    models=(
        ModelEntry(
            slug="k3",
            display_name="Kimi K3",
            default_reasoning_effort="medium",
            supported_reasoning_efforts=("low", "medium", "high"),
        ),
        ModelEntry(slug="bare"),
    ),
    source="live",
)
SILENT = ModelListing(models=(), source="none")


def load_fixture() -> dict:
    return json.loads(
        (Path(__file__).parent.parent / "fixtures" / "kimi_differentials.json").read_text()
    )


def make_backend(
    environ: dict | None = None,
    flags: FlagSupport = ALL_FLAGS,
    catalog: ModelListing | None = SILENT,
):
    """(plugin, backend) with the help probe pinned, the binary pinned to /KIMI and the
    model catalog pinned (default: silent). `catalog=None` leaves the live reader alone."""
    env = {"AMICUS_KIMI_BIN": "/KIMI", **(environ or {})}
    plugin = kimi_pkg.plugin(env)
    probe: HelpProbe = plugin.help_probe
    probe.flag_support = lambda force=False: flags  # type: ignore[method-assign]
    if catalog is not None:
        plugin.models.read = lambda force=False: catalog  # type: ignore[method-assign]
    backend = plugin.backend
    assert isinstance(backend, KimiBackend)
    return plugin, backend


_HANDSHAKE = re.compile(r"/[^\s]*amicus-kimi-handshake-[^/\s]+/")
_SKILLS = re.compile(r"/[^\s]*/empty-skills")


def normalize_argv(argv) -> list[str]:
    """The sibling's shape: `kimi` as argv[0], temp paths as /TMP/, the agent name theirs."""
    out = []
    for i, tok in enumerate(argv):
        tok = _SKILLS.sub("/TMP/empty-skills", _HANDSHAKE.sub("/TMP/", tok))
        out.append("kimi" if i == 0 else tok)
    return out


_ANSWER_POINTER = re.compile(r"write your final answer to (\S+?)\.?$")


def scripted_run_async(
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    timed_out: bool = False,
    answer_file: str | None = None,
    calls: list | None = None,
    write_in_cwd: dict[str, str] | None = None,
):
    """A `runtime.run_async` stand-in for kimi: records the call, substitutes `{WT}` in
    stdout/stderr with the run's cwd (the worktree path), writes the answer file the
    pointer names when `answer_file` is given, writes files into cwd (delegate), and
    returns the scripted CommandRun."""

    async def fake(
        cmd,
        cwd,
        timeout_seconds,
        stdin_text=None,
        *,
        env=None,
        on_stdout_line=None,
        max_output_bytes=0,
        orphan_marker=None,
    ):
        pointer = cmd[cmd.index("--prompt") + 1] if "--prompt" in cmd else ""
        if calls is not None:
            calls.append(
                {
                    "cmd": list(cmd),
                    "cwd": cwd,
                    "stdin_text": stdin_text,
                    "env": env,
                    "timeout": timeout_seconds,
                    "orphan_marker": orphan_marker,
                    "pointer": pointer,
                }
            )
        m = _ANSWER_POINTER.search(pointer)
        if answer_file is not None and m is not None:
            Path(m.group(1)).write_text(answer_file, encoding="utf-8")
        for name, content in (write_in_cwd or {}).items():
            Path(cwd, name).write_text(content, encoding="utf-8")
        out = stdout.replace("{WT}", cwd)
        err = stderr.replace("{WT}", cwd)
        if on_stdout_line is not None:
            for line in out.splitlines():
                on_stdout_line(line)
        return CommandRun(out, err, exit_code, 12, timed_out)

    return fake
```

- [ ] **Step 2: Write the failing tests**

`tests/test_kimi_adapter.py`:

```python
"""KimiBackend on the pontonier lifecycle: staging, the effort gate, extraction, the empty
answer inspection, and classification with the site sanitizer."""

from __future__ import annotations

from pathlib import Path

import pytest
from pontonier.backend.protocol import AgentBackend, OutcomeInspector, RunOutcome, RunRequest
from pontonier.core.runtime import CommandRun
from pontonier.testing import conformance
from tests.support import kimifixtures as kf

from amicus.backends.kimi import cli, contract
from amicus.schemas import instructions as ins

STRUCTURED = '{"summary": "Looks fine", "verdict": "pass", "confidence": "high", "findings": []}'
EVENTS = (
    '{"role":"meta","type":"system.version","version":"0.41.0"}\n'
    '{"role":"assistant","content":"from the stream"}\n'
    '{"role":"meta","type":"session.resume_hint","session_id":"session_x"}\n'
)


def _req(**kw) -> RunRequest:
    base = dict(kind="consult", prompt="why?", cwd="/repo/some/where", timeout_seconds=60)
    base.update(kw)
    return RunRequest(**base)


def test_backend_is_conformant(pinned_kimi_bin):
    plugin, backend = kf.make_backend()
    assert isinstance(backend, AgentBackend) and isinstance(backend, OutcomeInspector)
    assert conformance.check_contract(plugin.contract) == []
    assert conformance.check_backend(plugin.contract, backend) == []


def test_a_perturbed_backend_fails_conformance(pinned_kimi_bin):
    plugin, backend = kf.make_backend()

    class AcceptsAnything(type(backend)):  # type: ignore[misc]
        def validate_request(self, request):
            return None

    loose = AcceptsAnything(backend._config, backend._binary, backend._help_probe, backend._models)
    assert any("bogus reasoning_effort" in v for v in conformance.check_backend(plugin.contract, loose))

    class Raises(type(backend)):  # type: ignore[misc]
        def inspect_outcome(self, outcome, request):
            raise RuntimeError("boom")

    bad = Raises(backend._config, backend._binary, backend._help_probe, backend._models)
    assert any("inspect_outcome raised" in v for v in conformance.check_backend(plugin.contract, bad))


async def test_prepare_stages_a_read_only_run(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend({"AMICUS_STATE_DIR": str(tmp_path / "state")})
    async with backend.prepare(_req(cwd=str(tmp_path), schema={"type": "object"}, model="k3")) as p:
        assert p.stdin_text is None and p.cwd == str(tmp_path) and p.orphan_marker == str(tmp_path)
        assert p.argv[0] == "/KIMI" and p.argv[1] == "--prompt"
        agent = p.argv[p.argv.index("--agent-file") + 1]
        assert Path(agent).read_text() == cli.read_only_agent_document()
        assert p.argv[p.argv.index("--model") + 1] == "k3" and "--skills-dir" not in p.argv
        pointer = p.argv[2]
        prompt_path = pointer.split("Read the file ", 1)[1].split(" and follow", 1)[0]
        text = Path(prompt_path).read_text()
        assert text.startswith("why?") and "# Required output format" in text
        assert contract.HANDSHAKE_DIR_PREFIX in prompt_path and str(tmp_path) not in prompt_path
        assert p.artifact_paths == {} and all(contract.HANDSHAKE_DIR_PREFIX in a for a in p.artifacts)
        assert p.env["KIMI_MODEL_OUTPUT_FORMAT"] == "stream-json"
        assert "KIMI_MODEL_THINKING_EFFORT" not in p.env
    assert not Path(prompt_path).exists()


async def test_prepare_stages_a_delegate_run_and_applies_env_defaults(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend(
        {
            "AMICUS_KIMI_MODEL": "k3",
            "AMICUS_KIMI_REASONING_EFFORT": "low",
            "AMICUS_KIMI_ISOLATION": "ignore-skills",
            "AMICUS_STATE_DIR": str(tmp_path / "state"),
        }
    )
    async with backend.prepare(_req(kind="delegate", prompt="do", cwd=str(tmp_path))) as p:
        assert "--agent-file" not in p.argv and "answer" in p.artifact_paths
        assert p.artifact_paths["answer"].endswith(contract.ANSWER_FILE_NAME)
        assert p.argv[p.argv.index("--model") + 1] == "k3"
        assert p.argv[p.argv.index("--skills-dir") + 1] == str(tmp_path / "state" / "empty-skills")
        assert p.env["KIMI_MODEL_THINKING_EFFORT"] == "low"
        assert "write your final answer to" in p.argv[2]
    async with backend.prepare(_req(kind="delegate", prompt="do", cwd=str(tmp_path), access="read-only")) as p:
        assert "--agent-file" in p.argv  # explicit access wins


async def test_prepare_prepends_composed_instructions(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend()
    async with backend.prepare(_req(cwd=str(tmp_path), instructions_append="Focus on locking.")) as p:
        prompt_path = p.argv[2].split("Read the file ", 1)[1].split(" and follow", 1)[0]
        text = Path(prompt_path).read_text()
    assert text.startswith(ins.compose("Focus on locking.")) and text.endswith("why?")


async def test_prepare_help_gates_model_and_fails_closed(pinned_kimi_bin, tmp_path):
    _, backend = kf.make_backend(flags=kf.NO_MODEL)
    async with backend.prepare(_req(cwd=str(tmp_path), model="k3")) as p:
        assert "--model" not in p.argv and p.dropped_flags == ("--model",)
    with pytest.raises(ValueError):
        async with backend.prepare(_req(cwd=str(tmp_path), reasoning_effort="bogus-level")):
            pass  # pragma: no cover
    _, unresolved = kf.make_backend({"AMICUS_KIMI_BIN": str(tmp_path / "missing")})
    from amicus.backends.kimi.binary import BinaryNotFoundError

    with pytest.raises(BinaryNotFoundError):
        async with unresolved.prepare(_req(cwd=str(tmp_path))):
            pass  # pragma: no cover


def test_validate_request_catalog_first_then_fallback_then_fail_open(pinned_kimi_bin):
    _, catalog = kf.make_backend(catalog=kf.K3)
    assert catalog.validate_request(_req(model="k3", reasoning_effort="high")) is None
    refused = catalog.validate_request(_req(model="k3", reasoning_effort="xhigh"))
    assert refused is not None and refused.code == "invalid_reasoning_effort"
    assert refused.details == {"field": "reasoning_effort", "allowed_values": ["low", "medium", "high"]}
    assert refused.repair is not None and refused.repair.tool == "amicus_models"
    assert catalog.validate_request(_req(model="unlisted", reasoning_effort="xhigh")) is None
    assert catalog.validate_request(_req(model="unlisted", reasoning_effort="nope")) is not None
    assert catalog.validate_request(_req(model="bare", reasoning_effort="max")) is None
    _, silent = kf.make_backend(catalog=kf.SILENT)
    assert silent.validate_request(_req(reasoning_effort="xhigh")) is None
    fallback = silent.validate_request(_req(reasoning_effort="not-a-real-effort-level"))
    assert fallback is not None and fallback.details["allowed_values"] == sorted(
        contract.REASONING_EFFORT_FALLBACK_VOCABULARY
    )
    assert silent.validate_request(_req(reasoning_effort=" HIGH ")) is not None  # exact value
    assert silent.validate_request(_req()) is None
    shape = silent.validate_request(_req(reasoning_effort="x" * 40))
    assert shape is not None and "exceeds" in shape.detail
    _, from_env = kf.make_backend({"AMICUS_KIMI_REASONING_EFFORT": "zzz"})
    assert from_env.validate_request(_req()) is not None
    assert from_env.validate_request(_req(reasoning_effort="low")) is None


def test_validate_request_instructions_rules(pinned_kimi_bin):
    _, backend = kf.make_backend()
    bad_kind = backend.validate_request(_req(kind="delegate", instructions_append="x"))
    assert bad_kind is not None and bad_kind.details == {"field": "instructions_append"}
    blank = backend.validate_request(_req(instructions_append="   "))
    assert blank is not None and "blank" in blank.detail
    assert backend.validate_request(_req(instructions_append="Focus.")) is None


def _outcome(stdout=EVENTS, answer=None, exit_code=0, stderr="", timed_out=False):
    texts = {"answer": answer} if answer is not None else {}
    return RunOutcome(run=CommandRun(stdout, stderr, exit_code, 5, timed_out), events=stdout, artifact_texts=texts)


def test_finalize_prefers_the_answer_file_and_carries_cache_tokens(pinned_kimi_bin):
    _, backend = kf.make_backend()
    usage_line = '{"type":"token_count","usage":{"input_tokens":10,"output_tokens":2,"cached_input_tokens":8}}\n'
    res = backend.finalize(_outcome(stdout=EVENTS + usage_line, answer="  from the file  "), _req())
    assert res.answer == "from the file" and res.session_id == "session_x"
    assert res.usage is not None and res.usage.cached_input_tokens == 8 and res.usage.total_tokens == 12
    stream = backend.finalize(_outcome(), _req())
    assert stream.answer == "from the stream" and stream.usage is None and stream.structured is None
    structured = backend.finalize(_outcome(answer=STRUCTURED), _req(schema={"type": "object"}))
    assert structured.structured == {"summary": "Looks fine", "verdict": "pass", "confidence": "high", "findings": []}


def test_inspect_outcome_flags_only_a_zero_exit_run_without_an_answer(pinned_kimi_bin):
    _, backend = kf.make_backend()
    empty = backend.inspect_outcome(_outcome(stdout='{"role":"meta","type":"system.version"}\n'), _req())
    assert empty is not None and empty.code == "empty_response"
    assert backend.inspect_outcome(_outcome(), _req()) is None
    assert backend.inspect_outcome(_outcome(stdout="", answer="x"), _req()) is None
    assert backend.inspect_outcome(_outcome(stdout="", exit_code=1), _req()) is None
    assert backend.inspect_outcome(_outcome(stdout="", timed_out=True, exit_code=-9), _req()) is None


def test_classify_failure_uses_the_stream_message_and_the_site_sanitizer(pinned_kimi_bin):
    _, backend = kf.make_backend()
    auth = backend.classify_failure(
        _outcome(stdout='{"role":"assistant","content":"invalid api key"}\n', exit_code=2), _req()
    )
    assert auth.code == "kimi_auth_required"
    secret = "sk-" + "c" * 32
    out = _outcome(stdout="", stderr="x" * 290 + f" token={secret} at /wt/abc/src/a.py", exit_code=2)
    plain = backend.classify_failure(out, _req(sanitize_aliases=("/wt/abc",)))
    assert plain.code == "nonzero_exit" and "sk-c" not in plain.detail and "/wt/abc" not in plain.detail


def test_list_models_and_auth_probe(pinned_kimi_bin, monkeypatch):
    _, backend = kf.make_backend(catalog=kf.K3)
    assert backend.list_models() == ("k3", "bare")
    monkeypatch.setattr(cli, "login_status", lambda binary, timeout_seconds=10: (True, "ok"))
    assert backend.auth_probe() is True
    _, unresolved = kf.make_backend({"AMICUS_KIMI_BIN": "/definitely/not/here"})
    assert unresolved.auth_probe() is None
    assert backend.scrub_env({"A": "1"}, None) == {"A": "1"}
```

`tests/test_kimi_status.py`:

```python
"""The Kimi readiness probe: installed/version/auth plus advisory warnings."""

from __future__ import annotations

from pontonier.core.runtime import BINARY_NOT_FOUND, CommandRun
from tests.support import kimifixtures as kf

from amicus.backends.kimi import status as st

HELP = "  -p, --prompt <prompt>\n  --output-format <format>\n  --agent-file <path>\n  -m, --model <model>\n  --skills-dir <dir>\n"
PROVIDERS = '{"providers": {"p": {"apiKey": "sk-x"}}, "models": {}}'


def _probe_with(monkeypatch, *, version="0.41.0\n", providers=PROVIDERS, provider_exit=0, help_text=HELP):
    def fake(cmd, timeout_seconds, **k):
        if cmd[1:] == ["--version"]:
            return CommandRun(version, "", 0, 1, False) if version else CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
        if cmd[1:] == ["provider", "list", "--json"]:
            return CommandRun(providers, "", provider_exit, 1, False)
        return CommandRun(help_text, "", 0, 1, False)

    monkeypatch.setattr(st.cli.runtime, "run_sync_capture", fake)
    monkeypatch.setattr(st.preflight.runtime, "run_sync_capture", fake)


def test_ready_report(pinned_kimi_bin, monkeypatch):
    _probe_with(monkeypatch)
    plugin, _ = kf.make_backend()
    del plugin.help_probe.flag_support
    rep = plugin.status.probe()
    assert rep.installed and rep.version == "0.41.0" and rep.authenticated is True
    assert rep.warnings == ()


def test_unsupported_version_missing_flags_and_bad_extra_args_warn(pinned_kimi_bin, monkeypatch):
    _probe_with(monkeypatch, version="0.30.0\n", help_text="  --prompt <p>\n")
    plugin, _ = kf.make_backend({"AMICUS_KIMI_EXTRA_ARGS": "-p x", "MOONBRIDGE_MODEL": "m"})
    del plugin.help_probe.flag_support
    rep = plugin.status.probe()
    joined = "\n".join(rep.warnings)
    assert rep.installed and st.VERSION_WARNING in joined and "--agent-file" in joined
    assert "AMICUS_KIMI_EXTRA_ARGS is invalid" in joined and "read from legacy" in joined


def test_not_installed_bad_override_and_no_provider(pinned_kimi_bin, monkeypatch, tmp_path):
    _probe_with(monkeypatch, version=None)
    rep = kf.make_backend()[0].status.probe()
    assert rep.installed is False and rep.authenticated is None and rep.version is None
    bad = kf.make_backend({"AMICUS_KIMI_BIN": str(tmp_path / "missing")})[0].status.probe()
    assert bad.installed is False and any("AMICUS_KIMI_BIN" in w for w in bad.warnings)
    _probe_with(monkeypatch, providers='{"providers": {}}')
    plugin, _ = kf.make_backend()
    del plugin.help_probe.flag_support
    assert plugin.status.probe().authenticated is False
```

`tests/test_kimi_plugin.py`:

```python
"""The plugin factory through the real registry path, and the amicus-side declarations."""

from __future__ import annotations

from tests.support import kimifixtures as kf

from amicus import backends as in_tree
from amicus import registry
from amicus.backends import kimi as kimi_pkg
from amicus.backends.kimi import contract


def test_registry_loads_the_in_tree_kimi_plugin(pinned_kimi_bin):
    reg = registry.BackendRegistry.load(("kimi",), entry_points=())
    assert reg.ids == ("kimi",) and reg.unavailable == {}
    plugin = reg.get("kimi")
    assert plugin is not None and plugin.contract is contract.CONTRACT
    assert plugin.effects == in_tree.KNOWN_EFFECTS["kimi"]
    assert plugin.contract.display_name == in_tree.KNOWN_DISPLAY_NAMES["kimi"]
    assert plugin.env.prefix == contract.CONTRACT.env_prefix and plugin.local_codes == {}
    for phrase in contract.FORBIDDEN_SURFACE_PHRASES:
        assert phrase not in plugin.egress and phrase not in plugin.carriers
    assert "Kimi provider" in plugin.egress and "handshake" in plugin.carriers
    assert "instructions_append" in plugin.carriers and "stdin" in plugin.carriers


def test_options_carry_defaults_and_applicability(pinned_kimi_bin):
    plugin, _ = kf.make_backend({"AMICUS_KIMI_ISOLATION": "ignore-skills", "AMICUS_KIMI_MODEL": "m"})
    by_name = {o.name: o for o in plugin.options}
    assert by_name["isolation"].default == "ignore-skills"
    assert by_name["isolation"].applies_to == frozenset({"consult", "review_changes", "delegate"})
    assert by_name["model"].default == "m" and by_name["reasoning_effort"].default is None


def test_plugin_factory_reads_the_process_env_by_default(pinned_kimi_bin, monkeypatch):
    monkeypatch.setenv("AMICUS_KIMI_BIN", "/KIMI")
    monkeypatch.setenv("AMICUS_KIMI_MODEL", "from-env")
    plugin = kimi_pkg.plugin()
    assert {o.name: o.default for o in plugin.options}["model"] == "from-env"
    assert plugin.help_probe.help_argv == ("/KIMI", "--help")
    assert plugin.help_probe.always_send_flags == contract.ALWAYS_SEND_FLAGS


def test_both_in_tree_plugins_load_together_with_the_guards_in_place():
    reg = registry.BackendRegistry.load(("codex", "kimi", "claude"), entry_points=())
    assert set(reg.ids) == {"codex", "kimi"} and set(reg.unavailable) == {"claude"}
```

Existing-test updates:

- `tests/test_registry.py` lines 28–31: the comment and assertion become "codex (M1) and kimi (M3) load; claude stays import_failed": `assert set(reg.unavailable) == {"claude"}`.
- `tests/test_async_tools.py` lines 187–198: rename the `kimi` variable to `claude` and call with `"backend": "claude"`; the assertion stays `backend_unavailable`.
- `tests/test_dry_run.py` lines 87–92: same substitution (`"backend": "claude"`).
- `tests/test_paid_tools.py` line 31 comment: "kimi loads since M3; claude stays import_failed".

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_kimi_adapter.py tests/test_kimi_status.py tests/test_kimi_plugin.py -q --no-cov`
Expected: import errors (`adapter`, `status`, `options`, `kimi_pkg.plugin`).

- [ ] **Step 4: Write options.py and status.py**

`src/amicus/backends/kimi/options.py`:

```python
"""The OptionSpec table: `isolation` is the one wire-visible backend option; `model` and
`reasoning_effort` entries carry the AMICUS_KIMI_* defaults the tools resolve with."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.plugin import OptionSpec

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.kimi.config import KimiConfig

_PAID_VERBS = frozenset({"consult", "review_changes", "delegate"})


def options_for(config: KimiConfig) -> tuple[OptionSpec, ...]:
    return (
        OptionSpec("isolation", "isolation", _PAID_VERBS, config.isolation),
        OptionSpec("model", "model", _PAID_VERBS, config.model),
        OptionSpec("reasoning_effort", "reasoning_effort", _PAID_VERBS, config.reasoning_effort),
    )
```

`src/amicus/backends/kimi/status.py`:

```python
"""The Kimi readiness probe behind amicus_backends (ported from moonbridge kimi_status)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.conventions import preflight

from amicus.backends.kimi import cli
from amicus.backends.kimi.config import version_supported
from amicus.plugin import StatusReport

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.kimi.binary import KimiBinary
    from amicus.backends.kimi.config import KimiConfig

VERSION_WARNING = (
    "The installed kimi version is outside the versions amicus was built against; paid "
    "calls still run, but the CLI contract may have drifted."
)


class KimiStatus:
    def __init__(self, config: KimiConfig, binary: KimiBinary, help_probe: HelpProbe) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe

    def probe(self) -> StatusReport:
        warnings: list[str] = [*self._config.errors, *self._config.warnings]
        if not self._config.extra_args.valid:
            warnings.append(f"AMICUS_KIMI_EXTRA_ARGS is invalid: {self._config.extra_args.error}.")
        override_error = self._binary.override_error()
        if override_error is not None:
            return StatusReport(installed=False, warnings=(override_error, *warnings))
        binary = self._binary.resolve() or "kimi"
        version = cli.kimi_version(binary)
        if version is None:
            return StatusReport(installed=False, warnings=tuple(warnings))
        authenticated, _detail = cli.login_status(binary)
        if version_supported(version, self._config) is False:
            warnings.append(VERSION_WARNING)
        fs = self._help_probe.flag_support(force=True)
        missing = self._help_probe.missing_expected_flags(fs)
        if missing:
            warnings.append(
                f"`kimi --help` did not list expected flags: {', '.join(missing)}. "
                "The CLI contract may have drifted."
            )
        return StatusReport(
            installed=True,
            version=cli.version_display(version),
            authenticated=authenticated,
            warnings=tuple(warnings),
        )


__all__ = ["VERSION_WARNING", "KimiStatus", "preflight"]
```

- [ ] **Step 5: Write adapter.py**

```python
"""KimiBackend: the behavior half of the Kimi contract on the pontonier lifecycle (ported
from moonbridge `backend.py`, with the fixes the amicus spec names: the classifier gets the
last message and the site sanitizer; finalize carries cache tokens; the pre-spend effort
gate is the adapter's own; empty answers are an outcome inspection)."""

from __future__ import annotations

import contextlib
import os
import shutil
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, ExecResult, PreparedRun, RepairHint
from pontonier.core import runtime, worktree

from amicus.backends.kimi import cli, contract, models, normalize
from amicus.backends.kimi import config as kimi_config
from amicus.backends.kimi.binary import BinaryNotFoundError
from amicus.schemas import instructions
from amicus.schemas.params import reasoning_effort_shape_error

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    from pontonier.backend.protocol import RunOutcome, RunRequest
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.kimi.binary import KimiBinary
    from amicus.backends.kimi.config import KimiConfig
    from amicus.backends.kimi.models import KimiModels

_INSTRUCTION_KINDS = frozenset({"consult", "review_changes"})
EMPTY_RESPONSE_DETAIL = (
    "Kimi completed without producing an answer: no answer file and no assistant text in "
    "the event stream."
)


class KimiBackend:
    def __init__(
        self, config: KimiConfig, binary: KimiBinary, help_probe: HelpProbe, models: KimiModels
    ) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe
        self._models = models

    # --- resolution the adapter and the classifier must agree on ----------------------------
    def _model(self, request: RunRequest) -> str | None:
        return request.model or self._config.model

    def _effort(self, request: RunRequest) -> str | None:
        # Exact-None precedence: an explicit "" is the caller's value.
        if request.reasoning_effort is not None:
            return request.reasoning_effort
        return self._config.reasoning_effort

    @staticmethod
    def _read_only(request: RunRequest) -> bool:
        if request.access is not None:
            return request.access == contract.SANDBOX_READ_ONLY
        return request.kind != "delegate"

    @staticmethod
    def _answer(outcome: RunOutcome) -> str | None:
        answer = (outcome.artifact_texts.get("answer") or "").strip()
        return answer or normalize.extract_final_message(outcome.events or outcome.run.stdout)

    def _effort_refusal(self, detail: str, allowed: tuple[str, ...]) -> ClassifiedFailure:
        return ClassifiedFailure(
            code="invalid_reasoning_effort",
            detail=detail,
            details={"field": "reasoning_effort", "allowed_values": list(allowed)},
            repair=RepairHint(
                next_step="correct_arguments",
                tool="amicus_models",
                alternative=(
                    f"Pass one of: {', '.join(allowed)} — or omit reasoning_effort to use the "
                    "model's default. amicus_models lists each alias's declared efforts. "
                    "Refused locally (zero spend): kimi ignores an unrecognized effort instead "
                    "of rejecting it, so the run would silently use the default while the "
                    "result claimed otherwise."
                ),
            ),
        )

    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        # ORDER MATTERS: shape, then the catalog (it decides alone when it names the alias),
        # then the fallback vocabulary ONLY when the catalog is silent. Compare the EXACT
        # value prepare() will send: normalizing here would validate a string the run never
        # uses. See ADR 0009.
        effort = self._effort(request)
        if effort is not None:
            reason = reasoning_effort_shape_error(effort)
            if reason is not None:
                return ClassifiedFailure(
                    code="invalid_reasoning_effort",
                    detail=f"the requested reasoning_effort {reason}.",
                    details={"field": "reasoning_effort"},
                )
            supported = models.supported_efforts_for(self._model(request), self._models.read())
            if supported:
                if effort not in supported:
                    return self._effort_refusal(
                        "the requested reasoning_effort is not one this model declares.",
                        supported,
                    )
            elif effort not in contract.REASONING_EFFORT_FALLBACK_VOCABULARY:
                return self._effort_refusal(
                    "the requested reasoning_effort matches no known kimi effort level.",
                    tuple(sorted(contract.REASONING_EFFORT_FALLBACK_VOCABULARY)),
                )
        raw = request.instructions_append
        if raw is not None and request.kind not in _INSTRUCTION_KINDS:
            return ClassifiedFailure(
                code="invalid_arguments",
                detail=(
                    f"instructions_append is not accepted for kind {request.kind!r}: only "
                    "consult and review_changes carry caller instructions (delegate edits files)."
                ),
                details={"field": "instructions_append"},
            )
        if raw is not None:
            text = instructions.normalize(raw)
            if text is None:
                return ClassifiedFailure(
                    code="invalid_arguments",
                    detail="instructions_append is blank after normalization.",
                    details={"field": "instructions_append"},
                )
            boundary = instructions.boundary_error(text)
            if boundary is not None:
                return ClassifiedFailure(
                    code="invalid_arguments",
                    detail=f"instructions_append {boundary[0]}",
                    details={"field": "instructions_append"},
                )
        return None

    @contextlib.asynccontextmanager
    async def prepare(self, request: RunRequest) -> AsyncIterator[PreparedRun]:
        """Stage the out-of-workspace handshake dir (prompt file; read-only agent profile or
        answer file), the argv pointer, and the effort/output-format environment; tear the
        dir down on exit, so the answer file must be read inside the context."""
        if (invalid := self.validate_request(request)) is not None:
            raise ValueError(invalid.detail)
        resolved_bin = self._binary.resolve()
        if resolved_bin is None:
            raise BinaryNotFoundError(
                "the kimi binary could not be resolved; refusing to spawn a PATH-searched "
                "fallback."
            )
        read_only = self._read_only(request)
        prompt_text = request.prompt
        caller = instructions.normalize(request.instructions_append)
        if caller is not None:
            prompt_text = instructions.compose(caller) + "\n\n" + prompt_text
        if request.schema is not None:
            prompt_text += cli.schema_instruction(request.schema)
        isolation = request.isolation or self._config.isolation
        handshake_dir = cli.create_handshake_dir()
        try:
            paths = cli.write_handshake(handshake_dir, prompt_text, read_only=read_only)
            cmd, dropped = cli.build_exec_command(
                kimi_bin=resolved_bin,
                read_only=read_only,
                prompt_pointer=cli.build_prompt_pointer(paths, read_only=read_only),
                model=self._model(request),
                agent_file_path=paths.get("agent"),
                skills_dir=kimi_config.skills_dir_for(isolation, self._config.state_dir),
                flag_support=self._help_probe.flag_support(),
            )
            yield PreparedRun(
                argv=tuple(cmd),
                env=cli.build_run_env(
                    self.scrub_env(dict(os.environ), request.config_mode), self._effort(request)
                ),
                cwd=request.cwd,
                stdin_text=None,  # kimi ignores stdin
                orphan_marker=request.cwd
                if len(request.cwd) >= runtime.MIN_ORPHAN_MARKER_LENGTH
                else None,
                artifacts=tuple(paths.values()),
                # Only the answer file is an artifact the loop reads back; the prompt and
                # agent files are inputs, and the loop's reader is the hardened one.
                artifact_paths={"answer": paths["answer"]} if "answer" in paths else {},
                dropped_flags=tuple(dropped),
            )
        finally:
            shutil.rmtree(handshake_dir, ignore_errors=True)

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        answer = self._answer(outcome) or ""
        events = outcome.events or outcome.run.stdout
        usage, session_id = normalize.parse_event_metadata(events)
        structured = normalize.parse_structured(answer) if request.schema is not None else None
        return ExecResult(answer=answer, structured=structured, usage=usage, session_id=session_id)

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        """A zero-exit run with no answer is `empty_response`: kimi has no
        --output-last-message, so a read-only run's only answer channel is the stream, and
        a success whose summary says "no message" would launder that into a result."""
        run = outcome.run
        if run.exit_code != 0 or run.timed_out or run.binary_missing:
            return None
        if self._answer(outcome):
            return None
        return ClassifiedFailure(code="empty_response", detail=EMPTY_RESPONSE_DETAIL)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        aliases = request.sanitize_aliases
        sanitize = (lambda t: worktree.sanitize_echo_prose(t, aliases) or "") if aliases else None
        return cli.classify_failure(
            outcome.run,
            last_message=self._answer(outcome),
            events=outcome.events or outcome.run.stdout or None,
            reasoning_effort=self._effort(request),
            sanitize=sanitize,
        )

    def list_models(self) -> tuple[str, ...]:
        return tuple(m.slug for m in self._models.read().models)

    def auth_probe(self) -> bool | None:
        binary = self._binary.resolve()
        if binary is None:
            return None
        return cli.login_status(binary)[0]

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:  # noqa: ARG002
        # kimi inherits the caller's environment: the provider credentials in the user's
        # config are what authenticate the run; kimi has no config modes.
        return env
```

- [ ] **Step 6: Write the plugin factory**

Replace `src/amicus/backends/kimi/__init__.py`:

```python
"""The Kimi backend plugin (M3): `plugin()` assembles the frozen pontonier contract, the
adapter, and the amicus-side facts from the AMICUS_KIMI_* environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.conventions.annotations import AnnotationEffects
from pontonier.conventions.envelope import BackendErrorVocabulary
from pontonier.conventions.preflight import HelpProbe

from amicus.backends.kimi import config as kimi_config
from amicus.backends.kimi import contract
from amicus.backends.kimi.adapter import KimiBackend
from amicus.backends.kimi.binary import KimiBinary
from amicus.backends.kimi.models import KimiModels
from amicus.backends.kimi.options import options_for
from amicus.backends.kimi.status import KimiStatus
from amicus.plugin import BackendPlugin

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

VOCABULARY = BackendErrorVocabulary(
    backend_id="kimi",
    display_name="Kimi",
    install_hint="Install the kimi CLI (Kimi Code), then rerun amicus_backends.",
    login_hint=(
        "Run `kimi login` or configure a provider in kimi's config.toml, then rerun "
        "amicus_backends."
    ),
    status_tool="amicus_backends",
)
EGRESS = (
    "Sends your question/task, extra_context and instructions_append raw, and the "
    "secret-redacted diff for reviews, to your configured Kimi provider (Moonshot or any "
    "OpenAI-compatible endpoint named in kimi's config.toml) via the kimi CLI. "
    f"{contract.REDACTION_LIMIT_FACT} {contract.SKILLS_DISCOVERY_FACT_FULL} "
    f"{contract.SKILLS_ISOLATION_NOTE}"
)
CARRIERS = (
    "The prompt (framing, question/task/diff, extra_context, and instructions_append as a "
    "leading caller-instructions section) is written to a private handshake file under a "
    "temp dir outside the workspace; argv carries only a short pointer naming that file's "
    "path, the stream-json output flag and, for consult and review, the path of the "
    "generated read-only agent profile. Nothing you type rides argv, and kimi ignores stdin."
)


def plugin(environ: Mapping[str, str] | None = None) -> BackendPlugin:
    cfg = kimi_config.load_config(environ)
    binary = KimiBinary(cfg)
    # resolve() is None only for an unusable AMICUS_KIMI_BIN override; probe that same
    # already-known-unusable value rather than a PATH-searched "kimi".
    token = binary.resolve() or cfg.bin_override or contract.KIMI_BIN
    help_probe = HelpProbe(
        help_argv=(token, *contract.HELP_ARGS),
        always_send_flags=contract.CONTRACT.always_send_flags,
        cache_ttl_seconds=contract.HELP_CACHE_TTL_SECONDS,
    )
    catalog = KimiModels(cfg, binary)
    return BackendPlugin(
        contract=contract.CONTRACT,
        backend=KimiBackend(cfg, binary, help_probe, catalog),
        options=options_for(cfg),
        status=KimiStatus(cfg, binary, help_probe),
        models=catalog,
        binary=binary,
        help_probe=help_probe,
        vocabulary=VOCABULARY,
        env=kimi_config.ENV,
        effects=AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
        egress=EGRESS,
        carriers=CARRIERS,
    )
```

- [ ] **Step 7: Run the tests, then the whole suite**

Run: `uv run --no-sync pytest tests/test_kimi_adapter.py tests/test_kimi_status.py tests/test_kimi_plugin.py -q --no-cov`
Expected: all PASS.

Run: `uv run --no-sync pytest -q`
Expected: green after the four existing-test updates; if `test_discovery.py` or `test_resources.py` fail, they built an explicit registry and must not have changed — investigate before touching them.
Coverage may dip below 95% until Task 8 covers `KimiModels.read` and the status probe end to end; note the number and continue.

- [ ] **Step 8: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests && uv run --no-sync ty check && uv run --no-sync lint-imports
git add src/amicus/backends/kimi tests/support/kimifixtures.py tests/test_kimi_adapter.py tests/test_kimi_status.py tests/test_kimi_plugin.py tests/test_registry.py tests/test_async_tools.py tests/test_dry_run.py tests/test_paid_tools.py
git commit -m "feat(backends): add the kimi adapter, status probe and plugin factory"
```

---

### Task 6: Orchestration: the empty-dir site and the hardened artifact reader

**Files:**
- Modify: `src/amicus/orchestration/isolation.py` (`NO_REPO_WARNING`, `EmptyDirSite`, `select_site`)
- Modify: `src/amicus/orchestration/run.py` (`_read_artifacts`)
- Test: `tests/test_isolation.py` (append), `tests/test_run.py` (append)

**Interfaces:**
- Consumes: `pontonier.core.worktree.{is_git_repo, path_aliases}`, `IsolationPolicy.WORKTREE_ALL_TIERS`, `RunSpec.git_timeout`.
- Produces: `isolation.NO_REPO_WARNING: str`; `isolation.EmptyDirSite()` with the same `cwd`/`aliases`/`security_warnings`/`capture_diff()`/context-manager shape as `DirectSite`; `isolation.select_site(spec, plugin, on_parent=None) -> DirectSite | WorktreeSite | EmptyDirSite`; `run.MAX_ARTIFACT_BYTES = 1_000_000`; `run._read_artifacts(prepared) -> dict[str, str]` reading through `run._read_bounded(path) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_isolation.py`:

```python
def test_empty_dir_site_is_isolated_warned_and_torn_down():
    with isolation.EmptyDirSite() as site:
        assert Path(site.cwd).is_dir() and Path(site.cwd).name.startswith(isolation.WORKTREE_PREFIX)
        assert site.security_warnings == (isolation.NO_REPO_WARNING,)
        assert site.aliases and site.capture_diff() is None
        Path(site.cwd, "scratch.txt").write_text("x")
        cwd = site.cwd
    assert not Path(cwd).exists()


def test_select_site_uses_the_empty_dir_only_for_a_non_repo_consult_under_all_tiers(tmp_path, repo):
    import dataclasses

    all_tiers = fakeplugin.make_plugin(
        contract=dataclasses.replace(
            fakeplugin.make_contract(), isolation_policy=IsolationPolicy.WORKTREE_ALL_TIERS
        )
    )
    assert isinstance(
        isolation.select_site(_spec("consult", str(tmp_path)), all_tiers), isolation.EmptyDirSite
    )
    assert isinstance(
        isolation.select_site(_spec("consult", str(repo)), all_tiers), isolation.WorktreeSite
    )
    assert isinstance(
        isolation.select_site(_spec("review_changes", str(tmp_path)), all_tiers),
        isolation.WorktreeSite,
    )
    assert isinstance(
        isolation.select_site(_spec("delegate", str(tmp_path)), all_tiers), isolation.WorktreeSite
    )
    sandboxed = fakeplugin.make_plugin()
    assert isinstance(
        isolation.select_site(_spec("consult", str(tmp_path)), sandboxed), isolation.DirectSite
    )
```

Append to `tests/test_run.py`:

```python
async def test_non_repo_consult_under_all_tiers_runs_in_an_empty_dir_with_a_warning(
    monkeypatch, tmp_path
):
    import dataclasses

    from pontonier.backend.contract import IsolationPolicy

    from amicus.orchestration import isolation

    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stdout="answer", calls=calls)
    )
    plugin = fakeplugin.make_plugin(
        contract=dataclasses.replace(
            fakeplugin.make_contract(), isolation_policy=IsolationPolicy.WORKTREE_ALL_TIERS
        )
    )
    out = await run_mod.run_request(_spec(cwd=str(tmp_path)), plugin)
    assert out["ok"] is True and out["meta"]["security_warnings"] == [isolation.NO_REPO_WARNING]
    assert calls[0]["cwd"] != str(tmp_path) and not Path(calls[0]["cwd"]).exists()
    review = await run_mod.run_request(_spec(kind="review_changes", cwd=str(tmp_path)), plugin)
    assert review["ok"] is False and review["error"]["code"] == "not_a_git_repo"


def test_artifact_reads_are_hardened(tmp_path):
    import os

    from pontonier.backend.protocol import PreparedRun

    normal = tmp_path / "a.txt"
    normal.write_text("hello")
    link = tmp_path / "link.txt"
    link.symlink_to(normal)
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (run_mod.MAX_ARTIFACT_BYTES + 1))
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    prepared = PreparedRun(
        argv=("x",),
        env={},
        cwd=str(tmp_path),
        artifact_paths={
            "normal": str(normal),
            "link": str(link),
            "big": str(big),
            "fifo": str(fifo),
            "empty": str(empty),
            "missing": str(tmp_path / "missing"),
        },
    )
    assert run_mod._read_artifacts(prepared) == {"normal": "hello"}
```

(`Path` is already imported in `tests/test_run.py`? If not, add `from pathlib import Path`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_isolation.py tests/test_run.py -q --no-cov`
Expected: `AttributeError: EmptyDirSite`, `NO_REPO_WARNING`, `MAX_ARTIFACT_BYTES`; the non-repo consult returns `not_a_git_repo`.

- [ ] **Step 3: Extend isolation.py**

Add `import tempfile` and, after `WORKTREE_CONFIG`:

```python
# Stamped on meta.security_warnings when a consult runs outside a git repository under a
# backend that isolates every tier: the run is still isolated (an empty temp dir), but the
# backend can read nothing, so an answer that appears repo-grounded would be unfounded.
NO_REPO_WARNING = (
    "workspace_root is not a git repository, so this ran in an empty temporary directory: "
    "the backend could not read any repository files and answered only from the prompt."
)
```

Add the site after `DirectSite`:

```python
class EmptyDirSite:
    """An empty temp dir for a consult outside any repository (ADR 0009): isolation is kept,
    nothing is readable, and the caller is told so."""

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.cwd = ""
        self.aliases: tuple[str, ...] = ()
        self.security_warnings: tuple[str, ...] = (NO_REPO_WARNING,)

    def __enter__(self) -> EmptyDirSite:
        self._tmp = tempfile.TemporaryDirectory(prefix=WORKTREE_PREFIX)
        self.cwd = self._tmp.name
        self.aliases = worktree.path_aliases(self.cwd)
        return self

    def __exit__(self, *exc: object) -> bool:
        if self._tmp is not None:
            self._tmp.cleanup()
        return False

    def capture_diff(self) -> str | None:
        return None
```

Replace `select_site`:

```python
def select_site(
    spec: RunSpec, plugin: BackendPlugin, on_parent: Callable[[str], None] | None = None
) -> DirectSite | WorktreeSite | EmptyDirSite:
    all_tiers = plugin.contract.isolation_policy is IsolationPolicy.WORKTREE_ALL_TIERS
    if spec.kind != "delegate" and not all_tiers:
        return DirectSite(spec.cwd)
    # A consult has no diff to gather and nothing to apply, so outside a repository it can
    # still run — isolated in an empty dir. Review needs the repo's diff and delegate needs
    # a baseline, so both keep failing not_a_git_repo (review at gather, delegate at preflight).
    if (
        spec.kind == "consult"
        and all_tiers
        and not worktree.is_git_repo(spec.cwd, timeout=spec.git_timeout)
    ):
        return EmptyDirSite()
    return WorktreeSite(spec.cwd, git_timeout=spec.git_timeout, on_parent=on_parent)
```

- [ ] **Step 4: Harden run.py's reader**

Add `import os` and `from stat import S_ISREG`, then replace `_read_artifacts`:

```python
MAX_ARTIFACT_BYTES = 1_000_000


def _read_bounded(path: str) -> str:
    """An artifact, or "" if it is anything but a plain small regular file. A delegate's
    answer file is written by a full-tool agent, so its path is model-controlled at read
    time: O_NOFOLLOW rejects a substituted symlink, O_NONBLOCK keeps a FIFO from blocking
    before fstat can reject it, and the cap bounds memory (ADR 0009)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        st = os.fstat(fd)
        if not S_ISREG(st.st_mode) or st.st_size > MAX_ARTIFACT_BYTES:
            return ""
        raw = os.read(fd, MAX_ARTIFACT_BYTES)
    except OSError:
        return ""
    finally:
        os.close(fd)
    return raw.decode("utf-8", "replace")


def _read_artifacts(prepared: PreparedRun) -> dict[str, str]:
    texts: dict[str, str] = {}
    for name, path in prepared.artifact_paths.items():
        text = _read_bounded(path)
        if text:
            texts[name] = text
    return texts
```

Remove the now-unused `Path` import if nothing else in the module uses it.

- [ ] **Step 5: Run the tests, then the codex suites (the reader is shared)**

Run: `uv run --no-sync pytest tests/test_isolation.py tests/test_run.py tests/test_codex_adapter.py tests/test_codex_result_differential.py tests/test_sync_tools.py -q --no-cov`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests && uv run --no-sync ty check
git add src/amicus/orchestration/isolation.py src/amicus/orchestration/run.py tests/test_isolation.py tests/test_run.py
git commit -m "feat(orchestration): add the empty-dir consult site and harden artifact reads"
```

---

### Task 7: The moonbridge differentials

**Files:**
- Create: `scripts/capture_kimi_differentials.py`, `tests/fixtures/kimi_differentials.json` (generated)
- Test: `tests/test_kimi_argv_differential.py`, `tests/test_kimi_result_differential.py`

**Interfaces:**
- Consumes: `kimifixtures.{make_backend, normalize_argv, scripted_run_async, load_fixture, ALL_FLAGS, NO_MODEL}` (Task 5); `run_mod.run_request` (Task 6's site logic); `amicus.schemas.codes.generalize_code`.
- Produces: the fixture with keys `sibling_commit`, `argv`, `agent_document`, `schema_instruction`, `run_env`, `prompts`, `envelopes`.

- [ ] **Step 1: Write the capture script**

`scripts/capture_kimi_differentials.py`:

```python
#!/usr/bin/env python
"""Capture moonbridge's hot-path behaviour into a fixture amicus's differential tests
compare against. Run INSIDE the sibling's checkout so its package and venv are used:

    cd /Users/bdc/projects/moonbridge && uv run --no-sync python \
        /Users/bdc/projects/amicus-wt-m3/scripts/capture_kimi_differentials.py \
        > /Users/bdc/projects/amicus-wt-m3/tests/fixtures/kimi_differentials.json

Zero spend: nothing here spawns kimi. The argv cases pin the builder with the handshake
paths fixed at /TMP/; the envelope cases feed raw CommandRun/event fixtures through the
sibling's runspace finisher (failures, with the worktree sanitizer) and finalizers
(successes) and record a projection: codes, temporary, retry_after_ms, usage, session_id,
summary/verdict/findings, and four leak checks (secret, secret prefix, worktree path,
relative path).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

for key in list(os.environ):
    if key.startswith("MOONBRIDGE_"):
        del os.environ[key]

from moonbridge import cli_contract, kimi, orchestration, prompts, runspace  # noqa: E402
from moonbridge.backend import schema_instruction  # noqa: E402
from moonbridge.preflight import FlagSupport  # noqa: E402
from moonbridge.schemas import Coverage, Meta  # noqa: E402
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun  # noqa: E402

ALL = FlagSupport(
    supported=frozenset(set(cli_contract.ALWAYS_SEND_FLAGS) | set(cli_contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(cli_contract.ALWAYS_SEND_FLAGS), help_parsed=True)
PATHS_RO = {"prompt": "/TMP/prompt.md", "agent": "/TMP/readonly-agent.md"}
PATHS_RW = {"prompt": "/TMP/prompt.md", "answer": "/TMP/answer.md"}
WT = "/wt/abc"
ALIASES = (WT,)
SECRET = "sk-" + "c" * 32

ARGV_CASES: dict[str, dict] = {
    "consult_default": dict(kind="consult", read_only=True),
    "consult_model": dict(kind="consult", read_only=True, model="k3"),
    "consult_model_gated": dict(kind="consult", read_only=True, model="k3", flags="no_model"),
    "consult_ignore_skills": dict(kind="consult", read_only=True, skills_dir="/TMP/empty-skills"),
    "review_default": dict(kind="review_changes", read_only=True),
    "delegate_default": dict(kind="delegate", read_only=False),
    "delegate_model": dict(kind="delegate", read_only=False, model="k3"),
}


def _argv_case(spec: dict) -> dict:
    paths = PATHS_RO if spec["read_only"] else PATHS_RW
    cmd, dropped = kimi.build_exec_command(
        cwd="/repo",
        sandbox=cli_contract.SANDBOX_READ_ONLY
        if spec["read_only"]
        else cli_contract.SANDBOX_WORKSPACE_WRITE,
        isolation="ignore-skills" if spec.get("skills_dir") else "inherit",
        prompt_pointer=kimi.build_prompt_pointer(paths, read_only=spec["read_only"]),
        model=spec.get("model"),
        agent_file_path=paths.get("agent"),
        skills_dir=spec.get("skills_dir"),
        flag_support=NO_MODEL if spec.get("flags") == "no_model" else ALL,
    )
    return {"argv": cmd, "dropped": dropped, "request": {k: v for k, v in spec.items() if k != "flags"}}


def _meta(effort: str | None = None) -> Meta:
    return Meta(
        cwd="/repo",
        tier="consult",
        sandbox="read-only",
        isolation="inherit",
        model=None,
        reasoning_effort=effort,
        timeout_seconds=60,
        elapsed_ms=0,
    )


VERSION = '{"role":"meta","type":"system.version","version":"0.41.0"}\n'
RESUME = '{"role":"meta","type":"session.resume_hint","session_id":"session_abc"}\n'
USAGE = '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":80}}\n'
STRUCTURED = json.dumps(
    {
        "summary": "Looks fine",
        "verdict": "pass",
        "confidence": "high",
        "findings": [],
        "questions": [],
        "assumptions": [],
        "next_steps": [],
    }
)


def _assistant(text: str) -> str:
    return json.dumps({"role": "assistant", "content": text}) + "\n"


ENVELOPE_CASES: dict[str, dict] = {
    "consult_structured": dict(kind="consult", events=VERSION + _assistant(STRUCTURED) + RESUME, stderr="", exit_code=0),
    "consult_prose": dict(kind="consult", events=VERSION + _assistant("A plain answer.") + RESUME, stderr="", exit_code=0),
    "consult_usage": dict(kind="consult", events=VERSION + USAGE + _assistant("ok") + RESUME, stderr="", exit_code=0),
    "consult_tool_calls_only": dict(
        kind="consult",
        events=VERSION + '{"role":"assistant","tool_calls":[{"id":"Read:0"}]}\n' + RESUME,
        stderr="",
        exit_code=0,
    ),
    "consult_empty_stream": dict(kind="consult", events=VERSION + RESUME, stderr="", exit_code=0),
    "consult_malformed_events": dict(kind="consult", events='{not json\n' + _assistant("ok"), stderr="", exit_code=0),
    "review_structured": dict(kind="review_changes", events=VERSION + _assistant(STRUCTURED) + RESUME, stderr="", exit_code=0),
    "review_invalid_json": dict(kind="review_changes", events=VERSION + _assistant("prose") + RESUME, stderr="", exit_code=0),
    "review_non_object": dict(kind="review_changes", events=VERSION + _assistant("[1, 2]") + RESUME, stderr="", exit_code=0),
    "auth": dict(kind="consult", events="", stderr="Error: 401 Unauthorized", exit_code=1),
    "rate_limit": dict(kind="consult", events="", stderr="429 Too Many Requests; retry-after: 5", exit_code=1),
    "rate_limit_event": dict(
        kind="consult",
        events='{"type":"turn.failed","message":"rate limit reached; try again in 2 seconds"}\n',
        stderr="",
        exit_code=1,
    ),
    "drift": dict(kind="consult", events="", stderr="error: unknown option '--zap'", exit_code=1),
    "prompt_mode_drift": dict(kind="consult", events="", stderr="Cannot combine --prompt with --yolo.", exit_code=1),
    "invalid_model": dict(
        kind="consult", events="", stderr='error: failed to run prompt: Model "nope" is not configured in config.toml.', exit_code=1
    ),
    "unresolved_default_model": dict(
        kind="consult",
        events="",
        stderr="error: failed to run prompt: model foo does not resolve to a configured provider",
        exit_code=1,
    ),
    "model_prose_is_not_invalid_model": dict(
        kind="consult",
        events=_assistant("the alias does not resolve to a configured provider, per the docs"),
        stderr="",
        exit_code=3,
    ),
    "timeout": dict(kind="consult", events="", stderr=TIMED_OUT, exit_code=-9, timed_out=True),
    "binary_missing": dict(kind="consult", events="", stderr=BINARY_NOT_FOUND, exit_code=127),
    "nonzero_secret": dict(kind="consult", events="", stderr=f"boom token={SECRET}", exit_code=3),
    "nonzero_worktree_path": dict(kind="consult", events="", stderr="failed reading {WT}/src/a.py", exit_code=2),
    "nonzero_secret_straddles_cut": dict(kind="consult", events="", stderr="x" * 290 + f" token={SECRET}", exit_code=2),
}


def _envelope_case(spec: dict) -> dict:
    events = spec["events"]
    stderr = spec["stderr"].replace("{WT}", WT)
    run = CommandRun(events, stderr, spec["exit_code"], 12, spec.get("timed_out", False))
    result = kimi.KimiRunResult(run=run, last_message=kimi._resolve_answer(None, events), events=events)
    meta = _meta()
    finished = runspace._finish(result, meta, diff="", aliases=ALIASES)
    if finished.error is not None:
        env = finished.error
    elif spec["kind"] == "consult":
        env = orchestration.finalize_consult(result, meta=meta)
    else:
        env = orchestration.finalize_review(result, meta=meta, coverage=Coverage(status="complete"))
    projection: dict = {"ok": env["ok"]}
    if env["ok"]:
        for key in ("summary", "verdict", "confidence", "review_status"):
            if key in env:
                projection[key] = env[key]
        projection["findings"] = env.get("findings", [])
    else:
        message = env["error"]["message"]
        projection["error"] = {k: env["error"].get(k) for k in ("code", "temporary", "retry_after_ms")}
        projection["message_has_secret"] = SECRET in message
        projection["message_has_secret_prefix"] = "sk-cccc" in message
        projection["message_has_worktree_path"] = WT in message
        projection["message_has_relative_path"] = "src/a.py" in message
    m = env["meta"]
    projection["meta"] = {
        "usage": m.get("usage"),
        "session_id": m.get("session_id"),
        "command_exit_code": m.get("command_exit_code"),
    }
    return {"input": spec, "sibling": projection}


def main() -> int:
    commit = subprocess.run(
        ["git", "log", "-1", "--format=%h"], capture_output=True, text=True, check=True
    ).stdout.strip()
    run_env = kimi.build_run_env("high")
    out = {
        "sibling_commit": commit,
        "argv": {name: _argv_case(spec) for name, spec in ARGV_CASES.items()},
        "agent_document": kimi.read_only_agent_document(),
        "schema_instruction": schema_instruction({"type": "object"}),
        "run_env": {k: v for k, v in run_env.items() if k.startswith("KIMI_MODEL_")},
        "prompts": {
            "consult": prompts.build_consult_prompt("Why?", "some context"),
            "review": prompts.build_review_prompt("DIFF TEXT", "working_tree", "author intent"),
            "delegate": prompts.build_delegate_prompt("Do the thing."),
        },
        "envelopes": {name: _envelope_case(spec) for name, spec in ENVELOPE_CASES.items()},
    }
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Generate the fixture inside moonbridge's venv**

```bash
cd /Users/bdc/projects/moonbridge && uv run --no-sync python \
    /Users/bdc/projects/amicus-wt-m3/scripts/capture_kimi_differentials.py \
    > /Users/bdc/projects/amicus-wt-m3/tests/fixtures/kimi_differentials.json
cd /Users/bdc/projects/amicus-wt-m3
uv run --no-sync python -c "import json; d=json.load(open('tests/fixtures/kimi_differentials.json')); print(d['sibling_commit'], len(d['argv']), len(d['envelopes']))"
grep -c "sk-cccc" tests/fixtures/kimi_differentials.json
```

Expected: `f6df12d 7 22`; the secret appears only in the `input` halves (the grep count equals the number of secret-bearing inputs, 2) — open the file and confirm no `sibling.message_has_secret` is `true`.
If the script fails on a moonbridge API it expected (a renamed function, a Meta field), read the sibling's source at `f6df12d` and adapt the script; never edit the sibling.

- [ ] **Step 3: Write the differential tests**

`tests/test_kimi_argv_differential.py`:

```python
"""Differential: amicus's staged argv, agent document, schema instruction, run env and
prompts == moonbridge's (captured by scripts/capture_kimi_differentials.py), temp paths,
the binary token and the agent name aside."""

from __future__ import annotations

import pytest
from pontonier.backend.protocol import RunRequest
from pontonier.conventions.prompts import (
    build_consult_prompt,
    build_delegate_prompt,
    build_review_prompt,
    framings,
)
from tests.support import kimifixtures as kf

from amicus.backends.kimi import cli

SIBLING_HOST = "Claude Code"
FIXTURE = kf.load_fixture()


@pytest.mark.parametrize("case", sorted(FIXTURE["argv"]))
async def test_staged_argv_matches_the_sibling(pinned_kimi_bin, monkeypatch, tmp_path, case):
    entry = FIXTURE["argv"][case]
    req = entry["request"]
    environ = {"AMICUS_STATE_DIR": str(tmp_path / "state")}
    if req.get("skills_dir"):
        environ["AMICUS_KIMI_ISOLATION"] = "ignore-skills"
    _, backend = kf.make_backend(environ, flags=kf.NO_MODEL if entry["dropped"] else kf.ALL_FLAGS)
    request = RunRequest(
        kind=req["kind"],
        prompt="p",
        cwd=str(tmp_path),
        timeout_seconds=60,
        model=req.get("model"),
        access=None if req["read_only"] or req["kind"] == "delegate" else "read-only",
    )
    async with backend.prepare(request) as prepared:
        ours = kf.normalize_argv(prepared.argv)
        assert list(prepared.dropped_flags) == entry["dropped"]
    assert ours == entry["argv"]


def test_agent_document_schema_instruction_and_env_match_the_sibling():
    theirs = FIXTURE["agent_document"].replace("moonbridge-readonly", "amicus-readonly")
    assert cli.read_only_agent_document() == theirs
    assert cli.schema_instruction({"type": "object"}) == FIXTURE["schema_instruction"]
    env = cli.build_run_env({}, "high")
    assert {k: v for k, v in env.items() if k.startswith("KIMI_MODEL_")} == FIXTURE["run_env"]


def test_user_turn_framings_are_byte_identical_for_the_sibling_host():
    f = framings(SIBLING_HOST)
    p = FIXTURE["prompts"]
    assert build_consult_prompt(f.consult, "Why?", "some context") == p["consult"]
    assert build_review_prompt(f.review, "DIFF TEXT", "working_tree", "author intent") == p["review"]
    assert build_delegate_prompt(f.delegate, "Do the thing.") == p["delegate"]
```

If the prompt assertions fail because moonbridge's `prompts.py` framing names Codex-style host text differently, compare after the same host substitution M1 used (`theirs.replace(SIBLING_HOST, ...)`) and record the wording difference in the PR body; do not change amicus's framing.

`tests/test_kimi_result_differential.py`:

```python
"""Hot-path result differential: the same raw CommandRun/events through amicus's loop with
the real kimi plugin (a real worktree in a tmp repo) vs moonbridge's runspace finisher and
finalizers (captured fixture). Compared on the shared projection; codes are compared after
amicus's `backend_*` generalization."""

from __future__ import annotations

import subprocess

import pytest
from pontonier.core.gitdiff import DiffResult, DiffSummary
from tests.support import kimifixtures as kf

from amicus.orchestration import review
from amicus.orchestration import run as run_mod
from amicus.request import RunSpec
from amicus.schemas.codes import generalize_code

FIXTURE = kf.load_fixture()
SECRET = "sk-" + "c" * 32

# Codes whose `temporary` deliberately differs from the sibling (pontonier's shared table is
# the amicus default). Empty until a run of this test proves a difference; then record the
# pair here AND in the PR body. Value is (sibling_temporary, amicus_temporary).
KNOWN_TEMPORARY_DEVIATIONS: dict[str, tuple[bool, bool]] = {}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.co")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _spec(kind, cwd):
    return RunSpec(
        backend="kimi",
        kind=kind,
        tool=f"amicus_{kind}",
        cwd=str(cwd),
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=60,
        options={"isolation": "inherit"},
        question="q",
        scope="working_tree",
    )


@pytest.mark.parametrize("case", sorted(FIXTURE["envelopes"]))
async def test_envelope_projection_matches_the_sibling(pinned_kimi_bin, monkeypatch, repo, case):
    entry = FIXTURE["envelopes"][case]
    inp, theirs = entry["input"], entry["sibling"]
    plugin, _ = kf.make_backend()
    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        kf.scripted_run_async(
            stdout=inp["events"],
            stderr=inp["stderr"],
            exit_code=inp["exit_code"],
            timed_out=inp.get("timed_out", False),
            calls=calls,
        ),
    )
    if inp["kind"] == "review_changes":
        monkeypatch.setattr(
            review.gitdiff,
            "gather_diff",
            lambda *a, **k: DiffResult(text="DIFF", summary=DiffSummary(1, 1, 0), untracked_detected=0),
        )
    ours = await run_mod.run_request(_spec(inp["kind"], repo), plugin)
    assert ours["ok"] == theirs["ok"], ours
    if theirs["ok"]:
        for key in ("summary", "verdict", "confidence", "review_status"):
            if key in theirs:
                assert ours[key] == theirs[key], key
        assert ours["findings"] == theirs["findings"]
    else:
        assert generalize_code(theirs["error"]["code"], "kimi") == ours["error"]["code"]
        expected_temporary = theirs["error"]["temporary"]
        if ours["error"]["code"] in KNOWN_TEMPORARY_DEVIATIONS:
            expected_temporary = KNOWN_TEMPORARY_DEVIATIONS[ours["error"]["code"]][1]
        assert ours["error"]["temporary"] == expected_temporary
        assert ours["error"]["retry_after_ms"] == theirs["error"]["retry_after_ms"]
        message = ours["error"]["message"]
        assert not theirs["message_has_secret"] and SECRET not in message
        assert not theirs["message_has_secret_prefix"] and "sk-cccc" not in message
        worktree_path = calls[0]["cwd"]
        assert not theirs["message_has_worktree_path"] and worktree_path not in message
        assert ("src/a.py" in message) == theirs["message_has_relative_path"]
    m, tm = ours["meta"], theirs["meta"]
    assert m.get("session_id") == tm["session_id"]
    assert m.get("command_exit_code") == tm["command_exit_code"]
    if tm["usage"] is None:
        assert m.get("usage") is None
    else:
        for key, value in tm["usage"].items():
            assert m["usage"][key] == value, key
```

- [ ] **Step 4: Run the differentials**

Run: `uv run --no-sync pytest tests/test_kimi_argv_differential.py tests/test_kimi_result_differential.py -q --no-cov`
Expected: all PASS, or exactly these two kinds of deviation, each recorded rather than papered over:

1. A `temporary` mismatch on a code: add the `(sibling, amicus)` pair to `KNOWN_TEMPORARY_DEVIATIONS` with a comment naming why pontonier's table is kept (as M1 did for `nonzero_exit`), and list it in the PR body.
2. A `session_id`/`usage` mismatch: amicus's `parse_event_metadata` is a straight port, so a difference is a porting bug — fix normalize.py.

Any argv mismatch beyond the three normalized differences (binary token, temp paths, agent name) is a porting bug in `cli.build_exec_command`; fix the builder.

- [ ] **Step 5: Commit (script and fixture first, tests second)**

```bash
uv run --no-sync ruff check scripts tests && uv run --no-sync ruff format scripts tests
git add scripts/capture_kimi_differentials.py tests/fixtures/kimi_differentials.json
git commit -m "test(backends): capture the moonbridge hot-path differentials"
git add tests/test_kimi_argv_differential.py tests/test_kimi_result_differential.py
git commit -m "test(backends): pin the kimi port against the moonbridge differentials"
```

---

### Task 8: End to end through the fake kimi

**Files:**
- Create: `tests/support/fake_kimi.py`
- Modify: `tests/conftest.py` (the `fake_kimi` fixture)
- Test: `tests/test_kimi_sync_tools.py`

**Interfaces:**
- Consumes: the whole plugin (Task 5), the sites (Task 6), `server.create_app`, `lifecycle.job_store`, `isolation.NO_REPO_WARNING`.
- Produces: conftest fixture `fake_kimi -> Path` (session-scoped copy of the script, executable); the fake honours `FAKE_KIMI_ANSWER`, `FAKE_KIMI_EVENTS`, `FAKE_KIMI_STDERR`, `FAKE_KIMI_EXIT`, `FAKE_KIMI_SLEEP`, `FAKE_KIMI_WRITE`, `FAKE_KIMI_PROVIDERS`, `FAKE_KIMI_ARGV_FILE`, `FAKE_KIMI_PROMPT_FILE`.

- [ ] **Step 1: Write the fake**

`tests/support/fake_kimi.py`:

```python
#!/usr/bin/env python3
"""A stand-in `kimi` executable for end-to-end tests without spend (stdlib only).

Probes: `--version` prints `0.41.0`; `--help` lists every flag the contract sends or
refuses; `provider list --json` prints FAKE_KIMI_PROVIDERS (default: one provider and one
alias `k3` declaring low/medium/high). A `--prompt` run parses the pointer: it copies the
handshake prompt file to FAKE_KIMI_PROMPT_FILE, writes FAKE_KIMI_ANSWER (default: a
structured review/consult JSON) to the answer file the pointer names (write tier only),
optionally writes FAKE_KIMI_WRITE (a relative path) under cwd, prints FAKE_KIMI_EVENTS
(default: a version line, an assistant line carrying the answer, a resume hint) to stdout
and FAKE_KIMI_STDERR to stderr, sleeps FAKE_KIMI_SLEEP seconds, and exits FAKE_KIMI_EXIT
(default 0). FAKE_KIMI_ARGV_FILE gets one JSON line per invocation: the argv (binary
omitted) and the KIMI_MODEL_* environment."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_HELP = """Usage: kimi [options]
  -V, --version                 output the version number
  -S, --session [id]            Resume a session.
  -c, --continue                Continue the previous session.
  -y, --yolo                    Start in Ask When Needed mode.
  --auto                        Start in Never Ask mode.
  -m, --model <model>           LLM model alias to use for this invocation.
  -p, --prompt <prompt>         Run one prompt non-interactively and print the response.
  --output-format <format>      Output format for prompt mode. (choices: "text", "stream-json")
  --skills-dir <dir>            Load skills from this directory instead of auto-discovered.
  --agent-file <path>           Load an agent definition from a Markdown file.
  --add-dir <dir>               Add an additional workspace directory for this session.
  --plan                        Start in plan mode.
  -h, --help                    Show help.
"""
_DEFAULT_PROVIDERS = json.dumps(
    {
        "providers": {"fake": {"apiKey": "sk-fake-not-a-secret", "baseUrl": "https://fake.invalid"}},
        "models": {
            "k3": {
                "displayName": "Kimi K3",
                "defaultEffort": "medium",
                "supportEfforts": ["low", "medium", "high"],
                "provider": "fake",
            }
        },
    }
)
_DEFAULT_ANSWER = json.dumps(
    {
        "summary": "Looks fine",
        "verdict": "pass",
        "confidence": "high",
        "findings": [],
        "questions": [],
        "assumptions": [],
        "next_steps": [],
    }
)
_PROMPT_POINTER = re.compile(r"Read the file (\S+) and follow it exactly")
_ANSWER_POINTER = re.compile(r"write your final answer to (\S+?)\.?$")


def _record(argv: list[str]) -> None:
    path = os.environ.get("FAKE_KIMI_ARGV_FILE")
    if path:
        env = {k: v for k, v in os.environ.items() if k.startswith("KIMI_MODEL_")}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "env": env}) + "\n")


def main(argv: list[str]) -> int:
    _record(argv)
    if argv == ["--version"]:
        print("0.41.0")
        return 0
    if argv == ["--help"]:
        print(_HELP)
        return 0
    if argv == ["provider", "list", "--json"]:
        print(os.environ.get("FAKE_KIMI_PROVIDERS", _DEFAULT_PROVIDERS))
        return 0
    if "--prompt" not in argv:
        print("error: unknown command", file=sys.stderr)
        return 2
    pointer = argv[argv.index("--prompt") + 1]
    prompt_match = _PROMPT_POINTER.search(pointer)
    if prompt_match and os.environ.get("FAKE_KIMI_PROMPT_FILE"):
        Path(os.environ["FAKE_KIMI_PROMPT_FILE"]).write_text(
            Path(prompt_match.group(1)).read_text(encoding="utf-8"), encoding="utf-8"
        )
    answer = os.environ.get("FAKE_KIMI_ANSWER", _DEFAULT_ANSWER)
    answer_match = _ANSWER_POINTER.search(pointer)
    if answer_match and answer:
        Path(answer_match.group(1)).write_text(answer, encoding="utf-8")
    write = os.environ.get("FAKE_KIMI_WRITE")
    if write:
        Path(os.getcwd(), write).write_text("written by fake kimi\n", encoding="utf-8")
    events = os.environ.get("FAKE_KIMI_EVENTS")
    if events is None:
        lines = ['{"role":"meta","type":"system.version","version":"0.41.0"}']
        if answer:
            lines.append(json.dumps({"role": "assistant", "content": answer}))
        lines.append('{"role":"meta","type":"session.resume_hint","session_id":"session-fake"}')
        events = "\n".join(lines) + "\n"
    time.sleep(float(os.environ.get("FAKE_KIMI_SLEEP", "0")))
    sys.stdout.write(events)
    sys.stdout.flush()
    stderr = os.environ.get("FAKE_KIMI_STDERR")
    if stderr:
        sys.stderr.write(stderr + "\n")
    return int(os.environ.get("FAKE_KIMI_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Add to `tests/conftest.py` after `fake_codex`:

```python
@pytest.fixture(scope="session")
def fake_kimi(tmp_path_factory) -> Path:
    """An executable stand-in `kimi` (tests/support/fake_kimi.py) for spend-free runs."""
    src = Path(__file__).parent / "support" / "fake_kimi.py"
    exe = tmp_path_factory.mktemp("fake-kimi") / "kimi"
    shutil.copy(src, exe)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return exe
```

- [ ] **Step 2: Write the failing end-to-end tests**

`tests/test_kimi_sync_tools.py`:

```python
"""End to end, spend-free: MCP client → sync tool → detached worker → real kimi plugin →
the fake kimi executable → delivered envelope, a recoverable job record, and the discovery
tools reading the same fake."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.orchestration.isolation import NO_REPO_WARNING
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_kimi, monkeypatch):
    monkeypatch.setenv("AMICUS_KIMI_BIN", str(fake_kimi))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_KIMI_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_KIMI_PROMPT_FILE", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in (
        "FAKE_KIMI_EXIT",
        "FAKE_KIMI_STDERR",
        "FAKE_KIMI_ANSWER",
        "FAKE_KIMI_WRITE",
        "FAKE_KIMI_EVENTS",
        "FAKE_KIMI_PROVIDERS",
        "FAKE_KIMI_SLEEP",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    return server.create_app(settings, BackendRegistry.load(settings.enabled_backends, entry_points=()))


def _runs(tmp_path):
    """The recorded `--prompt` invocations (probes excluded)."""
    if not (tmp_path / "argv.jsonl").exists():
        return []
    lines = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    return [line for line in lines if "--prompt" in line["argv"]]


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.co")
    _git(r, "config", "user.name", "t")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


async def test_consult_end_to_end_in_a_repo(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "why?",
                "workspace_root": str(repo),
                "instructions_append": "Focus on locking.",
                "model": "k3",
                "reasoning_effort": "high",
            },
        )
    body = res.structured_content
    assert res.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    meta = body["meta"]
    assert meta["backend"] == "kimi" and meta["job_id"] and meta["session_id"] == "session-fake"
    assert meta.get("usage") is None and meta["backend_details"] == {"isolation": "inherit"}
    assert NO_REPO_WARNING not in meta.get("security_warnings", []) and meta["model"] == "k3"
    assert meta["instructions_append"]["bytes"] == 17 and "Focus on locking" not in json.dumps(body)
    prompt = (tmp_path / "prompt.txt").read_text()
    assert "Focus on locking." in prompt and "## Question\nwhy?" in prompt
    assert "TestHost" in prompt and "# Required output format" in prompt
    [run] = _runs(tmp_path)
    argv = run["argv"]
    assert argv[0] == "--prompt" and "--agent-file" in argv and "--add-dir" not in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--model") + 1] == "k3"
    assert run["env"] == {"KIMI_MODEL_THINKING_EFFORT": "high", "KIMI_MODEL_OUTPUT_FORMAT": "stream-json"}
    store = lifecycle.job_store(config.settings())
    rec, payload = store.result_payload(str(repo.resolve()), meta["job_id"])
    assert rec["status"] == "done" and rec["extra"]["backend"] == "kimi"
    assert "why?" not in (store._job_dir(str(repo.resolve()), meta["job_id"]) / "spec.json").read_text()
    listed = subprocess.run(["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert listed.strip().count("\n") == 0


async def test_consult_outside_a_repo_runs_in_an_empty_dir_with_a_warning(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(tmp_path)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["meta"]["security_warnings"] == [NO_REPO_WARNING]


async def test_review_and_delegate_end_to_end(app, tmp_path, repo, monkeypatch):
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes", {"backend": "kimi", "workspace_root": str(repo)}
        )
    body = review.structured_content
    assert body["ok"] is True and body["review_status"] == "completed" and body["verdict"] == "pass"
    assert body["meta"]["context_summary"]["files_changed"] == 1
    monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "Added b.py.")
    async with Client(app) as c:
        delegate = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = delegate.structured_content
    assert body["ok"] is True and body["summary"] == "Added b.py." and "+written by fake kimi" in body["diff"]
    assert not (repo / "b.py").exists() and (repo / "a.py").read_text() == "x = 2\n"
    argv = _runs(tmp_path)[-1]["argv"]
    assert "--agent-file" not in argv and "write your final answer to" in argv[1]


async def test_empty_answer_is_an_empty_response_error(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(repo)}, raise_on_error=False
        )
    assert res.is_error is True
    err = res.structured_content["error"]
    assert err["code"] == "empty_response" and err["backend"] == "kimi"
    assert res.structured_content["meta"]["command_exit_code"] == 0


async def test_unsupported_effort_is_refused_before_spend(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo), "model": "k3", "reasoning_effort": "xhigh"},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_reasoning_effort" and err["temporary"] is False
    assert err["details"]["allowed_values"] == ["low", "medium", "high"]
    assert err["repair"]["tool"] == "amicus_models"
    assert _runs(tmp_path) == []
    async with Client(app) as c:
        ok = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo), "model": "unlisted", "reasoning_effort": "xhigh"},
        )
    assert ok.structured_content["ok"] is True  # fail open on an unlisted alias
    assert _runs(tmp_path)[-1]["env"]["KIMI_MODEL_THINKING_EFFORT"] == "xhigh"


async def test_failures_are_classified_and_recorded(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_EXIT", "1")
    monkeypatch.setenv("FAKE_KIMI_STDERR", "Error: 401 Unauthorized")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(repo)}, raise_on_error=False
        )
    err = res.structured_content["error"]
    assert err["code"] == "backend_auth_required" and err["backend"] == "kimi" and err["temporary"] is False
    assert res.structured_content["meta"]["command_exit_code"] == 1
    monkeypatch.setenv("FAKE_KIMI_STDERR", 'error: failed to run prompt: Model "zz" is not configured in config.toml.')
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(repo), "model": "zz"}, raise_on_error=False
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_model" and err["details"]["field"] == "model" and err["repair"]["tool"] == "amicus_models"


async def test_discovery_tools_read_the_fake(app, tmp_path, repo):
    async with Client(app) as c:
        backends = await c.call_tool("amicus_backends", {"backend": "kimi"})
        models = await c.call_tool("amicus_models", {"backend": "kimi"})
        dry = await c.call_tool("amicus_dry_run", {"backend": "kimi", "workspace_root": str(repo)})
    [entry] = backends.structured_content["backends"]
    assert entry["available"] is True and entry["status"] == {
        "installed": True,
        "version": "0.41.0",
        "authenticated": True,
        "warnings": [],
    }
    assert entry["features"] == ["delegate", "empty_response_detection", "model_validation"]
    assert {o["name"] for o in entry["options"]} == {"isolation"}
    assert entry["options"][0]["allowed_values"] == ["inherit", "ignore-skills"]
    assert "handshake" in entry["carriers"] and "Kimi provider" in entry["egress"]
    body = models.structured_content
    assert body["source"] == "live" and [m["slug"] for m in body["models"]] == ["k3"]
    assert body["models"][0]["supported_reasoning_efforts"] == ["low", "medium", "high"]
    assert dry.structured_content["ok"] is True and dry.structured_content["meta"]["backend"] == "kimi"
    assert _runs(tmp_path) == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_kimi_sync_tools.py -q --no-cov`
Expected: fixture `fake_kimi` not found.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite with coverage**

Run: `uv run --no-sync pytest tests/test_kimi_sync_tools.py -q --no-cov -x`
Expected: all PASS.
If `test_consult_end_to_end_in_a_repo` fails on `security_warnings == []`, the fixture repo has a dirty tree and pontonier stamped a baseline warning; commit the fixture's files before the call (the fixture already commits) or assert `NO_REPO_WARNING not in ...` instead.
If the discovery test's `features` order differs, it is `sorted(contract.supported_features)`; fix the expected list.

Run: `uv run --no-sync pytest -q`
Expected: green, coverage ≥ 95%.

- [ ] **Step 5: Commit**

```bash
uv run --no-sync ruff check src tests && uv run --no-sync ruff format src tests && uv run --no-sync ty check
git add tests/support/fake_kimi.py tests/conftest.py tests/test_kimi_sync_tools.py
git commit -m "test(backends): drive kimi end to end through a fake executable"
```

---

### Task 9: Live gate, ADR 0009, README, pins, full gate, perturbation checks, draft PR

**Files:**
- Create: `tests/test_kimi_live.py`, `docs/adr/0009-m3-kimi-port-decisions.md`
- Modify: `tests/conftest.py` (`live_kimi`), `README.md`, `docs/kimi-help/0.41.0/FINDINGS.md` (live outcome)
- Verify unchanged: `tests/fixtures/manifest_snapshot.*.json`, `tests/fixtures/wire_shape_snapshot.json`, `tests/fixtures/result_format_snapshot.json`, `tests/test_manifest.py`, `tests/test_fingerprint.py`, `tests/test_discovery_cost.py`

- [ ] **Step 1: Write the live suite**

Add to `tests/conftest.py` after `live_codex`:

```python
@pytest.fixture
def live_kimi(monkeypatch, tmp_path):
    """Opt back into the real kimi CLI for `-m integration` tests. Skips when kimi is absent
    or has no provider, unless AMICUS_REQUIRE_LIVE=1 makes that a failure."""
    import json
    import shutil
    import subprocess

    monkeypatch.delenv("AMICUS_KIMI_BIN", raising=False)
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    require = os.environ.get("AMICUS_REQUIRE_LIVE") == "1"
    kimi = shutil.which("kimi")
    if kimi is None:
        (pytest.fail if require else pytest.skip)("kimi CLI not installed")
    probe = subprocess.run(
        [kimi, "provider", "list", "--json"], capture_output=True, text=True, check=False
    )
    try:
        providers = json.loads(probe.stdout).get("providers") or {}
    except (json.JSONDecodeError, AttributeError):
        providers = {}
    if probe.returncode != 0 or not providers:
        (pytest.fail if require else pytest.skip)("kimi has no configured provider")
    return kimi
```

`tests/test_kimi_live.py`:

```python
"""Live tests against the real kimi CLI: paid, opt in with

    AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_kimi_live.py

AMICUS_REQUIRE_LIVE=1 makes a missing or provider-less kimi a failure (the publish gate)."""

from __future__ import annotations

import re
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.orchestration.isolation import NO_REPO_WARNING
from amicus.registry import BackendRegistry

pytestmark = pytest.mark.integration


def _app():
    settings = config.settings()
    return server.create_app(settings, BackendRegistry.load(("kimi",), entry_points=()))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path):
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t.co")
    _git(path, "config", "user.name", "t")
    (path / "m.py").write_text("def f(xs):\n    return xs[0]\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")


async def test_backends_reports_kimi_ready_live(live_kimi):
    async with Client(_app()) as c:
        body = (await c.call_tool("amicus_backends", {"backend": "kimi"})).structured_content
        models = (await c.call_tool("amicus_models", {"backend": "kimi"})).structured_content
    entry = body["backends"][0]
    assert entry["available"] is True and entry["status"]["installed"] is True
    assert entry["status"]["authenticated"] is True, entry["status"]
    assert entry["status"]["version"].startswith("0.41"), entry["status"]
    assert entry["status"]["warnings"] == [], entry["status"]
    assert models["source"] == "live" and models["models"], models


async def test_consult_outside_a_repo_live(live_kimi, tmp_path):
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "Reply in one sentence: what does DRY mean?",
                "workspace_root": str(tmp_path),
                "timeout_seconds": 150,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error")
    assert body["summary"] and body["meta"]["session_id"] and body["meta"]["job_id"]
    assert body["meta"]["security_warnings"] == [NO_REPO_WARNING]


async def test_read_only_profile_is_enforced_live(live_kimi, tmp_path):
    _repo(tmp_path)
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": (
                    "Reply with ONLY a comma-separated list of the exact names of the tools "
                    "you have available in this session. No other words."
                ),
                "workspace_root": str(tmp_path),
                "timeout_seconds": 150,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error")
    names = {t.strip().lower() for t in re.split(r"[,\s]+", body["summary"]) if t.strip()}
    assert not names & {"bash", "write", "edit", "shell"}, body["summary"]
    assert names & {"read", "glob", "grep"}, body["summary"]


async def test_review_changes_live(live_kimi, tmp_path):
    _repo(tmp_path)
    (tmp_path / "m.py").write_text(
        "def f(xs):\n    out = []\n    for i in range(len(xs) + 1):\n        out.append(xs[i])\n    return out\n"
    )
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_review_changes",
            {"backend": "kimi", "workspace_root": str(tmp_path), "timeout_seconds": 150},
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error")
    assert body["review_status"] == "completed"
    assert body["verdict"] in ("concerns", "fail", "pass", "unknown")
    assert body["meta"]["context_summary"]["files_changed"] == 1


async def test_delegate_live(live_kimi, tmp_path):
    _repo(tmp_path)
    before = (tmp_path / "m.py").read_text()
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {
                "backend": "kimi",
                "task": "Add a function g(xs) returning xs[-1] to m.py.",
                "workspace_root": str(tmp_path),
                "timeout_seconds": 180,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error")
    assert body["diff"] and (tmp_path / "m.py").read_text() == before
    listed = subprocess.run(["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert listed.strip().count("\n") == 0


async def test_unknown_model_alias_is_invalid_model_live(live_kimi, tmp_path):
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "hi",
                "workspace_root": str(tmp_path),
                "model": "totally-made-up-alias-9000",
                "timeout_seconds": 60,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_model", body["error"]
```

Run: `uv run --no-sync pytest tests/test_kimi_live.py -q --no-cov`
Expected: `5 deselected` (the default run excludes `-m integration`); nothing spends.

- [ ] **Step 2: Write ADR 0009 and update the README**

`docs/adr/0009-m3-kimi-port-decisions.md`:

```markdown
# ADR 0009: What the M3 Kimi port kept, changed, and dropped

**Status:** Accepted (2026-09-06, M3)

## Context

M3 ports moonbridge's Kimi adapter, CLI contract, handshake staging, normalizer and model catalog behind the M0 plugin seam, onto the M1 orchestration loop.
Kimi differs from Codex in three ways that shape every decision below: it has no sandbox and no approvals, its prompt is argv-only, and it has no last-message output.
The maintainer approved the choices below in the M3 planning session.

## Decisions

- A consult outside a git repository runs in an empty temp dir (`EmptyDirSite`, prefix `amicus-wt-`) with `NO_REPO_WARNING` stamped on `meta.security_warnings`; review and delegate keep failing `not_a_git_repo`.
- `empty_response` is an outcome inspection: `KimiBackend` implements pontonier's `OutcomeInspector`, so a zero-exit run with no answer file and no assistant text is refused as a result without any Kimi branch in the loop.
- Pre-spend effort validation is the adapter's `validate_request`: shape, then the live catalog (which decides alone when it names the alias), then the fallback vocabulary only when the catalog is silent, and fail open on an unlisted alias; the refusal carries `details.allowed_values` and a repair naming `amicus_models`.
- `instructions_append` rides the handshake prompt file as a leading section composed by `schemas.instructions.compose`; consult and review only.
- Artifacts (Kimi's answer file, Codex's last message) are read through a hardened reader: no symlinks, no FIFOs, regular files only, 1 MB cap.
- Kimi 0.41.0 is supported on the captured evidence in `docs/kimi-help/0.41.0/`; the behavioural probes are inherited from moonbridge's 0.39.1 findings and re-checked only where the live gate can observe them.
- Names: `AMICUS_KIMI_*` with `MOONBRIDGE_` legacy twins (none for `BIN`), agent `amicus-readonly`, handshake prefix `amicus-kimi-handshake-`; `AMICUS_KIMI_EXTRA_ARGS` is always refused with the reason.
- Not ported: tiers and sandbox defaults, `WORKTREE_BASE`, the handshake-dir diff exclusion, `reconcile_dropped_model` (the loop's `stamp_run` already does it), the `extra_args_rejected` classifier branch.
- The model catalog is probed live with a 300 s in-process cache; provider names, base URLs and API keys are never parsed.
- The classifier receives the last message and the site sanitizer and sanitizes before truncating, as the spec requires; `finalize` carries `cached_input_tokens`.
- Differentials against moonbridge (`tests/fixtures/kimi_differentials.json`, captured at the sibling commit the fixture names) compare a projection: argv modulo temp paths, the binary token and the agent name; envelope codes after generalization, `temporary`, `retry_after_ms`, usage, session id, summary/verdict/findings, and four leak checks.

## Consequences

- M4 reuses the loop, the sites and the hardened reader unchanged; Claude's outcome inspector follows the same seam Kimi's does.
- A Kimi release that changes a flag or a stream-json line shape shows up as `cli_contract_changed` at run time and as a failed evidence test once the new help is captured under `docs/kimi-help/<version>/`.
```

README changes:

- Status paragraph: "**Status:** milestone M3 (Kimi)." and the sentence "`amicus_consult`, `amicus_review_changes`, `amicus_delegate`, their `_async` twins, both dry runs and the five `amicus_job_*` tools work for `backend=\"codex\"` and `backend=\"kimi\"`; ... Claude Code (M4) still returns `backend_unavailable`; ...".
- "Where things are": add `| The M3 plan (Kimi) | docs/superpowers/plans/2026-09-06-amicus-M3-kimi.md |` and `| Kimi CLI evidence captures | docs/kimi-help/ |`.
- "Resuming the work": `main` carries M3; say "Resume amicus at milestone M4 per the execution model".

- [ ] **Step 3: Verify the pins did not move**

```bash
for p in all codex-kimi claude; do uv run --no-sync python -m amicus.manifest --profile $p | diff -q - tests/fixtures/manifest_snapshot.$p.json && echo "$p unchanged"; done
uv run --no-sync python -m amicus.result_format_snapshot | diff -q - tests/fixtures/result_format_snapshot.json && echo "result format unchanged"
uv run --no-sync python -m amicus.manifest --measure
```

Expected: every profile `unchanged`; the measured bytes equal `MEASURED` in `tests/test_discovery_cost.py` (`all 90979, codex-kimi 90987, claude 90979`).
If anything moved, this milestone changed the wire surface unexpectedly: stop, find the change (`git diff main -- src/amicus/tools src/amicus/schemas`), and either revert it or, if it is deliberate and argued, regenerate the pins in their own commit and explain in the PR body.

- [ ] **Step 4: Full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest && uv run prek run --all-files`
Expected: every step clean; pytest ≥ 95% branch coverage.
Record the test count and coverage for the PR body.

- [ ] **Step 5: Perturbation checks (negative-result rule)**

1. Sanitize-before-truncate: in `src/amicus/backends/kimi/cli.py` change the generic branch to truncate first (`detail = sanitize(raw[:300]) ...`); run `uv run --no-sync pytest tests/test_kimi_cli.py tests/test_kimi_result_differential.py -q --no-cov -k "straddl or sanitized"`; expected: FAIL.
   Revert with `git checkout -- src/amicus/backends/kimi/cli.py`.
2. Read-only guarantee: in `src/amicus/backends/kimi/adapter.py` pass `agent_file_path=None` to `build_exec_command`; run `uv run --no-sync pytest tests/test_kimi_adapter.py tests/test_kimi_sync_tools.py -q --no-cov -k "read_only or consult_end_to_end"`; expected: FAIL (`ValueError: read-only runs require an agent file`).
   Revert.
3. Effort gate: in `adapter.validate_request` return `None` at the top; run `uv run --no-sync pytest tests/test_kimi_adapter.py tests/test_kimi_plugin.py tests/test_kimi_sync_tools.py -q --no-cov -k "conformant or catalog_first or refused_before_spend"`; expected: FAIL (conformance names the bogus effort; the end-to-end test records a run).
   Revert.
4. Empty-dir site: in `src/amicus/orchestration/isolation.py` remove the `EmptyDirSite` branch of `select_site`; run `uv run --no-sync pytest tests/test_isolation.py tests/test_run.py tests/test_kimi_sync_tools.py -q --no-cov -k "empty_dir or non_repo or outside_a_repo"`; expected: FAIL (`not_a_git_repo`).
   Revert.
5. Hardened reader: in `src/amicus/orchestration/run.py` make `_read_bounded` use `Path(path).read_text()`; run `uv run --no-sync pytest tests/test_run.py -q --no-cov -k hardened`; expected: FAIL (the symlink is followed) or a hang on the FIFO — if it hangs, `Ctrl-C` and count that as the failure.
   Revert.
6. Evidence: remove `(0, 41)` from `SUPPORTED_VERSIONS` in `src/amicus/backends/kimi/contract.py`; run `uv run --no-sync pytest tests/test_kimi_contract.py -q --no-cov -k supported_version`; expected: FAIL.
   Revert.
7. Spend guard: run `AMICUS_KIMI_BIN=/usr/bin/true uv run --no-sync pytest tests/test_kimi_adapter.py tests/test_kimi_plugin.py -q --no-cov` and confirm every test still passes without a `--prompt` run reaching `/usr/bin/true` (the conformance probes spawn nothing; `/usr/bin/true` returns empty output to the probes, which read as "not installed").
8. Import contracts: add `from amicus import tools  # noqa: F401` to `src/amicus/backends/kimi/adapter.py`; run `uv run --no-sync lint-imports`; expected: the "backends never import the server layer" contract broken.
   Revert.

Re-run the full gate after the reverts; expected: green.
`git status --short` must be clean.

- [ ] **Step 6: Run the live gate (authorized for this milestone)**

```bash
AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_kimi_live.py -v 2>&1 | tee /private/tmp/claude-501/-Users-bdc-projects-amicus/a0f9f2df-80b0-49b1-83e5-15886665a52f/scratchpad/m3-live.log
```

Expected: 6 passed.
Whatever the outcome, record it verbatim (pass/fail per test, and the error envelope of any failure) in `docs/kimi-help/0.41.0/FINDINGS.md` under "Live gate outcome" and in the PR body.
A failure in `test_read_only_profile_is_enforced_live` that names Bash or Write is a release blocker: stop and report it; do not weaken the assertion.
A model-quality failure (an unparseable review, a delegate that changed nothing) is reported, not retried more than once.

```bash
git add tests/test_kimi_live.py tests/conftest.py docs/adr/0009-m3-kimi-port-decisions.md docs/kimi-help/0.41.0/FINDINGS.md README.md
git commit -m "docs: record ADR 0009, the kimi live gate outcome and the M3 status"
```

(Commit the live test and conftest fixture with the docs; if the docs commit must precede the live run for any reason, split into `test(backends): add the kimi live gate` and `docs: ...`.)

- [ ] **Step 7: Push and open the draft PR**

```bash
git push -u origin feat/m3-kimi
gh pr create --draft --title "feat: M3 kimi backend" --body-file /private/tmp/claude-501/-Users-bdc-projects-amicus/a0f9f2df-80b0-49b1-83e5-15886665a52f/scratchpad/m3-pr-body.md
```

PR body (write it to the path above, filling every angle-bracket placeholder from measured output):

```markdown
## What & why

Milestone M3 of amicus (spec: `docs/superpowers/specs/2026-09-04-amicus-design.md`, row M3; plan: `docs/superpowers/plans/2026-09-06-amicus-M3-kimi.md`).

- `backend="kimi"` is real for `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, their `_async` twins, both dry runs, `amicus_backends` and `amicus_models`: moonbridge's contract, handshake staging, argv builder, stream-json normalizer, live model catalog and classifier ported into `src/amicus/backends/kimi/`.
- Adapter fixes the spec names: the classifier gets the last message and the site sanitizer and sanitizes before truncating; `finalize` carries `cached_input_tokens`; pre-spend effort validation (catalog first, fallback vocabulary, fail open) in `validate_request`; `empty_response` via `OutcomeInspector`.
- Every Kimi tier runs in a worktree; a consult outside a repo runs in an empty temp dir with a security warning (`EmptyDirSite`); the orphan sweep runs on the worktree marker; artifact reads are hardened.
- Kimi 0.41.0 evidence under `docs/kimi-help/0.41.0/`; `SUPPORTED_VERSIONS` gains `(0, 41)`.
- No surface change: `FINGERPRINT` stays `schema-3`, every pin byte-identical.
- ADR 0009 records the decisions.

## Decisions (ADR 0009)

<paste the ten numbered items from the plan's "Decisions made here" section>

## Differences from moonbridge (surfaced by the differentials)

- argv: binary token, handshake temp paths and the agent name (`amicus-readonly`) differ by construction; everything else byte-identical at sibling commit <commit>.
- `KNOWN_TEMPORARY_DEVIATIONS`: <none | the pairs recorded in tests/test_kimi_result_differential.py and why>.
- Prompts: <byte-identical for the sibling host | the wording difference found>.

## Verification

- Gate: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest && uv run prek run --all-files` — passed; <N> tests, coverage <X>% (branch). CI on this PR: <link/outcome>.
- New spend-free suites: `test_kimi_{contract,config,binary,normalize,models,cli,adapter,status,plugin,argv_differential,result_differential,sync_tools}.py`; `check_backend` positive and perturbed (`test_a_perturbed_backend_fails_conformance`).
- Pins: manifest, wire-shape, result-format and discovery-cost fixtures unchanged (verified by diff).
- Perturbation checks: truncate-before-sanitize (fails), agent file omitted (fails), effort gate removed (fails), empty-dir branch removed (fails), hardened reader replaced (fails), `(0, 41)` removed (fails), spend guard holds, import-linter fails on a backends→tools import. All reverted, gate green.
- Live gate (`AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_kimi_live.py`, kimi 0.41.0, one provider): <6 passed | the verbatim outcome>; the read-only tool-list probe reported <the list>.

## Out of scope

- Claude and `amicus_adversarial_review(_async)` (M4); `task=True` wiring (M5); M1's Codex live re-run (due after 2026-09-07T19:14Z).

🤖 Generated with Claude Code

<session link given in the session>
```

- [ ] **Step 8: Stop**

Do not merge, approve, tag, or release.
The maintainer reviews and merges (AGENTS.md rule 8).

---

## Self-review (writing-plans checklist)

- **Spec coverage (M3 row):** Kimi with adapter fixes → Tasks 4–5 (classifier with `last_message` + sanitizer before truncation; `cached_input_tokens` in `finalize`; `validate_request` effort gate; `OutcomeInspector`); `WorktreeSite` all tiers → the contract's `WORKTREE_ALL_TIERS` (Task 1) through the existing `select_site`, plus the empty-dir consult (Task 6); orphan sweep → `needs_orphan_sweep=True` (Task 1) and `orphan_marker=request.cwd` (Task 5), exercised by `run.py`'s existing sweep call; pre-spend effort validation → Task 5 (adapter) and Task 8 (`test_unsupported_effort_is_refused_before_spend` proves zero spend).
  Gate items: hot-path differential vs moonbridge incl. sanitize-before-truncate → Task 7 (`nonzero_secret_straddles_cut`, `nonzero_worktree_path`); `check_backend` positive and perturbed → Task 5 (`test_backend_is_conformant`, `test_a_perturbed_backend_fails_conformance`); `integration_kimi` → Task 9.
  Spec "Plugin interface": the factory, options, status, models, binary, help probe, vocabulary, env, effects, egress and carriers → Task 5.
  Spec "Config": `AMICUS_KIMI_*` with the legacy shim → Task 2.
  Spec "Testing architecture": `check_contract` + `check_backend` per plugin (Tasks 1, 5), argv and result differentials (Task 7), the spend guard (Task 2), the live gate (Task 9).
- **Decisions:** the ten items in "Decisions made here" (ADR 0009, Task 9).
  The plan makes no change to `.github/**`, `AGENTS.md`, `CLAUDE.md`.
- **Placeholder scan:** angle-bracket placeholders exist only in Task 9 Step 7's PR body and are filled from measured output by instruction; `KNOWN_TEMPORARY_DEVIATIONS` starts empty by design with the recording procedure stated (as M1 did); FINDINGS.md's "Live gate outcome" is filled by Task 9 Step 6.
- **Type consistency:** `cli.build_exec_command(*, kimi_bin, read_only, prompt_pointer, model, agent_file_path, skills_dir, flag_support)` (Task 4) is called with exactly those keywords by `adapter.prepare` (Task 5); `cli.classify_failure(run, *, last_message, events, reasoning_effort, sanitize)` (Task 4) is called in that shape by `adapter.classify_failure` (Task 5) and `tests/test_kimi_cli.py`; `models.supported_efforts_for(model, listing)` and `KimiModels.read(force=False)` (Task 3) are used by `adapter.validate_request`/`list_models` (Task 5) and pinned by `kimifixtures.make_backend(catalog=...)` (Task 5); `KimiBackend(config, binary, help_probe, models)` (Task 5) is constructed identically in `__init__.plugin` and in the perturbed-conformance test; `config.skills_dir_for(isolation, state_dir)` (Task 2) is called with `self._config.state_dir` (Task 5); `isolation.select_site` returns `EmptyDirSite` only for `(consult, WORKTREE_ALL_TIERS, not is_git_repo)` (Task 6), which Task 8's non-repo consult and Task 9's live consult rely on; `run._read_artifacts` reads only `artifact_paths`, and Task 5's `prepare` puts only the answer file there.
