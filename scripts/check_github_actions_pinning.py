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
Comments are found quote-aware, so a ``#`` inside a quoted scalar is not one.

The trigger check reads only the event names at the first level of the root ``on:``
(its scalar, its sequence items or its mapping keys), so an event's own
configuration (``paths:``, an input's description) never matches. It fails closed
the same way: a workflow with no root ``on:`` key, or an event name it cannot read
(an alias, a complex key, a nested collection, an escape JSON does not share), is a
violation rather than a pass.

Usage:
    uv run python scripts/check_github_actions_pinning.py [ROOT]

Exit codes:
    0  every ``uses:`` reference is immutably pinned and annotated, and no workflow
       uses ``pull_request_target``
    1  drift: at least one violation (a real blocker)
    2  nothing to scan (no .github/workflows/*.y[a]ml found) — verify nothing
"""

from __future__ import annotations

import json
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
# A version annotation: the comment opens with a version, optionally after a hyphenated
# prefix (``v7.0.1``, ``1.14.3``, ``codeql-bundle-v2.25.6``).
_VERSION_COMMENT_RE = re.compile(r"^(?:[\w.-]*-)?v?\d+(?:\.\d+)*\b")
# The root ``on:`` key, bare or quoted, capturing whatever follows it on the line.
_ON_KEY_RE = re.compile(r"""^(?:on|"on"|'on')\s*:(?:\s+(.*)|$)""")
# A block mapping key at the start of a line: a quoted or plain key, then ``:`` that
# ends the line or is followed by whitespace.
_KEY_RE = re.compile(
    r"""^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s"'?\-\[\]{}#&*!|>][^:]*?)\s*:(?:\s|$)"""
)
# A leading YAML tag (``!!str``) or anchor (``&a``), which does not change the name.
_DECORATION_RE = re.compile(r"^(?:[!&]\S*\s+)+")
# Reasons ``trigger_problems`` reports; the tests compare against these.
PRT_FORBIDDEN = "pull_request_target trigger is forbidden (AGENTS.md rule 15)"
NO_ON = "no root `on:` key found; write the triggers as a block `on:` so they can be checked"
UNREADABLE = "trigger written in a form this check cannot read"
# A full 40-char git commit SHA (case-insensitive; GitHub emits lowercase).
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
# A Docker image pinned by immutable digest: docker://image@sha256:<64 hex>.
_DOCKER_DIGEST_RE = re.compile(r"^docker://[^@]+@sha256:[0-9a-fA-F]{64}$")


def _split_comment(line: str) -> tuple[str, str | None]:
    """Split ``line`` into its content and its inline comment text (``None`` if none).

    A comment opens at a ``#`` that starts the line or follows whitespace, outside any
    quoted scalar; a quote opens a scalar only where a token can start.
    """
    quote: str | None = None
    i = 0
    while i < len(line):
        char = line[i]
        if quote == '"':
            if char == "\\":
                i += 2
                continue
            if char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                if line[i + 1 : i + 2] == "'":
                    i += 2
                    continue
                quote = None
        elif char in "\"'" and (i == 0 or line[i - 1] in " \t[{,:"):
            quote = char
        elif char == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip(), line[i + 1 :].strip()
        i += 1
    return line.rstrip(), None


def _clean_value(raw: str) -> str:
    """Strip any surrounding quotes from a comment-free value."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


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
        content, comment = _split_comment(line)
        match = _USES_RE.match(content) or _FLOW_USES_RE.search(content)
        if not match:
            continue
        value = _clean_value(match.group(1))
        if value:
            found.append((lineno, value, comment))
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


def _scalar(token: str) -> str | None:
    """The name a scalar token spells, or ``None`` if this check cannot read it."""
    token = _DECORATION_RE.sub("", token.strip())
    if not token or token[0] in "*?|>[{":
        return None
    if token[0] == '"':
        try:
            value = json.loads(token)
        except ValueError:
            return None
        return value if isinstance(value, str) else None
    if token[0] == "'":
        if len(token) < 2 or token[-1] != "'":
            return None
        return token[1:-1].replace("''", "'")
    return token


def _flow_items(flow: str) -> list[str] | None:
    """Split one flow collection's top-level items, or ``None`` if it is unbalanced."""
    items: list[str] = []
    depth = 0
    quote: str | None = None
    start = 1
    escaped = False
    for i, char in enumerate(flow):
        if escaped:
            escaped = False
        elif quote:
            if quote == '"' and char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'" and flow[:i].rstrip()[-1:] in ("", "[", "{", ",", ":"):
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                items.append(flow[start:i])
                return (
                    [item.strip() for item in items if item.strip()]
                    if not flow[i + 1 :].strip()
                    else None
                )
        elif char == "," and depth == 1:
            items.append(flow[start:i])
            start = i + 1
    return None


def _flow_events(flow: str) -> list[str | None] | None:
    """The event names a flow ``on:`` value spells (``None`` for an unreadable one)."""
    items = _flow_items(flow)
    if items is None:
        return None
    if flow.startswith("["):
        return [_scalar(item) for item in items]
    keys: list[str | None] = []
    for item in items:
        key = _KEY_RE.match(item + " ")
        keys.append(_scalar(key.group(1)) if key else None)
    return keys


def trigger_problems(text: str) -> list[tuple[int, str]]:
    """Return ``(lineno, reason)`` for every trigger problem; lineno is 1-based.

    Reads each root ``on:`` key's first level only: its scalar, its flow collection's
    items or keys, or its block sequence items or mapping keys.
    """
    lines = [_split_comment(line)[0] for line in text.splitlines()]
    body = [
        (n, line)
        for n, line in enumerate(lines, start=1)
        if line.strip() and line.strip() not in ("---", "...") and not line.startswith("%")
    ]
    if not body:
        return [(1, NO_ON)]
    root = len(body[0][1]) - len(body[0][1].lstrip(" "))
    problems: list[tuple[int, str]] = []
    found_on = False
    for index, (lineno, line) in enumerate(body):
        indent = len(line) - len(line.lstrip(" "))
        on_key = _ON_KEY_RE.match(line[root:]) if indent == root else None
        if not on_key:
            continue
        found_on = True
        value_lines: list[tuple[int, str]] = []
        for n, nxt in body[index + 1 :]:
            nxt_indent = len(nxt) - len(nxt.lstrip(" "))
            if nxt_indent < root or (
                nxt_indent == root and not nxt.lstrip().startswith(("-", "]", "}"))
            ):
                break
            value_lines.append((n, nxt))
        events: list[tuple[int, str | None]] = []
        inline = (on_key.group(1) or "").strip()
        if inline.startswith(("[", "{")):
            flow = " ".join([inline, *(v.strip() for _, v in value_lines)])
            names = _flow_events(flow)
            events = [(lineno, name) for name in names] if names is not None else [(lineno, None)]
        elif inline:
            events = [(lineno, _scalar(inline))]
        elif value_lines:
            child = min(len(v) - len(v.lstrip(" ")) for _, v in value_lines)
            for n, v in value_lines:
                if len(v) - len(v.lstrip(" ")) != child:
                    continue
                item = v.strip()
                if item.startswith("- ") or item == "-":
                    events.append((n, _scalar(item[1:])))
                else:
                    key = _KEY_RE.match(item)
                    events.append((n, _scalar(key.group(1)) if key else None))
        else:
            events = [(lineno, None)]
        for n, name in events:
            if name is None:
                problems.append((n, UNREADABLE))
            elif name == "pull_request_target":
                problems.append((n, PRT_FORBIDDEN))
    if not found_on:
        return [(body[0][0], NO_ON)]
    return problems


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
        for lineno, reason in trigger_problems(text):
            violations.append(f"{rel}:{lineno}: on — {reason}")

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
