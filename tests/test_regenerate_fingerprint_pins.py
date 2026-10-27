"""`scripts/regenerate_fingerprint_pins.py` (#373): the refusal and the write/check logic.

Every test drives a temporary tree with an injected renderer; none runs the script against
this repository, so no test can regenerate a committed pin.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "regenerate_fingerprint_pins.py"
_spec = importlib.util.spec_from_file_location("regenerate_fingerprint_pins", _SCRIPT)
assert _spec is not None and _spec.loader is not None
regen = importlib.util.module_from_spec(_spec)
sys.modules["regenerate_fingerprint_pins"] = regen
_spec.loader.exec_module(regen)

_SOURCE_TEMPLATE = '"""fingerprint."""\n\nFINGERPRINT = "{fp}"\nRESULT_FORMAT: int = 9\n'


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _write_source(root: Path, fp: str) -> None:
    path = root / regen.FINGERPRINT_SOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SOURCE_TEMPLATE.format(fp=fp), encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A git repo whose `base` branch carries schema-7 and whose HEAD branches from it."""
    _git(tmp_path, "init", "-q", "-b", "base")
    _write_source(tmp_path, "amicus/0.1/schema-7")
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / regen.PINS).write_text("old pins\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "work")
    return tmp_path


def _render() -> dict[str, str]:
    return {regen.PINS: "new pins\n", regen.snapshot_path("all"): "snapshot\n"}


def _no_drift(root: Path) -> list[str]:
    return []


def _run(root: Path, *, check: bool) -> regen.Outcome:
    return regen.run(root, check=check, base_ref="base", render=_render, drift=_no_drift)


@pytest.mark.parametrize(
    ("current", "message"),
    [
        ("amicus/0.1/schema-7", "is unchanged from"),
        ("amicus/0.1/schema-6", "is lower than"),
        ("amicus/0.1/schema-07", "working tree FINGERPRINT is malformed"),
        ("amicus/0.1/schema-x", "working tree FINGERPRINT is malformed"),
        ("amicus/0.2/schema-8", "changes name or major"),
        ("other/0.1/schema-8", "changes name or major"),
    ],
)
def test_require_advance_refuses(current, message):
    with pytest.raises(regen.Refusal, match=message):
        regen.require_advance(current, "amicus/0.1/schema-7")


def test_require_advance_refuses_a_malformed_base():
    with pytest.raises(regen.Refusal, match="base FINGERPRINT is malformed"):
        regen.require_advance("amicus/0.1/schema-8", "amicus/0.1/schema")


@pytest.mark.parametrize("current", ["amicus/0.1/schema-8", "amicus/0.1/schema-70"])
def test_require_advance_accepts_a_higher_schema(current):
    regen.require_advance(current, "amicus/0.1/schema-7")


@pytest.mark.parametrize(
    "source",
    ["X = 1\n", 'FINGERPRINT = "a/0.1/schema-1"\nFINGERPRINT = "a/0.1/schema-2"\n'],
)
def test_fingerprint_literal_needs_exactly_one_assignment(source):
    with pytest.raises(regen.Refusal, match="assignments in here"):
        regen.fingerprint_literal(source, "here")


def test_base_fingerprint_reads_the_merge_base_not_the_base_tip(tree):
    _git(tree, "checkout", "-q", "base")
    _write_source(tree, "amicus/0.1/schema-9")
    _git(tree, "commit", "-q", "--no-verify", "-am", "base moves on")
    _git(tree, "checkout", "-q", "work")
    _sha, fp = regen.base_fingerprint(tree, "base")
    assert fp == "amicus/0.1/schema-7"


def test_an_unreadable_base_refuses(tree):
    with pytest.raises(regen.Refusal, match="merge-base HEAD no-such-ref"):
        regen.base_fingerprint(tree, "no-such-ref")


def test_a_base_without_the_source_file_refuses(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "base")
    (tmp_path / "README").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "base")
    with pytest.raises(regen.Refusal, match="git show"):
        regen.base_fingerprint(tmp_path, "base")


@pytest.mark.parametrize("fp", ["amicus/0.1/schema-7", "amicus/0.1/schema-6", "amicus/schema-8"])
def test_write_mode_refuses_without_an_advance_and_writes_nothing(tree, fp):
    _write_source(tree, fp)
    with pytest.raises(regen.Refusal):
        _run(tree, check=False)
    assert (tree / regen.PINS).read_text(encoding="utf-8") == "old pins\n"
    assert not (tree / regen.snapshot_path("all")).exists()


def test_write_mode_regenerates_every_stale_pin_after_a_bump(tree):
    _write_source(tree, "amicus/0.1/schema-8")
    outcome = _run(tree, check=False)
    assert outcome.code == regen.EXIT_OK
    assert (tree / regen.PINS).read_text(encoding="utf-8") == "new pins\n"
    assert (tree / regen.snapshot_path("all")).read_text(encoding="utf-8") == "snapshot\n"
    assert "amicus/0.1/schema-7 -> amicus/0.1/schema-8" in outcome.report
    assert "-old pins\n+new pins" in outcome.report
    assert "--- /dev/null" in outcome.report
    assert "regenerated: " in outcome.report
    # A rerun on the regenerated tree has nothing left to do.
    again = _run(tree, check=False)
    assert again.code == regen.EXIT_OK
    assert "every fingerprint pin is current" in again.report


def test_check_mode_reports_stale_pins_without_an_advance_and_writes_nothing(tree):
    outcome = _run(tree, check=True)
    assert outcome.code == regen.EXIT_STALE
    assert "stale: " in outcome.report and "-old pins\n+new pins" in outcome.report
    assert (tree / regen.PINS).read_text(encoding="utf-8") == "old pins\n"
    assert not (tree / regen.snapshot_path("all")).exists()


def test_check_mode_passes_when_every_pin_is_current(tree):
    for path, text in _render().items():
        (tree / path).write_text(text, encoding="utf-8")
    outcome = _run(tree, check=True)
    assert outcome.code == regen.EXIT_OK
    assert "every fingerprint pin is current" in outcome.report


def test_manual_drift_is_reported_and_never_changes_the_exit_code(tree):
    for path, text in _render().items():
        (tree / path).write_text(text, encoding="utf-8")
    outcome = regen.run(
        tree, check=True, base_ref="base", render=_render, drift=lambda root: ["it moved"]
    )
    assert outcome.code == regen.EXIT_OK
    assert "warning: it moved" in outcome.report


def test_committed_measured_reads_the_literal(tmp_path):
    path = tmp_path / regen.DISCOVERY_COST_TEST
    path.parent.mkdir(parents=True)
    path.write_text('X = 1\nMEASURED: dict[str, int] = {"all": 5}\n', encoding="utf-8")
    assert regen.committed_measured(tmp_path) == {"all": 5}
    path.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no MEASURED"):
        regen.committed_measured(tmp_path)


def test_committed_measured_reads_this_repositorys_test():
    """The parser finds the real discovery-cost literal, so its drift report can fire."""
    measured = regen.committed_measured(regen.REPO)
    assert set(measured) == {"all", "claude", "codex-kimi"}
    assert all(isinstance(v, int) and v > 0 for v in measured.values())


def test_render_covers_every_pin_a_bump_moves_and_agrees_with_the_tests():
    """Every profile snapshot, the pins file and the wire-shape snapshot, never the manual
    result-format snapshot; and on this tree, whose pins the other tests hold current, each
    rendering equals the committed file. That agreement is what makes the gate pass right
    after the script writes: a renderer that hashed differently from `manifest_hash` or
    `surface_digest` would fail here. Read-only: nothing is written."""
    from amicus import manifest

    rendered = regen.render_pins()
    assert set(rendered) == {regen.snapshot_path(p) for p in manifest.PROFILES} | {
        regen.PINS,
        regen.WIRE_SHAPE,
    }
    assert regen.RESULT_FORMAT_SNAPSHOT not in rendered
    for path, text in rendered.items():
        assert text == (regen.REPO / path).read_text(encoding="utf-8"), path
