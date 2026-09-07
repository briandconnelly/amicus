"""A spend-free guard on the live suite's text: a failing live assertion must never print the
model's prose. `tests/test_claude_live.py` is `-m integration`, so this pin lives outside it and
runs in the ordinary gate."""

from __future__ import annotations

import re
from pathlib import Path

LIVE_SUITE = Path(__file__).with_name("test_claude_live.py")

# An assert whose message is the whole envelope (or one of its string fields) carries model
# prose — summary, findings, the raw answer — straight into the pytest report.
PROSE_MESSAGE = re.compile(r"^\s*assert .*, body(\[.*\])?\s*$")

# The forms the reviewer named, matched as plain text on assert lines so a reformat cannot hide
# them. Only assert lines: reading `body["summary"]` to parse an answer is exactly what the
# toolless test must do; printing it on failure is the thing being banned.
FORBIDDEN_SUBSTRINGS = (", body)", ', body["summary"]', 'body["raw_response"]')

# A known-bad line, so a broken regex cannot pass as a clean result.
KNOWN_BAD = '    assert body["findings"] or body["next_steps"], body'


def test_the_regex_can_fail():
    """Both instruments, proven on positives before their negative results are trusted."""
    assert PROSE_MESSAGE.match(KNOWN_BAD)
    assert PROSE_MESSAGE.match('    assert not names & {"bash"}, body["summary"]')
    samples = {
        ", body)": "    assert ok, body)",
        ', body["summary"]': '    assert ok, body["summary"]',
        'body["raw_response"]': '    assert ok, body["raw_response"]',
    }
    assert set(samples) == set(FORBIDDEN_SUBSTRINGS)
    for bad, sample in samples.items():
        assert bad in sample and sample.strip().startswith("assert ")


def test_the_live_suite_never_prints_model_prose_on_failure():
    lines = LIVE_SUITE.read_text().splitlines()
    offenders = [(n, line) for n, line in enumerate(lines, 1) if PROSE_MESSAGE.match(line)]
    assert offenders == [], offenders
    asserts = [(n, line) for n, line in enumerate(lines, 1) if line.strip().startswith("assert ")]
    assert asserts, "the live suite has no assertions; the file was not read"
    for bad in FORBIDDEN_SUBSTRINGS:
        hits = [n for n, line in asserts if bad in line]
        assert hits == [], (bad, hits)
