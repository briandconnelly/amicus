"""Positive control for the GIT_HOOK_ENV scrub in conftest.py: proves the instrument can
fail (a redirected git actually gets redirected) before proving the fixture fixes it."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.conftest import GIT_HOOK_ENV, NEVER_SPAWN_CODEX, _scrub_git_hook_env

from amicus.backends import codex as codex_pkg
from amicus.orchestration import run as run_mod
from amicus.request import RunSpec


def test_git_hook_env_is_scrubbed_during_a_test():
    assert not (set(GIT_HOOK_ENV) & set(os.environ))


def test_scrub_undoes_a_redirected_git_dir(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)

    monkeypatch.setenv("GIT_DIR", str(elsewhere))

    # Before scrubbing: the instrument can fail. GIT_DIR points at a directory that is not
    # a git dir, so `git -C <repo> rev-parse --git-dir` must fail (non-zero).
    redirected = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert redirected.returncode != 0

    # After scrubbing (what the autouse fixture does): the same command resolves the
    # repo's own .git, unaffected by the stale GIT_DIR.
    _scrub_git_hook_env(monkeypatch)
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert resolved.stdout.strip() == ".git"


# --- the never-spawn guard: AMICUS_CODEX_BIN is unusable, so the real codex plugin's
# binary never resolves and orchestration.run.run_request never reaches a subprocess spawn.


def test_never_spawn_env_is_set_to_the_unusable_path():
    assert os.environ["AMICUS_CODEX_BIN"] == NEVER_SPAWN_CODEX


def test_the_real_codex_plugin_does_not_resolve_a_binary():
    plugin = codex_pkg.plugin(os.environ)
    assert plugin.binary.resolve() is None


async def test_run_request_fails_closed_without_spawning_a_subprocess(monkeypatch):
    def _must_not_spawn(*args, **kwargs):
        raise AssertionError("spawned")

    monkeypatch.setattr(run_mod.runtime, "run_async", _must_not_spawn)

    plugin = codex_pkg.plugin(os.environ)
    spec = RunSpec(
        backend="codex",
        kind="consult",
        tool="amicus_consult",
        cwd="/repo",
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=10,
        question="why?",
    )
    out = await run_mod.run_request(spec, plugin)
    assert out["ok"] is False
    assert out["error"]["code"] == "backend_not_found"


def test_positive_control_a_usable_override_does_resolve(monkeypatch):
    """The instrument can see a usable binary: proves the None above is not just a broken
    resolver, without actually running anything."""
    monkeypatch.setenv("AMICUS_CODEX_BIN", "/usr/bin/true")
    plugin = codex_pkg.plugin(os.environ)
    assert plugin.binary.resolve() is not None


# --- the never-spawn guard for Kimi: AMICUS_KIMI_BIN is unusable


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


# --- the never-spawn guard for Claude: AMICUS_CLAUDE_BIN is unusable


def test_claude_guard_is_in_force_by_default():
    from tests.conftest import NEVER_SPAWN_CLAUDE

    assert os.environ["AMICUS_CLAUDE_BIN"] == NEVER_SPAWN_CLAUDE
    assert not Path(NEVER_SPAWN_CLAUDE).exists()
