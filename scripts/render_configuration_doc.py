#!/usr/bin/env python
"""Render docs/CONFIGURATION.md from the environment-variable declarations.

Every variable amicus reads is declared once (`GLOBAL_ENV` in `amicus.config`, and each
backend's `ENV`), with its description and default. This renders those declarations as a
reference: `--write` rewrites the file, `--check` exits 1 when the committed file differs,
and tests/test_configuration_doc.py runs the check in the gate so the doc cannot drift.

Rule 16 (AGENTS.md) holds under docs/, so a description is split one sentence per line at
the boundary scripts/check_sentence_per_line.py recognises: a `.`, `?` or `!`, a single space,
then a capital, a code span, a link or emphasis. The splitter has no abbreviation guard and
cannot see a second sentence that starts lowercase, so a declaration must keep a capital, a
code span, a link or emphasis after each full stop.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from amicus import packaging

if TYPE_CHECKING:
    from amicus.config.envspec import EnvVar

DOC = Path(__file__).resolve().parents[1] / "docs" / "CONFIGURATION.md"
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.?!]) (?=[A-Z`\[*_])")
_GROUPS: tuple[tuple[str, str], ...] = (
    ("AMICUS_CODEX_", "Codex"),
    ("AMICUS_KIMI_", "Kimi"),
    ("AMICUS_CLAUDE_", "Claude"),
)

HEADER = "\n".join(
    (
        "# Configuration reference",
        "",
        "Every environment variable amicus declares, rendered from its declaration in the code by "
        "`scripts/render_configuration_doc.py`; edit the declaration, not this file.",
        "After changing a declaration, run "
        "`uv run python scripts/render_configuration_doc.py --write` and commit the result.",
        "A value is read once at startup.",
        "`AMICUS_ALLOW_UNSUPPORTED_PLATFORM` is the one variable read outside the declarations: "
        "an unsupported escape hatch for the POSIX startup check, "
        "left undeclared on purpose so that no reference or host passthrough advertises it.",
        "`AMICUS_BACKENDS` is the one most installs set; "
        "see the README for where a client sets environment variables.",
        "Former sibling names are listed in `docs/MIGRATION.md` and are not read.",
        "",
    )
)


def _group(var: EnvVar) -> str:
    for prefix, title in _GROUPS:
        if var.name.startswith(prefix):
            return title
    return "Server"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text.strip()) if s.strip()]


def _section(var: EnvVar) -> list[str]:
    lines = [f"### `{var.name}`", ""]
    lines.extend(_sentences(var.description))
    if var.default is None:
        lines.append("Unset by default.")
    else:
        lines.append(f"Default: `{var.default}`.")
    if var.secret:
        lines.append("Its value is never echoed in an error, a warning or a log.")
    if var.removed:
        names = ", ".join(f"`{n}`" for n in var.removed)
        lines.append(f"Former names, no longer read: {names}.")
    lines.append("")
    return lines


def render() -> str:
    groups: dict[str, list[EnvVar]] = {}
    for var in packaging.declared_vars():
        groups.setdefault(_group(var), []).append(var)
    out = [HEADER]
    for title in ("Server", "Codex", "Kimi", "Claude"):
        if title not in groups:
            continue
        out.append(f"## {title}")
        out.append("")
        for var in groups[title]:
            out.extend(_section(var))
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    mode.add_argument("--write", action="store_true", help="rewrite docs/CONFIGURATION.md")
    args = parser.parse_args(argv)
    rendered = render()
    if args.write:
        DOC.write_text(rendered, encoding="utf-8")
        print(f"wrote {DOC}")
        return 0
    current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if current == rendered:
        return 0
    print(f"{DOC} is stale; run with --write", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
