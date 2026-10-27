#!/usr/bin/env python
"""Assert every GitHub Actions ``uses:`` reference is pinned to an immutable ref.

It also enforces the rest of AGENTS.md rules 14 and 15: an external SHA pin carries
its version in a trailing comment (``@<sha> # v4.2.2``), and no workflow is triggered
by ``pull_request_target``.

Every workflow ``uses:`` entry in this repo is pinned to a full commit SHA, but
nothing at the repo level *enforces* it (``allowed_actions: all`` and
``sha_pinning_required: false``), so a future workflow edit could reintroduce a
mutable tag (``@v4``) or branch (``@main``) reference unnoticed. This is the CI lint
half of that enforcement (the ``prek`` pre-commit hook is the local half).
This script scans the committed workflow YAML and fails if any reference is mutable,
any external SHA pin lacks a version comment, or any ``on:`` names
``pull_request_target``.

"Immutable" means:
    * a local action            -> ``./path`` (lives in this repo, no external ref)
    * an external action / reusable workflow -> ``owner/repo[/path]@<40-hex SHA>``
    * a Docker action           -> ``docker://image@sha256:<64-hex digest>``

Only the external SHA pin must carry the version comment: a local action has no
version, and a Docker digest is not the commit SHA rule 14 names.

Pure stdlib (no PyYAML): it matches ``uses:`` keys line by line — plain scalars
and single-line flow mappings (``- { uses: ... }``) — and avoids adding a parse
dependency to a CI gate. A ``uses:`` written as a block scalar (``uses: >-``) is
reported as a violation rather than parsed: the reference belongs inline.

Usage:
    uv run python scripts/check_github_actions_pinning.py [ROOT]

Exit codes:
    0  every ``uses:`` reference is immutably pinned and annotated, and no workflow
       uses ``pull_request_target``
    1  drift: at least one violation (a real blocker)
    2  nothing to scan (no .github/workflows/*.y[a]ml found) — verify nothing
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OK = "OK  "
FAIL = "FAIL"
WARN = "WARN"

# A ``uses:`` key, optionally as a YAML list item, capturing the rest of the line.
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(.+?)\s*$")
# A key opening a block scalar (``run: |``, ``run: >-``, ``script: |2-`` …). Lines
# indented deeper than such a key are literal content, not YAML keys, so a content
# line beginning ``uses:`` must NOT be treated as an action reference. The header may
# carry chomping (``+``/``-``) and indentation (digit) indicators in either order.
_BLOCK_SCALAR_RE = re.compile(r"^\s*(?:-\s*)?[^\s:#]+:\s*[|>][-+0-9]*\s*(?:#.*)?$")
# A ``uses:`` key inside a single-line flow mapping (``- { uses: x, with: {...} }``
# or ``steps: [{ uses: x }]``); the value ends at the next ``,`` or ``}``.
_FLOW_USES_RE = re.compile(r"\{[^}]*?\buses:\s*([^,}]+)")
# Sentinel reported for a ``uses:`` key that opens a block scalar: the script does not
# reassemble folded content, so the entry is classified as a violation instead.
BLOCK_SCALAR = "<block scalar>"
# A YAML inline comment: whitespace, then ``#``. A ``#`` glued to the value is part of it.
_COMMENT_RE = re.compile(r"\s#\s*(.*?)\s*$")
# A version annotation: the comment opens with a version, optionally after a hyphenated
# prefix (``v7.0.1``, ``1.14.3``, ``codeql-bundle-v2.25.6``).
_VERSION_COMMENT_RE = re.compile(r"^(?:[\w.-]*-)?v?\d+(?:\.\d+)*\b")
# The top-level ``on:`` key, bare or quoted, capturing whatever follows it on the line.
_ON_KEY_RE = re.compile(r"""^(?:on|"on"|'on')\s*:(.*)$""")
# Any other top-level mapping key, which ends the ``on:`` value. A column-0 ``- item``
# or a closing ``]``/``}`` still belongs to it.
_TOP_LEVEL_KEY_RE = re.compile(r"""^["']?[\w-]+["']?\s*:""")
# The event name as a whole token, not a prefix or suffix of a longer one.
_PRT_RE = re.compile(r"(?<![\w-])pull_request_target(?![\w-])")
# A full 40-char git commit SHA (case-insensitive; GitHub emits lowercase).
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
# A Docker image pinned by immutable digest: docker://image@sha256:<64 hex>.
_DOCKER_DIGEST_RE = re.compile(r"^docker://[^@]+@sha256:[0-9a-fA-F]{64}$")


def _clean_value(raw: str) -> str:
    """Strip an inline ``# comment`` and any surrounding quotes from a value."""
    # YAML inline comments require whitespace before the '#'.
    value = re.sub(r"\s+#.*$", "", raw).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _trailing_comment(line: str) -> str | None:
    """The text of the line's inline ``# comment``, or ``None`` if it has none."""
    match = _COMMENT_RE.search(line)
    return match.group(1) if match else None


def iter_uses(text: str) -> list[tuple[int, str, str | None]]:
    """Return ``(lineno, value, comment)`` for every ``uses:`` entry; lineno is 1-based.

    ``comment`` is the line's trailing comment text, ``None`` when there is none.

    Lines inside a ``run: |`` / ``run: >`` block scalar (more indented than the key
    that opened it) are skipped so a shell line starting ``uses:`` is not mistaken
    for an action reference.
    """
    found: list[tuple[int, str, str | None]] = []
    block_indent: int | None = None  # column of the key that opened a block scalar
    for lineno, line in enumerate(text.splitlines(), start=1):
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:
            if line.strip() == "" or indent > block_indent:
                continue  # blank line or still inside the block's content
            block_indent = None  # dedented back to the opener's level: block ended
        if line.lstrip().startswith("#"):
            continue
        if _BLOCK_SCALAR_RE.match(line):
            block_indent = indent
            if _USES_RE.match(line):
                found.append((lineno, BLOCK_SCALAR, None))
            continue
        match = _USES_RE.match(line) or _FLOW_USES_RE.search(line)
        if not match:
            continue
        value = _clean_value(match.group(1))
        if value:
            found.append((lineno, value, _trailing_comment(line)))
    return found


def classify(value: str) -> str | None:
    """Return ``None`` if ``value`` is immutably pinned, else a violation reason."""
    if value == BLOCK_SCALAR:
        return "uses: written as a block scalar is not checked; write the reference inline"
    if value.startswith("./"):
        return None
    if value.startswith("docker://"):
        if _DOCKER_DIGEST_RE.match(value):
            return None
        return "Docker action must be pinned by @sha256:<digest>, not a tag"
    _owner_repo, sep, ref = value.partition("@")
    if not sep:
        return "missing @<sha> ref"
    if _SHA_RE.match(ref):
        return None
    return f"ref '{ref}' is not a full 40-char commit SHA"


def version_comment_problem(value: str, comment: str | None) -> str | None:
    """Return ``None`` if ``value`` needs no version comment or has one, else a reason.

    Call it only on a value ``classify`` accepted; a mutable ref is reported there.
    """
    if value.startswith(("./", "docker://")):
        return None
    if comment is None:
        return "SHA pin has no trailing version comment (e.g. `# v4.2.2`)"
    if not _VERSION_COMMENT_RE.match(comment):
        return f"trailing comment {comment!r} does not open with a version"
    return None


def find_pull_request_target(text: str) -> list[int]:
    """Return the 1-based line of every ``pull_request_target`` in the top-level ``on:``.

    The ``on:`` value runs from its key to the next top-level key, so the scalar, flow
    and block forms (one line or several) are all covered. Comments are ignored, and so
    is the name anywhere outside ``on:``, such as in an ``if:`` expression.
    """
    found: list[int] = []
    inside = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        on_key = _ON_KEY_RE.match(line)
        if on_key:
            inside = True
            body = on_key.group(1)
        elif inside and _TOP_LEVEL_KEY_RE.match(line):
            inside = False
            continue
        elif inside:
            body = line
        else:
            continue
        body = re.sub(r"(?:^|\s)#.*$", "", body)
        if _PRT_RE.search(body):
            found.append(lineno)
    return found


def _workflow_files(root: Path) -> list[Path]:
    base = root / ".github" / "workflows"
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.suffix in {".yml", ".yaml"} and p.is_file())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path.cwd()

    files = _workflow_files(root)
    if not files:
        print(f"{WARN}: no .github/workflows/*.y[a]ml under {root} — nothing to verify.")
        return 2

    violations: list[str] = []
    for path in files:
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        for lineno, value, comment in iter_uses(text):
            reason = classify(value)
            if reason is None:
                reason = version_comment_problem(value, comment)
            if reason is not None:
                violations.append(f"{rel}:{lineno}: {value} — {reason}")
        for lineno in find_pull_request_target(text):
            violations.append(
                f"{rel}:{lineno}: pull_request_target — trigger forbidden (AGENTS.md rule 15)"
            )

    if violations:
        for v in violations:
            print(f"{FAIL}: {v}")
        print(f"\n{len(violations)} GitHub Actions policy violation(s) found.")
        return 1

    print(
        f"{OK}: all GitHub Actions references across {len(files)} workflow file(s) are pinned "
        "with a version comment, and none uses pull_request_target."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
