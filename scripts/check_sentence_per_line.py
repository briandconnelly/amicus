#!/usr/bin/env python
"""Assert every Markdown line under ``docs/`` holds at most one sentence.

AGENTS.md rule 16 says prose under ``docs/`` is written one sentence per line, so a
one-word edit shows as a one-line diff rather than a reflowed paragraph. Nothing
else enforces it: ``tests/test_check_sentence_per_line.py`` runs this script over
the committed tree, which puts it in the rule-2 gate, and ``prek`` runs it on
commit as the local half.

It checks the direction that degrades a diff: two sentences sharing a line. A
sentence wrapped across several lines is not reported.

A sentence here is what grammar calls one, so ``A; B`` and ``A: B`` are a single
sentence. A sentence ends at ``.``, ``?`` or ``!`` followed by whitespace and a
character that can open the next one (a capital, a code span, a link, emphasis or
an opening bracket or quote); an ellipsis and a short list of abbreviations do
not end one.

Not prose, so never checked: fenced code blocks, HTML comments (only the comment,
so prose beside one on the same line is still checked), YAML front matter,
tables (from the header row above a delimiter row to the next blank line, with or
without leading pipes), link reference definitions and blockquotes, which in this
repository carry captured output verbatim. On a checked line, inline code spans,
link targets, URLs and double-quoted text are masked before segmenting, and a
leading heading marker, list marker or bold run-in label (``**Label.**``) is
not counted as a sentence. A quotation keeps a terminator it closes on, because
that terminator can end the enclosing sentence too.

Pure stdlib, line by line, in the style of the other ``scripts/check_*.py``.

Usage:
    uv run python scripts/check_sentence_per_line.py [ROOT]

Exit codes:
    0  every checked line under ROOT/docs holds at most one sentence
    1  at least one line holds two or more sentences
    2  nothing to scan (no docs/**/*.md under ROOT) — verify nothing
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OK = "OK  "
FAIL = "FAIL"
WARN = "WARN"

# An opening or closing code fence: three or more backticks or tildes, at any
# indentation so a fence nested in a list item is recognised too.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# An inline code span: a run of N backticks closed by a run of exactly N.
_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# An inline link or image target, with an optional title: ``](target "title")``.
_LINK_TARGET_RE = re.compile(r"\]\([^)\s]*(?:\s+\"[^\"]*\")?\)")
# A bare or angle-bracketed URL; a trailing sentence terminator is not part of it.
_URL_RE = re.compile(r"<?https?://[^\s<>]*[^\s<>.,;:!?)]>?")
# Double-quoted text, straight or curly: a quotation is reproduced as written.
_QUOTE_RE = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d")
# Prefixes that are structure, not a sentence: a heading marker, a list marker, a
# task-list box, or a bold run-in label ending in ``.``, ``:`` or ``?``.
_PREFIX_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|\[[ xX]\]\s+|(\*\*|__)[^*_]+?[.:?]\1\s+)"
)
# A table's delimiter row, with or without leading and trailing pipes:
# ``| --- | :-: |`` or ``--- | ---``. A row with no pipe is a thematic break.
_DELIMITER_ROW_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
# A link reference or footnote definition: ``[label]: target``.
_REFERENCE_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s")
# A sentence boundary: the offset where its match ends is where the next one begins.
_BOUNDARY_RE = re.compile(
    r"(?<![.\u2026])[.?!](?!\.)"  # the terminator, not part of an ellipsis
    r"[)\]\"'\u2019\u201d*_]*"  # closing brackets, quotes or emphasis
    r"\s+(?=[A-Z`\[(*_\"\u201c])"  # whitespace, then what opens a sentence
)
# Abbreviations whose trailing period does not end a sentence (case-insensitive).
ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "vs", "cf", "al", "approx"})
_WORD_BEFORE_RE = re.compile(r"([A-Za-z.]+)$")


def _fill(match: re.Match[str]) -> str:
    """Stand in for a masked span at its own length, so offsets survive masking.

    It opens with a capital, so a masked code span can still open a sentence, and
    holds no punctuation, so nothing inside it can end one.
    """
    return "X" + "x" * (len(match.group(0)) - 1)


def _fill_quote(match: re.Match[str]) -> str:
    """Mask a quotation but keep a terminator it closes on: ``"Done." Then`` ends one."""
    quote = match.group(0)
    if len(quote) >= 3 and quote[-2] in ".?!":
        return "X" + "x" * (len(quote) - 3) + quote[-2:]
    return _fill(match)


def _hide_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Blank every HTML comment span in ``line``, carrying an open comment across lines.

    Returns the line with comment text replaced by spaces, so what is left is the
    visible prose at its own offsets, and whether a comment is still open at its end.
    """
    out: list[str] = []
    pos = 0
    while pos < len(line):
        if in_comment:
            end = line.find("-->", pos)
            if end < 0:
                out.append(" " * (len(line) - pos))
                break
            out.append(" " * (end + 3 - pos))
            pos, in_comment = end + 3, False
        else:
            start = line.find("<!--", pos)
            if start < 0:
                out.append(line[pos:])
                break
            out.append(line[pos:start] + " " * 4)
            pos, in_comment = start + 4, True
    return "".join(out), in_comment


def _mask(line: str) -> str:
    """Blank out spans whose punctuation is not sentence punctuation."""
    line = _CODE_SPAN_RE.sub(_fill, line)
    while prefix := _PREFIX_RE.match(line):  # each pass blanks at least one character
        line = " " * prefix.end() + line[prefix.end() :]
    line = _LINK_TARGET_RE.sub(lambda m: "]" + "x" * (len(m.group(0)) - 1), line)
    line = _URL_RE.sub(_fill, line)
    return _QUOTE_RE.sub(_fill_quote, line)


def sentence_breaks(line: str) -> list[int]:
    """Return the offset in ``line`` at which each sentence after the first begins."""
    masked = _mask(line)
    breaks: list[int] = []
    for match in _BOUNDARY_RE.finditer(masked):
        if masked[match.start()] == ".":
            word = _WORD_BEFORE_RE.search(masked[: match.start()])
            if word and word.group(1).lower().lstrip(".") in ABBREVIATIONS:
                continue
        breaks.append(match.end())
    return breaks


def iter_violations(text: str) -> list[tuple[int, str]]:
    """Return ``(lineno, line)`` for every prose line holding two or more sentences."""
    found: list[tuple[int, str]] = []
    lines = text.splitlines()
    fence: str | None = None  # the fence run that opened the current code block
    in_comment = False
    in_table = False
    in_front_matter = bool(lines) and lines[0].strip() == "---"
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if in_front_matter:
            if lineno > 1 and stripped == "---":
                in_front_matter = False
            continue
        if fence is not None:
            closing = _FENCE_RE.match(line)
            if (
                closing
                and closing.group(1)[0] == fence[0]
                and len(closing.group(1)) >= len(fence)
                and stripped == closing.group(1)
            ):
                fence = None
            continue
        visible, in_comment = _hide_comments(line, in_comment)
        if in_table:
            in_table = bool(visible.strip())
            continue
        opening = _FENCE_RE.match(visible)
        if opening:
            fence = opening.group(1)
            continue
        following = lines[lineno] if lineno < len(lines) else ""
        if "|" in visible and "|" in following and _DELIMITER_ROW_RE.match(following):
            in_table = True
            continue
        if visible.lstrip().startswith(("|", ">")) or _REFERENCE_DEF_RE.match(visible):
            continue
        if sentence_breaks(visible):
            found.append((lineno, line))
    return found


def _doc_files(root: Path) -> list[Path]:
    base = root / "docs"
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path.cwd()

    files = _doc_files(root)
    if not files:
        print(f"{WARN}: no docs/**/*.md under {root} — nothing to verify.")
        return 2

    violations: list[str] = []
    for path in files:
        rel = path.relative_to(root)
        for lineno, line in iter_violations(path.read_text(encoding="utf-8")):
            violations.append(f"{rel}:{lineno}: {line.strip()}")

    if violations:
        for v in violations:
            print(f"{FAIL}: {v}")
        print(f"\n{len(violations)} line(s) under docs/ hold two or more sentences (rule 16).")
        return 1

    print(
        f"{OK}: every line across {len(files)} docs/ Markdown file(s) holds at most one sentence."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
