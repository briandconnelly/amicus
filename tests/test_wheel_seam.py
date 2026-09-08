"""A third-party backend, built as a real wheel and installed out of tree, is discoverable.

The entry-point group is the plugin seam's whole promise. An in-repo import path cannot
prove it: a group that scanned nothing would look identical to success. Hence the negative
control below."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fakebackend"
REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.slow  # registered in pyproject.toml


def _build_and_install(tmp_path: Path, api_version: int) -> Path:
    """Build the fixture wheel with a given api_version and install it beside amicus."""
    src = tmp_path / "src"
    shutil.copytree(FIXTURE, src)
    init = src / "src" / "fakebackend" / "__init__.py"
    init.write_text(init.read_text().replace("API_VERSION_PLACEHOLDER", str(api_version)))
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist"), str(src)],
        check=True,
        capture_output=True,
    )
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True)
    wheel = next((tmp_path / "dist").glob("*.whl"))
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin" / "python"),
            str(REPO_ROOT),
            str(wheel),
        ],
        check=True,
        capture_output=True,
    )
    return venv / "bin" / "python"


def _probe(python: Path) -> dict:
    """Ask the installed amicus what it thinks of the installed third-party backend.

    The subprocess environment is reduced to an allowlist (no `PATH`, no `PYTHONPATH`, no
    ambient `VIRTUAL_ENV`) so the probe cannot silently satisfy its `import amicus` from this
    repo's own dev `.venv` or any other interpreter reachable on the ambient environment --
    only the throwaway venv built above, invoked by its absolute interpreter path, is on the
    table. That is the same defense `tests/test_packaging.py::_minimal_subprocess_path` uses
    for the same reason: an unguarded inherited environment can make a broken artifact look
    like it passed."""
    code = (
        "import json;"
        "from amicus.registry import BackendRegistry;"
        "r = BackendRegistry.load(('fakebackend',));"
        "print(json.dumps({'available': sorted(r.available), "
        "'unavailable': {k: v.reason for k, v in r.unavailable.items()}}))"
    )
    env = {"HOME": os.environ.get("HOME", "")}
    out = subprocess.run(
        [str(python), "-c", code], check=True, capture_output=True, text=True, env=env
    )
    return json.loads(out.stdout)


def test_a_wheel_declaring_the_entry_point_is_loaded(tmp_path):
    from amicus.plugin import PLUGIN_API_VERSION

    result = _probe(_build_and_install(tmp_path, PLUGIN_API_VERSION))
    assert result["available"] == ["fakebackend"]
    assert result["unavailable"] == {}


def test_a_wheel_with_a_wrong_api_version_is_rejected_by_reason(tmp_path):
    """The negative control: an empty scan and a rejection must not look the same."""
    from amicus.plugin import PLUGIN_API_VERSION

    result = _probe(_build_and_install(tmp_path, PLUGIN_API_VERSION + 1))
    assert result["available"] == []
    assert result["unavailable"] == {"fakebackend": "api_version"}
