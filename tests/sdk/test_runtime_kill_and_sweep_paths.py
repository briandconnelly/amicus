"""Kill/sweep paths of runtime that the bridges exercise through their own suites.

In the source repos these lines were reached via consumer-level tests (delegate
runs, worker cancellation). The standalone library covers them directly: the
public ``kill_process_tree`` contract and ``run_async``'s orphan sweep on the
timeout, cancellation, and success paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import anyio
import pytest
from tests.sdk.test_orphan_sweep import _spawn_detached_child, _wait_for_orphan

from amicus.sdk.core import runtime


def _wait_no_orphans(marker: str, timeout: float = 10.0) -> bool:
    """Poll until no live process matches the marker. A swept child can linger as a
    zombie while its still-alive parent holds it unreaped; zombies show as <defunct>
    in ps with no argv, so marker matching (the sweep's own view) is the right
    liveness signal — not kill(pid, 0), which succeeds on zombies."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not runtime.find_orphans(marker):
            return True
        time.sleep(0.1)
    return not runtime.find_orphans(marker)


@pytest.fixture
def marker() -> str:
    return f"pontonier-worktree-{uuid.uuid4().hex}"


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_kill_process_tree_kills_live_group():
    proc = _sleeper()
    try:
        runtime.kill_process_tree(proc)
        assert proc.wait(timeout=5) != 0
    finally:
        runtime.kill_process_tree(proc)


def test_kill_process_tree_noop_after_exit():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    runtime.kill_process_tree(proc)  # early-return: poll() is not None
    assert proc.returncode == 0


def test_kill_process_tree_falls_back_when_group_lookup_fails(monkeypatch):
    """The ProcessLookupError branch: group kill fails, direct kill still runs."""
    proc = _sleeper()
    try:

        def _raise(_pid):
            raise ProcessLookupError

        monkeypatch.setattr(os, "getpgid", _raise)
        runtime.kill_process_tree(proc)
        assert proc.wait(timeout=5) != 0
    finally:
        monkeypatch.undo()
        runtime.kill_process_tree(proc)


async def test_run_async_timeout_sweeps_marked_orphans(marker):
    """A run that times out leaves a detached, marked descendant; the timeout path's
    second pass reclaims it."""
    detached = _spawn_detached_child(marker)
    try:
        orphans = _wait_for_orphan(marker)
        assert orphans, "detached child never appeared"
        run = await runtime.run_async(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=str(Path.cwd()),
            timeout_seconds=1,
            orphan_marker=marker,
        )
        assert run.timed_out
        assert _wait_no_orphans(marker), "marked orphan survived the timeout sweep"
    finally:
        runtime.kill_process_tree(detached)
        runtime.sweep_orphans(marker)


async def test_run_async_success_sweeps_marked_orphans(marker):
    """A run that exits 0 can still have backgrounded marked work; the success path
    sweeps it rather than leaving it holding the worktree."""
    detached = _spawn_detached_child(marker)
    try:
        orphans = _wait_for_orphan(marker)
        assert orphans, "detached child never appeared"
        run = await runtime.run_async(
            [sys.executable, "-c", "pass"],
            cwd=str(Path.cwd()),
            timeout_seconds=30,
            orphan_marker=marker,
        )
        assert run.exit_code == 0
        assert _wait_no_orphans(marker), "marked orphan survived the success-path sweep"
    finally:
        runtime.kill_process_tree(detached)
        runtime.sweep_orphans(marker)


async def test_run_async_cancellation_sweeps_marked_orphans(marker):
    """Cancellation mid-run kills the group AND sweeps marked strays before
    re-raising."""
    detached = _spawn_detached_child(marker)
    try:
        orphans = _wait_for_orphan(marker)
        assert orphans, "detached child never appeared"

        async def _run():
            await runtime.run_async(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=str(Path.cwd()),
                timeout_seconds=60,
                orphan_marker=marker,
            )

        with anyio.move_on_after(1.0):
            await _run()
        assert _wait_no_orphans(marker), "marked orphan survived the cancellation sweep"
    finally:
        runtime.kill_process_tree(detached)
        runtime.sweep_orphans(marker)
