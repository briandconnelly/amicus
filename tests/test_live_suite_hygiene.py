"""A spend-free guard on every live suite's text: a failing live assertion must never print the
model's prose. The live suites are `-m integration`, so this pin lives outside them and runs in
the ordinary gate.

It covers all three backends, discovered rather than listed, because
`scripts/record_live_gate_evidence.py` now persists a failed suite's per-test outcome: a suite
that prints prose on failure would leak it into `.release-evidence/`, not only into a terminal.

The guard reads the ASTs, not the lines. A lexical version of this file (up to 2026-09-09) was
defeated by every ordinary refactor tried against it — a `ruff format` wrap of a long assert onto
two lines, an f-string message, a helper call, `pytest.fail`, `raise AssertionError`, and a
trailing comment after the message, which is how `body["meta"]` had been sitting in the claude
suite unnoticed. `test_the_guard_catches_every_known_bypass` keeps each of those as a control.

The rule: an assertion message (and the argument of a failure helper) may reference `body` only
in one of the exact forms in `SAFE_BODY_MESSAGES`. A message that never mentions `body` is fine —
`len(names)`, `sorted(write_tools)`, a local already narrowed to an enum.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).parent

# Every backend's live suite, found by name so a fourth backend is covered the day it lands
# rather than the day someone remembers this file.
LIVE_SUITES = sorted(TESTS_DIR.glob("test_*_live.py"))

# The suites that must exist; a rename that silently drops one from the glob is the failure this
# pins, because an empty glob would otherwise pass as a clean result.
REQUIRED_SUITES = ("test_claude_live.py", "test_codex_live.py", "test_kimi_live.py")

# Body-rooted messages that carry no model text. Compared as `ast.unparse` output, so formatting
# and quote style cannot smuggle anything past: an error's `code` is a fixed enum, unlike the
# `message` beside it.
SAFE_BODY_MESSAGES = frozenset(
    {
        "body.get('error', {}).get('code')",
        "body.get('error', {}).get('code', None)",
        # The claude suite's own reducer. Safe only for as long as it stays a reducer, which
        # `test_the_shape_helper_exposes_no_prose` is what holds.
        "_shape(body)",
    }
)

# What `_shape` in tests/test_claude_live.py may expose: list lengths and enums. `summary`,
# `raw_response` and `answer` are the fields that would turn it into a leak, and allowlisting
# `_shape(body)` above is only defensible while this holds.
SHAPE_KEYS_ALLOWED = frozenset(
    {"findings", "questions", "next_steps", "verdict", "confidence", "review_status"}
)

# Raising one of these with a model-derived argument is the same leak as an assert message.
FAILURE_HELPERS = frozenset({"pytest.fail", "AssertionError"})


def _references_body(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "body" for n in ast.walk(node))


def _is_unsafe(node: ast.AST | None) -> bool:
    """A message is unsafe when it reaches into `body` in any form but an allowlisted one."""
    if node is None:
        return False
    return _references_body(node) and ast.unparse(node) not in SAFE_BODY_MESSAGES


def offenders_in(source: str, label: str = "<source>") -> list[tuple[str, int, str]]:
    """Every assertion message or failure-helper argument that could print model prose."""
    found: list[tuple[str, int, str]] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and _is_unsafe(node.msg):
            assert node.msg is not None  # narrowed by _is_unsafe
            found.append((label, node.lineno, ast.unparse(node.msg)))
        elif isinstance(node, ast.Call) and ast.unparse(node.func) in FAILURE_HELPERS:
            for arg in node.args:
                if _is_unsafe(arg):
                    found.append((label, node.lineno, ast.unparse(arg)))
    return found


# Each one defeated the lexical guard this replaced; they are controls, not illustrations.
KNOWN_BYPASSES = {
    "multiline wrap": 'assert cond, (\n    body["summary"]\n)',
    "f-string message": "assert cond, f\"got {body['summary']}\"",
    "nested in a call": 'assert cond, str(body["summary"])',
    "whole envelope": "assert cond, body",
    "error object": 'assert cond, body.get("error")',
    "trailing comment": 'assert cond, body["meta"]  # a real run really spent',
    "pytest.fail": 'pytest.fail(body["summary"])',
    "raise AssertionError": 'raise AssertionError(body["summary"])',
    "tuple message": 'assert cond, (body["summary"], 1)',
}

KNOWN_SAFE = {
    "error code": 'assert body["ok"] is True, body.get("error", {}).get("code")',
    "a count": "assert read_tools, len(names)",
    "a narrowed set": "assert not write_tools, sorted(write_tools)",
    "a local enum": 'assert code == "invalid_model", code',
    "no message": 'assert body["ok"] is True',
    "literal message": 'assert body["ok"] is True, "the call failed"',
}


def test_the_guard_catches_every_known_bypass():
    """The instrument, proven on positives before any negative result is trusted."""
    missed = [name for name, src in KNOWN_BYPASSES.items() if not offenders_in(src)]
    assert missed == [], missed


def test_the_guard_permits_every_safe_form():
    """A guard that also rejected the fixes would leave an offender no way out."""
    flagged = [name for name, src in KNOWN_SAFE.items() if offenders_in(src)]
    assert flagged == [], flagged


def test_the_shape_helper_exposes_no_prose():
    """`_shape(body)` is allowlisted as an assertion message, so its key list is load-bearing.

    Read `_SHAPE_KEYS` out of the suite's AST rather than importing it: the module is
    `-m integration` and importing it here would drag in the live fixtures.
    """
    suite = TESTS_DIR / "test_claude_live.py"
    tree = ast.parse(suite.read_text())
    assigned = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_SHAPE_KEYS" for t in node.targets)
    ]
    assert len(assigned) == 1, "expected exactly one _SHAPE_KEYS assignment"
    keys = set(ast.literal_eval(assigned[0].value))
    assert keys, "the key list was read as empty; the AST lookup is broken"
    assert keys <= SHAPE_KEYS_ALLOWED, sorted(keys - SHAPE_KEYS_ALLOWED)


def test_the_guard_covers_every_live_suite():
    """The glob is the instrument; prove it actually found each backend's suite."""
    found = {path.name for path in LIVE_SUITES}
    missing = [name for name in REQUIRED_SUITES if name not in found]
    assert missing == [], missing


def test_no_live_suite_prints_model_prose_on_failure():
    offenders: list[tuple[str, int, str]] = []
    for suite in LIVE_SUITES:
        source = suite.read_text()
        assert "assert " in source, f"{suite.name} has no assertions; the file was not read"
        offenders.extend(offenders_in(source, suite.name))
    assert offenders == [], offenders
