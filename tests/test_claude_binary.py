"""AMICUS_CLAUDE_BIN precedence: an unusable override is loud, never a PATH fallthrough."""

from __future__ import annotations

import pytest

from amicus.backends.claude import binary, config


def test_override_is_used_exactly_as_given(tmp_path):
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    cfg = config.load_config({"AMICUS_CLAUDE_BIN": str(exe)})
    assert binary.claude_bin(cfg) == str(exe)
    assert binary.ClaudeBinary(cfg).resolve() == str(exe)
    assert binary.ClaudeBinary(cfg).override_error() is None


@pytest.mark.parametrize("kind", ["missing", "directory", "not_executable"])
def test_unusable_override_raises_without_echoing_the_value(tmp_path, kind):
    target = tmp_path / "x"
    if kind == "directory":
        target.mkdir()
    elif kind == "not_executable":
        target.write_text("")
    cfg = config.load_config({"AMICUS_CLAUDE_BIN": str(target)})
    with pytest.raises(binary.BinaryNotFoundError) as info:
        binary.claude_bin(cfg)
    assert "AMICUS_CLAUDE_BIN" in str(info.value) and str(target) not in str(info.value)
    resolver = binary.ClaudeBinary(cfg)
    assert resolver.resolve() is None and "AMICUS_CLAUDE_BIN" in (resolver.override_error() or "")


def test_no_override_falls_back_to_path_then_the_bare_literal(monkeypatch):
    cfg = config.load_config({})
    monkeypatch.setattr(binary.shutil, "which", lambda name: "/opt/claude")
    assert binary.claude_bin(cfg) == "/opt/claude"
    monkeypatch.setattr(binary.shutil, "which", lambda name: None)
    assert binary.claude_bin(cfg) == "claude"
