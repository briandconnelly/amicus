> **Status:** EXECUTED 2026-09-04 on pontonier branch `feat/amicus-seams` — draft PR briandconnelly/pontonier#25, closes pontonier#24. Kept as the template for later milestone plans. Deviations from this text made during execution: the committed plan document was dropped from the pontonier branch; `ClassifiedFailure.usage` was added; the consumer script gained a provenance check; the conformance probe gained a timed-out row.

# Part 3 — M-1 Implementation Plan: pontonier 0.9.0 amicus seams

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release pontonier 0.9.0 with the four additive protocol seams amicus needs, without breaking the frozen contract or any of the three consuming bridges.

**Architecture:** All changes are defaulted fields on frozen dataclasses or an optional runtime-checkable capability Protocol, which is exactly what the freeze in `src/pontonier/backend/__init__.py` permits. `CONTRACT_API_VERSION` stays 1. A new shell script runs every consuming bridge's suite against the built wheel so the release candidate is proven against real adapters before a human publishes.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage), `import-linter`, `hatchling`. Runtime dependency: `anyio` only.

**Spec:** Part 1 of this document (the amicus design spec), section "Milestones", row M-1; and Part 1 → "Verified constraints" → pontonier adapter gaps.

## Global Constraints

- Repo: `/Users/bdc/projects/pontonier`. Work on branch `feat/amicus-seams` in a sibling git worktree `../pontonier-wt-amicus-seams`. Never push to `main`. Do not commit this plan into pontonier (see Part 2 rule 1).
- The working tree currently has unrelated modified/untracked files under `.agents/skills/agent-bot-identity/`. Do not stage, commit, or revert them.
- `pontonier.core` never imports from the rest of the package (import-linter enforces).
- `pontonier.backend` is frozen at `CONTRACT_API_VERSION = 1`: only defaulted fields and optional capability protocols. No new required Protocol member. `CONTRACT_API_VERSION` must remain `1` after this plan.
- Runtime dependencies: `anyio` only. Do not add any.
- Coverage floor 95%; never lower `fail_under`.
- Commit messages: Conventional Commits, `type(scope): subject`, scopes from `core|backend|conventions|testing|packaging|release|changelog|ci|deps`, imperative lowercase subject, no trailing period. End every commit body with the attribution trailer given in the session.
- The gate is `./scripts/check.sh` run directly (not via `uv run`). While iterating, `SKIP_WHEEL_CHECK=1 ./scripts/check.sh` is acceptable; the final run must not skip the wheel check.
- Markdown: one sentence per line.
- Off limits: releasing (tags, publish workflow, PyPI), merging or approving your own PR, editing `.github/workflows/**`, `CODEOWNERS`, `AGENTS.md`.
- Changelog entries go under a `## [Unreleased]` heading inserted above `## [0.8.0] — 2026-08-31`; the release task renames it.

---

### Task 0: Branch and baseline

**Files:** none modified.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /Users/bdc/projects/pontonier
git worktree add ../pontonier-wt-amicus-seams -b feat/amicus-seams main
cd ../pontonier-wt-amicus-seams
```

If `superpowers:using-git-worktrees` is available, use it instead; the branch name must be `feat/amicus-seams`.

- [ ] **Step 2: Confirm the baseline gate passes before touching anything**

Run: `SKIP_WHEEL_CHECK=1 ./scripts/check.sh`
Expected: ends with `==> gate passed`. If it does not, stop and report; do not start Task 1 on a red baseline.

- [ ] **Step 3: Confirm the freeze marker**

Run: `uv run --no-sync python -c "from pontonier.backend import CONTRACT_API_VERSION as v; print(v)"`
Expected: `1`

---

### Task 1: `Usage` cache-token fields

**Files:**
- Modify: `src/pontonier/backend/protocol.py:114-119` (the `Usage` dataclass)
- Test: `tests/test_usage_cache_fields.py`

**Interfaces:**
- Consumes: `pontonier.backend.protocol.Usage` (existing: `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd`, all `int|float|None = None`).
- Produces: `Usage.cached_input_tokens: int | None = None` and `Usage.cache_creation_input_tokens: int | None = None`, appended after `cost_usd`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_cache_fields.py`:

```python
"""``Usage.cached_input_tokens`` / ``cache_creation_input_tokens``: defaulted fields so the
three adapters can carry the cache accounting their bridges already report (Codex and Kimi
``cached_input_tokens``; Claude ``cache_read_input_tokens`` / ``cache_creation_input_tokens``)
without a protocol break. Today every adapter's ``finalize`` drops these figures."""

from __future__ import annotations

import dataclasses

import pytest

from pontonier.backend import CONTRACT_API_VERSION
from pontonier.backend.protocol import Usage


def test_cache_fields_default_to_none_and_keep_the_freeze():
    usage = Usage()
    assert usage.cached_input_tokens is None
    assert usage.cache_creation_input_tokens is None
    assert CONTRACT_API_VERSION == 1


def test_positional_construction_is_unchanged():
    # Adapters build Usage(input, output, total, cost) positionally or by keyword; the
    # new fields are appended, so those calls keep their meaning.
    usage = Usage(1, 2, 3, 0.5)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens, usage.cost_usd) == (
        1,
        2,
        3,
        0.5,
    )
    assert usage.cached_input_tokens is None
    assert usage.cache_creation_input_tokens is None


@pytest.mark.parametrize("value", [0, 1, 123_456])
def test_cache_fields_carry_integers_verbatim(value: int):
    usage = Usage(cached_input_tokens=value, cache_creation_input_tokens=value)
    assert usage.cached_input_tokens == value
    assert usage.cache_creation_input_tokens == value


def test_cache_fields_are_frozen_and_last():
    usage = Usage(cached_input_tokens=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.cached_input_tokens = 2  # type: ignore[misc]
    names = [f.name for f in dataclasses.fields(Usage)]
    assert names[-2:] == ["cached_input_tokens", "cache_creation_input_tokens"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_usage_cache_fields.py -v --no-cov`
Expected: FAIL with `TypeError: Usage.__init__() got an unexpected keyword argument 'cached_input_tokens'` (and `AttributeError` on the first test).

- [ ] **Step 3: Add the fields**

In `src/pontonier/backend/protocol.py`, replace the `Usage` class (lines 114-119) with:

```python
@dataclass(frozen=True)
class Usage:
    """Token and cost accounting as the backend reported it; every field is None
    when the backend did not report that figure.

    ``cached_input_tokens`` (0.9.0) is the prompt-token count served from the
    provider's cache (Codex and Kimi ``cached_input_tokens``, Claude
    ``cache_read_input_tokens``); ``cache_creation_input_tokens`` (0.9.0) is the
    count written into the cache (Claude only). Both are defaulted: the freeze
    permits an appended defaulted field, and every existing positional
    ``Usage(input, output, total, cost)`` call keeps its meaning.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_usage_cache_fields.py tests/test_conformance_fakes.py -v --no-cov`
Expected: all PASS (the fakes prove existing constructions are untouched).

- [ ] **Step 5: Commit**

```bash
git add src/pontonier/backend/protocol.py tests/test_usage_cache_fields.py
git commit -m "feat(backend): add cached-token fields to Usage

Codex, Kimi and Claude all report cache accounting that every adapter's
finalize currently drops because the protocol type had no field for it.
Both fields are defaulted, so the freeze holds and CONTRACT_API_VERSION
stays 1."
```

---

### Task 2: `RepairHint` and defaulted machine fields on `ClassifiedFailure` (closes #24)

**Files:**
- Modify: `src/pontonier/backend/protocol.py:140-151` (the `ClassifiedFailure` dataclass; add `RepairHint` immediately above it)
- Test: `tests/test_classified_failure_fields.py`

**Interfaces:**
- Consumes: `pontonier.backend.protocol.ClassifiedFailure` (existing: `code: str`, `detail: str`, `retry_after_ms: int | None = None`); `pontonier.backend.classify.classify(contract, outcome, request, *, detail, backend_hook)`; `tests/conftest.make_run`; `tests/test_contract.make_contract`.
- Produces: `RepairHint(next_step: str, tool: str | None = None, arguments: dict[str, Any] | None = None, alternative: str | None = None)` (frozen); `ClassifiedFailure.retryable: bool | None = None`, `ClassifiedFailure.details: dict[str, Any] | None = None`, `ClassifiedFailure.repair: RepairHint | None = None`, appended in that order after `retry_after_ms`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_classified_failure_fields.py`:

```python
"""``ClassifiedFailure.retryable`` / ``details`` / ``repair`` (#24; background
briandconnelly/claude-in-codex#145): defaulted machine
fields so an adapter that already computes them (Claude's ``ErrorInfo`` carries repair,
details and retryable) can hand them to a generic consumer instead of dropping them.
``None`` on any of them means "the backend expressed no opinion; apply your defaults" —
it is never a claim. The shared classifier leaves all three None."""

from __future__ import annotations

import dataclasses

import pytest
from conftest import make_run
from pontonier.backend import CONTRACT_API_VERSION, classify
from pontonier.backend.protocol import ClassifiedFailure, RepairHint, RunOutcome, RunRequest
from test_contract import make_contract

CONTRACT = make_contract()
REQUEST = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)


def test_new_fields_default_to_none_and_keep_the_freeze():
    failure = ClassifiedFailure(code="timeout", detail="d")
    assert failure.retryable is None
    assert failure.details is None
    assert failure.repair is None
    assert CONTRACT_API_VERSION == 1


def test_positional_construction_is_unchanged():
    failure = ClassifiedFailure("nonzero_exit", "d", 250)
    assert (failure.code, failure.detail, failure.retry_after_ms) == ("nonzero_exit", "d", 250)
    names = [f.name for f in dataclasses.fields(ClassifiedFailure)]
    assert names == ["code", "detail", "retry_after_ms", "retryable", "details", "repair"]


def test_repair_hint_is_a_frozen_next_action():
    hint = RepairHint(next_step="run_status")
    assert (hint.tool, hint.arguments, hint.alternative) == (None, None, None)
    full = RepairHint(
        next_step="run_status",
        tool="amicus_backends",
        arguments={"backend": "claude"},
        alternative="Run `claude /login` and retry.",
    )
    assert full.arguments == {"backend": "claude"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        full.next_step = "other"  # type: ignore[misc]


def test_shared_classifier_expresses_no_opinion():
    outcome = RunOutcome(run=make_run(stderr="boom", exit_code=1))
    failure = classify.classify(CONTRACT, outcome, REQUEST, detail="detail")
    assert failure.code == "nonzero_exit"
    assert (failure.retryable, failure.details, failure.repair) == (None, None, None)


def test_backend_hook_result_passes_through_untouched():
    # A backend that knows more (Claude's timeout is NOT retryable because a replay may
    # double-charge) returns a populated failure; the skeleton must not strip it.
    populated = ClassifiedFailure(
        code="timeout",
        detail="deadline",
        retryable=False,
        details={"field": "timeout_seconds", "reason": "exceeded"},
        repair=RepairHint(next_step="raise_timeout", tool="amicus_consult"),
    )
    outcome = RunOutcome(run=make_run(exit_code=1, timed_out=True))
    result = classify.classify(
        CONTRACT, outcome, REQUEST, detail="detail", backend_hook=lambda _o, _r: populated
    )
    assert result is populated
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_classified_failure_fields.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'RepairHint'`.

- [ ] **Step 3: Add `RepairHint` and the fields**

In `src/pontonier/backend/protocol.py`, replace the `ClassifiedFailure` class (lines 140-151) with:

```python
@dataclass(frozen=True)
class RepairHint:
    """One corrective next action, in the shape the bridges' error envelopes already
    use: ``next_step`` is a stable symbolic label, ``tool``/``arguments`` name the
    single callable repair when one exists, ``alternative`` is optional prose for a
    human or agent when the primary call does not fit. Pure data; a consumer
    serializes it into its own envelope (0.9.0, #24)."""

    next_step: str
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    alternative: str | None = None


@dataclass(frozen=True)
class ClassifiedFailure:
    """A failure mapped into the shared taxonomy (see conventions.envelope).

    ``code`` is a taxonomy code. ``detail`` is sanitized, redacted prose safe
    for the wire. ``retry_after_ms`` is set only for temporary failures that
    declared a delay.

    ``retryable``, ``details`` and ``repair`` (0.9.0, #24) let a backend that
    already computes them hand them to a generic consumer; ``None`` on any of
    them means the backend expressed no opinion and the consumer applies its own
    defaults — it is never a claim. The shared skeleton in ``classify`` leaves
    all three ``None``. ``details`` is the envelope's field-detail object
    (``{field, value, reason}``), redacted by the backend before it lands here.
    """

    code: str
    detail: str
    retry_after_ms: int | None = None
    retryable: bool | None = None
    details: dict[str, Any] | None = None
    repair: RepairHint | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_classified_failure_fields.py tests/test_classify.py tests/test_conformance_fakes.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pontonier/backend/protocol.py tests/test_classified_failure_fields.py
git commit -m "feat(backend): carry retryable, details and repair on ClassifiedFailure

Closes #24 (background: briandconnelly/claude-in-codex#145). Claude's
adapter documents its classify_failure as
faithfully lossy because the protocol type could not carry the machine
fields its ErrorInfo already computes. All three are defaulted and None
means no opinion, so the freeze holds and the shared classifier is
unchanged."
```

---

### Task 3: `OutcomeInspector` capability and `inspect_outcome()` helper

**Files:**
- Modify: `src/pontonier/backend/protocol.py` (append after the `AgentBackend` Protocol, end of file)
- Test: `tests/test_outcome_inspector.py`

**Interfaces:**
- Consumes: `AgentBackend`, `ClassifiedFailure`, `RunOutcome`, `RunRequest` from `pontonier.backend.protocol`; `tests.test_conformance_fakes.ClaudeLikeBackend` and `CodexLikeBackend`; `tests/conftest.make_run`.
- Produces: `@runtime_checkable class OutcomeInspector(Protocol)` with one member `inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None`; module function `inspect_outcome(backend: object, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None` that returns `None` for backends without the capability.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outcome_inspector.py`:

```python
"""``OutcomeInspector`` (0.9.0): an OPTIONAL capability a backend adds when a process
that exited 0 can still be a failure. Claude's CLI reports errors in a zero-exit JSON
envelope (``is_error`` / a non-success ``subtype``), so a consumer that branches on exit
status alone reports those as successful empty answers. The consumer calls
``inspect_outcome`` on EVERY completed process before ``finalize``; a backend without the
capability yields None and nothing changes for it. The base ``AgentBackend`` protocol does
not grow, which is what keeps this inside the freeze."""

from __future__ import annotations

import json

from conftest import make_run
from pontonier.backend import CONTRACT_API_VERSION
from pontonier.backend.protocol import (
    AgentBackend,
    ClassifiedFailure,
    OutcomeInspector,
    RunOutcome,
    RunRequest,
    inspect_outcome,
)
from test_conformance_fakes import ClaudeLikeBackend, CodexLikeBackend

REQUEST = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)


class EnvelopeInspectingBackend(ClaudeLikeBackend):
    """ClaudeLike plus the capability: a zero-exit envelope with is_error is a failure."""

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        try:
            envelope = json.loads(outcome.run.stdout)
        except json.JSONDecodeError:
            return ClassifiedFailure(code="invalid_json", detail="stdout was not a JSON envelope")
        if envelope.get("is_error"):
            return ClassifiedFailure(
                code="nonzero_exit",
                detail=str(envelope.get("result", ""))[:80],
                retryable=False,
            )
        return None


def test_backend_without_the_capability_yields_none_and_the_freeze_holds():
    backend = CodexLikeBackend()
    assert not isinstance(backend, OutcomeInspector)
    assert isinstance(backend, AgentBackend)  # the base protocol did not grow
    outcome = RunOutcome(run=make_run(stdout="anything", exit_code=0))
    assert inspect_outcome(backend, outcome, REQUEST) is None
    assert CONTRACT_API_VERSION == 1


def test_inspector_is_detected_structurally():
    backend = EnvelopeInspectingBackend()
    assert isinstance(backend, OutcomeInspector)
    assert isinstance(backend, AgentBackend)


def test_inspector_flags_a_zero_exit_error_envelope():
    backend = EnvelopeInspectingBackend()
    stdout = json.dumps({"is_error": True, "result": "budget exceeded"})
    outcome = RunOutcome(run=make_run(stdout=stdout, exit_code=0))
    failure = inspect_outcome(backend, outcome, REQUEST)
    assert failure is not None
    assert failure.code == "nonzero_exit"
    assert failure.detail == "budget exceeded"
    assert failure.retryable is False


def test_inspector_passes_a_clean_envelope():
    backend = EnvelopeInspectingBackend()
    stdout = json.dumps({"result": "ok", "subtype": "success"})
    outcome = RunOutcome(run=make_run(stdout=stdout, exit_code=0))
    assert inspect_outcome(backend, outcome, REQUEST) is None


def test_helper_does_not_prefilter_on_exit_status():
    # The consumer's rule is "inspect every completed process"; the helper must not
    # decide for it, so a nonzero exit still reaches the inspector.
    backend = EnvelopeInspectingBackend()
    outcome = RunOutcome(run=make_run(stdout="not json", exit_code=2))
    failure = inspect_outcome(backend, outcome, REQUEST)
    assert failure is not None
    assert failure.code == "invalid_json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_outcome_inspector.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'OutcomeInspector'`.

- [ ] **Step 3: Add the capability protocol and helper**

Append to the end of `src/pontonier/backend/protocol.py` (after the `AgentBackend` class):

```python
@runtime_checkable
class OutcomeInspector(Protocol):
    """OPTIONAL capability (0.9.0): a backend whose process can exit 0 and still
    have failed — Claude's CLI reports errors inside a zero-exit JSON envelope —
    implements this so a generic consumer can learn that before ``finalize``.

    The consumer calls :func:`inspect_outcome` on EVERY completed process,
    whatever its exit status, and treats a returned failure exactly like one
    from ``classify_failure``. Implementations must tolerate any stdout (empty,
    not JSON, truncated) and return ``None`` rather than raise; the conformance
    kit probes that. A backend without the capability is unaffected: the base
    ``AgentBackend`` protocol did not grow, which keeps this inside the freeze.
    """

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        """Return a failure the exit status could not reveal, else ``None``."""
        ...


def inspect_outcome(
    backend: object, outcome: RunOutcome, request: RunRequest
) -> ClassifiedFailure | None:
    """Run the backend's :class:`OutcomeInspector` if it has one.

    Returns ``None`` for a backend without the capability. Deliberately does
    not look at the exit status: which processes get inspected is the
    consumer's rule ("every completed one"), not this helper's.
    """
    if isinstance(backend, OutcomeInspector):
        return backend.inspect_outcome(outcome, request)
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_outcome_inspector.py tests/test_conformance_fakes.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Lint and type-check the new code**

Run: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync ty check`
Expected: no findings. If `ruff format --check` reports the new file or protocol.py, run `uv run --no-sync ruff format src tests` and re-run the tests.

- [ ] **Step 6: Commit**

```bash
git add src/pontonier/backend/protocol.py tests/test_outcome_inspector.py
git commit -m "feat(backend): add the optional OutcomeInspector capability

A backend whose process can exit 0 and still have failed (Claude's
zero-exit is_error envelope) implements inspect_outcome; a consumer
calls the inspect_outcome helper on every completed process before
finalize. Optional and runtime-checkable, so AgentBackend is unchanged
and the freeze holds."
```

---

### Task 4: `check_backend` probes inspector tolerance

**Files:**
- Modify: `src/pontonier/testing/conformance.py:8-16` (imports) and `:49-75` (`check_backend`)
- Test: `tests/test_conformance_inspector.py`

**Interfaces:**
- Consumes: `OutcomeInspector`, `ClassifiedFailure`, `RunOutcome`, `RunRequest` from `pontonier.backend.protocol`; `pontonier.core.runtime.CommandRun`; `pontonier.testing.conformance.check_backend(contract, backend) -> list[str]`; `tests.test_conformance_fakes.ClaudeLikeBackend`, `CLAUDE_CONTRACT`.
- Produces: `check_backend` additionally returns a violation string starting with `inspect_outcome raised` or `inspect_outcome returned` when an `OutcomeInspector` backend raises on, or returns a non-`ClassifiedFailure` for, any of three hostile stdouts (`""`, `"not json"`, `"{"`). Backends without the capability are unaffected.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_conformance_inspector.py`:

```python
"""``check_backend`` and the OutcomeInspector capability: an inspector runs on EVERY
completed process, including ones whose stdout is empty or not JSON, so one that raises
there turns a classifiable run into a consumer crash. The probe feeds three hostile
stdouts and reports a raise or a wrong return type as a violation. Backends without the
capability are untouched (issue #15 is about a self-disabling check; this one has no
contract flag to disable it)."""

from __future__ import annotations

import json

from pontonier.backend.protocol import ClassifiedFailure, RunOutcome, RunRequest
from pontonier.testing import conformance
from test_conformance_fakes import CLAUDE_CONTRACT, ClaudeLikeBackend


class TolerantInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        try:
            envelope = json.loads(outcome.run.stdout)
        except json.JSONDecodeError:
            return None
        if isinstance(envelope, dict) and envelope.get("is_error"):
            return ClassifiedFailure(code="nonzero_exit", detail="error envelope")
        return None


class RaisingInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        return json.loads(outcome.run.stdout).get("is_error") and ClassifiedFailure(
            code="nonzero_exit", detail="error envelope"
        )


class WrongTypeInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest):  # type: ignore[override]
        return "not a ClassifiedFailure"


def test_backend_without_the_capability_is_unaffected():
    assert conformance.check_backend(CLAUDE_CONTRACT, ClaudeLikeBackend()) == []


def test_tolerant_inspector_is_clean():
    assert conformance.check_backend(CLAUDE_CONTRACT, TolerantInspector()) == []


def test_raising_inspector_is_a_violation():
    violations = conformance.check_backend(CLAUDE_CONTRACT, RaisingInspector())
    assert violations, "the probe must catch an inspector that raises on non-JSON stdout"
    assert all(v.startswith("inspect_outcome raised") for v in violations)
    assert any("JSONDecodeError" in v for v in violations)


def test_wrong_return_type_is_a_violation():
    violations = conformance.check_backend(CLAUDE_CONTRACT, WrongTypeInspector())
    assert violations
    assert all(v.startswith("inspect_outcome returned") for v in violations)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_conformance_inspector.py -v --no-cov`
Expected: `test_raising_inspector_is_a_violation` FAILS (the probe does not exist yet, so `check_backend` returns `[]`; the raising inspector is never called). `test_wrong_return_type_is_a_violation` FAILS the same way. The other two PASS.

- [ ] **Step 3: Add the probe**

In `src/pontonier/testing/conformance.py`, change the import block (lines 8-16) to:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.backend.protocol import (
    AgentBackend,
    ClassifiedFailure,
    OutcomeInspector,
    RunOutcome,
    RunRequest,
)
from pontonier.core.runtime import CommandRun
from pontonier.testing.surface_honesty import find_contract_self_contradictions

if TYPE_CHECKING:
    from pontonier.backend.contract import BackendContract
```

Then, inside `check_backend`, insert the following block immediately before the final `return out` (after the `effort_silently_ignored_upstream` block):

```python
    if isinstance(backend, OutcomeInspector):
        # The inspector runs on EVERY completed process, including ones whose
        # stdout is empty or not JSON. One that raises there turns a classifiable
        # run into a consumer crash, so tolerance is the invariant, not accuracy.
        probe = RunRequest(kind="consult", prompt="conformance probe", cwd=".", timeout_seconds=1)
        for stdout in ("", "not json", "{"):
            outcome = RunOutcome(run=CommandRun(stdout, "", 0, 1, False))
            try:
                result = backend.inspect_outcome(outcome, probe)
            except Exception as exc:  # noqa: BLE001 — any exception IS the violation
                out.append(
                    f"inspect_outcome raised {type(exc).__name__} on stdout {stdout!r}; "
                    "it must return None or a ClassifiedFailure"
                )
                continue
            if result is not None and not isinstance(result, ClassifiedFailure):
                out.append(
                    f"inspect_outcome returned {type(result).__name__} on stdout "
                    f"{stdout!r}; it must return None or a ClassifiedFailure"
                )
```

Make no other edits to the file. If `ruff check` later reorders the imports (isort), accept its ordering.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_conformance_inspector.py tests/test_conformance_fakes.py tests/test_outcome_inspector.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Lint**

Run: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check .`
Expected: clean. If ruff reports `RUF100` (unused `noqa`) on the `except` line, delete the `# noqa: BLE001 …` comment and keep the rest of the line. If it reports `BLE001` without the comment, restore it. Re-run until clean.

- [ ] **Step 6: Commit**

```bash
git add src/pontonier/testing/conformance.py tests/test_conformance_inspector.py
git commit -m "feat(testing): probe OutcomeInspector tolerance in check_backend

An inspector runs on every completed process, so one that raises on
empty or non-JSON stdout crashes the consumer instead of classifying
the run. The probe feeds three hostile stdouts and reports a raise or a
wrong return type. Backends without the capability are unaffected."
```

---

### Task 5: Changelog

**Files:**
- Modify: `CHANGELOG.md` (insert above line 9, `## [0.8.0] — 2026-08-31`)

- [ ] **Step 1: Insert the Unreleased section**

Insert this block directly above the `## [0.8.0] — 2026-08-31` heading, leaving one blank line after it:

```markdown
## [Unreleased]

### Added

- `Usage.cached_input_tokens` and `Usage.cache_creation_input_tokens`: defaulted fields for
  the cache accounting every bridge already reports and every adapter's `finalize` dropped.
  **Bridges:** each adapter can now carry the figure; nothing changes until it does.
- `ClassifiedFailure.retryable`, `.details` and `.repair` (with the new `RepairHint`
  dataclass) — #24 (background: briandconnelly/claude-in-codex#145). Defaulted; `None`
  means the backend expressed no opinion, never a
  claim. The shared classifier leaves all three `None`.
  **Bridges:** `claude-in-codex` can stop documenting its `classify_failure` as lossy.
- `OutcomeInspector`, an optional runtime-checkable capability, and the
  `pontonier.backend.protocol.inspect_outcome` helper: a backend whose process can exit 0
  and still have failed implements it, and a consumer calls the helper on every completed
  process before `finalize`. `AgentBackend` is unchanged and `CONTRACT_API_VERSION`
  stays 1.
- `testing.conformance.check_backend` probes an `OutcomeInspector` with empty, non-JSON and
  truncated stdout and reports a raise or a wrong return type as a violation.
- `scripts/check_consumers.sh`: runs each consuming bridge's suite against this tree's
  built wheel, asserting the wheel is the version each suite imports. Manual for now; the
  release procedure runs it before a release PR.

All four protocol additions exist for `amicus`, the unified multi-backend server that
replaces the three bridges; its design spec records why each is needed.

```

- [ ] **Step 2: Read the result back**

Run: `sed -n '9,40p' CHANGELOG.md`
Expected: `## [Unreleased]` on line 9, the five bullets and the closing paragraph, one blank line, then `## [0.8.0] — 2026-08-31`. The existing entries below are unchanged.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record the 0.9.0 amicus seams"
```

---

### Task 6: Reverse-dependency check script

**Files:**
- Create: `scripts/check_consumers.sh`

**Interfaces:**
- Consumes: the three sibling checkouts at `../codex-in-claude`, `../moonbridge`, `../claude-in-codex` relative to the pontonier repo root (override by passing paths as arguments).
- Produces: exit 0 only when every consumer's suite passes with the built wheel installed and `importlib.metadata.version("pontonier")` equals this tree's `pyproject.toml` version; restores each consumer's locked environment afterwards.

- [ ] **Step 1: Write the script**

Create `scripts/check_consumers.sh`:

```bash
#!/usr/bin/env bash
# Reverse-dependency check: run each consuming bridge's suite against THIS tree's wheel.
#
# The bridges pin an exact pontonier version, so their normal `uv sync` would silently
# test the PREVIOUS release. This script builds the wheel, force-installs it into each
# consumer's own environment, asserts the consumer really imports it, runs the
# consumer's suite, and then restores the consumer's locked environment.
#
# Usage:
#   scripts/check_consumers.sh                      # the three sibling checkouts
#   scripts/check_consumers.sh /path/to/bridge ...  # explicit consumers
#
# Run it directly, not via `uv run`. Documented in docs/releasing.md.
set -euo pipefail

cd "$(dirname "$0")/.."
root="$(pwd)"

wheel_dir="$(mktemp -d)"
trap 'rm -rf "$wheel_dir"' EXIT
uv build --wheel --out-dir "$wheel_dir" >/dev/null
wheel="$(find "$wheel_dir" -name '*.whl')"
expected="$(uv run --no-sync python -c \
  'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"

consumers=("$@")
if [[ ${#consumers[@]} -eq 0 ]]; then
  consumers=("$root/../codex-in-claude" "$root/../moonbridge" "$root/../claude-in-codex")
fi

status=0
for consumer in "${consumers[@]}"; do
  printf '\n\033[1m==> %s\033[0m\n' "$consumer"
  if [[ ! -f "$consumer/pyproject.toml" ]]; then
    echo "no pyproject.toml in $consumer" >&2
    status=1
    continue
  fi
  (
    cd "$consumer"
    uv sync --locked
    uv pip install --python .venv/bin/python --reinstall "$wheel"
    got="$(uv run --no-sync python -c 'import importlib.metadata as m; print(m.version("pontonier"))')"
    if [[ "$got" != "$expected" ]]; then
      echo "consumer imports pontonier $got, expected $expected" >&2
      exit 1
    fi
    uv run --no-sync pytest -q -p no:cacheprovider
  ) || status=1
  # Restore the consumer's pinned pontonier whatever happened above.
  (cd "$consumer" && uv sync --locked) || status=1
done

if [[ $status -ne 0 ]]; then
  printf '\n\033[1;31m==> consumer check FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[1;32m==> all consumers passed against pontonier %s\033[0m\n' "$expected"
```

Then: `chmod +x scripts/check_consumers.sh`

- [ ] **Step 2: Prove the script can fail (negative-result rule)**

Run: `scripts/check_consumers.sh /tmp/definitely-not-a-consumer`
Expected: prints `no pyproject.toml in /tmp/definitely-not-a-consumer` and ends with `==> consumer check FAILED`, exit code 1.

- [ ] **Step 3: Run it for real**

Run: `scripts/check_consumers.sh`
Expected: three `==>` sections, each ending in a passing pytest run, then `==> all consumers passed against pontonier 0.8.0` (the version is still 0.8.0 at this point; Task 7 bumps it). Runtime is several minutes; the three suites have ~1,700, ~1,400 and ~600 tests.
If a consumer fails, read its output: a failure caused by these additive changes is a plan defect and must be fixed here before continuing; a failure unrelated to pontonier (a live-CLI test, a stale local checkout) is reported in the PR description with the failing test id, not silently skipped.

- [ ] **Step 4: Document the step in the release procedure**

In `docs/releasing.md`, under `## 1. Prepare (agent-safe)`, insert a new step 3 and renumber the existing steps 3 and 4 to 4 and 5:

```markdown
3. Run the reverse-dependency check: `scripts/check_consumers.sh`.
   It force-installs the built wheel into each consuming bridge and runs that bridge's suite, so a release candidate is proven against the real adapters, not only the fakes.
   Record the result in the release PR description.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/check_consumers.sh docs/releasing.md
git commit -m "chore(packaging): add the reverse-dependency consumer check

Bridges pin an exact version, so a plain sync in a consumer tests the
previous release. The script force-installs this tree's wheel, asserts
the consumer imports it, runs the consumer's suite and restores its
lock. Manual for now; releasing.md runs it before a release PR."
```

---

### Task 7: Full gate and draft PR

**Files:** none new.

- [ ] **Step 1: Run the full gate without skipping the wheel check**

Run: `./scripts/check.sh`
Expected: ends with `==> gate passed`. The coverage line must show ≥95% total.

- [ ] **Step 2: Perturbation check on the new conformance probe**

Temporarily edit `src/pontonier/testing/conformance.py` and change the tuple `("", "not json", "{")` to `("{}",)`. Run:

`uv run --no-sync pytest tests/test_conformance_inspector.py -q --no-cov`

Expected: `test_raising_inspector_is_a_violation` FAILS (the raising inspector no longer raises on valid JSON). Revert the edit (`git checkout -- src/pontonier/testing/conformance.py`) and re-run the same command; expected: all pass. This proves the probe is a live instrument.

- [ ] **Step 3: Push the branch and open a draft PR**

```bash
git push -u origin feat/amicus-seams
gh pr create --draft --title "feat(backend): additive 0.9.0 seams for amicus" --body-file - <<'EOF'
## Summary

Four additive protocol seams needed by amicus, the unified multi-backend server:

- `Usage.cached_input_tokens` / `Usage.cache_creation_input_tokens` (defaulted)
- `ClassifiedFailure.retryable` / `details` / `repair` + `RepairHint` (defaulted)
- `OutcomeInspector` optional capability + `inspect_outcome()` helper
- `check_backend` probes inspector tolerance

Plus `scripts/check_consumers.sh`, a manual reverse-dependency check.

`CONTRACT_API_VERSION` stays 1.

Closes #24.

## Verification

- `./scripts/check.sh`: passed (coverage: <fill in the total from Step 1>).
- Perturbation check on the conformance probe: the raising-inspector test fails when the hostile stdouts are replaced with valid JSON, and passes again after revert.
- `scripts/check_consumers.sh`: <fill in: all three passed, or the exact failing test ids and why they are unrelated>.

🤖 Generated with Claude Code
EOF
```

Fill in the two placeholders from the actual outputs before submitting; do not leave angle-bracket text in the PR body.

- [ ] **Step 4: Stop**

Do not merge, approve, tag, or release. The human reviews and merges this PR, then a separate release-prep commit (`chore(release): 0.9.0`, per `docs/releasing.md` step 1, on a new `chore/release-0.9.0` branch) is prepared only when the human asks.

---

## Self-review (writing-plans checklist)

- **Spec coverage:** M-1 row lists five deliverables; Tasks 1, 2, 3, 4, 6 implement them one-to-one; Task 5 records them; Task 7 is the gate. `Usage.cache_creation_input_tokens` was added to the row because Claude reports it and the Codex review named it.
- **Placeholder scan:** the only placeholders are the two angle-bracket fields in the PR body, which Step 3 of Task 7 instructs the agent to fill from measured output.
- **Type consistency:** `RepairHint` fields (`next_step`, `tool`, `arguments`, `alternative`) match between Task 2's implementation, its tests, and the Part 1 envelope shape. `inspect_outcome` has the same signature in Task 3's protocol, helper, tests, and Task 4's probe. `check_backend(contract, backend)` keeps its existing signature.
