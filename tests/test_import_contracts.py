"""The import rules from the spec, enforced by import-linter inside the gate."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_import_linter_contracts_hold():
    exe = shutil.which("lint-imports")
    assert exe, "import-linter is a dev dependency; run under `uv run`"
    proc = subprocess.run([exe], cwd=ROOT, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Contracts: 3 kept, 0 broken" in proc.stdout
