"""M8's structural guards: pontonier's code lives in amicus.sdk, and nothing reaches the old
package. Each scan has a planted-positive control, so an empty result is evidence rather than
a broken scan."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import amicus.sdk

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


def test_pontonier_is_not_installed():
    """amicus runs without the pontonier distribution: nothing requires it any more, and
    `uv sync` removes what nothing requires."""
    assert importlib.util.find_spec("pontonier") is None


def test_the_sdk_root_names_its_origin_and_has_no_version_lookup():
    """R4: the package root cites the tag's commit instead of asking the pontonier
    distribution for a version it no longer has."""
    assert not hasattr(amicus.sdk, "__version__")
    assert "185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d" in (amicus.sdk.__doc__ or "")


# The only lines under src/ that may name pontonier after M8 (spec §1, R5): the origin note in
# the sdk's package root, a link into pontonier's repository, and the four defaults that keep
# their literal until a follow-up renames them.
_PONTONIER_DEFAULTS = frozenset(
    {
        'WORKTREE_PREFIX = "pontonier-worktree-"',
        'identity_name: str = "pontonier"',
        'identity_email: str = "pontonier@local"',
        'return tempfile.mkdtemp(prefix="pontonier-nohooks-")',
    }
)


def _unexplained_pontonier_lines(src: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        if rel == "amicus/sdk/__init__.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "pontonier" not in line.lower():
                continue
            if "briandconnelly/pontonier" in line or line.strip() in _PONTONIER_DEFAULTS:
                continue
            hits.append(f"{rel}:{n}")
    return hits


def test_src_names_pontonier_only_as_provenance_or_a_kept_default():
    assert _unexplained_pontonier_lines(ROOT / "src") == []


def test_the_prose_scan_detects_a_planted_mention(tmp_path):
    planted = tmp_path / "amicus" / "x.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        '"""Built on Pontonier."""\nURL = "https://github.com/briandconnelly/pontonier"\n',
        encoding="utf-8",
    )
    assert _unexplained_pontonier_lines(tmp_path) == ["amicus/x.py:1"]
