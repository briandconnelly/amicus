"""Ship the served skill in the wheel: exactly the files the server serves (ADR 0055).

A static force-include would copy all of `references/`, backups and hidden files included,
so this hook applies the server's own selection, `src/amicus/skill_files.py`, at build time."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

SKILL = "collaborating-with-amicus"


def _skill_files(root: Path):
    spec = importlib.util.spec_from_file_location(
        "_amicus_skill_files", root / "src" / "amicus" / "skill_files.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("src/amicus/skill_files.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SkillBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # noqa: ARG002
        if self.target_name != "wheel":
            return
        root = Path(self.root)
        source = root / "skills" / SKILL
        for rel in _skill_files(root).served_files(source):
            build_data["force_include"][str(source / rel)] = f"amicus/_skill/{SKILL}/{rel}"
