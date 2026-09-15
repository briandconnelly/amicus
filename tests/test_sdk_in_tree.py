"""M8's structural guards: pontonier's code lives in amicus.sdk, and nothing reaches the old
package. Each scan has a planted-positive control, so an empty result is evidence rather than
a broken scan."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# scripts/ is exempt: the differential capture scripts run inside a sibling's virtualenv and
# feed that sibling's own pontonier objects (M8 spec, change 5).
SCANNED = ("src", "tests")


def _pontonier_imports(root: Path) -> list[str]:
    hits: list[str] = []
    for base in SCANNED:
        for path in sorted((root / base).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                if any(n == "pontonier" or n.startswith("pontonier.") for n in names):
                    hits.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    return sorted(hits)


def test_nothing_under_src_or_tests_imports_pontonier():
    assert _pontonier_imports(ROOT) == []


def test_the_import_scan_detects_a_planted_import(tmp_path):
    planted = tmp_path / "src" / "planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("from pontonier.core import runtime\nimport pontonier\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    assert _pontonier_imports(tmp_path) == ["src/planted.py:1", "src/planted.py:2"]
