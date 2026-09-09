"""A spend-free guard on every live suite's text: a failing live assertion must never print the
model's prose. The live suites are `-m integration`, so this pin lives outside them and runs in
the ordinary gate.

It covers all three backends, discovered rather than listed: `scripts/record_live_gate_evidence.py`
persists a failed suite's per-test outcome, so a suite that prints prose on failure would leak into
a file, not only into a terminal. The guard was Claude-only until 2026-09-09, and the codex and
kimi suites had drifted past it."""

from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).parent

# Every backend's live suite, found by name so a fourth backend is covered the day it lands
# rather than the day someone remembers this file.
LIVE_SUITES = sorted(TESTS_DIR.glob("test_*_live.py"))

# The suites that must exist; a rename that silently drops one from the glob is the failure this
# pins, because an empty glob would otherwise pass as a clean result.
REQUIRED_SUITES = ("test_claude_live.py", "test_codex_live.py", "test_kimi_live.py")

# An assert whose message is the whole envelope (or one of its string fields) carries model
# prose — summary, findings, the raw answer — straight into the pytest report.
PROSE_MESSAGE = re.compile(r"^\s*assert .*, body(\[.*\])?\s*$")

# The forms the reviewer named, matched as plain text on assert lines so a reformat cannot hide
# them. Only assert lines: reading `body["summary"]` to parse an answer is exactly what the
# toolless test must do; printing it on failure is the thing being banned.
#
# `body.get("error")` and `body["error"]` are here because an error object carries the backend's
# own message text; the safe form is the code alone, `body.get("error", {}).get("code")`.
FORBIDDEN_SUBSTRINGS = (
    ", body)",
    ', body["summary"]',
    'body["raw_response"]',
    ', body.get("error")',
    ', body["error"]',
)

# A known-bad line, so a broken regex cannot pass as a clean result.
KNOWN_BAD = '    assert body["findings"] or body["next_steps"], body'

# The replacement every offender takes: the error's code enum, never its message.
KNOWN_GOOD = '    assert body["ok"] is True, body.get("error", {}).get("code")'


def test_the_regex_can_fail():
    """Both instruments, proven on positives before their negative results are trusted."""
    assert PROSE_MESSAGE.match(KNOWN_BAD)
    assert PROSE_MESSAGE.match('    assert not names & {"bash"}, body["summary"]')
    samples = {
        ", body)": "    assert ok, body)",
        ', body["summary"]': '    assert ok, body["summary"]',
        'body["raw_response"]': '    assert ok, body["raw_response"]',
        ', body.get("error")': '    assert body["ok"] is True, body.get("error")',
        ', body["error"]': '    assert body["ok"] is True, body["error"]',
    }
    assert set(samples) == set(FORBIDDEN_SUBSTRINGS)
    for bad, sample in samples.items():
        assert bad in sample and sample.strip().startswith("assert ")


def test_the_safe_form_is_not_flagged():
    """A guard that also rejects the fix would leave an offender no way out."""
    assert not PROSE_MESSAGE.match(KNOWN_GOOD)
    assert not [bad for bad in FORBIDDEN_SUBSTRINGS if bad in KNOWN_GOOD]


def test_the_guard_covers_every_live_suite():
    """The glob is the instrument; prove it actually found each backend's suite."""
    found = {path.name for path in LIVE_SUITES}
    missing = [name for name in REQUIRED_SUITES if name not in found]
    assert missing == [], missing


def test_no_live_suite_prints_model_prose_on_failure():
    offenders: list[tuple[str, int, str]] = []
    for suite in LIVE_SUITES:
        lines = suite.read_text().splitlines()
        asserts = [
            (n, line) for n, line in enumerate(lines, 1) if line.strip().startswith("assert ")
        ]
        assert asserts, f"{suite.name} has no assertions; the file was not read"
        offenders.extend(
            (suite.name, n, line.strip())
            for n, line in enumerate(lines, 1)
            if PROSE_MESSAGE.match(line)
        )
        for bad in FORBIDDEN_SUBSTRINGS:
            offenders.extend((suite.name, n, bad) for n, line in asserts if bad in line)
    assert offenders == [], offenders
