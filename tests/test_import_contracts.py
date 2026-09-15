"""The import rules from the spec, enforced by import-linter inside the gate."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_import_linter_contracts_hold():
    exe = shutil.which("lint-imports")
    assert exe, "import-linter is a dev dependency; run under `uv run`"
    proc = subprocess.run([exe], cwd=ROOT, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Contracts: 5 kept, 0 broken" in proc.stdout


def _contracts() -> dict[str, dict]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {c["name"]: c for c in config["tool"]["importlinter"]["contracts"]}


def test_the_sdk_contract_forbids_every_other_top_level_module():
    """A new top-level module is forbidden to the sdk the day it lands, not when someone
    remembers to extend the list."""
    package = ROOT / "src" / "amicus"
    top = {
        f"amicus.{p.stem}"
        for p in package.iterdir()
        if (p.suffix == ".py" and p.stem != "__init__")
        or (p.is_dir() and (p / "__init__.py").exists())
    } - {"amicus.sdk"}
    forbidden = set(_contracts()["the sdk never imports the rest of amicus"]["forbidden_modules"])
    assert forbidden == top


def test_sdk_core_stays_a_leaf_layer():
    contract = _contracts()["sdk core is a leaf layer"]
    assert contract["source_modules"] == ["amicus.sdk.core"]
    assert set(contract["forbidden_modules"]) == {
        "amicus.sdk.backend",
        "amicus.sdk.conventions",
        "amicus.sdk.testing",
    }
