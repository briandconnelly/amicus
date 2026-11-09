"""The pi binary resolver: override wins and fails loudly; PATH; bare literal."""

from __future__ import annotations

import os
import stat

import pytest

from amicus.backends.pi import binary
from amicus.backends.pi import config as pc


def _exe(tmp_path, name="pi"):
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_usable_override_is_used_exactly_as_given(tmp_path):
    exe = _exe(tmp_path)
    cfg = pc.load_config({"AMICUS_PI_BIN": str(exe)})
    assert binary.pi_bin(cfg) == str(exe)
    resolver = binary.PiBinary(cfg)
    assert resolver.resolve() == str(exe) and resolver.override_error() is None


def test_unusable_override_is_loud_and_never_echoes_its_value(tmp_path):
    cfg = pc.load_config({"AMICUS_PI_BIN": str(tmp_path / "missing-secret-name")})
    with pytest.raises(binary.BinaryNotFoundError) as exc:
        binary.pi_bin(cfg)
    assert "AMICUS_PI_BIN" in str(exc.value) and "missing-secret-name" not in str(exc.value)
    resolver = binary.PiBinary(cfg)
    assert resolver.resolve() is None and "AMICUS_PI_BIN" in (resolver.override_error() or "")
    assert binary.PiBinary(pc.load_config({"AMICUS_PI_BIN": str(tmp_path)})).resolve() is None


def test_relative_override_is_refused():
    resolver = binary.PiBinary(pc.load_config({"AMICUS_PI_BIN": "pi"}))
    assert resolver.resolve() is None and "absolute" in (resolver.override_error() or "")


def test_path_search_then_bare_literal(tmp_path, monkeypatch, clean_env):
    monkeypatch.delenv("AMICUS_PI_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    cfg = pc.load_config({})
    assert binary.pi_bin(cfg) == "pi"
    exe = _exe(tmp_path)
    assert binary.pi_bin(cfg) == str(exe)
    assert os.access(exe, os.X_OK)
