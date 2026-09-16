"""M8's structural guards: pontonier's code lives in amicus.sdk, and nothing reaches the old
package. Each scan has a planted-positive control, so an empty result is evidence rather than
a broken scan."""

from __future__ import annotations

import ast
import subprocess
import sys
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


_BLOCK_PONTONIER = "import sys\nsys.modules['pontonier'] = None\n"


def _run_blocked(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_PONTONIER + code],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


def _walk_amicus_code() -> str:
    return (
        "import importlib, pkgutil\n"
        "import amicus\n"
        "\n"
        "def _fail(name):\n"
        "    raise ImportError(name)\n"
        "\n"
        "names = [m.name for m in\n"
        "         pkgutil.walk_packages(amicus.__path__, 'amicus.', onerror=_fail)]\n"
        "for name in names:\n"
        "    importlib.import_module(name)\n"
        "print(len(names))\n"
    )


def test_every_amicus_module_imports_with_pontonier_blocked():
    """amicus runs without pontonier: every module imports with pontonier made unimportable,
    whether or not an older environment still has the distribution installed (`uv run`
    syncs inexactly, so an upgraded checkout can keep it)."""
    proc = _run_blocked(_walk_amicus_code())
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip()) > 50  # the walk really found the package tree


def test_the_pontonier_block_bites():
    """Control for the test above: under the same block, importing pontonier fails."""
    proc = _run_blocked("import pontonier.core\n")
    assert proc.returncode != 0
    assert "ModuleNotFoundError" in proc.stderr or "ImportError" in proc.stderr


def test_the_sdk_core_modules_log_under_amicus_sdk():
    """ADR 0029: 'the SDK's modules log on amicus.sdk.*.' Pin the actual logger names,
    not just the claim: each module's module-level `logger` must be named after its own
    `__name__`, and every one of those names must start with `amicus.sdk.`."""
    from amicus.sdk.core import idempotency, jobs, runtime

    for module in (jobs, runtime, idempotency):
        assert module.logger.name == module.__name__
        assert module.logger.name.startswith("amicus.sdk.")


def test_the_sdk_root_names_its_origin_and_has_no_version_lookup():
    """R4: the package root cites the tag's commit instead of asking the pontonier
    distribution for a version it no longer has."""
    assert not hasattr(amicus.sdk, "__version__")
    assert "185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d" in (amicus.sdk.__doc__ or "")


# The only lines under src/ that may name pontonier after M8 (spec §1, R5): the origin note in
# the sdk's package root and a link into pontonier's repository. #123 renamed the four defaults
# that used to be exempt, so no value under src/ carries a pontonier literal any more.
def _unexplained_pontonier_lines(src: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        if rel == "amicus/sdk/__init__.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "pontonier" not in line.lower():
                continue
            if "briandconnelly/pontonier" in line:
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


def test_no_pontonier_named_value_reaches_the_filesystem():
    """#123's end state, pinned as behaviour rather than as an absent grep hit. The worktree
    prefix and the baseline identity were already amicus's, overridden at the isolation seam;
    the empty-hooks temp dir was the one pontonier-named value that actually reached disk."""
    from amicus.orchestration import isolation, worktree

    assert worktree.WORKTREE_PREFIX == "amicus-wt-"
    assert (worktree.DEFAULT_CONFIG.identity_name, worktree.DEFAULT_CONFIG.identity_email) == (
        "amicus",
        "amicus@local",
    )
    assert Path(worktree._empty_hooks_dir()).name.startswith("amicus-nohooks-")
    # isolation no longer overrides: it reads the module's own defaults.
    assert isolation.WORKTREE_PREFIX == worktree.WORKTREE_PREFIX
    assert isolation.WORKTREE_CONFIG is worktree.DEFAULT_CONFIG
