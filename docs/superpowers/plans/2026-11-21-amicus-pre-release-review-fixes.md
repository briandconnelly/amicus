# Pre-release Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.
> Dispatch every implementer and every reviewer as an Opus agent (`Agent` tool with `model: "opus"`).
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven findings of the 2026-11-21 pre-release review of `main` (`66c8e73`) against `v0.15.0`, so the next release can be cut.

**Architecture:** Two independent pull requests, worked in parallel in two sibling worktrees.
Track A changes only the job store's internal state: a termination claim in `meta.json` backed by a per-job claimant lock, and a start rollback that covers every failure after the worker is spawned.
Track B removes the export's unlink-by-name cleanup and corrects four published or documented texts under one fingerprint bump.

**Tech Stack:** Python, `uv`, pytest, ruff, ty, import-linter; POSIX `flock` and `ftruncate`.

**Spec:** The "Design" section of this document.
The host drafted it and Codex critiqued it twice (amicus jobs `93a8c93aff15491a9859e06fb8b1070c` and `69e2dd98575345e68c592b8191f863fb`); "Decisions and declined suggestions" records what changed and what was not taken.

## Findings addressed

| # | Finding | Track | Task |
|---|---|---|---|
| 1 | A peer server sharing the state root reads an overrun job as `failed`, and can evict it, while another server terminates its worker with the record lock released. | A | A1, A2 |
| 2 | `_remove_if_ours` checks with `lstat` and then unlinks by name, so it can delete a file swapped in under that name. | B | B1 |
| 3 | A failed start drops its idempotency reservation before the spawned worker is stopped, so a same-key retry can overlap it. | A | Declined by the maintainer; A3 fixes the orphaned-worker gap found beside it |
| 4 | A whole-value `${...}` in `AMICUS_DENY_MODELS` is refused as `unexpanded_env_placeholder`, and the changelog says `model_policy_invalid`. | B | B3 |
| 5 | Both dry-run capability rows omit `model` and `reasoning_effort` from `key_optional_params`. | B | B2 |
| 6 | The `amicus_job_export_diff` description says `meta.truncated` and `meta.redacted_paths` tell whether the diff is whole, which is wrong for `source: "partial"`. | B | B3 |
| 7 | The changelog says an unfinished export file is removed, and the code can report that it was not. | B | B4 |

## Global Constraints

- Use `uv` for everything; a task is done only when the gate in `AGENTS.md` rule 2 passes in that task's worktree.
- Track A works in `~/projects/amicus-wt-termination-claims` on branch `fix/termination-claims`; Track B works in `~/projects/amicus-wt-export-cleanup` on branch `fix/export-cleanup`; both branch from `origin/main`.
- Never commit to `main`, never merge a pull request, never approve your own (`AGENTS.md` rule 8); open each pull request as a draft.
- Commit messages follow `AGENTS.md` rule 12, with only the scopes in `scripts/check_commit_message.py`; this plan uses `jobs`, `tools`, `schemas` and `docs`.
- Track A must not change any published text, schema, status or error code, so `FINGERPRINT` stays `amicus/0.1/schema-81` there; if `tests/test_manifest.py` moves, stop and report.
- Track B bumps `FINGERPRINT` to `amicus/0.1/schema-82` exactly once, with the regenerated pins, in a commit of its own (`AGENTS.md` rule 10, Task B5).
- `RESULT_FORMAT` does not move in either track: no stored `result.json` shape changes.
- No exception message, log line or error envelope carries the export path or any diff text, and the diff is written to no file but the one the caller names (`AGENTS.md` rule 18).
- Do not touch `.github/**`, `AGENTS.md`, `CLAUDE.md`, the version literals or `.claude-plugin/marketplace.json`.
- Use a closing keyword in a pull-request body only if an issue exists and the pull request resolves all of it (`AGENTS.md` rule 26).
- Both tracks add to `## [Unreleased]` in `CHANGELOG.md`; the second to merge rebases.
- Never run `-m integration` tests.
- A test listed below as a regression guard passes before the change; every other new test must be seen to fail first.

## Design

### D1: the termination claim and its claimant lock (finding 1)

A process that is about to stop a worker with the record lock released becomes that job's claimant first, under `_LOCK` and the record flock.
It writes `meta["terminating"] = {"reason": "timeout" | "cancelled", "epoch": <time.time()>}` if no well-formed claim is there, and takes an exclusive, non-blocking `flock` on `<job dir>/terminate.lock`.
The first claim wins and is never replaced, so the reason a job finalizes with is the reason of whoever claimed it first.
The claimant holds the lock through signalling and finalization and releases it only after the record is stamped, or when it gives up on an error; a claimant that dies releases it with its descriptors.
The claimant lock is only ever tried, never waited for, while `_LOCK` or the record flock is held, so the store's lock order gains no rule.
Writing the claim is best effort: on `OSError` the claimant proceeds with the lock alone, and the in-process `_TERMINATING` and `_OVERRAN` sets keep today's behaviour for its own threads.
A claim is well formed only when `reason` is one of the two strings and `epoch` is a finite number; a malformed one is treated as absent.

`_status_of`, in any process, for a record with no `terminal_status` that is not in this process's `_OVERRAN` or `_TERMINATING`:

- With a well-formed claim and the claimant lock held by someone else, the job reads `running`: it is counted as held, never reported `failed`, never evicted and never signalled by this reader.
- With a well-formed claim, the claimant lock free and the worker not running by `_job_running`, the reader finalizes the record on the spot with `_finish_terminated`.
- With a well-formed claim, the claimant lock free and the worker still running, the reader takes the lock and raises `_Overrun`, becoming the claimant whatever the claim's reason is.
- With no claim, a running worker past its deadline makes the reader claim `timeout`, take the lock and raise `_Overrun`; if the lock cannot be taken the job reads `running`.
- A claimant lock that reads as indeterminate (`None`: the file is missing or `fcntl` is unavailable) is treated as free.

`_finish_terminated(jd, meta, default)` replaces `_finish_overrun` and is the one finalizer for a stopped job that was claimed or terminated here.
An existing stamp is returned; else a readable `result.json` makes it `done`; else it is stamped with the claim's reason, or `default` without a claim, with the cleanup manifest re-read and applied.
It removes the `terminating` key in the same write that stamps the record and discards the job from `_OVERRAN`.
An unreadable result still raises `ResultUnreadable`, stamps nothing and keeps the claim.

`cancel` uses the same protocol.
Under the locks, for a running job, it tries to become the claimant with reason `cancelled`.
If it does, it terminates with the locks released and then finalizes with `_finish_terminated`, passing `default="timeout"` when the job is in this process's `_TERMINATING` or `_OVERRAN` and `default="cancelled"` otherwise.
If another claimant holds the lock, `cancel` signals nothing: it polls with every lock released, for at most `terminate_grace_seconds` plus one second, until the claimant lock is free, then re-reads the record under the locks and returns what `_status_of` gives.

The guarantee holds among servers of this release or later.
A `v0.15.0` server sharing the root ignores the key and the lock and can still derive `failed`, which the store's module docstring and the changelog state.
The gap between a liveness check and the signal that follows it, in which a PID could be reused, exists today for every signaller and is not changed here.

### D3: every post-spawn failure is rolled back (beside finding 3)

Finding 3 itself is declined: the reservation is still dropped before the rollback's grace, as #536 chose and `tests/sdk/test_jobs_overrun.py` pins, and no reservation code changes.
What is fixed is a gap the review of that finding exposed.
Today only a failed `_write_meta` queues the rollback, so a failure closing the stderr log file or starting the stdin thread, both of which happen after `Popen` returned, leaves a paid worker running with no record.
Everything `_start_locked` does from the moment `Popen` returns until `_write_meta` succeeds is put under the one handler that withdraws `meta.json` and queues `_rollback_unrecorded`.
`_rollback_unrecorded` keeps its signature and its behaviour.

### D2: no cleanup by name (finding 2)

`write_diff_file` keeps creating the file at the caller's name with `O_CREAT | O_EXCL | O_NOFOLLOW`, which is what makes the export a new file that overwrites nothing.
What changes is failure: the function never unlinks anything.
On any failure after the file is created it empties the file through the descriptor it already holds (`os.ftruncate(fd, 0)`, then `fsync`), which can only ever touch the inode this call created.
The descriptor therefore stays open until after the check that `lstat(path)` still names the created inode, and a mismatch there empties the file too, wherever it now lives, so no diff bytes outlive a failed call.
`_remove_if_ours` is deleted.
`ExportFailed` reports what the call left behind: `"nothing"` (the file was never created), `"empty_file"` (created, then emptied, and still wherever its name is), or `"partial_file"` (it could not be emptied).
After `"empty_file"` the path may still hold the emptied file, someone else's file or nothing, because the export can be moved or removed during the call, so the repair text says to delete what is at the path only if it is an empty file, otherwise to pass another path.

### D4 to D7: texts (findings 4 to 7)

D4 keeps the behaviour and corrects the words: a malformed list is `model_policy_invalid`, and a whole-value placeholder is `unexpanded_env_placeholder` like every other variable.
D5 adds `model` and `reasoning_effort` to both dry-run rows.
D6 states that `meta.diff_export.source` `"partial"` is always an incomplete change, and that `meta.truncated` and `meta.redacted_paths` are separate checks.
D7 says a failed export is emptied rather than removed, and that `export_failed` says what remains.

### Decisions and declined suggestions

- **Decided by the maintainer, finding 3:** declined, and #536's choice stands, because the overlap is at most the terminate grace of a worker whose output is discarded, while holding the reservation would block a legitimate same-key retry until the idempotency horizon whenever the stop could not be confirmed.
- **Decided by the maintainer, finding 2:** a failed export is emptied and left; a staged write published with a hard link was drafted and dropped, because it puts diff bytes in a second named file and rule 18 allows exactly one, and no rule-18 change is sought.
- **Decided by the maintainer, mixed versions:** accepted and documented, because closing it for a `v0.15.0` peer means holding the record lock through termination, which is the stall #531 fixed.
- **Taken from Codex, D1:** the per-job claimant lock, which replaced a wall-clock stale bound that could not tell a paused claimant from a dead one.
- **Taken from Codex, D3:** covering the log file's close and the stdin thread's start with the rollback.
- **Declined, finding 4:** routing a denylist placeholder to `model_policy_invalid`, because every other variable reports a placeholder the same way and `tests/test_model_policy.py` pins it.
- **Not addressed:** `cancel` of an unowned worker with no verified lock stamps `cancelled` without having signalled it, as it does today.

## Review Focus

- A peer reads a claimed job while the claimant is mid-termination: it must read `running`, send no signal and evict nothing (Task A1).
- The claimant process dies between the signal and the stamp: the next reader in any process must finalize by the claim, and never as `failed` (Task A1).
- The claim cannot be written because the disk is full: status, list and start must still terminate the overrun job and finalize it `timeout` (Task A1).
- A cancel lands on a job another server is terminating as an overrun: it must send no signal, return `timeout`, and the cleanup manifest must be applied once (Task A2).
- A file is swapped in under the export's name while the write fails: that file must be byte-identical afterwards and nothing may be unlinked (Task B1).

---

## Track A: job store (`fix/termination-claims`)

### Task A0: Worktree

- [ ] **Step 1: Create the worktree**

```sh
git -C ~/projects/amicus fetch origin
git -C ~/projects/amicus worktree add ~/projects/amicus-wt-termination-claims -b fix/termination-claims origin/main
cd ~/projects/amicus-wt-termination-claims && uv sync
```

- [ ] **Step 2: Confirm the baseline**

Run: `uv run pytest tests/sdk/test_jobs_overrun.py -q`
Expected: all pass.

- [ ] **Step 3: Commit this plan**

Copy this file to the same path in the worktree, then:

```sh
git add docs/superpowers/plans/2026-11-21-amicus-pre-release-review-fixes.md
git commit -m "docs(docs): plan the pre-release review fixes"
```

### Task A1: The overrun claim, the claimant lock and the one finalizer

**Files:**
- Modify: `src/amicus/jobs/store.py` (`_Overrun`, `_status_of`, `_finish_overrun`, `_finalize_overrun`, `_terminate_overruns`, the module docstring)
- Test: `tests/sdk/test_jobs_overrun.py`

**Interfaces:**
- Produces: `_TERMINATE_LOCK_NAME = "terminate.lock"` (module constant).
- Produces: `JobStore._claim_of(meta: dict) -> tuple[str, float] | None` (static), the well-formed claim's `(reason, epoch)`.
- Produces: `JobStore._try_claim(self, jd: Path, meta: dict, reason: Literal["timeout", "cancelled"]) -> int | None`, which writes the claim when none is well formed (suppressing `OSError`), then returns a descriptor holding the claimant lock, or `None` when another holder has it.
- Produces: `_release_claim(fd: int | None) -> None` (module function), which unlocks and closes, and accepts `None`.
- Produces: `JobStore._finish_terminated(self, jd: Path, meta: dict, default: Literal["timeout", "cancelled"]) -> str`, which replaces `_finish_overrun`.
- Changes: `_Overrun.__init__(self, jd: Path, meta: dict, claim_fd: int | None)`; `_terminate_overruns` releases `claim_fd` after `_finalize_overrun`, and in its `finally` for every claim it still holds.
- Reuses: `_worker_lock_held(path) -> bool | None` to read whether `terminate.lock` is held.

- [ ] **Step 1: Write the tests**

Add to `tests/sdk/test_jobs_overrun.py`, using its `_store`, `_overrun_job`, `_bounded` and `_declare` helpers.
A peer is a real second Python process, in the style of `_OTHER_PROCESS` in `tests/test_job_durability.py`: a `-c` script that builds a `JobStore` on the same root with the same options, makes the calls the test names, and prints one JSON line.
The claimant is parked by patching `job_store._terminate_pid_tree` in the test process to call the real function, wait for the worker to be reaped, run the peer, and then return; the test asserts the patched function ran.

```python
def test_a_peer_process_reads_a_terminating_overrun_as_running(tmp_path, monkeypatch):
    # peer: {"status": store.status(cwd, job_id)["status"]}
    assert parked.is_set()
    assert seen["status"] == "running"
    assert store.status(cwd, job_id)["status"] == "timeout"
    assert "terminating" not in store._read_meta(jd)


def test_a_peer_at_the_cap_does_not_evict_a_terminating_overrun(tmp_path, monkeypatch):
    # max_count=1; the peer calls start() while the claimant is parked
    assert seen["start"] == "cap"  # JobCapReached in the peer
    assert store.status(cwd, job_id)["status"] == "timeout"
    assert not declared_worktree.exists()


def test_a_peer_does_not_signal_a_job_another_process_is_terminating(tmp_path, monkeypatch):
    # the worker ignores SIGTERM; the peer's own _terminate_pid_tree is patched to record calls
    assert seen["terminate_calls"] == 0


def test_a_dead_claimants_job_is_finalized_by_the_next_reader(tmp_path):
    # meta: unowned, dead pid, a "timeout" claim, terminate.lock present and free, no result
    assert store.status(cwd, job_id)["status"] == "timeout"
    assert "terminating" not in store._read_meta(jd)


def test_a_dead_claimants_live_worker_is_taken_over(tmp_path, monkeypatch):
    # a "timeout" claim, terminate.lock free, the worker still running before its deadline
    assert store.status(cwd, job_id)["status"] == "timeout"
    assert terminate_calls == 1


def test_a_claimed_job_whose_result_reads_is_done_and_unclaimed(tmp_path):
    assert store.status(cwd, job_id)["status"] == "done"
    assert "terminating" not in store._read_meta(jd)


def test_the_claimant_lock_is_released_after_finalization_and_after_an_error(tmp_path, monkeypatch):
    assert job_store._worker_lock_held(jd / "terminate.lock") is False


# Regression guards: these pass before the change.
def test_a_malformed_claim_is_ignored(tmp_path):
    # "terminating": "yes"; {"reason": "paused", "epoch": 1}; {"reason": "timeout", "epoch": "x"}
    assert store.status(cwd, job_id)["status"] == "failed"


def test_an_unwritable_claim_still_terminates_and_times_out(tmp_path, monkeypatch):
    # _write_meta raises OSError(ENOSPC) for the claim write only
    assert claim_write_attempted
    assert store.status(cwd, job_id)["status"] == "timeout"
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/sdk/test_jobs_overrun.py -q -k "peer or claim"`
Expected: every test above the regression-guard comment fails; the two guards pass.

- [ ] **Step 3: Implement D1 for the overrun path**

Follow the five `_status_of` rules in D1, in that order, after the existing `_OVERRAN`, `terminal_status` and `_TERMINATING` checks.
`_status_of` passes the descriptor from `_try_claim` to `_Overrun`.
Rename `_finish_overrun` to `_finish_terminated` with the `default` parameter; every existing caller passes `default="timeout"`.
Pop `terminating` from `meta` before `_finish_terminated` calls `_mark_done` or `_finalize_cleanup`, so the stamping write removes it.
Extend the store's module docstring with the claim, the claimant lock, that the lock is never waited for under the other locks, and the mixed-version limit.

- [ ] **Step 4: Run the files**

Run: `uv run pytest tests/sdk tests/test_job_durability.py -q`
Expected: all pass, including every pre-existing test.

- [ ] **Step 5: Commit**

```sh
git commit -am "fix(jobs): claim an overrun's termination so a peer never reads it as failed"
```

### Task A2: Give cancel the same protocol

**Files:**
- Modify: `src/amicus/jobs/store.py` (`cancel`)
- Test: `tests/sdk/test_jobs_overrun.py`

**Interfaces:**
- Consumes: `_try_claim`, `_release_claim`, `_claim_of`, `_finish_terminated` from Task A1.

- [ ] **Step 1: Write the tests**

```python
def test_a_peer_process_reads_a_cancelling_job_as_running(tmp_path, monkeypatch):
    # this process's cancel is parked in the patched _terminate_pid_tree; the peer reads status
    assert seen["status"] == "running"
    assert result["status"] == "cancelled"


def test_a_cancel_claim_survives_the_deadline(tmp_path, monkeypatch):
    # cancel claims; while it is parked the deadline passes and a peer reads the job
    assert seen["status"] == "running"
    assert store.status(cwd, job_id)["status"] == "cancelled"


def test_a_cancel_of_a_job_a_peer_is_terminating_sends_no_signal(tmp_path, monkeypatch):
    # a peer process holds terminate.lock under a "timeout" claim and finalizes after a pause
    assert terminate_calls == 0
    assert result["status"] == "timeout"
    assert cleanup_calls == [str(declared_worktree)]


def test_a_cancel_gives_up_waiting_for_a_claimant_that_never_finishes(tmp_path, monkeypatch):
    # terminate_grace_seconds=0.2; the lock stays held by a helper process
    assert result["status"] == "running"
    assert elapsed < 5


# Regression guard: passes before the change.
def test_a_cancel_during_a_local_overrun_whose_claim_was_not_written_is_timeout(tmp_path, monkeypatch):
    # _write_meta fails for the claim; another thread's cancel meets _TERMINATING
    assert result["status"] == "timeout"
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/sdk/test_jobs_overrun.py -q -k "cancel"`
Expected: the first four fail; the guard and the pre-existing cancel tests pass.

- [ ] **Step 3: Implement**

Follow D1's `cancel` paragraph.
Keep the two `MetaUnreadable` handlers that set `signalled = True`, and set it only when this cancel signalled.
Keep the `result_ok` backfill the old block did with `setdefault` when a result is found on a record whose `completed_epoch` is already set.
Release the claim in a `finally` that covers the unlocked termination and the finalization.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/sdk tests/test_job_durability.py tests/test_job_tools.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```sh
git commit -am "fix(jobs): make cancel a claimant so a peer finalizes it as cancelled"
```

### Task A3: Roll back every failure after the worker is spawned

**Files:**
- Modify: `src/amicus/jobs/store.py` (`_start_locked`)
- Test: `tests/sdk/test_jobs_overrun.py`

**Interfaces:**
- Unchanged: `_rollback_unrecorded(self, pid: int, jd: Path) -> None`, `start_idempotent`, and everything in `src/amicus/jobs/idempotency.py`.

- [ ] **Step 1: Write the tests**

Capture the spawned `Popen` by wrapping `subprocess.Popen` in `job_store`, so each test can assert on the child it started.

```python
def test_a_failure_closing_the_log_after_spawn_is_rolled_back(tmp_path, monkeypatch):
    # the stderr log file's close raises OSError(EIO) once Popen has returned
    assert isinstance(raised, OSError) and raised.errno == errno.EIO
    assert spawned.wait(timeout=_WAIT) is not None
    assert not jd.exists()


def test_a_failure_starting_the_stdin_thread_is_rolled_back(tmp_path, monkeypatch):
    # stdin_text is given and threading.Thread.start raises RuntimeError
    assert isinstance(raised, RuntimeError)
    assert spawned.wait(timeout=_WAIT) is not None
    assert not jd.exists()


def test_a_post_spawn_failure_is_rolled_back_with_the_locks_released(tmp_path, monkeypatch):
    # _terminate_pid_tree is patched to record _locks_free(store, cwd) when it is called
    assert seen["locks_free"] is True


# Regression guards: these pass before the change.
def test_a_spawn_failure_removes_the_job_dir_and_queues_nothing(tmp_path, monkeypatch):
    # Popen raises OSError
    assert store._job_dirs(store._ws_dir(cwd)) == []
    assert terminate_calls == 0


def test_a_keyed_retry_during_rollback_is_still_created(tmp_path, monkeypatch):
    # the existing idempotent case of test_start_rollback_terminates_the_unrecorded_worker_unlocked
    # already pins this; do not change it
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/sdk/test_jobs_overrun.py -q -k "spawn or log or stdin or rollback"`
Expected: the first three fail (the child is still alive, or the job dir remains); the guards and every pre-existing rollback test pass.

- [ ] **Step 3: Implement D3**

In `_start_locked`, open the log file without a `with`.
Keep an `except OSError` around `Popen` alone that closes the file, removes `jd` and re-raises.
Put the file's close, the stdin thread's start, the building of `meta` and `_write_meta` under the one existing `except BaseException` handler, which withdraws `meta.json`, queues `functools.partial(self._rollback_unrecorded, proc.pid, jd)` and re-raises.
Close the log file in that handler too if it is still open, suppressing `OSError`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/sdk tests/test_job_durability.py tests/test_job_tools.py -q`
Expected: all pass, and `tests/sdk/test_idempotency.py` is untouched.

- [ ] **Step 5: Commit**

```sh
git commit -am "fix(jobs): roll back a worker when anything fails between its spawn and its record"
```

### Task A4: Changelog, gate, draft pull request

- [ ] **Step 1: Add two `### Fixed` entries to `CHANGELOG.md`**

One for finding 1: the claim, that it covers cancel, that it holds among servers of this release or later sharing a state root, and that sessions still running an older server must be restarted after upgrading for it to hold.
One for Task A3: a start that fails after its worker is spawned, at any step before the job is recorded, now stops that worker.

- [ ] **Step 2: Run the gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`
Expected: all pass, the coverage floor holds, and no pinned fixture changed.

- [ ] **Step 3: Commit, push, open the draft**

```sh
git commit -am "docs(jobs): record the termination claim and the wider start rollback"
git push -u origin fix/termination-claims
gh pr create --draft --title "fix(jobs): claim terminations across servers and roll back every post-spawn failure" --body-file <body>
```

The body lists finding 1, the mixed-version limit and the restart it asks for, finding 3 as declined with the maintainer's reason, the post-spawn rollback fix, and what was not addressed.

---

## Track B: export and surface (`fix/export-cleanup`)

### Task B0: Worktree

- [ ] **Step 1: Create the worktree**

```sh
git -C ~/projects/amicus worktree add ~/projects/amicus-wt-export-cleanup -b fix/export-cleanup origin/main
cd ~/projects/amicus-wt-export-cleanup && uv sync
```

- [ ] **Step 2: Confirm the baseline**

Run: `uv run pytest tests/test_job_export.py tests/test_job_tools.py tests/test_discovery.py -q`
Expected: all pass.

### Task B1: Empty a failed export through its descriptor and never unlink

**Files:**
- Modify: `src/amicus/jobs/export.py` (`ExportFailed`, `_create`, delete `_remove_if_ours`, the module docstring)
- Modify: `src/amicus/tools/jobs.py` (`_EXPORT_FAILED_REMOVED`, `_EXPORT_FAILED_KEPT`, the `ExportFailed` handler)
- Modify: `src/amicus/errors.py` (the `export_failed` rule's text)
- Modify: `src/amicus/schemas/params.py` (the `path` contract's `full` text)
- Test: `tests/test_job_export.py`, `tests/test_job_tools.py`

**Interfaces:**
- Produces: `ExportFailed(errno_: int | None = None, *, left: Literal["nothing", "empty_file", "partial_file"] = "nothing")` with attributes `errno` and `left`; the `removed` attribute is gone.
- Unchanged: `write_diff_file(path: str, diff: str, *, job_store_root: str) -> DiffExport`, `ExportRefused.reason` and its six tokens.

- [ ] **Step 1: Write the tests**

In `tests/test_job_export.py`, using its `scratch` and `store_root` fixtures.
Rewrite `test_failed_write_removes_the_file`, `test_cleanup_never_unlinks_a_file_swapped_in_under_the_name`, `test_a_file_unlinked_during_the_write_is_export_failed`, `test_a_parent_renamed_during_the_write_is_export_failed` and `test_a_failed_write_says_whether_it_removed_the_file` into the tests below, keeping the fault each one injects.

```python
def test_a_failed_write_leaves_an_empty_file(scratch, store_root, monkeypatch):
    # os.write raises OSError(ENOSPC) after some bytes were written
    assert exc.value.left == "empty_file"
    assert (scratch / "out.diff").read_bytes() == b""


def test_a_failed_export_never_unlinks_or_removes_anything(scratch, store_root, monkeypatch):
    # os.unlink, os.remove and os.rmdir are patched to record calls
    assert removals == []


def test_a_file_swapped_in_under_the_name_is_untouched(scratch, store_root, monkeypatch):
    # during the failing write, out.diff is renamed away and another file is renamed into its place
    assert (scratch / "out.diff").read_bytes() == b"theirs"
    assert (scratch / "moved.diff").read_bytes() == b""
    assert exc.value.left == "empty_file"


def test_a_path_that_stops_naming_the_export_empties_it(scratch, store_root, monkeypatch):
    # the complete file is renamed away after the last write and before the identity check
    assert exc.value.errno == errno.ESTALE and exc.value.left == "empty_file"
    assert (scratch / "moved.diff").read_bytes() == b""


def test_a_file_that_cannot_be_emptied_is_partial(scratch, store_root, monkeypatch):
    # os.ftruncate raises OSError(EIO)
    assert exc.value.left == "partial_file"


def test_a_create_failure_that_is_not_a_refusal_leaves_nothing(scratch, store_root, monkeypatch):
    # os.open of the name raises OSError(EIO)
    assert exc.value.left == "nothing"
    assert list(scratch.iterdir()) == []


def test_no_failure_message_carries_the_path(scratch, store_root, monkeypatch):
    # for each value of left: str(scratch) not in str(exc.value)
```

In `tests/test_job_tools.py`, change the export-failure tests to assert one fixed repair text for each of the three `left` values, that the job stays undelivered for all three, and that the `empty_file` text makes deleting what is at the path conditional on it being an empty file.

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_job_export.py tests/test_job_tools.py -q -k "export or empt or partial or swapped or unlink"`
Expected: the new and rewritten tests fail.

- [ ] **Step 3: Implement D2**

In `_create`, keep the descriptor open until after the `lstat(path)` identity check, and on any `OSError` after the create call `os.ftruncate(fd, 0)` and `os.fsync(fd)` before closing it.
Give each `left` value one fixed message with no path.
In `tools/jobs.py`, map the three values to three repair texts; rewrite the `export_failed` rule in `errors.py` and the `path` contract's sentences about an unfinished file and a cancelled call in `params.py` to match.
State in the module docstring that the function never unlinks, and why.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_job_export.py tests/test_job_tools.py -q`
Expected: all pass except comparisons against pinned fixtures, which Task B5 regenerates.

- [ ] **Step 5: Commit**

```sh
git commit -am "fix(jobs): empty a failed diff export through its descriptor and never unlink"
```

### Task B2: List the selectors on the dry-run capability rows

**Files:**
- Modify: `src/amicus/tools/discovery.py` (`_REVIEW_PREVIEW_PARAMS`, the `amicus_delegate_dry_run` row of `_JOB_PARAMS`)
- Test: `tests/test_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("tool", ["amicus_review_changes_dry_run", "amicus_delegate_dry_run"])
def test_a_dry_run_row_lists_the_selectors_model_policy_checks(tool):
    _required, optional = discovery._JOB_PARAMS[tool]
    assert {"model", "reasoning_effort"} <= set(optional)
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run pytest tests/test_discovery.py -q -k selectors`
Expected: FAIL for both tools.

- [ ] **Step 3: Add `"model"` and `"reasoning_effort"` to both optional lists**

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: all pass except comparisons against pinned fixtures; `test_hand_listed_params_match_each_tools_input_schema` passes.

- [ ] **Step 5: Commit**

```sh
git commit -am "fix(tools): list model and reasoning_effort on the dry-run capability rows"
```

### Task B3: Correct the export description and the denylist description

**Files:**
- Modify: `src/amicus/tools/jobs.py` (the `amicus_job_export_diff` description)
- Modify: `src/amicus/config/__init__.py` (the `AMICUS_DENY_MODELS` `EnvVar` description)
- Regenerate: `docs/CONFIGURATION.md`
- Test: `tests/test_job_tools.py`, `tests/test_model_policy.py`

- [ ] **Step 1: Write the failing tests**

Read the tool's description through `Client.list_tools()`, as `tests/test_job_tools.py` already does, and the variable through `GLOBAL_ENV.var("AMICUS_DENY_MODELS")` from `amicus.config`.

```python
async def test_the_export_description_does_not_call_a_partial_diff_whole(...):
    assert "say if it is whole" not in description
    assert "partial" in description and "incomplete" in description
    assert "meta.truncated" in description and "meta.redacted_paths" in description


def test_the_denylist_description_names_both_refusals():
    text = GLOBAL_ENV.var("AMICUS_DENY_MODELS").description
    assert "model_policy_invalid" in text
    assert "unexpanded_env_placeholder" in text
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/test_job_tools.py tests/test_model_policy.py -q -k "description"`
Expected: both fail.

- [ ] **Step 3: Reword**

In the tool description, replace `meta.truncated and meta.redacted_paths say if it is whole.` with `meta.diff_export.source "partial" is always an incomplete change; also check meta.truncated and meta.redacted_paths.`
In the `EnvVar` description, replace `Malformed, every paid tool and dry run refuses.` with `Malformed, every paid tool and dry run refuses with model_policy_invalid; a value that is an unexpanded ${...} placeholder is refused as unexpanded_env_placeholder, like any other variable.`
Then run `uv run python scripts/render_configuration_doc.py --write`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_job_tools.py tests/test_model_policy.py tests/test_configuration_doc.py tests/test_discovery_cost.py tests/test_check_sentence_per_line.py -q`
Expected: all pass except comparisons against pinned fixtures; if a `tools/list` byte budget in `tests/test_discovery_cost.py` fails, shorten the new description and never raise the budget.

- [ ] **Step 5: Commit**

```sh
git commit -am "fix(tools): say a partial export is incomplete and name both denylist refusals"
```

### Task B4: Changelog and skill text

**Files:**
- Modify: `CHANGELOG.md` (`## [Unreleased]`)
- Modify, only if it describes a removed or partial export file: `skills/collaborating-with-amicus/references/reviewing-a-returned-diff.md`

- [ ] **Step 1: Edit the entries**

In the `amicus_job_export_diff` entry, replace the sentence that says an unfinished file "is removed" with one saying a file the call could not finish is emptied and left, never unlinked, and that `export_failed` says what remains.
In the `AMICUS_DENY_MODELS` entry, after the `model_policy_invalid` sentence, add that a whole-value `${...}` placeholder is refused as `unexpanded_env_placeholder`.
Add a `### Fixed` entry for finding 2 and one line for finding 5.
Change the export entry's closing sentence so the discovery surface moves to `amicus/0.1/schema-82`.

- [ ] **Step 2: Commit**

```sh
git commit -am "docs(tools): correct the export and denylist entries and record the fixes"
```

### Task B5: Bump the fingerprint, gate, draft pull request

**Files:**
- Modify: `src/amicus/schemas/fingerprint.py` (`FINGERPRINT`)
- Regenerate: the pins under `tests/fixtures/`

- [ ] **Step 1: Bump and regenerate**

Set `FINGERPRINT = "amicus/0.1/schema-82"`, then run `uv run python scripts/regenerate_fingerprint_pins.py`.

- [ ] **Step 2: Check what moved**

Run: `git diff --stat`
Expected: only `fingerprint.py` and the files the script reports rewriting; inside the pins, only the export prose, the `path` contract, the two capability rows, the export description and the fingerprint string differ.

- [ ] **Step 3: Commit alone**

```sh
git commit -am "chore(schemas): bump the fingerprint to schema-82 and regenerate the pins"
```

- [ ] **Step 4: Run the gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest`
Expected: all pass and the coverage floor holds.

- [ ] **Step 5: Push and open the draft**

```sh
git push -u origin fix/export-cleanup
gh pr create --draft --title "fix(jobs): never unlink a failed diff export and correct four published texts" --body-file <body>
```

The body lists findings 2, 4, 5, 6 and 7, the empty file a failed export now leaves, and the fingerprint move.

---

## After both tracks

- [ ] Whichever pull request merges second is rebased on `main`, keeping both sets of `CHANGELOG.md` entries.
- [ ] The maintainer reviews and merges; no agent merges.
