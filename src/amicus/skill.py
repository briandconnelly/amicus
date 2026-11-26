"""The collaborating-with-amicus skill, as served over the MCP skills extension (ADR 0055).

The served files are the plugin's own: `SKILL.md` and every regular file under
`references/`, read from the wheel (force-included under `amicus/_skill/`) or, in a
checkout, from `skills/`. Nothing else in the skill folder, `tests/` included, is served."""

from __future__ import annotations

import importlib.resources
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import Skill

from amicus.skill_files import SkillUnavailable, served_files

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

SKILL_NAME = "collaborating-with-amicus"


def _has_skill_md(root: Traversable) -> bool:
    try:
        return root.joinpath("SKILL.md").is_file()
    except OSError:
        return False


def _checkout_root() -> Path | None:
    repo = Path(__file__).resolve().parents[2]
    try:
        project = tomllib.loads((repo / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if project.get("project", {}).get("name") != "amicus":
        return None
    root = repo / "skills" / SKILL_NAME
    return root if _has_skill_md(root) else None


def skill_root() -> Traversable | None:
    """Where the skill's files live: the installed package first, then a checkout."""
    packaged = importlib.resources.files("amicus").joinpath("_skill", SKILL_NAME)
    if _has_skill_md(packaged):
        return packaged
    return _checkout_root()


def build_skill() -> Skill:
    """The skill, built from the shipped files; raises `SkillUnavailable` otherwise."""
    root = skill_root()
    if root is None:
        raise SkillUnavailable("the skill's files are not installed")
    files = served_files(root)
    try:
        return Skill.from_files(files)
    except ValueError as exc:  # pydantic's ValidationError is a ValueError
        raise SkillUnavailable(f"the skill is not a valid Agent Skill: {exc}") from exc
