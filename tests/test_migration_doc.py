"""The migration doc's env table is asserted equal to the declarations (spec: Config)."""

from __future__ import annotations

import re
from pathlib import Path

from amicus import packaging
from amicus.config.envspec import LEGACY_REMOVAL_VERSION

DOC = Path(__file__).resolve().parents[1] / "docs" / "MIGRATION.md"


def _table_rows() -> dict[str, set[str]]:
    """Parse the env table: amicus name -> the legacy names it lists."""
    rows: dict[str, set[str]] = {}
    for line in DOC.read_text().splitlines():
        match = re.match(r"^\|\s*`(AMICUS_[A-Z0-9_]+)`\s*\|([^|]*)\|", line)
        if match:
            legacy = set(re.findall(r"`([A-Z0-9_]+)`", match.group(2)))
            rows[match.group(1)] = legacy
    return rows


def _table_defaults() -> dict[str, str | None]:
    """Parse the env table's third column: amicus name -> the doc's default cell.

    A literal `—` (no default) parses to None so it compares directly against
    `EnvVar.default`, which is None for the same case.
    """
    defaults: dict[str, str | None] = {}
    for line in DOC.read_text().splitlines():
        match = re.match(
            r"^\|\s*`(AMICUS_[A-Z0-9_]+)`\s*\|([^|]*)\|([^|]*)\|",
            line,
        )
        if match:
            cell = match.group(3).strip()
            default_match = re.match(r"^`(.*)`$", cell)
            defaults[match.group(1)] = default_match.group(1) if default_match else None
    return defaults


def test_every_declared_var_appears_in_the_table():
    rows = _table_rows()
    for var in packaging.declared_vars():
        assert var.name in rows, f"{var.name} is declared but missing from MIGRATION.md"


def test_no_invented_vars_in_the_table():
    declared = {v.name for v in packaging.declared_vars()}
    assert set(_table_rows()) <= declared


def test_legacy_names_match_the_declarations_exactly():
    rows = _table_rows()
    for var in packaging.declared_vars():
        assert rows[var.name] == set(var.legacy), (
            f"{var.name}: doc lists {rows[var.name]}, declarations say {set(var.legacy)}"
        )


def test_default_column_matches_the_declarations_exactly():
    """The generation script also emits a `default` column; verify it too.

    The brief's parser only checks names and legacy aliases, leaving `default`
    unverified and free to drift. This closes that gap.
    """
    defaults = _table_defaults()
    for var in packaging.declared_vars():
        assert defaults[var.name] == var.default, (
            f"{var.name}: doc lists default {defaults[var.name]!r}, "
            f"declarations say {var.default!r}"
        )


def test_removal_version_is_stated():
    assert LEGACY_REMOVAL_VERSION in DOC.read_text()


def test_every_sibling_tool_prefix_is_mapped():
    text = DOC.read_text()
    for prefix in ("codex_", "kimi_", "claude_"):
        assert prefix in text, f"no tool map for {prefix}*"
