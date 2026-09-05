"""Packaging invariants: version literals agree, classifiers match the floor."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import amicus

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_version_literal_matches_package():
    assert _pyproject()["project"]["version"] == amicus.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", amicus.__version__)


def test_python_floor_matches_classifiers():
    project = _pyproject()["project"]
    floor = project["requires-python"]
    assert floor == ">=3.11"
    minors = sorted(
        int(c.rsplit(".", 1)[1])
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    )
    assert minors[0] == 11
    assert minors == list(range(minors[0], minors[-1] + 1))


def test_runtime_dependencies_are_exactly_the_spec_set():
    deps = _pyproject()["project"]["dependencies"]
    names = sorted(re.split(r"[<>=!\[]", d, maxsplit=1)[0] for d in deps)
    assert names == ["anyio", "fastmcp", "mcp", "pontonier", "pydantic"]
    assert "pontonier==0.9.0" in deps


def test_console_script_points_at_server_main():
    assert _pyproject()["project"]["scripts"] == {"amicus-mcp": "amicus.server:main"}
