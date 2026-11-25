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

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

SKILL_NAME = "collaborating-with-amicus"
_BACKUP_SUFFIXES = ("~", ".swp", ".bak", ".orig")


class SkillUnavailable(Exception):
    """The skill's files are missing, incomplete, or not regular files."""


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


def _skipped(name: str) -> bool:
    return name.startswith(".") or name.endswith(_BACKUP_SUFFIXES)


def _reject_symlink(node: Traversable, rel: str) -> None:
    if isinstance(node, Path) and node.is_symlink():
        raise SkillUnavailable(f"{rel} is a symlink")


def _walk(node: Traversable, prefix: str, out: dict[str, bytes]) -> None:
    for child in sorted(node.iterdir(), key=lambda c: c.name):
        if _skipped(child.name):
            continue
        rel = f"{prefix}/{child.name}"
        _reject_symlink(child, rel)
        if child.is_dir():
            _walk(child, rel, out)
        elif child.is_file():
            out[rel] = child.read_bytes()
        else:
            raise SkillUnavailable(f"{rel} is not a regular file")


def served_files(root: Traversable) -> dict[str, bytes]:
    """`SKILL.md` and every regular file under `references/`, keyed by POSIX path."""
    try:
        _reject_symlink(root.joinpath("SKILL.md"), "SKILL.md")
        if not root.joinpath("SKILL.md").is_file():
            raise SkillUnavailable("SKILL.md is missing")
        references = root.joinpath("references")
        _reject_symlink(references, "references")
        if not references.is_dir():
            raise SkillUnavailable("references/ is missing")
        out = {"SKILL.md": root.joinpath("SKILL.md").read_bytes()}
        _walk(references, "references", out)
    except OSError as exc:
        raise SkillUnavailable(f"the skill's files could not be read: {exc}") from exc
    if len(out) == 1:
        raise SkillUnavailable("references/ is empty")
    return out


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
