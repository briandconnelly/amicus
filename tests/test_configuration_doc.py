"""docs/CONFIGURATION.md is rendered from the env declarations; the committed file must
match the rendering (#310), the way MIGRATION.md's table is held to the same declarations."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_configuration_doc.py"
DOC = ROOT / "docs" / "CONFIGURATION.md"


def test_configuration_doc_matches_the_declarations():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, (
        f"{proc.stdout}{proc.stderr}\nrun `uv run python scripts/render_configuration_doc.py "
        "--write` and commit docs/CONFIGURATION.md"
    )


def test_every_declared_var_has_a_section():
    from amicus import packaging

    text = DOC.read_text(encoding="utf-8")
    for var in packaging.declared_vars():
        assert f"### `{var.name}`" in text, var.name
