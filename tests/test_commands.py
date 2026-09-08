"""Every command file names only tools that exist, and every paid verb has a command."""

from __future__ import annotations

import re
from pathlib import Path

from amicus.tools import TOOL_ORDER

COMMANDS = Path(__file__).resolve().parents[1] / "commands" / "amicus"


def test_every_referenced_tool_exists():
    referenced = set()
    for path in COMMANDS.glob("*.md"):
        referenced.update(re.findall(r"\bamicus_[a-z_]+\b", path.read_text()))
    unknown = referenced - set(TOOL_ORDER)
    assert not unknown, f"commands name tools that do not exist: {sorted(unknown)}"


def test_every_tool_is_reachable_from_some_command():
    referenced = set()
    for path in COMMANDS.glob("*.md"):
        referenced.update(re.findall(r"\bamicus_[a-z_]+\b", path.read_text()))
    assert set(TOOL_ORDER) - referenced == set()
