"""codex binary resolution: override, WSL2 candidates, PATH.

Never raises except for a bad override.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from amicus.backends.codex import binary
from amicus.backends.codex import config as cc


def _cfg(**kw):
    base = cc.load_config({})
    return cc.CodexConfig(**{**base.__dict__, **kw})


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_override_is_used_exactly_as_given(tmp_path):
    exe = _executable(tmp_path / "my-codex")
    cfg = _cfg(bin_override=str(exe))
    assert binary.codex_bin(cfg) == str(exe)
    assert binary.CodexBinary(cfg).resolve() == str(exe)
    assert binary.CodexBinary(cfg).override_error() is None


@pytest.mark.parametrize("kind", ["missing", "directory", "no_exec_bit"])
def test_bad_override_raises_and_resolves_to_none_without_echoing_the_value(tmp_path, kind):
    if kind == "missing":
        target = tmp_path / "nope"
    elif kind == "directory":
        target = tmp_path / "dir"
        target.mkdir()
    else:
        target = tmp_path / "plain"
        target.write_text("x")
    cfg = _cfg(bin_override=str(target))
    with pytest.raises(binary.BinaryNotFoundError) as exc:
        binary.codex_bin(cfg)
    assert str(target) not in str(exc.value) and "AMICUS_CODEX_BIN" in str(exc.value)
    assert binary.CodexBinary(cfg).resolve() is None
    assert binary.CodexBinary(cfg).override_error() is not None


def test_falls_back_to_bare_literal_when_nothing_found(monkeypatch):
    monkeypatch.setattr(binary, "resolve_codex_bin", lambda: None)
    assert binary.codex_bin(_cfg(bin_override=None)) == "codex"
    assert binary.CodexBinary(_cfg(bin_override=None)).resolve() == "codex"


def test_plain_host_skips_candidates_and_uses_which(monkeypatch, tmp_path):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(binary, "PROC_VERSION_PATH", tmp_path / "absent")
    home = tmp_path / "home"
    _executable(
        (home / ".local" / "bin").mkdir(parents=True) or (home / ".local" / "bin" / "codex")
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(binary.shutil, "which", lambda name: "/opt/bin/codex")
    assert binary.resolve_codex_bin() == "/opt/bin/codex"


def test_wsl2_prefers_home_local_bin(monkeypatch, tmp_path):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    exe = _executable(home / ".local" / "bin" / "codex")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(binary.shutil, "which", lambda name: "/should/not/win")
    assert binary.resolve_codex_bin() == str(exe)


def test_wsl2_detected_from_proc_version_and_npm_candidate(monkeypatch, tmp_path):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    proc = tmp_path / "version"
    proc.write_text("Linux version 5.15 (Microsoft@Microsoft.com)")
    monkeypatch.setattr(binary, "PROC_VERSION_PATH", proc)
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    monkeypatch.setattr(binary, "USR_LOCAL_BIN", tmp_path / "usr-local-absent")
    npm_prefix = tmp_path / "npm"
    exe = _executable((npm_prefix / "bin").mkdir(parents=True) or (npm_prefix / "bin" / "codex"))
    from pontonier.core.runtime import CommandRun

    monkeypatch.setattr(
        binary.runtime,
        "run_sync_capture",
        lambda cmd, timeout_seconds: CommandRun(str(npm_prefix) + "\n", "", 0, 1, False),
    )
    assert binary.resolve_codex_bin() == str(exe)


def test_resolver_never_raises(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    def boom(*a, **k):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(binary, "_home_local_bin_candidate", boom)
    assert binary.resolve_codex_bin() is None
