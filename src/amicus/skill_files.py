"""Which of the skill's files are served, and so shipped (ADR 0055).

Standard library only: `hatch_build.py` loads this file by path at build time, before any of
amicus's dependencies exist, so the wheel and the running server select the same files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

_BACKUP_SUFFIXES = ("~", ".swp", ".bak", ".orig")


class SkillUnavailable(Exception):
    """The skill's files are missing, incomplete, or not regular files."""


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
        _reject_symlink(root, "the skill root")
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
