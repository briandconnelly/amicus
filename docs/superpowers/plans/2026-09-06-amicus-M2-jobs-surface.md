# amicus M2 Implementation Plan: the jobs surface

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three `_async` twins (`amicus_consult_async`, `amicus_review_changes_async`, `amicus_delegate_async`) and the five `amicus_job_*` tools real: keyed idempotent starts, the task-id lookup, cancellation with hard-kill cleanup, restart survival, and delivery through the one chokepoint.

**Architecture:** The twins run the same `prepare_run` as their sync siblings with the job deadline as the run timeout, then start the detached worker either unkeyed (`start_job`, M1) or keyed through pontonier's `JobStore.start_idempotent`, whose identity is the public `RunSpec` half minus per-connection fields plus a digest of the inputs. The job tools resolve the workspace per ADR 0003, read the store, and deliver stored results through `jobs.delivery.finished_job_envelope`; the task map (`jobs.taskmap.TaskJobMap`) is read for `task_id` filters and echoes. Nothing new is persisted, so `RESULT_FORMAT` stays 1; descriptions change, so `FINGERPRINT` moves to `schema-3`.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `prek`. Runtime: `pontonier==0.9.0` (`JobStore.start_idempotent`, `DiscardOutcome`, `idempotency.arg_hash`/`canonical_json`), `fastmcp>=4.0,<4.1`, `mcp>=2.1,<2.2`, `pydantic>=2`, `anyio>=4`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-04-amicus-design.md` — "Milestones" row M2 (scope: `_async` twins, `amicus_job_*`, idempotency, task↔job mapping, delivery; gate: keyed replay, cancel (keyed/unkeyed), hard-kill cleanup, restart-survival, task-id lookup); "Jobs and tasks"; "Error envelope and codes"; "Testing architecture". ADR 0003 (workspace), ADR 0004 (tasks and jobs), ADR 0005 (envelope), ADR 0007 (M1 decisions). Execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`; binding repo rules: `AGENTS.md`. Sibling read for reference (never edited): `/Users/bdc/projects/codex-in-claude` at `fcd2674` (`server.py` `_start_async`, `_run_sync`, `codex_job_*`).

## Global Constraints

- Repo: `/Users/bdc/projects/amicus`. Work on branch `feat/m2-jobs` in the sibling git worktree `/Users/bdc/projects/amicus-wt-m2` (created from `main` at `376b763`; baseline 575 tests green, 97.05% branch coverage). Never commit to `main`.
- Dependencies exactly as `pyproject.toml` has them; this plan adds none.
- Gate (AGENTS.md rule 2): `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest` at ≥95% branch coverage. Coverage floor never lowered. Every `uv run` assumes `uv sync` ran once; `uv run --no-sync` is fine while iterating.
- Import rules (import-linter, `pyproject.toml`): `amicus.backends.*` never imports `amicus.tools`/`server`/`orchestration`/`jobs`/`middleware`/`errors`/`registry`/`manifest`; `amicus.orchestration`, `amicus.jobs` and `amicus._worker` never import `amicus.server` or `amicus.tools`; `amicus.tools` never imports `amicus.server`. New module `amicus/jobs/lookup.py` may import `amicus.errors`, `amicus.orchestration.workspace`, `amicus.schemas.*`, `amicus.jobs.*`.
- Tool surface stays exactly 18 tools in `amicus.tools.TOOL_ORDER`; 6 resources; no prompts. No tool gains or loses a parameter (`tests/test_paid_tools.py` derives every schema from the matrix; a `ctx: Context | None = None` argument is invisible to the schema and is added freely).
- `backend="kimi"` and `"claude"` keep returning `backend_unavailable`; `amicus_adversarial_review_async` keeps returning `not_implemented` with a loaded backend (verb lands in M4); `task=True` wiring and recording into the task map stay M5.
- Fingerprint: `FINGERPRINT` moves from `amicus/0.1/schema-2` to `amicus/0.1/schema-3` in Task 1 and stays there. `RESULT_FORMAT` stays `1`. Snapshot, hash and digest regeneration is always its own commit (Task 1 Step 6, Task 8 Step 1).
- Prompt inputs never land in `spec.json`, on the worker's argv, in the idempotency index or in a log. The identity hash carries only a sha256 of the canonical inputs JSON.
- Spend guard: `tests/conftest.py` keeps `AMICUS_CODEX_BIN` unusable (autouse); every test in this plan drives `tests/support/fake_codex.py` or a fake worker command. No `-m integration` test is added or run in this milestone (AGENTS.md rule 5).
- Commit messages: Conventional Commits `type(scope): subject`; scopes from `scripts/check_commit_message.py` (`schemas`, `plugin`, `registry`, `config`, `errors`, `middleware`, `server`, `tools`, `resources`, `manifest`, `orchestration`, `jobs`, `tasks`, `backends`, `packaging`, `docs`, `ci`, `deps`, `release`). Imperative lowercase subject, no trailing period. End every commit body with the attribution trailer given in the session.
- Markdown under `docs/`: one sentence per line.
- Off limits (AGENTS.md rules 9, 17): `.github/**`, `AGENTS.md`, `CLAUDE.md`; any sibling checkout; releasing; merging or approving the PR.

## Decisions made here (surface in ADR 0008 and the PR body)

1. **Idempotency identity** = `RunSpec.public()` minus `cwd`, `workspace_source`, `roots_source`, `host_name`, `kind`, `tool` (the index is already keyed by tool, and the rest is per-connection or provenance) plus `inputs_digest` = sha256 of `canonical_json(RunSpec.inputs())`. Same key with a different prompt is `idempotency_conflict`. Supersedes the `request.py` docstring's "public half" wording.
2. **Outcome mapping** for a keyed start: `created` → running handle; `replay` → the existing job's REAL handle (its true status, timestamps, poll hint) with `meta.idempotency_replayed: true`; `conflict` → `idempotency_conflict` (repair `use_new_idempotency_key`, tool = the twin); `unavailable` → `idempotency_result_unavailable` (same repair); `in_progress` → `idempotency_in_progress` with `retry_after_ms: 250`; `io_error` → `internal_error` with `retry_after_ms: 1000` and the repair "retry the same call with the same idempotency_key". An `_async` caller never blocks on `in_progress`.
3. **Sync tools stay unkeyed** (M1 deviation 8); the sibling's keyed-await path (`_await_job_result(keyed=True)`) is not ported.
4. **Async deadline**: a twin's `RunSpec.timeout_seconds` is `settings.job_max_seconds` (default 1800), unclamped; `JobStarted.deadline_seconds` and `meta.timeout_seconds` report it.
5. **`task_id` is a filter**: `amicus_job_list(task_id=...)` with no mapping returns an empty list (`truncated: false`), never an error. The task map lives at `<AMICUS_STATE_DIR>/tasks.json`; every handle, status and summary echoes `task_id` by reverse lookup (null until M5 records entries).
6. **Foreign records**: a record whose `extra.backend` is missing or not a valid backend ref was not written by amicus; status/result/consume/cancel report `job_not_found` for it and list omits it.
7. **Lifecycle-error meta**: a job tool's generated error carries `backend` = the record's backend when resolved (else null), `job_kind` = the record's kind when resolved, `timeout_seconds` = `job_max_seconds`, and the roots state this lookup saw.
8. **Cancel**: `amicus_job_cancel` is the store's `cancel` (SIGTERM, grace `terminate_grace_seconds`, then SIGKILL of the process group, guarded external-path cleanup). A terminal job is returned unchanged. Task-scoped cancel semantics are M5.
9. **Snapshots**: the wire-shape fixture gains a `handles` section (JobStarted, JobStatus, JobListResult) rendered through the real builders; the result-format fixture is unchanged (nothing new is persisted).

## File map

Created:

- `src/amicus/jobs/lookup.py` — everything a job tool needs before it touches the store: workspace resolution per ADR 0003, lifecycle-error meta, `job_not_found`, the backend/kind readers, `JobStatus`/`JobSummary` builders, the task map handle.
- `tests/test_async_tools.py` — the twins end to end through the fake codex (handles, keyed replay/conflict, pre-spend refusals).
- `tests/test_job_tools.py` — the five job tools end to end (status/result/consume/cancel/list, filters, task-id echo, workspace errors).
- `tests/test_job_durability.py` — hard-kill cleanup and restart survival at the store/worker level.
- `tests/test_lookup.py` — unit tests for `jobs/lookup.py`.
- `docs/adr/0008-m2-jobs-surface-decisions.md` — the nine decisions above.

Modified: `src/amicus/schemas/fingerprint.py` (schema-3), `src/amicus/request.py` (`identity`, `arg_hash`), `src/amicus/jobs/lifecycle.py` (`start_async`, replay stamp, idempotency envelopes, `poll_after_ms`/`task_id` on the handle), `src/amicus/tools/_prepare.py` (`background`, advisory text), `src/amicus/tools/{consult,review,delegate}.py` (real twins), `src/amicus/tools/jobs.py` (real tools), `src/amicus/tools/discovery.py` (error-code lists), `src/amicus/wire_shape_snapshot.py` (handles section), `README.md`, `docs/adr/0004-tasks-and-jobs.md`, the pins (`tests/fixtures/*`, `tests/test_manifest.py`, `tests/test_fingerprint.py`, `tests/test_discovery_cost.py`), and the tests that pinned M1's `not_implemented` behavior (`tests/test_paid_tools.py`, `tests/test_sync_tools.py`, `tests/test_discovery.py`, `tests/test_prepare.py`, `tests/test_request.py`, `tests/test_lifecycle.py`, `tests/test_wire_shape.py`).

---

### Task 0: Worktree and baseline

**Files:** none modified.

- [ ] **Step 1: Use the worktree**

The worktree was created while this plan was written:

```bash
cd /Users/bdc/projects/amicus-wt-m2
git status --short          # expected: clean
git branch --show-current   # expected: feat/m2-jobs
git log --oneline -1        # expected: the "docs: add the M2 implementation plan" commit on top of 376b763
```

If it does not exist: `cd /Users/bdc/projects/amicus && git worktree add ../amicus-wt-m2 -b feat/m2-jobs main`, then commit this plan file there.

- [ ] **Step 2: Confirm the prerequisites**

Run: `uv sync && uv run --no-sync python -c "import importlib.metadata as m; print(m.version('pontonier'), m.version('fastmcp'))"`
Expected: `0.9.0 4.0.x`.

Run: `uv run --no-sync python -c "from pontonier.core.jobs import JobStore, DiscardOutcome; from pontonier.core import idempotency; print(JobStore.start_idempotent.__doc__.splitlines()[0]); print(list(DiscardOutcome))"`
Expected: the docstring's first line (`Deduplicated :meth:`start`...`) and the four outcomes `removed`, `missing`, `not_done`, `delete_failed`.

Run: `uv run --no-sync prek install --prepare-hooks`
Expected: hooks installed (the commit-msg hook validates every commit below).

- [ ] **Step 3: Baseline gate**

Run: `uv run --no-sync pytest -q`
Expected: `575 passed, 5 deselected`, coverage ≥ 95%.

---

### Task 1: Fingerprint → schema-3 and the idempotency identity

**Files:**
- Modify: `src/amicus/schemas/fingerprint.py:7`
- Modify: `src/amicus/request.py`
- Test: `tests/test_request.py`, `tests/test_fingerprint.py`, `tests/test_manifest.py`, `tests/test_discovery_cost.py`, `tests/fixtures/manifest_snapshot.*.json`

**Interfaces:**
- Consumes: `pontonier.core.idempotency.canonical_json(payload) -> str`, `idempotency.arg_hash(payload: dict) -> str`.
- Produces: `request.IDENTITY_EXCLUDE: frozenset[str]`; `RunSpec.identity() -> dict[str, Any]`; `RunSpec.arg_hash() -> str` (64 hex chars). Task 2 hashes with `spec.arg_hash()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_request.py`:

```python
def test_identity_drops_connection_and_provenance_fields_and_digests_the_inputs():
    spec = _spec()
    ident = spec.identity()
    for name in ("cwd", "workspace_source", "roots_source", "host_name", "kind", "tool"):
        assert name not in ident, name
    for name in INPUT_FIELDS:
        assert name not in ident, name
    assert ident["backend"] == "codex" and ident["timeout_seconds"] == 60
    assert len(ident["inputs_digest"]) == 64 and int(ident["inputs_digest"], 16) >= 0
    assert "why?" not in json.dumps(ident) and "focus" not in json.dumps(ident)


def test_arg_hash_is_stable_across_connections_but_not_across_prompts_or_knobs():
    a = _spec().arg_hash()
    assert len(a) == 64
    assert _spec(cwd="/elsewhere", host_name="Codex", roots_source="none").arg_hash() == a
    assert _spec(question="why not?").arg_hash() != a
    assert _spec(extra_context=None).arg_hash() != a
    assert _spec(model="o3").arg_hash() != a
    assert _spec(scope="branch").arg_hash() != a
    assert _spec(options={"isolation": "worktree"}).arg_hash() != a
```

Replace the body of `tests/test_fingerprint.py`'s `EXPECTED_SURFACE_DIGEST` and `tests/test_manifest.py`'s `EXPECTED_MANIFEST_HASH` only in Step 6 (they are re-pinned from printed values, never typed by hand).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_request.py -q --no-cov`
Expected: the two new tests FAIL with `AttributeError: 'RunSpec' object has no attribute 'identity'`.

- [ ] **Step 3: Bump the fingerprint and add the identity**

In `src/amicus/schemas/fingerprint.py` change line 7 to:

```python
FINGERPRINT = "amicus/0.1/schema-3"
```

In `src/amicus/request.py` replace the module docstring and add the identity (imports first):

```python
"""RunSpec: the one serializable description of a paid run, split into a PUBLIC half
(spec.json in the job record) and an INPUT half that only ever travels over the worker's
stdin, so amicus itself never persists a prompt. The keyed-dedup identity (ADR 0008) is
the public half minus per-connection fields plus a digest of the input half."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from pontonier.core import idempotency

from amicus.schemas import instructions
from amicus.schemas.envelope import Meta

INPUT_FIELDS: tuple[str, ...] = (
    "question",
    "task",
    "extra_context",
    "instructions_append",
    "focus",
)
# Public fields that describe HOW a call was resolved, not WHAT it asks for: the index is
# already keyed by tool and workspace, and the rest is per-connection (a reconnect must
# replay, not conflict).
IDENTITY_EXCLUDE: frozenset[str] = frozenset(
    {"cwd", "workspace_source", "roots_source", "host_name", "kind", "tool"}
)
```

and inside `RunSpec`, after `inputs_json`:

```python
    def identity(self) -> dict[str, Any]:
        """The effective run inputs a keyed start is deduplicated on. Prompt text never
        enters it; only a sha256 of the canonical inputs JSON does."""
        ident = {k: v for k, v in self.public().items() if k not in IDENTITY_EXCLUDE}
        digest = hashlib.sha256(idempotency.canonical_json(self.inputs()).encode("utf-8"))
        ident["inputs_digest"] = digest.hexdigest()
        return ident

    def arg_hash(self) -> str:
        return idempotency.arg_hash(self.identity())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_request.py -q --no-cov`
Expected: all pass.

Run: `uv run --no-sync pytest -q --no-cov -x -k "not manifest and not fingerprint and not discovery_cost and not wire_shape and not result_format"`
Expected: pass (nothing else reads the fingerprint literal).

- [ ] **Step 5: Commit the code**

```bash
git add src/amicus/schemas/fingerprint.py src/amicus/request.py tests/test_request.py
git commit -m "feat(jobs): define the keyed-dedup identity and move the fingerprint to schema-3"
```

- [ ] **Step 6: Regenerate and re-pin (own commit)**

```bash
for p in all codex-kimi claude; do uv run --no-sync python -m amicus.manifest --profile $p > tests/fixtures/manifest_snapshot.$p.json; done
uv run --no-sync python -m amicus.wire_shape_snapshot > tests/fixtures/wire_shape_snapshot.json
uv run --no-sync python -m amicus.result_format_snapshot > tests/fixtures/result_format_snapshot.json
uv run --no-sync python - <<'PY'
import asyncio
from amicus import manifest, surface
for p in manifest.PROFILES:
    app = manifest.app_for_profile(p)
    print(p, asyncio.run(manifest.manifest_hash(app)), asyncio.run(surface.surface_digest(app)), asyncio.run(manifest.tools_list_bytes(app)))
PY
git diff --stat tests/fixtures
```

Review the diffs: only the fingerprint literal should have moved in the manifest snapshots (and the sentinel-pinned wire/result snapshots should be byte-identical; if they are not, stop and find out why before pinning). Paste the printed hashes into `EXPECTED_MANIFEST_HASH` (`tests/test_manifest.py`), the digests into `EXPECTED_SURFACE_DIGEST` (`tests/test_fingerprint.py`), and the byte counts into `MEASURED` (`tests/test_discovery_cost.py`, update its docstring's "Measured … at schema-2" line to schema-3 and today's date).

```bash
uv run --no-sync pytest -q
git add tests/fixtures tests/test_manifest.py tests/test_fingerprint.py tests/test_discovery_cost.py
git commit -m "test(manifest): re-pin the snapshots at schema-3"
```

---

### Task 2: Keyed start in the lifecycle

**Files:**
- Modify: `src/amicus/jobs/lifecycle.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: `RunSpec.arg_hash()` (Task 1); `JobStore.start_idempotent(cmd_factory, cwd, *, kind, tool, key, arg_hash, extra, write_spec, stdin_text, lock_timeout) -> dict` with `kind` in `created | replay | conflict | unavailable | in_progress | io_error`; `JobStore.status(cwd, job_id) -> dict | None`.
- Produces: `lifecycle.IDEM_LOCK_ACQUIRE_TIMEOUT_S = 0.5`, `IDEM_IN_PROGRESS_RETRY_MS = 250`, `IDEM_IO_ERROR_RETRY_MS = 1000`; `lifecycle.idem_error(code: str, meta: Meta, plugin: BackendPlugin, *, tool: str, retry_after_ms: int | None = None) -> dict`; `lifecycle.mark_replayed(envelope: dict) -> dict`; `lifecycle.job_started_handle(job_id, *, spec, status, started_at, deadline, expires_at, meta, poll_after_ms: int = 1000, task_id: str | None = None) -> dict`; `async lifecycle.start_async(store, spec, meta, plugin, *, deadline: int, idempotency_key: str | None, task_id: str | None = None) -> dict`. Task 3 calls `start_async`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lifecycle.py` (the file already defines `_spec`, `_settings`, `_success`, `_fake_worker_cmd`, `_sleeping_worker_cmd`; `pontonier.core.jobs` is importable as `pjobs`):

```python
from pontonier.core import jobs as pjobs


async def _start(store, spec, key, **kw):
    return await lifecycle.start_async(
        store, spec, meta_for(spec), fakeplugin.make_plugin(), deadline=1800, idempotency_key=key, **kw
    )


async def test_unkeyed_async_start_returns_a_running_handle(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _sleeping_worker_cmd(30))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, None)
    assert out["ok"] is True and out["status"] == "running" and out["deadline_seconds"] == 1800
    assert out["backend"] == "fake" and out["kind"] == "consult" and out["task_id"] is None
    assert out["poll_after_ms"] == 1000 and out["expires_at"] is None
    assert out["follow_up"]["tool"] == "amicus_job_status"
    assert out["follow_up"]["arguments"] == {"job_id": out["job_id"], "workspace_root": str(tmp_path)}
    assert out["meta"]["job_id"] == out["job_id"] and "idempotency_replayed" not in out["meta"]
    store.cancel(str(tmp_path), out["job_id"])


async def test_keyed_start_creates_then_replays_the_real_handle(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    first = await _start(store, spec, "k1")
    assert first["ok"] is True and "idempotency_replayed" not in first["meta"]
    deadline = time.monotonic() + 10
    while store.status(str(tmp_path), first["job_id"])["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    again = await _start(store, spec, "k1")
    assert again["ok"] is True and again["job_id"] == first["job_id"]
    assert again["meta"]["idempotency_replayed"] is True
    assert again["status"] == "done" and again["expires_at"] is not None
    assert again["started_at"] == first["started_at"]
    assert len(store.list_jobs(str(tmp_path))) == 1
    spec_on_disk = json.loads(
        (store._job_dir(str(tmp_path), first["job_id"]) / "spec.json").read_text()
    )
    assert "why?" not in json.dumps(spec_on_disk)


async def test_keyed_start_with_different_inputs_is_a_conflict(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    first = await _start(store, spec, "k2")
    other = await _start(store, _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800, question="else?"), "k2")
    assert other["ok"] is False and other["error"]["code"] == "idempotency_conflict"
    assert other["error"]["temporary"] is False
    assert other["error"]["repair"]["next_step"] == "use_new_idempotency_key"
    assert other["error"]["repair"]["tool"] == "amicus_consult_async"
    assert other["meta"]["backend"] == "fake" and "job_id" not in other["meta"]
    assert len(store.list_jobs(str(tmp_path))) == 1 and first["ok"] is True


async def test_keyed_start_after_the_record_is_gone_is_unavailable(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _fake_worker_cmd(_success(str(tmp_path))))
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    first = await _start(store, spec, "k3")
    deadline = time.monotonic() + 10
    while store.status(str(tmp_path), first["job_id"])["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    assert store.discard(str(tmp_path), first["job_id"]) is pjobs.DiscardOutcome.REMOVED
    gone = await _start(store, spec, "k3")
    assert gone["ok"] is False and gone["error"]["code"] == "idempotency_result_unavailable"
    assert gone["error"]["repair"]["next_step"] == "use_new_idempotency_key"


@pytest.mark.parametrize(
    ("outcome", "code", "retry"),
    [
        ({"kind": "in_progress"}, "idempotency_in_progress", 250),
        ({"kind": "io_error"}, "internal_error", 1000),
        ({"kind": "something_new"}, "idempotency_in_progress", 250),
    ],
)
async def test_transient_keyed_outcomes_are_retryable_envelopes(
    tmp_path, monkeypatch, outcome, code, retry
):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(store, "start_idempotent", lambda *a, **kw: outcome)
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, "k4")
    assert out["ok"] is False and out["error"]["code"] == code
    assert out["error"]["temporary"] is True and out["error"]["retry_after_ms"] == retry
    assert "idempotency_key" in out["error"]["repair"]["alternative"]


async def test_keyed_replay_whose_record_vanished_is_unavailable(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(store, "start_idempotent", lambda *a, **kw: {"kind": "replay", "job_id": "0" * 32})
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, "k5")
    assert out["ok"] is False and out["error"]["code"] == "idempotency_result_unavailable"


async def test_keyed_spawn_failure_is_an_internal_error(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", lambda jd: ["/nonexistent-binary-xyz"])
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    out = await _start(store, spec, "k6")
    assert out["ok"] is False and out["error"]["code"] == "internal_error"
    assert "failed to start background job" in out["error"]["message"]
    assert store.list_jobs(str(tmp_path)) == []


async def test_keyed_start_runs_off_the_event_loop(tmp_path, monkeypatch):
    store = lifecycle.job_store(_settings(tmp_path))
    seen: dict = {}

    def blocking(cmd_factory, cwd, **kw):
        seen["thread"] = threading.current_thread().name
        seen["kw"] = kw
        return {"kind": "conflict"}

    monkeypatch.setattr(store, "start_idempotent", blocking)
    spec = _spec(str(tmp_path), tool="amicus_consult_async", timeout_seconds=1800)
    await _start(store, spec, "k7")
    assert seen["thread"] != threading.main_thread().name
    assert seen["kw"]["key"] == "k7" and seen["kw"]["tool"] == "amicus_consult_async"
    assert seen["kw"]["arg_hash"] == spec.arg_hash() and seen["kw"]["kind"] == "consult"
    assert seen["kw"]["lock_timeout"] == lifecycle.IDEM_LOCK_ACQUIRE_TIMEOUT_S
    assert seen["kw"]["write_spec"] == spec.public() and seen["kw"]["stdin_text"] == spec.inputs_json()
    assert seen["kw"]["extra"] == {"result_format": 1, "backend": "fake", "tool": "amicus_consult_async"}


def test_mark_replayed_stamps_meta_only_when_present():
    assert lifecycle.mark_replayed({"ok": True, "meta": {"job_id": "x"}})["meta"]["idempotency_replayed"] is True
    assert lifecycle.mark_replayed({"ok": False}) == {"ok": False}
```

Add `import time` to the file's imports (it already imports `asyncio`, `json`, `sys`, `threading`, `pytest`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_lifecycle.py -q --no-cov -k "async_start or keyed or transient or mark_replayed"`
Expected: FAIL with `AttributeError: module 'amicus.jobs.lifecycle' has no attribute 'start_async'` (and `mark_replayed`).

- [ ] **Step 3: Implement the keyed start**

In `src/amicus/jobs/lifecycle.py`, update the module docstring's parenthetical to `(the keyed path lands here in M2; ADR 0008)`, then add after `SYNC_PROGRESS_REPORT_TIMEOUT_S`:

```python
# Bound on acquiring the idempotency coordination locks for a keyed start: a peer holding
# the flock degrades to a retryable idempotency_in_progress instead of hanging a worker.
IDEM_LOCK_ACQUIRE_TIMEOUT_S = 0.5
IDEM_IN_PROGRESS_RETRY_MS = 250
IDEM_IO_ERROR_RETRY_MS = 1000
_IDEM_MESSAGES: dict[str, str] = {
    "idempotency_conflict": (
        "idempotency_key already used with different effective arguments (backend, model, "
        "reasoning_effort, scope, options or the prompt inputs)."
    ),
    "idempotency_result_unavailable": (
        "A prior run for this idempotency_key already completed; its result is no longer "
        "available (consumed or evicted)."
    ),
    "idempotency_in_progress": (
        "Idempotency coordination is momentarily busy (a run is still starting or the "
        "workspace lock is contended); retry shortly."
    ),
}
# Terminal keyed outcomes -> (code, retry_after_ms). Anything unexpected degrades to the
# retryable in_progress so a new pontonier outcome can never become a silent success.
_IDEM_TERMINAL: dict[str, tuple[str, int | None]] = {
    "conflict": ("idempotency_conflict", None),
    "unavailable": ("idempotency_result_unavailable", None),
    "in_progress": ("idempotency_in_progress", IDEM_IN_PROGRESS_RETRY_MS),
}
```

Change `job_started_handle`'s signature and body to carry the poll hint and task id:

```python
def job_started_handle(
    job_id: str,
    *,
    spec: RunSpec,
    status: str,
    started_at: str,
    deadline: int,
    expires_at: str | None,
    meta: Meta,
    poll_after_ms: int = 1000,
    task_id: str | None = None,
) -> dict[str, Any]:
    meta.job_id = job_id
    meta.task_id = task_id
    poll_arguments: dict[str, Any] = {"job_id": job_id, "workspace_root": spec.cwd}
    return JobStarted(
        job_id=job_id,
        backend=spec.backend,
        kind=spec.kind,
        status=status,  # ty: ignore[invalid-argument-type]
        started_at=started_at,
        deadline_seconds=deadline,
        poll_after_ms=poll_after_ms,
        expires_at=expires_at,
        task_id=task_id,
        follow_up=Repair(
            next_step="poll_job_status",
            tool="amicus_job_status",
            arguments=poll_arguments,
            alternative=(
                "Poll amicus_job_status with these arguments, honoring poll_after_ms; read "
                "the result with amicus_job_result once result_available is true. Recover a "
                "lost job_id with amicus_job_list."
            ),
        ),
        meta=meta,
    ).model_dump(mode="json")
```

`JobStarted.status` is `Literal["running"]`; a replayed handle of a finished job must still report its real state, so widen the model in `src/amicus/schemas/results.py`:

```python
class JobStarted(SuccessBase):
    job_id: str
    backend: BackendRef
    kind: str
    status: JobState = "running"
```

(`JobState` is already imported there; this widening is a `tool_output_schemas` change and is covered by the schema-3 bump of Task 1 — the pins are regenerated again in Task 8.)

Add after `_spawn_failure`:

```python
def idem_error(
    code: str,
    meta: Meta,
    plugin: BackendPlugin,
    *,
    tool: str,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    return error_envelope(
        code,
        _IDEM_MESSAGES[code],
        meta,
        plugin=plugin,
        retry_after_ms=retry_after_ms,
        repair_tool=tool,
        repair_alternative=(
            "Retry the same call with the same idempotency_key after retry_after_ms."
            if code == "idempotency_in_progress"
            else "Call the same tool again with a new idempotency_key (a new paid run)."
        ),
    )


def _idem_io_error(meta: Meta, plugin: BackendPlugin, *, tool: str) -> dict[str, Any]:
    return error_envelope(
        "internal_error",
        "Transient storage error reading the idempotency record.",
        meta,
        plugin=plugin,
        retry_after_ms=IDEM_IO_ERROR_RETRY_MS,
        repair_tool=tool,
        repair_alternative="Retry the same call with the same idempotency_key.",
    )


def mark_replayed(envelope: dict[str, Any]) -> dict[str, Any]:
    """Stamp meta.idempotency_replayed on an outgoing envelope so the caller can see that no
    new spend occurred. Applied after the envelope is built, never persisted."""
    meta = envelope.get("meta")
    if isinstance(meta, dict):
        meta["idempotency_replayed"] = True
    return envelope
```

Add after `start_job`:

```python
async def start_async(
    store: JobStore,
    spec: RunSpec,
    meta: Meta,
    plugin: BackendPlugin,
    *,
    deadline: int,
    idempotency_key: str | None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """The _async return path. Unkeyed it is exactly start_job. Keyed it reserves
    (tool, key) in the workspace index: a first reservation spawns and returns a running
    handle; a duplicate returns the existing job's REAL handle; the other outcomes become
    their envelopes (ADR 0008 decision 2). The store call blocks on a cross-process lock,
    so it runs off the event loop; an _async caller never waits on in_progress."""
    if idempotency_key is None:
        handle = await start_job(store, spec, meta, plugin, deadline=deadline)
        if handle.get("ok") is True and task_id is not None:
            handle["task_id"] = task_id
            handle["meta"]["task_id"] = task_id
        return handle
    try:
        outcome = await asyncio.to_thread(
            store.start_idempotent,
            worker_cmd,
            spec.cwd,
            kind=spec.kind,
            tool=spec.tool,
            key=idempotency_key,
            arg_hash=spec.arg_hash(),
            extra=_extra(spec),
            write_spec=spec.public(),
            stdin_text=spec.inputs_json(),
            lock_timeout=IDEM_LOCK_ACQUIRE_TIMEOUT_S,
        )
    except OSError as exc:
        return _spawn_failure(exc, meta, plugin)
    result_kind = outcome["kind"]
    if result_kind == "created":
        return job_started_handle(
            outcome["job_id"],
            spec=spec,
            status="running",
            started_at=outcome["started_at"],
            deadline=deadline,
            expires_at=None,
            meta=meta,
            task_id=task_id,
        )
    if result_kind == "replay":
        snap = await asyncio.to_thread(store.status, spec.cwd, outcome["job_id"])
        if snap is None:
            return idem_error("idempotency_result_unavailable", meta, plugin, tool=spec.tool)
        return mark_replayed(
            job_started_handle(
                outcome["job_id"],
                spec=spec,
                status=snap["status"],
                started_at=snap["started_at"],
                deadline=snap["deadline_seconds"],
                expires_at=snap["expires_at"],
                meta=meta,
                poll_after_ms=snap["poll_after_ms"],
                task_id=task_id,
            )
        )
    if result_kind == "io_error":
        return _idem_io_error(meta, plugin, tool=spec.tool)
    code, retry = _IDEM_TERMINAL.get(result_kind, _IDEM_TERMINAL["in_progress"])
    return idem_error(code, meta, plugin, tool=spec.tool, retry_after_ms=retry)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_lifecycle.py tests/test_request.py -q --no-cov`
Expected: all pass. If `test_keyed_start_with_different_inputs_is_a_conflict` reports `in_progress` instead of `conflict`, the first job's reservation was still being published: the fake worker finishes in milliseconds and pontonier publishes inside the same critical section, so this indicates a real bug in the call (check that `write_spec`/`stdin_text` are passed and no exception was swallowed).

Run: `uv run --no-sync pytest -q --no-cov -x -k "not manifest and not fingerprint and not discovery_cost and not wire_shape and not result_format"`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/amicus/jobs/lifecycle.py src/amicus/schemas/results.py tests/test_lifecycle.py
git commit -m "feat(jobs): keyed idempotent starts with real-handle replay"
```

---

### Task 3: The three async twins, end to end

**Files:**
- Modify: `src/amicus/tools/_prepare.py:45-67, 87-110`
- Modify: `src/amicus/tools/consult.py`, `src/amicus/tools/review.py:69-178`, `src/amicus/tools/delegate.py`
- Modify: `src/amicus/tools/discovery.py:121-131, 135-143, 160-175`
- Modify: `tests/test_paid_tools.py:109-119`, `tests/test_sync_tools.py:199-207`, `tests/test_prepare.py:229-240`
- Create: `tests/test_async_tools.py`

**Interfaces:**
- Consumes: `lifecycle.start_async(store, spec, meta, plugin, *, deadline, idempotency_key)` (Task 2); `prepare_run(...)` (M1).
- Produces: `prepare_run(..., background: bool = False)` — when `background` is true the run timeout is `settings.job_max_seconds`, unclamped, and `timeout_seconds` is ignored; `deadline_advisory(would_call_model, prompt_bytes, effort, timeout_seconds, async_tool)` keeps its signature with new text.

- [ ] **Step 1: Write the failing end-to-end tests**

Create `tests/test_async_tools.py`:

```python
"""The _async twins end to end, spend-free: MCP client → twin → keyed/unkeyed detached
worker → real codex plugin → the fake codex executable → a recoverable job record."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_CODEX_STDIN_FILE", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in ("FAKE_CODEX_EXIT", "FAKE_CODEX_STDERR", "FAKE_CODEX_ANSWER", "FAKE_CODEX_WRITE", "FAKE_CODEX_EVENTS", "FAKE_CODEX_SLEEP"):
        monkeypatch.delenv(key, raising=False)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


@pytest.fixture
def store(app):
    return lifecycle.job_store(server.state_of(app).settings)


def _argv_lines(tmp_path):
    p = tmp_path / "argv.jsonl"
    return p.read_text().splitlines() if p.exists() else []


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


async def _wait_done(store, cwd, job_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while True:
        rec = store.status(str(cwd), job_id)
        assert rec is not None, "record vanished"
        if rec["status"] != "running":
            return rec
        assert time.monotonic() < deadline, "job did not finish"
        await asyncio.sleep(0.05)


async def test_consult_async_returns_a_handle_and_the_job_completes(app, store, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult_async",
            {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path)},
        )
        tool = next(t for t in await c.list_tools() if t.name == "amicus_consult_async")
    body = res.structured_content
    Draft202012Validator(tool.output_schema).validate(body)
    assert res.is_error is False and body["ok"] is True and body["status"] == "running"
    assert body["backend"] == "codex" and body["kind"] == "consult"
    assert body["deadline_seconds"] == 1800 and body["meta"]["timeout_seconds"] == 1800
    assert body["meta"]["job_id"] == body["job_id"] and body["task_id"] is None
    assert body["follow_up"]["arguments"] == {"job_id": body["job_id"], "workspace_root": str(tmp_path)}
    rec = await _wait_done(store, tmp_path, body["job_id"])
    assert rec["status"] == "done" and rec["result_ok"] is True
    assert rec["extra"] == {"result_format": 1, "backend": "codex", "tool": "amicus_consult_async"}
    _rec, payload = store.result_payload(str(tmp_path), body["job_id"])
    assert payload["ok"] is True and payload["summary"] == "Looks fine"
    assert "why?" in (tmp_path / "prompt.txt").read_text()
    spec_on_disk = json.loads((store._job_dir(str(tmp_path), body["job_id"]) / "spec.json").read_text())
    assert "why?" not in json.dumps(spec_on_disk) and spec_on_disk["timeout_seconds"] == 1800


async def test_keyed_consult_async_replays_and_conflicts(app, store, tmp_path):
    args = {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path), "idempotency_key": "abc"}
    async with Client(app) as c:
        first = (await c.call_tool("amicus_consult_async", args)).structured_content
        await _wait_done(store, tmp_path, first["job_id"])
        again = (await c.call_tool("amicus_consult_async", args)).structured_content
        other = await c.call_tool(
            "amicus_consult_async", {**args, "question": "why not?"}, raise_on_error=False
        )
    assert "idempotency_replayed" not in first["meta"]
    assert again["ok"] is True and again["job_id"] == first["job_id"]
    assert again["meta"]["idempotency_replayed"] is True and again["status"] == "done"
    assert other.is_error and other.structured_content["error"]["code"] == "idempotency_conflict"
    assert other.structured_content["error"]["repair"]["tool"] == "amicus_consult_async"
    assert len(_argv_lines(tmp_path)) == 1


async def test_review_and_delegate_async_run_in_the_background(app, store, repo, tmp_path, monkeypatch):
    (repo / "a.py").write_text("x = 2\n")
    monkeypatch.setenv("FAKE_CODEX_WRITE", "b.py")
    async with Client(app) as c:
        rev = (await c.call_tool(
            "amicus_review_changes_async",
            {"backend": "codex", "workspace_root": str(repo), "focus": "locking"},
        )).structured_content
        dele = (await c.call_tool(
            "amicus_delegate_async", {"backend": "codex", "task": "add b", "workspace_root": str(repo)}
        )).structured_content
    assert rev["ok"] is True and rev["kind"] == "review_changes"
    assert dele["ok"] is True and dele["kind"] == "delegate"
    rec = await _wait_done(store, repo, rev["job_id"])
    _r, payload = store.result_payload(str(repo), rev["job_id"])
    # A stored result's `tool` is the result KIND's sync name (the models pin it as a
    # Literal); the twin that started the job is on the record's extra.tool.
    assert rec["result_ok"] is True and payload["tool"] == "amicus_review_changes"
    assert rec["extra"]["tool"] == "amicus_review_changes_async"
    assert payload["review_status"] == "completed"
    rec = await _wait_done(store, repo, dele["job_id"])
    _r, payload = store.result_payload(str(repo), dele["job_id"])
    assert rec["result_ok"] is True and "b.py" in (payload["diff"] or "")
    assert not (repo / "b.py").exists()


async def test_async_pre_spend_refusals_never_spawn(app, tmp_path):
    async with Client(app) as c:
        blank = await c.call_tool(
            "amicus_consult_async", {"backend": "codex", "question": "  ", "workspace_root": str(tmp_path)}, raise_on_error=False
        )
        opts = await c.call_tool(
            "amicus_review_changes_async",
            {"backend": "codex", "workspace_root": str(tmp_path), "backend_options": {"access": "readonly"}},
            raise_on_error=False,
        )
        norepo = await c.call_tool(
            "amicus_delegate_async", {"backend": "codex", "task": "t", "workspace_root": str(tmp_path)}, raise_on_error=False
        )
        kimi = await c.call_tool(
            "amicus_consult_async", {"backend": "kimi", "question": "q", "workspace_root": str(tmp_path)}, raise_on_error=False
        )
        sessionless = await c.call_tool(
            "amicus_consult_async", {"backend": "codex", "question": "q"}, raise_on_error=False
        )
    assert blank.structured_content["error"]["code"] == "invalid_arguments"
    assert opts.structured_content["error"]["code"] == "invalid_arguments"
    assert norepo.structured_content["error"]["code"] == "not_a_git_repo"
    assert kimi.structured_content["error"]["code"] == "backend_unavailable"
    assert sessionless.structured_content["error"]["code"] == "invalid_workspace_root"
    assert _argv_lines(tmp_path) == []
```

Then update the three tests that pinned M1's behavior:

`tests/test_paid_tools.py` — replace `test_with_a_loaded_backend_every_async_tool_is_not_implemented_until_m2` with:

```python
@pytest.mark.parametrize("name", sorted(ASYNC_TOOLS))
async def test_async_twins_refuse_pre_spend_without_a_workspace(name):
    app = _app(registry=_fake_registry())
    async with Client(app) as c:
        res = await c.call_tool(name, VALID[name], raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == name)
    err = res.structured_content["error"]
    if name == "amicus_adversarial_review_async":
        assert err["code"] == "not_implemented", err
        assert err["temporary"] is False and err["repair"]["tool"] == "amicus_capabilities"
    else:
        assert err["code"] == "invalid_workspace_root", err
    Draft202012Validator(tool.output_schema).validate(res.structured_content)
```

`tests/test_sync_tools.py` — in `test_delegate_preflight_and_other_backends`, replace the `asy` call and its assertion:

```python
        asy = await c.call_tool(
            "amicus_adversarial_review_async",
            {"backend": "claude", "target": "t", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
    assert plain.structured_content["error"]["code"] == "not_a_git_repo"
    assert kimi.structured_content["error"]["code"] == "backend_unavailable"
    assert asy.structured_content["error"]["code"] == "backend_unavailable"
```

`tests/test_prepare.py` — in `test_clamp_and_deadline_advisory`, replace the last three assertions with:

```python
    text = _prepare.deadline_advisory(True, 10, "high", 300, "amicus_review_changes_async")
    assert text and "amicus_review_changes_async" in text and "300s" in text
    assert "narrow the input" in text and "AMICUS_JOB_MAX_SECONDS" in text and "M2" not in text
    assert _prepare.deadline_advisory(True, 200_000, None, 300, "amicus_delegate_async")
```

and append:

```python
async def test_background_prepare_uses_the_job_deadline_unclamped():
    settings = config.settings({"AMICUS_JOB_MAX_SECONDS": "1500", "AMICUS_TIMEOUT_SECONDS": "60"})
    registry = BackendRegistry({"codex": fakeplugin.make_plugin("codex")}, {})
    prep = await _prepare.prepare_run(
        registry=registry, settings=settings, tool_name="amicus_consult_async", verb="consult",
        backend="codex", backend_options=None, ctx=None, workspace_root="/tmp", model=None,
        reasoning_effort=None, timeout_seconds=5, background=True, question="q",
    )
    assert not isinstance(prep, dict)
    assert prep.spec.timeout_seconds == 1500 and prep.meta.timeout_seconds == 1500
```

(`tests/test_prepare.py` already imports `config`, `BackendRegistry` and `fakeplugin`; check its header and add whichever is missing.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_async_tools.py tests/test_prepare.py -q --no-cov`
Expected: `test_async_tools.py` FAILS with `not_implemented` in the returned envelopes (`assert body["ok"] is True`); `test_background_prepare_uses_the_job_deadline_unclamped` FAILS with `TypeError: prepare_run() got an unexpected keyword argument 'background'`.

- [ ] **Step 3: Implement `background` and the advisory text**

In `src/amicus/tools/_prepare.py`, replace `deadline_advisory`'s returned text:

```python
    return (
        f"This previewed call's prompt size or reasoning effort may exceed the "
        f"{timeout_seconds}s synchronous deadline; narrow the input, raise "
        f"timeout_seconds, or call {async_tool}: a background job is polled instead of "
        "terminated and runs to its own deadline (AMICUS_JOB_MAX_SECONDS)."
    )
```

and delete the `# M2: once the async twins are real, recommend them directly.` comment. In `prepare_run` add the keyword after `timeout_seconds: int | None,`:

```python
    background: bool = False,
```

and replace the timeout computation:

```python
    timeout = (
        settings.job_max_seconds
        if background
        else clamp_timeout(timeout_seconds if timeout_seconds is not None else settings.timeout_seconds)
    )
```

- [ ] **Step 4: Make the twins real**

`src/amicus/tools/consult.py`: delete the inner `_async_run`, and replace the `amicus_consult_async` function with:

```python
    @guard("amicus_consult_async", settings)
    async def amicus_consult_async(
        backend: BackendParam,
        question: QuestionParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        extra_context: ExtraContextParam = None,
        instructions_append: InstructionsAppendParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background consult on the selected backend."""
        err = _resolve.blank_input_error(
            question, "question", "amicus_consult_async", settings, backend
        )
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_consult_async",
            verb="consult",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            background=True,
            instructions_append=instructions_append,
            extra_context=extra_context,
            question=question,
        )
        if isinstance(prep, dict):
            return prep
        return await lifecycle.start_async(
            lifecycle.job_store(settings),
            prep.spec,
            prep.meta,
            prep.plugin,
            deadline=prep.spec.timeout_seconds,
            idempotency_key=idempotency_key,
        )
```

Update `_ASYNC_DESC` to name the deadline: append `" The job runs to AMICUS_JOB_MAX_SECONDS (default 1800s); idempotency_key dedups a retry."` to the existing string (keep the egress sentence). Update `_DESC`: keep as is (it already says to prefer the twin).

`src/amicus/tools/review.py`: in `register_review_changes` delete the inner `_async_run` and replace `amicus_review_changes_async` with:

```python
    @guard("amicus_review_changes_async", settings)
    async def amicus_review_changes_async(
        backend: BackendParam,
        ctx: Context | None = None,
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
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_review_changes_async",
            verb="review_changes",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            background=True,
            instructions_append=instructions_append,
            extra_context=extra_context,
            focus=focus,
            scope=scope,
            base=base,
            commit=commit,
            paths=paths,
            untracked=untracked,
        )
        if isinstance(prep, dict):
            return prep
        return await lifecycle.start_async(
            lifecycle.job_store(settings),
            prep.spec,
            prep.meta,
            prep.plugin,
            deadline=prep.spec.timeout_seconds,
            idempotency_key=idempotency_key,
        )
```

Append to `_REVIEW_ASYNC_DESC`: `" The job runs to AMICUS_JOB_MAX_SECONDS (default 1800s); idempotency_key dedups a retry."`. `register_adversarial` is unchanged (both adversarial tools keep `_run` → `not_implemented`).

`src/amicus/tools/delegate.py`: delete the inner `_async_run`; replace `amicus_delegate_async` with:

```python
    @guard("amicus_delegate_async", settings)
    async def amicus_delegate_async(
        backend: BackendParam,
        task: TaskParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        model: ModelParam = None,
        reasoning_effort: ReasoningEffortParam = None,
        idempotency_key: IdempotencyKeyParam = None,
        backend_options: BackendOptionsParam = None,
    ) -> dict[str, Any]:
        """Start a background delegate on the selected backend."""
        err = _resolve.blank_input_error(task, "task", "amicus_delegate_async", settings, backend)
        if err is not None:
            return err
        prep = await prepare_run(
            registry=registry,
            settings=settings,
            tool_name="amicus_delegate_async",
            verb="delegate",
            backend=backend,
            backend_options=backend_options,
            ctx=ctx,
            workspace_root=workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=None,
            background=True,
            task=task,
        )
        if isinstance(prep, dict):
            return prep
        return await lifecycle.start_async(
            lifecycle.job_store(settings),
            prep.spec,
            prep.meta,
            prep.plugin,
            deadline=prep.spec.timeout_seconds,
            idempotency_key=idempotency_key,
        )
```

Append to `_ASYNC_DESC` in `delegate.py`: `" The job runs to AMICUS_JOB_MAX_SECONDS (default 1800s); idempotency_key dedups a retry."`.

`src/amicus/tools/discovery.py`: define once, above `TOOL_DETAILS`:

```python
_IDEMPOTENCY_CODES = [
    "idempotency_conflict",
    "idempotency_in_progress",
    "idempotency_result_unavailable",
]
```

and set the three real twins' `error_codes` to `_COMMON_PAID_CODES_SYNC + _IDEMPOTENCY_CODES` (consult), `_COMMON_PAID_CODES_SYNC + _REVIEW_CODES + _IDEMPOTENCY_CODES` (review), and `[*_COMMON_PAID_CODES_SYNC, "not_a_git_repo", "git_unavailable", "worktree_error", *_IDEMPOTENCY_CODES]` (delegate). `amicus_adversarial_review_async` keeps `_COMMON_PAID_CODES` (it still returns `not_implemented`) and gains `_IDEMPOTENCY_CODES` in place of its two-code list for consistency.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_async_tools.py tests/test_prepare.py tests/test_paid_tools.py tests/test_sync_tools.py tests/test_discovery.py -q --no-cov`
Expected: all pass. If `test_review_and_delegate_async_run_in_the_background` fails on `payload["tool"]`, check that `RunSpec.tool` (not the sync name) reaches `finalize`; the worker stamps `tool` from the spec.

Run: `uv run --no-sync pytest -q --no-cov -x -k "not manifest and not fingerprint and not discovery_cost and not wire_shape and not result_format"`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/amicus/tools/_prepare.py src/amicus/tools/consult.py src/amicus/tools/review.py src/amicus/tools/delegate.py src/amicus/tools/discovery.py tests/test_async_tools.py tests/test_paid_tools.py tests/test_sync_tools.py tests/test_prepare.py
git commit -m "feat(tools): make the consult, review and delegate async twins real"
```

---

### Task 4: Job lookup helpers

**Files:**
- Create: `src/amicus/jobs/lookup.py`
- Create: `tests/test_lookup.py`

**Interfaces:**
- Consumes: `orchestration.workspace.resolve(explicit, roots, *, allow_cwd) -> WorkspaceResolution(path, source, error_code, error_detail)`, `workspace.roots_from_ctx(ctx) -> (roots, roots_source)`, `workspace.workspace_warning_for(source, cwd)`; `schemas.envelope.Meta`, `Workspace`, `ErrorDetail`; `schemas.results.JobStatus`, `JobSummary`; `jobs.taskmap.TaskJobMap`; `jobs.delivery.STATE_TO_ERROR`; `errors.error_envelope`.
- Produces:
  - `lookup.BACKEND_REF_RE` (compiled `^[a-z][a-z0-9_]*$`, max 64).
  - `lookup.backend_of(row: dict) -> str | None`, `lookup.kind_of(row: dict) -> str`.
  - `async lookup.resolve_job_workspace(settings, ctx, workspace_root) -> tuple[str | None, str | None, str, dict | None]` — `(cwd, source, roots_source, error_envelope)`.
  - `lookup.job_meta(settings, cwd, source, roots_source, *, backend=None, kind=None) -> Meta`.
  - `lookup.workspace_of(cwd, source) -> Workspace`.
  - `lookup.job_not_found(job_id, meta, workspace_root) -> dict`.
  - `lookup.status_model(row, workspace, task_id, meta) -> dict` (a `JobStatus` dump; `meta` is the lifecycle meta from `job_meta`), `lookup.summary_model(row, task_id) -> JobSummary`.
  - `lookup.task_map(settings) -> TaskJobMap` (path `settings.state_dir / "tasks.json"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lookup.py`:

```python
"""jobs/lookup.py: what a job tool resolves and builds before and after touching the store."""

from __future__ import annotations

import pytest

from amicus import config
from amicus.jobs import lookup
from amicus.schemas.results import JobStatus


def _settings(tmp_path, **env):
    return config.settings({"AMICUS_STATE_DIR": str(tmp_path / "state"), **env})


def _row(**kw):
    base = {
        "job_id": "a" * 32,
        "kind": "consult",
        "status": "running",
        "started_at": "2026-09-06T00:00:00+00:00",
        "started_epoch": 0.0,
        "elapsed_ms": 5,
        "deadline_seconds": 1800,
        "completed_epoch": None,
        "expires_at": None,
        "result_available": False,
        "result_ok": None,
        "poll_after_ms": 1000,
        "ttl_seconds": 86400,
        "cleanup_warnings": [],
        "extra": {"result_format": 1, "backend": "codex", "tool": "amicus_consult_async"},
        "events_seen": 0,
        "last_event_at": None,
        "event_age_ms": None,
    }
    base.update(kw)
    return base


def test_backend_and_kind_readers_reject_foreign_rows():
    assert lookup.backend_of(_row()) == "codex"
    assert lookup.backend_of(_row(extra={})) is None
    assert lookup.backend_of(_row(extra={"backend": "Not Valid"})) is None
    assert lookup.backend_of(_row(extra="junk")) is None
    assert lookup.kind_of(_row()) == "consult" and lookup.kind_of(_row(kind="")) == ""


async def test_resolve_job_workspace_explicit_roots_and_errors(tmp_path):
    settings = _settings(tmp_path)
    cwd, source, roots_source, err = await lookup.resolve_job_workspace(settings, None, str(tmp_path))
    assert cwd == str(tmp_path) and source == "param" and err is None
    assert roots_source == "not_negotiated"  # no ctx: no session, no roots capability
    cwd, source, roots_source, err = await lookup.resolve_job_workspace(settings, None, None)
    assert cwd is None and err["ok"] is False
    assert err["error"]["code"] == "invalid_workspace_root"
    assert err["error"]["details"]["field"] == "workspace_root"
    assert err["meta"]["roots_source"] == "not_negotiated" and err["meta"]["timeout_seconds"] == 1800
    _cwd, _source, _rs, err = await lookup.resolve_job_workspace(settings, None, "relative/path")
    assert err["error"]["code"] == "invalid_workspace_root"


async def test_resolve_job_workspace_falls_back_to_cwd_only_when_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path, AMICUS_ALLOW_CWD_WORKSPACE="1")
    cwd, source, _rs, err = await lookup.resolve_job_workspace(settings, None, None)
    assert err is None and source == "cwd" and cwd == str(tmp_path.resolve())
    assert lookup.workspace_of(cwd, source).workspace_warning


def test_job_meta_and_not_found(tmp_path):
    settings = _settings(tmp_path)
    meta = lookup.job_meta(settings, "/repo", "param", "client", backend="codex", kind="delegate")
    assert meta.backend == "codex" and meta.job_kind == "delegate" and meta.cwd == "/repo"
    assert meta.timeout_seconds == 1800 and meta.roots_source == "client"
    bare = lookup.job_meta(settings, None, None, "none")
    assert bare.backend is None and bare.job_kind is None and bare.cwd is None
    env = lookup.job_not_found("b" * 32, meta, "/repo")
    assert env["error"]["code"] == "job_not_found" and "b" * 32 in env["error"]["message"]
    assert env["error"]["repair"]["tool"] == "amicus_job_list"
    assert env["error"]["repair"]["arguments"] == {"workspace_root": "/repo"}
    assert env["error"]["details"]["field"] == "job_id"
    assert "arguments" not in lookup.job_not_found("b" * 32, meta, None)["error"]["repair"]


def test_status_and_summary_models_carry_backend_task_and_detail(tmp_path):
    settings = _settings(tmp_path)
    ws = lookup.workspace_of("/repo", "param")
    meta = lookup.job_meta(settings, "/repo", "param", "client", backend="codex", kind="consult")
    running = lookup.status_model(_row(), ws, None, meta)
    JobStatus.model_validate(running)
    assert running["backend"] == "codex" and running["status"] == "running"
    assert running["poll_after_ms"] == 1000 and running["task_id"] is None
    assert running["workspace"]["cwd"] == "/repo" and running["cleanup_warnings"] == []
    assert running["meta"]["job_kind"] == "consult" and running["meta"]["timeout_seconds"] == 1800
    cancelled = lookup.status_model(
        _row(status="cancelled", cleanup_warnings=["/tmp/x"]), ws, "t-1", meta
    )
    assert cancelled["task_id"] == "t-1" and cancelled["cleanup_warnings"] == ["/tmp/x"]
    assert cancelled["poll_after_ms"] is None and cancelled["meta"]["task_id"] == "t-1"
    summary = lookup.summary_model(_row(status="done", result_available=True, result_ok=False), "t-2")
    assert summary.result_ok is False and summary.task_id == "t-2" and summary.backend == "codex"
    with pytest.raises(ValueError):
        lookup.status_model(_row(extra={}), ws, None, meta)


def test_task_map_lives_under_the_state_dir(tmp_path):
    settings = _settings(tmp_path)
    tm = lookup.task_map(settings)
    tm.record("task-1", "c" * 32)
    assert (tmp_path / "state" / "tasks.json").exists()
    assert lookup.task_map(settings).job_for("task-1") == "c" * 32
    assert lookup.task_map(settings).task_for("c" * 32) == "task-1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_lookup.py -q --no-cov`
Expected: FAIL at import with `ModuleNotFoundError: No module named 'amicus.jobs.lookup'`.

- [ ] **Step 3: Implement the helpers**

Create `src/amicus/jobs/lookup.py`:

```python
"""What every amicus_job_* tool does before and after it touches the JobStore: resolve
the workspace (ADR 0003), build the lifecycle-error meta, read the record's backend and
kind, and render JobStatus/JobSummary. Foreign records (no valid backend tag) are never
reported (ADR 0008 decision 6)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pontonier.core import redaction

from amicus.errors import error_envelope
from amicus.jobs.delivery import STATE_TO_ERROR
from amicus.jobs.taskmap import TaskJobMap
from amicus.orchestration import workspace as ws
from amicus.schemas.envelope import ErrorDetail, Meta, Workspace
from amicus.schemas.results import JobStatus, JobSummary

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings

BACKEND_REF_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TASK_MAP_FILENAME = "tasks.json"


def backend_of(row: dict[str, Any]) -> str | None:
    """The backend tag amicus stamps on every record, or None for a foreign record."""
    extra = row.get("extra")
    value = extra.get("backend") if isinstance(extra, dict) else None
    return value if isinstance(value, str) and BACKEND_REF_RE.match(value) else None


def kind_of(row: dict[str, Any]) -> str:
    kind = row.get("kind")
    return kind if isinstance(kind, str) else ""


def task_map(settings: Settings) -> TaskJobMap:
    return TaskJobMap(settings.state_dir / TASK_MAP_FILENAME)


def workspace_of(cwd: str, source: str | None) -> Workspace:
    return Workspace(
        cwd=cwd,
        workspace_source=source,  # ty: ignore[invalid-argument-type]
        workspace_warning=ws.workspace_warning_for(source, cwd),
    )


def job_meta(
    settings: Settings,
    cwd: str | None,
    source: str | None,
    roots_source: str,
    *,
    backend: str | None = None,
    kind: str | None = None,
) -> Meta:
    """Meta for a lifecycle-GENERATED envelope: the job's backend and kind when a record
    was resolved, the job deadline as the timeout, and the roots state this lookup saw."""
    return Meta(
        backend=backend,
        cwd=cwd,
        workspace_source=source,  # ty: ignore[invalid-argument-type]
        workspace_warning=ws.workspace_warning_for(source, cwd),
        roots_source=roots_source,  # ty: ignore[invalid-argument-type]
        timeout_seconds=settings.job_max_seconds,
        job_kind=kind or None,
    )


async def resolve_job_workspace(
    settings: Settings, ctx: Any, workspace_root: str | None
) -> tuple[str | None, str | None, str, dict[str, Any] | None]:
    """(cwd, source, roots_source, error). The error is a ready envelope whose meta
    carries the roots state, which is often why the caller looks in the wrong place."""
    roots, roots_source = await ws.roots_from_ctx(ctx)
    res = ws.resolve(workspace_root, roots, allow_cwd=settings.allow_cwd_workspace)
    if res.error_code is not None:
        meta = job_meta(settings, None, None, roots_source)
        return (
            None,
            None,
            roots_source,
            error_envelope(
                res.error_code,
                redaction.sanitize_echo_prose(res.error_detail) or "invalid workspace",
                meta,
                details=ErrorDetail(field="workspace_root"),
                candidate_roots=list(roots)
                if res.error_code == "workspace_outside_roots" and roots
                else None,
            ),
        )
    assert res.path is not None
    return res.path, res.source, roots_source, None


def job_not_found(job_id: str, meta: Meta, workspace_root: str | None) -> dict[str, Any]:
    args = {"workspace_root": workspace_root} if workspace_root else None
    return error_envelope(
        "job_not_found",
        f"No job '{redaction.sanitize_echo(job_id)}' in this workspace.",
        meta,
        details=ErrorDetail(field="job_id"),
        repair_arguments=args,
    )


def status_model(
    row: dict[str, Any], workspace: Workspace, task_id: str | None, meta: Meta
) -> dict[str, Any]:
    """A JobStatus dump. Raises ValueError for a foreign row; callers report not-found."""
    backend = backend_of(row)
    if backend is None:
        raise ValueError("record carries no amicus backend tag")
    state = row["status"]
    meta.job_id = row["job_id"]
    meta.task_id = task_id
    return JobStatus(
        meta=meta,
        job_id=row["job_id"],
        backend=backend,
        kind=kind_of(row),
        status=state,
        elapsed_ms=row["elapsed_ms"],
        result_available=row["result_available"],
        result_ok=row["result_ok"],
        poll_after_ms=row["poll_after_ms"] if state == "running" else None,
        expires_at=row["expires_at"],
        task_id=task_id,
        workspace=workspace,
        cleanup_warnings=list(row.get("cleanup_warnings", [])),
    ).model_dump(mode="json")


def summary_model(row: dict[str, Any], task_id: str | None) -> JobSummary:
    backend = backend_of(row)
    if backend is None:
        raise ValueError("record carries no amicus backend tag")
    return JobSummary(
        job_id=row["job_id"],
        backend=backend,
        kind=kind_of(row),
        status=row["status"],
        started_at=row["started_at"],
        elapsed_ms=row["elapsed_ms"],
        result_available=row["result_available"],
        result_ok=row["result_ok"],
        expires_at=row["expires_at"],
        task_id=task_id,
    )


__all__ = [
    "BACKEND_REF_RE",
    "STATE_TO_ERROR",
    "backend_of",
    "job_meta",
    "job_not_found",
    "kind_of",
    "resolve_job_workspace",
    "status_model",
    "summary_model",
    "task_map",
    "workspace_of",
]
```

(`STATE_TO_ERROR` is re-exported so `tools/jobs.py` has one import for everything job-shaped; the `detail` prose for terminal states is not duplicated onto `JobStatus`, which has no such field in the M0 schema.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_lookup.py -q --no-cov && uv run --no-sync lint-imports && uv run --no-sync ty check`
Expected: all pass; contracts kept; no type errors. If `ty` flags `roots_source=roots_source` on `Meta`, keep the targeted `# ty: ignore[invalid-argument-type]` shown above (the `RootsSource` literal is narrower than `str`).

- [ ] **Step 5: Commit**

```bash
git add src/amicus/jobs/lookup.py tests/test_lookup.py
git commit -m "feat(jobs): add the lookup helpers the job tools share"
```

---

### Task 5: The five job tools, end to end

**Files:**
- Modify: `src/amicus/tools/jobs.py`
- Modify: `src/amicus/tools/discovery.py:251-300` (job tools' `error_codes`)
- Modify: `tests/test_discovery.py:86-89`
- Create: `tests/test_job_tools.py`

**Interfaces:**
- Consumes: everything in `jobs.lookup` (Task 4); `jobs.delivery.finished_job_envelope(rec, payload, job_id, kind, meta, detail, workspace_root) -> (dict, bool)`; `JobStore.status/result_payload/discard/cancel/list_jobs`; `pontonier.core.jobs.DiscardOutcome`.
- Produces: the five tools as registered (names unchanged); `tools.jobs.register(app, settings, registry) -> tuple[str, ...]` unchanged.

- [ ] **Step 1: Write the failing end-to-end tests**

Create `tests/test_job_tools.py`:

```python
"""The five amicus_job_* tools end to end through the fake codex: status, result, consume,
cancel, list, the filters, the task-id echo, and the workspace and not-found envelopes."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from pontonier.core.jobs import JobStore

from amicus import config, server
from amicus.jobs import lifecycle, lookup
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in ("FAKE_CODEX_EXIT", "FAKE_CODEX_STDERR", "FAKE_CODEX_ANSWER", "FAKE_CODEX_WRITE", "FAKE_CODEX_EVENTS", "FAKE_CODEX_SLEEP"):
        monkeypatch.delenv(key, raising=False)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


@pytest.fixture
def settings(app):
    return server.state_of(app).settings


@pytest.fixture
def store(settings):
    return lifecycle.job_store(settings)


async def _schemas(c):
    return {t.name: Draft202012Validator(t.output_schema) for t in await c.list_tools()}


async def _start(c, tmp_path, **extra):
    body = (await c.call_tool(
        "amicus_consult_async",
        {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path), **extra},
    )).structured_content
    assert body["ok"] is True
    return body["job_id"]


async def _wait_done(store, cwd, job_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while store.status(str(cwd), job_id)["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)


async def test_status_result_and_consume_lifecycle(app, store, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        job_id = await _start(c, tmp_path)
        status = (await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})).structured_content
        schemas["amicus_job_status"].validate(status)
        assert status["ok"] is True and status["backend"] == "codex" and status["kind"] == "consult"
        assert status["status"] in ("running", "done") and status["task_id"] is None
        assert status["workspace"]["cwd"] == str(tmp_path) and status["workspace"]["workspace_source"] == "param"
        early = await c.call_tool("amicus_job_result", {"job_id": job_id, **ws}, raise_on_error=False)
        if early.is_error:  # the fake finishes in milliseconds; either branch is legitimate
            err = early.structured_content["error"]
            assert err["code"] == "job_running" and err["retry_after_ms"] >= 1000
            assert err["repair"]["arguments"] == {"job_id": job_id, "workspace_root": str(tmp_path)}
            assert early.structured_content["meta"]["job_kind"] == "consult"
        await _wait_done(store, tmp_path, job_id)
        done = (await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})).structured_content
        assert done["status"] == "done" and done["result_available"] is True and done["result_ok"] is True
        assert done["poll_after_ms"] is None and done["expires_at"]
        res = await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})
        body = res.structured_content
        schemas["amicus_job_result"].validate(body)
        assert res.is_error is False and body["ok"] is True and body["tool"] == "amicus_consult"
        assert body["summary"] == "Looks fine" and body["raw_response"]["text"] is None
        assert body["meta"]["job_id"] == job_id and "idempotency_replayed" not in body["meta"]
        full = (await c.call_tool("amicus_job_result", {"job_id": job_id, "detail": "full", **ws})).structured_content
        assert full["raw_response"]["text"]
        again = (await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})).structured_content
        assert again["ok"] is True, "a plain read retains the record"
        consumed = (await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})).structured_content
        assert consumed["ok"] is True and consumed["summary"] == "Looks fine"
        gone = await c.call_tool("amicus_job_result", {"job_id": job_id, **ws}, raise_on_error=False)
        assert gone.is_error and gone.structured_content["error"]["code"] == "job_not_found"
        assert gone.structured_content["error"]["repair"]["arguments"] == ws
        twice = await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False)
        assert twice.structured_content["error"]["code"] == "job_not_found"


async def test_consume_keeps_a_record_it_could_not_deliver(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_EXIT", "7")
    monkeypatch.setenv("FAKE_CODEX_STDERR", "boom")
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        status = (await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})).structured_content
        assert status["result_available"] is True and status["result_ok"] is False
        stored = await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False)
        assert stored.is_error and stored.structured_content["ok"] is False
        assert stored.structured_content["meta"]["job_id"] == job_id
        assert store.status(str(tmp_path), job_id) is None, "a delivered stored error is consumed"
        # A corrupt payload is described, not delivered, so it survives a consume.
        job2 = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job2)
        (store._job_dir(str(tmp_path), job2) / "result.json").write_text('{"ok": true, "tool": "x"}')
        corrupt = await c.call_tool("amicus_job_consume_result", {"job_id": job2, **ws}, raise_on_error=False)
        assert corrupt.structured_content["error"]["code"] == "internal_error"
        assert store.status(str(tmp_path), job2) is not None


async def test_cancel_running_then_terminal_is_idempotent(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "30")
    # The tools build a fresh JobStore per call, so patch the class default, not `store`.
    monkeypatch.setattr(JobStore, "terminate_grace_seconds", 2.0)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        job_id = await _start(c, tmp_path)
        # The worker takes worker.lock before it reads the spec; wait for that, not for
        # backend events (the fake codex prints its events only after its sleep).
        lock = store._job_dir(str(tmp_path), job_id) / "worker.lock"
        deadline = time.monotonic() + 10
        while not lock.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert lock.exists()
        t0 = time.monotonic()
        cancelled = (await c.call_tool("amicus_job_cancel", {"job_id": job_id, **ws})).structured_content
        schemas["amicus_job_cancel"].validate(cancelled)
        assert cancelled["ok"] is True and cancelled["status"] == "cancelled"
        assert cancelled["result_available"] is False and cancelled["cleanup_warnings"] == []
        assert time.monotonic() - t0 < 10
        again = (await c.call_tool("amicus_job_cancel", {"job_id": job_id, **ws})).structured_content
        assert again["status"] == "cancelled" and again["elapsed_ms"] == cancelled["elapsed_ms"]
        res = await c.call_tool("amicus_job_result", {"job_id": job_id, **ws}, raise_on_error=False)
        assert res.structured_content["error"]["code"] == "job_cancelled"
        missing = await c.call_tool("amicus_job_cancel", {"job_id": "f" * 32, **ws}, raise_on_error=False)
        assert missing.structured_content["error"]["code"] == "job_not_found"


async def test_list_filters_and_the_task_id_lookup(app, store, settings, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        first = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, first)
        second = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, second)
        lookup.task_map(settings).record("task-xyz", first)
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        schemas["amicus_job_list"].validate(listed)
        assert [j["job_id"] for j in listed["jobs"]] == [second, first]
        assert listed["truncated"] is False and "truncation_hint" not in listed
        assert listed["jobs"][1]["task_id"] == "task-xyz" and listed["jobs"][0]["task_id"] is None
        assert listed["jobs"][0]["backend"] == "codex" and listed["jobs"][0]["result_ok"] is True
        limited = (await c.call_tool("amicus_job_list", {"limit": 1, **ws})).structured_content
        assert [j["job_id"] for j in limited["jobs"]] == [second] and limited["truncated"] is True
        assert "omit `limit`" in limited["truncation_hint"]
        by_task = (await c.call_tool("amicus_job_list", {"task_id": "task-xyz", **ws})).structured_content
        assert [j["job_id"] for j in by_task["jobs"]] == [first]
        no_task = (await c.call_tool("amicus_job_list", {"task_id": "nope", **ws})).structured_content
        assert no_task["ok"] is True and no_task["jobs"] == [] and no_task["truncated"] is False
        by_status = (await c.call_tool("amicus_job_list", {"status": "running", **ws})).structured_content
        assert by_status["jobs"] == []
        by_backend = (await c.call_tool("amicus_job_list", {"backend": "kimi", **ws})).structured_content
        assert by_backend["jobs"] == []
        status = (await c.call_tool("amicus_job_status", {"job_id": first, **ws})).structured_content
        assert status["task_id"] == "task-xyz"
        result = (await c.call_tool("amicus_job_result", {"job_id": first, **ws})).structured_content
        assert result["meta"]["task_id"] == "task-xyz"


async def test_foreign_and_malformed_records_are_not_found(app, store, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        meta_path = store._job_dir(str(tmp_path), job_id) / "meta.json"
        meta = meta_path.read_text().replace('"backend": "codex"', '"backend": "Not Ours"')
        meta_path.write_text(meta)
        for tool in ("amicus_job_status", "amicus_job_result", "amicus_job_consume_result", "amicus_job_cancel"):
            res = await c.call_tool(tool, {"job_id": job_id, **ws}, raise_on_error=False)
            assert res.structured_content["error"]["code"] == "job_not_found", tool
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        assert listed["jobs"] == []
        assert store.status(str(tmp_path), job_id) is not None, "never deleted, only hidden"


async def test_workspace_rules_apply_to_every_job_tool(app, tmp_path):
    async with Client(app) as c:
        for tool, args in (
            ("amicus_job_status", {"job_id": "a" * 32}),
            ("amicus_job_result", {"job_id": "a" * 32}),
            ("amicus_job_consume_result", {"job_id": "a" * 32}),
            ("amicus_job_cancel", {"job_id": "a" * 32}),
            ("amicus_job_list", {}),
        ):
            res = await c.call_tool(tool, args, raise_on_error=False)
            err = res.structured_content["error"]
            assert err["code"] == "invalid_workspace_root" and err["details"]["field"] == "workspace_root", tool
            assert res.structured_content["meta"]["roots_source"] in ("not_negotiated", "client")
            res = await c.call_tool(tool, {**args, "workspace_root": str(tmp_path)}, raise_on_error=False)
            if tool == "amicus_job_list":
                assert res.structured_content["ok"] is True and res.structured_content["jobs"] == []
            else:
                assert res.structured_content["error"]["code"] == "job_not_found", tool
```

Update `tests/test_discovery.py` lines 86-89 so the free-tool sweep accepts the real outcomes:

```python
                assert res.structured_content["error"]["code"] in {
                    "not_implemented",
                    "backend_unavailable",
                    "invalid_workspace_root",
                }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_job_tools.py -q --no-cov`
Expected: every test FAILS with `not_implemented` envelopes (the stubs).

- [ ] **Step 3: Implement the tools**

Replace `src/amicus/tools/jobs.py` entirely:

```python
"""The five amicus_job_* tools: status, result, consume_result, cancel, list. Every
stored result is delivered through jobs.delivery.finished_job_envelope, the chokepoint
the sync path shares; workspace and roots follow ADR 0003; a record without amicus's
backend tag is foreign and reported not-found (ADR 0008)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastmcp import Context
from pontonier.core.jobs import DiscardOutcome

from amicus.jobs import lifecycle, lookup
from amicus.jobs.delivery import finished_job_envelope
from amicus.schemas.params import (
    DetailParam,
    JobIdParam,
    JobLimitParam,
    JobStatusFilterParam,
    OptionalBackendParam,
    TaskIdParam,
    WorkspaceRootParam,
)
from amicus.schemas.results import JOB_LIST_SCHEMA, JOB_RESULT_SCHEMA, JOB_STATUS_SCHEMA, JobListResult
from amicus.tools._guard import guard
from amicus.tools._meta import annotations_for, lifecycle_meta
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
    def store():
        return lifecycle.job_store(settings)

    async def resolve(ctx: Any, workspace_root: str | None):
        return await lookup.resolve_job_workspace(settings, ctx, workspace_root)

    def task_for(job_id: str) -> str | None:
        return lookup.task_map(settings).task_for(job_id)

    async def read_status(
        ctx: Any, workspace_root: str | None, job_id: str, *, cancel: bool
    ) -> dict[str, Any]:
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        # Read first, even for a cancel: a foreign record is never signalled (decision 6).
        row = await asyncio.to_thread(store().status, cwd, job_id)
        if row is not None and cancel and lookup.backend_of(row) is not None:
            row = await asyncio.to_thread(store().cancel, cwd, job_id)
        if row is None or lookup.backend_of(row) is None:
            return lookup.job_not_found(
                job_id, lookup.job_meta(settings, cwd, source, roots_source), workspace_root
            )
        meta = lookup.job_meta(
            settings, cwd, source, roots_source,
            backend=lookup.backend_of(row), kind=lookup.kind_of(row),
        )
        return lookup.status_model(row, lookup.workspace_of(cwd, source), task_for(job_id), meta)

    async def read_result(
        ctx: Any, workspace_root: str | None, job_id: str, detail: str, *, consume: bool
    ) -> dict[str, Any]:
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        rec, payload = await asyncio.to_thread(store().result_payload, cwd, job_id)
        backend = lookup.backend_of(rec) if rec is not None else None
        if rec is None or backend is None:
            return lookup.job_not_found(
                job_id, lookup.job_meta(settings, cwd, source, roots_source), workspace_root
            )
        kind = lookup.kind_of(rec)
        meta = lookup.job_meta(settings, cwd, source, roots_source, backend=backend, kind=kind)
        meta.task_id = task_for(job_id)
        envelope, delivered = finished_job_envelope(
            rec, payload, job_id, kind, meta, detail, workspace_root
        )
        if delivered and isinstance(envelope.get("meta"), dict) and meta.task_id is not None:
            envelope["meta"]["task_id"] = meta.task_id
        if not (consume and delivered):
            return envelope
        outcome = await asyncio.to_thread(store().discard, cwd, job_id)
        if outcome is DiscardOutcome.MISSING:
            return lookup.job_not_found(job_id, meta, workspace_root)
        return envelope

    @app.tool(
        name="amicus_job_status",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Poll a background job (free)",
        meta=lifecycle_meta("amicus_job_status"),
        description=(
            f"{FREE_MARKER} Poll a job's state without fetching its result: status, elapsed "
            "time, result_available, result_ok, and poll_after_ms to honor before the next "
            f"poll (it grows with elapsed time). Works for any _async job and any sync call's "
            f"meta.job_id. {_RETENTION}"
        ),
    )
    @guard("amicus_job_status", settings)
    async def amicus_job_status(
        job_id: JobIdParam, ctx: Context | None = None, workspace_root: WorkspaceRootParam = None
    ) -> dict[str, Any]:
        """Poll a background job."""
        return await read_status(ctx, workspace_root, job_id, cancel=False)

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
    async def amicus_job_result(
        job_id: JobIdParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch a background job's result."""
        return await read_result(ctx, workspace_root, job_id, detail, consume=False)

    @app.tool(
        name="amicus_job_consume_result",
        annotations=annotations_for("job_consume", settings),
        output_schema=JOB_RESULT_SCHEMA,
        title="Fetch and delete a background job's result (free)",
        meta=lifecycle_meta("amicus_job_consume_result"),
        description=(
            f"{FREE_MARKER} Like amicus_job_result, then delete the record: a repeat call "
            "returns job_not_found, so this is not idempotent. Only a result read intact "
            "(a success or the job's own error) is deleted; a corrupt or incompatible "
            "record survives for amicus_job_result."
        ),
    )
    @guard("amicus_job_consume_result", settings)
    async def amicus_job_consume_result(
        job_id: JobIdParam,
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        detail: DetailParam = "summary",
    ) -> dict[str, Any]:
        """Fetch and delete a background job's result."""
        return await read_result(ctx, workspace_root, job_id, detail, consume=True)

    @app.tool(
        name="amicus_job_cancel",
        annotations=annotations_for("job_cancel", settings),
        output_schema=JOB_STATUS_SCHEMA,
        title="Cancel a background job (free)",
        meta=lifecycle_meta("amicus_job_cancel"),
        description=(
            f"{FREE_MARKER} Ask the worker to stop (SIGTERM, then SIGKILL after a grace "
            "period), remove its throwaway worktree, and mark the job cancelled; a terminal "
            "job is returned unchanged, so cancel is idempotent. cleanup_warnings names any "
            "leftover path."
        ),
    )
    @guard("amicus_job_cancel", settings)
    async def amicus_job_cancel(
        job_id: JobIdParam, ctx: Context | None = None, workspace_root: WorkspaceRootParam = None
    ) -> dict[str, Any]:
        """Cancel a background job."""
        return await read_status(ctx, workspace_root, job_id, cancel=True)

    @app.tool(
        name="amicus_job_list",
        annotations=annotations_for("job_read", settings),
        output_schema=JOB_LIST_SCHEMA,
        title="List background jobs (free)",
        meta=lifecycle_meta("amicus_job_list"),
        description=(
            f"{FREE_MARKER} List the jobs known for this workspace, newest first, across all "
            "backends; narrow with `backend`, `status`, or `task_id` (the tasks-extension id "
            "recorded at task creation; no match is an empty list). Only an explicit `limit` "
            f"truncates (truncated: true, no cursor). {_RETENTION}"
        ),
    )
    @guard("amicus_job_list", settings)
    async def amicus_job_list(
        ctx: Context | None = None,
        workspace_root: WorkspaceRootParam = None,
        limit: JobLimitParam = None,
        status: JobStatusFilterParam = None,
        backend: OptionalBackendParam = None,
        task_id: TaskIdParam = None,
    ) -> dict[str, Any]:
        """List background jobs."""
        cwd, source, roots_source, err = await resolve(ctx, workspace_root)
        if err is not None:
            return err
        assert cwd is not None
        rows = await asyncio.to_thread(store().list_jobs, cwd)
        tasks = lookup.task_map(settings).entries()
        task_by_job = {job: task for task, job in tasks.items()}
        rows = [r for r in rows if lookup.backend_of(r) is not None]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if backend is not None:
            rows = [r for r in rows if lookup.backend_of(r) == backend]
        if task_id is not None:
            wanted = tasks.get(task_id)
            rows = [r for r in rows if wanted is not None and r["job_id"] == wanted]
        truncated = limit is not None and len(rows) > limit
        if limit is not None:
            rows = rows[:limit]
        result = JobListResult(
            jobs=[lookup.summary_model(r, task_by_job.get(r["job_id"])) for r in rows],
            workspace=lookup.workspace_of(cwd, source),
            truncated=truncated,
            truncation_hint=(
                f"showing the {limit} newest of more matching jobs; omit `limit` for every "
                "retained match, or narrow with `status`, `backend` or `task_id`"
                if truncated
                else None
            ),
            meta=lookup.job_meta(settings, cwd, source, roots_source),
        ).model_dump(mode="json")
        if result["truncation_hint"] is None:
            del result["truncation_hint"]
        return result

    return (
        "amicus_job_status",
        "amicus_job_result",
        "amicus_job_consume_result",
        "amicus_job_cancel",
        "amicus_job_list",
    )
```

`JobListResult` and `JobStatus` extend `SuccessBase`, which requires `meta`: the list passes `lookup.job_meta(...)` and `read_status` builds the record-aware meta before calling `lookup.status_model(row, workspace, task_id, meta)` (Task 4's four-argument signature).

`src/amicus/tools/discovery.py`: in the five job tools' `TOOL_DETAILS`, remove `"not_implemented"` and add `"invalid_workspace_root", "workspace_outside_roots"` to each (`amicus_job_list` already lists `invalid_workspace_root`; add `workspace_outside_roots`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_job_tools.py tests/test_lookup.py tests/test_discovery.py -q --no-cov`
Expected: all pass. `test_cancel_running_then_terminal_is_idempotent` takes about 1–3 s (the SIGTERM path: the worker's signal handler cancels the run and the runtime terminates the fake codex with its process group). If it exceeds 10 s, the worker did not act on SIGTERM within the 2 s grace and was SIGKILLed instead; that is a finding about `_worker._run`'s signal handler to report, not a reason to widen the assertion.

Run: `uv run --no-sync pytest -q --no-cov -x -k "not manifest and not fingerprint and not discovery_cost and not wire_shape and not result_format"`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/amicus/tools/jobs.py src/amicus/jobs/lookup.py src/amicus/tools/discovery.py tests/test_job_tools.py tests/test_lookup.py tests/test_discovery.py
git commit -m "feat(tools): make the five job tools real"
```

---

### Task 6: Hard-kill cleanup and restart survival

**Files:**
- Create: `tests/test_job_durability.py`

**Interfaces:**
- Consumes: `lifecycle.job_store(settings)`, `lifecycle.worker_cmd`, `JobStore.start/status/cancel/result_payload`, `orchestration.isolation.WORKTREE_PREFIX`; the real worker (`python -m amicus._worker`) and the fake codex.
- Produces: nothing new in `src/`; these tests pin behavior the store and worker already have and the M2 gate names.

- [ ] **Step 1: Write the tests (they should pass first time; if one fails, that is a finding to report, not a test to weaken)**

Create `tests/test_job_durability.py`:

```python
"""Durability the M2 gate names: a worker that ignores SIGTERM is hard-killed and its
declared worktree removed; a job started by one server process is readable, pollable and
finishable from a fresh process (restart survival, via the per-job worker lock)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pontonier.core.jobs import JobStore

from amicus import config
from amicus.jobs import lifecycle
from amicus.orchestration.isolation import WORKTREE_PREFIX


def _settings(tmp_path):
    return config.settings({"AMICUS_STATE_DIR": str(tmp_path / "state")})


def _stubborn_worker_cmd(worktree: Path):
    """A worker that declares `worktree` in cleanup.json, ignores SIGTERM, and sleeps."""
    code = (
        "import json,signal,sys,time,pathlib;"
        "d=pathlib.Path(sys.argv[1]);"
        "(d/'cleanup.json').write_text(json.dumps({'paths':[sys.argv[2]]}));"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(120)"
    )

    def factory(job_dir):
        return [sys.executable, "-c", code, str(job_dir), str(worktree)]

    return factory


async def test_cancel_hard_kills_a_worker_that_ignores_sigterm_and_removes_its_worktree(
    tmp_path, monkeypatch
):
    worktree = Path(tempfile.mkdtemp(prefix=WORKTREE_PREFIX, dir=tempfile.gettempdir()))
    (worktree / "file").write_text("x")
    monkeypatch.setattr(JobStore, "terminate_grace_seconds", 1.0)
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _stubborn_worker_cmd(worktree))
    job_id, _ = store.start(lifecycle.worker_cmd, str(tmp_path), kind="delegate", extra={"backend": "codex"})
    deadline = time.monotonic() + 5
    while not (store._job_dir(str(tmp_path), job_id) / "cleanup.json").exists():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    t0 = time.monotonic()
    row = await asyncio.to_thread(store.cancel, str(tmp_path), job_id)
    assert row is not None and row["status"] == "cancelled"
    assert 0.9 <= time.monotonic() - t0 < 5, "graceful wait, then the kill"
    assert row["cleanup_warnings"] == [] and not worktree.exists()
    pid = json.loads((store._job_dir(str(tmp_path), job_id) / "meta.json").read_text())["pid"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        alive = subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0
        if not alive:
            break
        await asyncio.sleep(0.05)
    assert not alive


async def test_cancel_reports_a_worktree_it_may_not_remove(tmp_path, monkeypatch):
    outside = tmp_path / "not-a-worktree"
    outside.mkdir()
    monkeypatch.setattr(JobStore, "terminate_grace_seconds", 0.2)
    store = lifecycle.job_store(_settings(tmp_path))
    monkeypatch.setattr(lifecycle, "worker_cmd", _stubborn_worker_cmd(outside))
    job_id, _ = store.start(lifecycle.worker_cmd, str(tmp_path), kind="delegate", extra={"backend": "codex"})
    deadline = time.monotonic() + 5
    while not (store._job_dir(str(tmp_path), job_id) / "cleanup.json").exists():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    row = await asyncio.to_thread(store.cancel, str(tmp_path), job_id)
    assert row["status"] == "cancelled" and outside.exists()
    assert row["cleanup_warnings"] and str(outside) in row["cleanup_warnings"][0]


_OTHER_PROCESS = """
import json, sys, time
from amicus import config
from amicus.jobs import lifecycle
settings = config.settings({"AMICUS_STATE_DIR": sys.argv[1]})
store = lifecycle.job_store(settings)
cwd, job_id = sys.argv[2], sys.argv[3]
seen = []
deadline = time.monotonic() + 20
while True:
    rec = store.status(cwd, job_id)
    seen.append(None if rec is None else rec["status"])
    if rec is None or rec["status"] != "running" or time.monotonic() > deadline:
        break
    time.sleep(0.05)
rec, payload = store.result_payload(cwd, job_id)
print(json.dumps({"seen": seen, "final": rec and rec["status"], "ok": payload and payload.get("ok")}))
"""


async def test_a_job_survives_the_server_that_started_it(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "1.5")
    settings = _settings(tmp_path)
    store = lifecycle.job_store(settings)
    from amicus.request import RunSpec

    spec = RunSpec(
        backend="codex", kind="consult", tool="amicus_consult_async", cwd=str(tmp_path),
        workspace_source="param", roots_source="none", host_name="H", timeout_seconds=60,
        question="why?",
    )
    job_id, _ = store.start(
        lifecycle.worker_cmd, str(tmp_path), kind="consult",
        extra={"result_format": 1, "backend": "codex", "tool": "amicus_consult_async"},
        write_spec=spec.public(), stdin_text=spec.inputs_json(),
    )
    # "Restart": a different Python process (a fresh _PROCESS_OWNER) reads the same store.
    other = subprocess.run(
        [sys.executable, "-c", _OTHER_PROCESS, str(tmp_path / "state"), str(tmp_path), job_id],
        capture_output=True, text=True, check=True, timeout=60,
    )
    out = json.loads(other.stdout.strip().splitlines()[-1])
    assert out["seen"][0] == "running", out  # the worker's lock proves liveness to a stranger
    assert out["final"] == "done" and out["ok"] is True, out
    assert store.status(str(tmp_path), job_id)["status"] == "done"
```

- [ ] **Step 2: Run the tests**

Run: `uv run --no-sync pytest tests/test_job_durability.py -q --no-cov -v`
Expected: 3 passed in roughly 6–8 s. If `test_a_job_survives_the_server_that_started_it` sees `"failed"` first, the worker had not yet taken `worker.lock` when the other process looked (the lock is taken at `_hold_job_lock` before the spec is read); report this as a finding with the timing rather than adding a sleep — the M1 worker holds the lock before any other work, so a real race here is a bug. If the hard-kill test's timing assertion fails on a loaded machine, widen only the upper bound.

- [ ] **Step 3: Commit**

```bash
git add tests/test_job_durability.py
git commit -m "test(jobs): pin hard-kill cleanup and restart survival"
```

---

### Task 7: Snapshots, documents, README

**Files:**
- Modify: `src/amicus/wire_shape_snapshot.py`, `tests/test_wire_shape.py`
- Modify: `docs/adr/0004-tasks-and-jobs.md:3`
- Create: `docs/adr/0008-m2-jobs-surface-decisions.md`
- Modify: `README.md:6-8, 30-34`

**Interfaces:**
- Consumes: `lifecycle.job_started_handle(...)`, `lookup.status_model(...)`, `lookup.summary_model(...)`, `JobListResult`.
- Produces: `wire_shape_snapshot.build_snapshot()["handles"]` with keys `job_started`, `job_started_replayed`, `job_status_running`, `job_status_cancelled`, `job_list`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wire_shape.py`:

```python
def test_handles_section_pins_the_job_envelopes():
    snap = wss.build_snapshot()
    handles = snap["handles"]
    assert set(handles) == {
        "job_started", "job_started_replayed", "job_status_running", "job_status_cancelled", "job_list"
    }
    assert handles["job_started"]["status"] == "running" and handles["job_started"]["task_id"] is None
    assert handles["job_started_replayed"]["meta"]["idempotency_replayed"] is True
    assert handles["job_started_replayed"]["status"] == "done"
    assert handles["job_status_running"]["poll_after_ms"] == 1000
    assert handles["job_status_cancelled"]["poll_after_ms"] is None
    assert handles["job_status_cancelled"]["cleanup_warnings"] == ["/tmp/amicus-wt-leftover"]
    assert handles["job_list"]["truncated"] is True and "omit `limit`" in handles["job_list"]["truncation_hint"]
    assert handles["job_list"]["jobs"][0]["task_id"] == "task-0"
    for env in handles.values():
        assert env["meta"]["fingerprint"] == "<fingerprint>" and env["meta"]["request_id"] == "0" * 32
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --no-sync pytest tests/test_wire_shape.py -q --no-cov -k handles`
Expected: FAIL with `KeyError: 'handles'`.

- [ ] **Step 3: Render the handles through the real builders**

In `src/amicus/wire_shape_snapshot.py` add the imports:

```python
from amicus.jobs import lifecycle, lookup
from amicus.request import RunSpec
from amicus.schemas.results import JobListResult
```

and, above `build_snapshot`, the renderers:

```python
_STARTED_AT = "1970-01-01T00:00:00+00:00"
_EXPIRES_AT = "1970-01-02T00:00:00+00:00"


def _spec() -> RunSpec:
    return RunSpec(
        backend="codex", kind="consult", tool="amicus_consult_async", cwd="/repo",
        workspace_source="param", roots_source="client", host_name="Host", timeout_seconds=1800,
    )


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "job_id": _JOB_ID_SENTINEL, "kind": "consult", "status": "running", "started_at": _STARTED_AT,
        "elapsed_ms": 1, "deadline_seconds": 1800, "expires_at": None, "result_available": False,
        "result_ok": None, "poll_after_ms": 1000, "cleanup_warnings": [],
        "extra": {"result_format": RESULT_FORMAT, "backend": "codex", "tool": "amicus_consult_async"},
    }
    row.update(overrides)
    return row


def _handle_meta() -> Meta:
    # `_meta` fixes timeout_seconds=1 itself (a duplicate keyword would raise); the
    # handle's deadline rides JobStarted.deadline_seconds, not the meta.
    return _meta(workspace_source="param", roots_source="client")


def _job_meta() -> Meta:
    meta = _handle_meta()
    meta.job_kind = "consult"
    return meta


def _handles() -> dict[str, Any]:
    ws = lookup.workspace_of("/repo", "param")
    started = lifecycle.job_started_handle(
        _JOB_ID_SENTINEL, spec=_spec(), status="running", started_at=_STARTED_AT, deadline=1800,
        expires_at=None, meta=_handle_meta(),
    )
    replayed = lifecycle.mark_replayed(
        lifecycle.job_started_handle(
            _JOB_ID_SENTINEL, spec=_spec(), status="done", started_at=_STARTED_AT, deadline=1800,
            expires_at=_EXPIRES_AT, meta=_handle_meta(), poll_after_ms=1000, task_id="task-0",
        )
    )
    running = lookup.status_model(_row(), ws, None, _job_meta())
    cancelled = lookup.status_model(
        _row(status="cancelled", cleanup_warnings=["/tmp/amicus-wt-leftover"], expires_at=_EXPIRES_AT),
        ws, "task-0", _job_meta(),
    )
    listed = JobListResult(
        jobs=[
            lookup.summary_model(
                _row(status="done", result_available=True, result_ok=True, expires_at=_EXPIRES_AT), "task-0"
            ),
            lookup.summary_model(_row(), None),
        ],
        workspace=ws,
        truncated=True,
        truncation_hint=(
            "showing the 2 newest of more matching jobs; omit `limit` for every retained match, "
            "or narrow with `status`, `backend` or `task_id`"
        ),
        meta=_handle_meta(),
    ).model_dump(mode="json")
    return {
        "job_started": started,
        "job_started_replayed": replayed,
        "job_status_running": running,
        "job_status_cancelled": cancelled,
        "job_list": listed,
    }
```

In `build_snapshot`, add `"handles": _handles()` to the returned dict (after the existing `"delivered"` key). Every meta above is built by `_meta`, which pins the fingerprint, version and request-id sentinels.

- [ ] **Step 4: Run the tests and regenerate the fixture**

Run: `uv run --no-sync pytest tests/test_wire_shape.py -q --no-cov -k handles`
Expected: PASS.

```bash
uv run --no-sync python -m amicus.wire_shape_snapshot > tests/fixtures/wire_shape_snapshot.json
git diff --stat tests/fixtures/wire_shape_snapshot.json
uv run --no-sync pytest tests/test_wire_shape.py -q --no-cov
```

Expected: only the new `handles` block was added; every wire-shape test passes.

- [ ] **Step 5: Documents**

`docs/adr/0004-tasks-and-jobs.md` line 3 becomes:

```markdown
**Status:** Accepted for the durable-jobs half (2026-09-06, M2: `_async` twins, `amicus_job_*`, keyed replay, task-id lookup); the `task=True` half stays Proposed until M5.
```

Create `docs/adr/0008-m2-jobs-surface-decisions.md`:

```markdown
# ADR 0008: The M2 jobs surface — identity, outcomes, filters, foreign records

**Status:** Accepted (2026-09-06, M2)

## Context

M2 makes the `_async` twins and `amicus_job_*` real on top of pontonier's `JobStore`.
The spec fixes the shape; the sibling (codex-in-claude) persisted its whole spec, prompt included, and hashed it for dedup, which amicus cannot do because it never persists a prompt.
The maintainer settled the open choices on 2026-09-06.

## Decisions

- The keyed-dedup identity is `RunSpec.public()` minus `cwd`, `workspace_source`, `roots_source`, `host_name`, `kind` and `tool`, plus `inputs_digest`, a sha256 of the canonical inputs JSON.
  A key reused with a different prompt is `idempotency_conflict`; a reconnect with different roots replays.
- Keyed outcomes: `created` returns a running handle; `replay` returns the existing job's real handle with `meta.idempotency_replayed`; `conflict` and `unavailable` repair with `use_new_idempotency_key` naming the twin; `in_progress` and a transient `io_error` are temporary with `retry_after_ms` (250 and 1000 ms).
  An `_async` caller never blocks on `in_progress`.
- The sync tools stay unkeyed (ADR 0007, deviation 8); the sibling's keyed-await path is not ported.
- A twin's run timeout is `AMICUS_JOB_MAX_SECONDS` (default 1800 s), unclamped; the handle's `deadline_seconds` and `meta.timeout_seconds` report it.
- `amicus_job_list(task_id=...)` is a filter: no match is an empty list.
  The task map lives at `<AMICUS_STATE_DIR>/tasks.json`; handles, statuses and summaries echo `task_id` by reverse lookup (recording lands in M5).
- A record without a valid `extra.backend` tag was not written by amicus: the job tools report `job_not_found` for it and `amicus_job_list` omits it; nothing deletes it.
- A job tool's generated error carries the record's backend and kind when resolved, the job deadline as `timeout_seconds`, and the roots state the lookup saw.
- `amicus_job_cancel` is the store's cancel: SIGTERM, a grace period, SIGKILL of the process group, then guarded removal of the declared worktree; a terminal job is returned unchanged.
  Task-scoped cancel semantics (an unkeyed task cancels its job; a keyed job survives) are wired in M5.
- The wire-shape fixture gains a `handles` section rendered through the real builders; nothing new is persisted, so `RESULT_FORMAT` stays 1 while `FINGERPRINT` moves to `schema-3` for the description and schema changes.

## Consequences

- Every host can drive a background run through ordinary tools today; the tasks extension (M5) adds a second entry point onto the same records.
- A caller that wants a retry to be a new paid run must pass a new key; a caller that wants a replay must repeat the inputs exactly.
```

`README.md`: replace the status paragraph (lines 6–8) with:

```markdown
**Status:** milestone M2 (jobs surface).
`amicus_consult`, `amicus_review_changes`, `amicus_delegate`, their `_async` twins, both dry runs and the five `amicus_job_*` tools work for `backend="codex"`; every paid call runs in a detached worker and records a job (`meta.job_id`), and `idempotency_key` dedups an `_async` retry.
Kimi (M3) and Claude Code (M4) still return `backend_unavailable`; `amicus_adversarial_review(_async)` returns `not_implemented` until M4; `task=True` wiring lands in M5.
```

and in "Resuming the work" replace the three steps with:

```markdown
1. `main` carries M2.
2. In a fresh session say "Resume amicus at milestone M3 per the execution model".
3. The agent writes the M3 plan from the spec and executes it.
```

and add the row `| The M2 plan (jobs surface) | `docs/superpowers/plans/2026-09-06-amicus-M2-jobs-surface.md` |` to the "Where things are" table.

- [ ] **Step 6: Commit (snapshot fixture in its own commit)**

```bash
git add src/amicus/wire_shape_snapshot.py tests/test_wire_shape.py
git commit -m "test(jobs): render the job handles into the wire-shape snapshot"
git add tests/fixtures/wire_shape_snapshot.json
git commit -m "test(manifest): regenerate the wire-shape fixture with the handles section"
git add docs/adr/0004-tasks-and-jobs.md docs/adr/0008-m2-jobs-surface-decisions.md README.md
git commit -m "docs(jobs): record the M2 decisions in ADR 0008 and update the status"
```

---

### Task 8: Regenerate the pins, full gate, perturbation checks, draft PR

**Files:**
- Modify: `tests/fixtures/manifest_snapshot.*.json`, `tests/test_manifest.py`, `tests/test_fingerprint.py`, `tests/test_discovery_cost.py`

- [ ] **Step 1: Regenerate and re-pin (own commit)**

Descriptions moved in Tasks 3 and 5 and `JobStarted.status` widened in Task 2; the fingerprint is already `schema-3` (Task 1) and stays.

```bash
for p in all codex-kimi claude; do uv run --no-sync python -m amicus.manifest --profile $p > tests/fixtures/manifest_snapshot.$p.json; done
uv run --no-sync python -m amicus.result_format_snapshot > tests/fixtures/result_format_snapshot.json
uv run --no-sync python - <<'PY'
import asyncio
from amicus import manifest, surface
for p in manifest.PROFILES:
    app = manifest.app_for_profile(p)
    print(p, asyncio.run(manifest.manifest_hash(app)), asyncio.run(surface.surface_digest(app)), asyncio.run(manifest.tools_list_bytes(app)))
PY
git diff --stat tests/fixtures
```

Review the manifest diff: only the async twins' and job tools' descriptions, the `JobStarted.status` enum, and `capabilities.tool_details[*].error_codes` should have moved since Task 1. The result-format fixture must be byte-identical (nothing new is persisted); if it moved, stop and explain in the PR body. Paste the hashes into `EXPECTED_MANIFEST_HASH`, the digests into `EXPECTED_SURFACE_DIGEST`, the byte counts into `MEASURED`. If a profile's `tools/list` bytes exceed its `BUDGET`, compact the twin descriptions (the appended deadline sentence is the first candidate) rather than raising the budget; raising it is a reviewed decision that must be argued in the PR body.

```bash
uv run --no-sync pytest -q
git add tests/fixtures tests/test_manifest.py tests/test_fingerprint.py tests/test_discovery_cost.py
git commit -m "test(manifest): regenerate the snapshots after the M2 surface updates"
```

- [ ] **Step 2: Full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest && uv run prek run --all-files`
Expected: every step clean; pytest ≥ 95% branch coverage. Record the test count and coverage for the PR body.

- [ ] **Step 3: Perturbation checks (negative-result rule)**

1. Identity: in `src/amicus/request.py` remove `"inputs_digest"` from `identity()`; run `uv run --no-sync pytest tests/test_request.py tests/test_lifecycle.py -q --no-cov -k "arg_hash or conflict"`; expected: FAIL (a different prompt now replays). Revert with `git checkout -- src/amicus/request.py`.
2. Replay stamp: in `src/amicus/jobs/lifecycle.py` make `mark_replayed` return the envelope unchanged; run `uv run --no-sync pytest tests/test_async_tools.py tests/test_wire_shape.py -q --no-cov -k "replays or handles"`; expected: FAIL. Revert.
3. Foreign records: in `src/amicus/jobs/lookup.py` make `backend_of` return `"codex"` unconditionally; run `uv run --no-sync pytest tests/test_job_tools.py tests/test_lookup.py -q --no-cov -k "foreign"`; expected: FAIL. Revert.
4. Consume safety: in `src/amicus/tools/jobs.py` change `if not (consume and delivered):` to `if not consume:`; run `uv run --no-sync pytest tests/test_job_tools.py -q --no-cov -k could_not_deliver`; expected: FAIL. Revert.
5. Manifest: append ` probe` to `_ASYNC_DESC` in `src/amicus/tools/consult.py`; run `uv run --no-sync pytest tests/test_manifest.py tests/test_fingerprint.py -q --no-cov`; expected: FAIL for every profile. Revert.
6. Spend guard: run `AMICUS_CODEX_BIN=/usr/bin/true uv run --no-sync pytest tests/test_paid_tools.py -q --no-cov -k async_twins_refuse` and confirm it still passes without spawning (every case fails pre-spend on the workspace).
7. Import contracts: add `from amicus import tools  # noqa: F401` to `src/amicus/jobs/lookup.py`; run `uv run --no-sync lint-imports`; expected: the "orchestration and jobs" contract broken. Revert.

Re-run the full gate after the reverts; expected: green. `git status --short` must be clean.

- [ ] **Step 4: Push and open the draft PR**

```bash
git push -u origin feat/m2-jobs
gh pr create --draft --title "feat: M2 jobs surface" --body-file /private/tmp/claude-501/-Users-bdc-projects-amicus/41c18805-f451-4bcd-bf9b-a1ae0f7b161a/scratchpad/m2-pr-body.md
```

PR body (write it to the path above, filling every angle-bracket placeholder from measured output):

```markdown
## What & why

Milestone M2 of amicus (spec: `docs/superpowers/specs/2026-09-04-amicus-design.md`, row M2; plan: `docs/superpowers/plans/2026-09-06-amicus-M2-jobs-surface.md`).

- `amicus_consult_async`, `amicus_review_changes_async`, `amicus_delegate_async` are real for `backend="codex"`: same pre-spend preparation as the sync tools, the job deadline (`AMICUS_JOB_MAX_SECONDS`) as the run timeout, unkeyed or keyed (`idempotency_key`) starts through pontonier's `start_idempotent`, replay of the existing job's real handle with `meta.idempotency_replayed`.
- `amicus_job_status/result/consume_result/cancel/list` are real across backends: ADR 0003 workspace resolution, delivery through the one chokepoint, consume only of a faithfully delivered record, idempotent cancel with hard-kill and worktree cleanup, `status`/`backend`/`task_id` filters, `task_id` echoed by reverse lookup.
- `jobs/lookup.py` (shared helpers), `RunSpec.identity()/arg_hash()`, `JobStarted.status` widened to every job state.
- Fingerprint `schema-3` (descriptions, `JobStarted.status`, error-code lists); `RESULT_FORMAT` stays 1.
- ADR 0008 records the nine decisions; ADR 0004 is Accepted for its jobs half.

## Decisions (ADR 0008)

<paste the nine numbered items from the plan's "Decisions made here" section>

## Verification

- Gate: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest && uv run prek run --all-files` — passed; <N> tests, coverage <X>% (branch). CI on this PR: <link/outcome>.
- New spend-free suites: `test_async_tools.py` (handles, keyed replay/conflict, pre-spend refusals), `test_job_tools.py` (lifecycle, consume safety, cancel, filters, task-id, foreign records, workspace rules), `test_job_durability.py` (SIGTERM-ignoring worker hard-killed with worktree removed; a job read, polled and finished from a fresh process), `test_lookup.py`, plus the keyed-start cases in `test_lifecycle.py`.
- Snapshots: manifest per profile regenerated (schema-3); wire-shape fixture gained the `handles` section; result-format fixture unchanged; tools/list measured all <bytes>, codex-kimi <bytes>, claude <bytes>.
- Perturbation checks: identity without the inputs digest replays a different prompt (fails); replay stamp removed (fails); foreign-record guard removed (fails); consume of an undelivered record (fails); description change breaks the manifest pins; spend guard holds; import-linter fails on a jobs→tools import. All reverted, gate green.
- No live gate in this milestone (AGENTS.md rule 5). M1's live re-run is still due after 2026-09-07T19:14Z.

## Out of scope

- `task=True` wiring, task-map recording and task-scoped cancel (M5); Kimi (M3); Claude and `amicus_adversarial_review(_async)` (M4).

🤖 Generated with Claude Code

<session link given in the session>
```

- [ ] **Step 5: Stop**

Do not merge, approve, tag, or release. The maintainer reviews and merges (AGENTS.md rule 8).

---

## Self-review (writing-plans checklist)

- **Spec coverage (M2 row):** `_async` twins → Task 3 (consult, review, delegate; adversarial stays `not_implemented` per the M4 boundary); `amicus_job_*` → Tasks 4–5; idempotency → Tasks 1–2 (identity) and 3 (twins carry `idempotency_key`); task↔job mapping → Task 5 (`task_id` filter and echo via `TaskJobMap`; recording is M5 per ADR 0004); delivery → Task 5 through `finished_job_envelope`. Gate items: keyed replay → Tasks 2, 3; cancel (keyed/unkeyed) → Task 5 (`amicus_job_cancel` on a keyed and an unkeyed job are the same store cancel; the keyed job's index entry then classifies as replay-of-a-cancelled-job, exercised by `test_keyed_start_creates_then_replays_the_real_handle`'s shape) and Task 6; hard-kill cleanup → Task 6; restart-survival → Task 6; task-id lookup → Task 5. Spec "Jobs and tasks": `extra.backend` on every record (M1, asserted in Task 3), arg hash includes `backend` (Task 1), `meta.job_id` always stamped (Task 2 handle, Task 5 delivery). Spec "Error envelope": idempotency codes render through the repair table with the twin named as the tool (Task 2).
- **Decisions:** the nine items in "Decisions made here" (ADR 0008, Task 7). The plan makes no change to `.github/**`, `AGENTS.md`, `CLAUDE.md`.
- **Placeholder scan:** angle-bracket placeholders exist only in Task 8 Step 4's PR body and are filled from measured output by instruction; every pinned hash/digest/count is pasted from a printed value in Tasks 1 and 8; `status_model(row, workspace, task_id, meta)` is defined with its four arguments in Task 4 and used in that form by Tasks 5 and 7.
- **Type consistency:** `RunSpec.arg_hash()` (Task 1) is what `start_async` passes as `arg_hash=` (Task 2); `start_async(store, spec, meta, plugin, *, deadline, idempotency_key, task_id=None)` is called identically from the three twins (Task 3); `prepare_run(..., background=True)` (Task 3) yields `spec.timeout_seconds == settings.job_max_seconds`, which the twins pass as `deadline=`; `job_started_handle(..., poll_after_ms, task_id)` (Task 2) is used by `start_async` and by `wire_shape_snapshot._handles` (Task 7); `lookup.resolve_job_workspace(settings, ctx, workspace_root) -> (cwd, source, roots_source, err)` (Task 4) is consumed by every tool in Task 5; `lookup.status_model(row, workspace, task_id, meta)` and `lookup.summary_model(row, task_id)` (Tasks 4–5) are used by Task 5 and Task 7; `finished_job_envelope(rec, payload, job_id, kind, meta, detail, workspace_root) -> (dict, bool)` (M1) is called with `lookup.kind_of(rec)` and `lookup.job_meta(...)` in Task 5; `DiscardOutcome.MISSING` is the only outcome mapped to not-found (Task 5), matching pontonier 0.9.0's enum (verified in Task 0 Step 2).
