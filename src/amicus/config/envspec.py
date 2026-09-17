"""Declared environment variables with a legacy-name shim and removed-name tombstones.

Every variable this server reads is declared once (name, description, default, legacy
names, removed names). The shim reads a legacy name only when the amicus name is unset and
reports it as a warning naming the removal version; a legacy value that disagrees with the
amicus value, or two legacy values that disagree, is an error. A removed name is a
tombstone: its presence is reported as a warning naming the amicus name, and its value is
never read, not even to see whether it is a placeholder, so it can neither supply a setting
nor conflict with one. `${VAR}` placeholders an MCP host failed to expand are detected on
the names that are read and treated as unset.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

# The release that drops every `EnvVar.legacy` alias. `scripts/check_release_state.py`
# refuses to release at or past it while any alias is still declared. Moved from 0.3.0 on
# 2026-09-14: 0.2.0, the first release to warn on the aliases, shipped four days before 0.3.0
# was cut, and one warning-bearing release is too short a window for an operator-facing
# rename. No declaration has carried an alias since #176, so this is the window for any
# alias declared later: its author moves this version forward, and the guard holds it there.
LEGACY_REMOVAL_VERSION = "0.4.0"

# The release that stopped reading the three siblings' names (`CODEX_IN_CLAUDE_*`,
# `MOONBRIDGE_*`, `CLAUDE_IN_CODEX_*`), now `EnvVar.removed` tombstones (#176). A fact of
# history that never moves, so a tombstone warning quotes it rather than the window above,
# which a later alias may move. docs/MIGRATION.md states it (tests/test_migration_doc.py).
SIBLING_ALIASES_REMOVED_IN = "0.4.0"

_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def is_env_placeholder(value: str | None) -> bool:
    """True when an env value is a literal, unexpanded `${...}` placeholder."""
    return value is not None and bool(_PLACEHOLDER_RE.match(value.strip()))


class EnvConflictError(ValueError):
    """Two names for one setting carry different values."""


def _join(*warnings: str | None) -> str | None:
    """One warning string from the parts that exist, or None when none does."""
    present = [w for w in warnings if w]
    return "; ".join(present) if present else None


@dataclass(frozen=True)
class EnvVar:
    name: str
    description: str
    default: str | None = None
    legacy: tuple[str, ...] = ()
    secret: bool = False
    # Former names whose values are never read; a set one is reported so an operator who
    # kept a sibling's configuration learns which amicus name replaced it.
    removed: tuple[str, ...] = ()


Source = Literal["env", "legacy", "default", "unset"]


@dataclass(frozen=True)
class Resolved:
    name: str
    value: str | None
    source: Source
    warning: str | None = None


@dataclass(frozen=True)
class EnvReport:
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EnvNamespace:
    prefix: str
    vars: tuple[EnvVar, ...]

    def __post_init__(self) -> None:
        if not self.prefix.endswith("_") or not self.prefix.isupper():
            raise ValueError(f"prefix {self.prefix!r} must be UPPER_SNAKE_ ending in _")
        for var in self.vars:
            if not var.name.startswith(self.prefix):
                raise ValueError(f"{var.name!r} must start with {self.prefix!r}")

    def names(self) -> tuple[str, ...]:
        return tuple(v.name for v in self.vars)

    def var(self, name: str) -> EnvVar:
        """Look up a declared variable by name; KeyError if it isn't declared."""
        for var in self.vars:
            if var.name == name:
                return var
        raise KeyError(name)

    def resolve(self, name: str, environ: Mapping[str, str] | None = None) -> Resolved:
        env = os.environ if environ is None else environ
        var = self.var(name)
        own = env.get(name)
        if is_env_placeholder(own):
            own = None
        legacy = [(n, env[n]) for n in var.legacy if n in env and not is_env_placeholder(env[n])]
        distinct = {v for _, v in legacy}
        stale_warning = self._stale_warning(var, env)
        if own is not None:
            if distinct - {own}:
                names = ", ".join(n for n, v in legacy if v != own)
                raise EnvConflictError(
                    f"{name} and legacy {names} are both set with different values; "
                    f"unset the legacy name(s)"
                )
            warning = None
            if legacy:
                warning = (
                    f"{', '.join(n for n, _ in legacy)} ignored: {name} is set "
                    f"(legacy names are removed in {LEGACY_REMOVAL_VERSION})"
                )
            return Resolved(name, own, "env", _join(warning, stale_warning))
        if len(distinct) > 1:
            raise EnvConflictError(
                f"legacy names for {name} disagree: {', '.join(n for n, _ in legacy)}"
            )
        if legacy:
            legacy_name, value = legacy[0]
            return Resolved(
                name,
                value,
                "legacy",
                _join(
                    f"{name} read from legacy {legacy_name}; rename it — legacy names are "
                    f"removed in {LEGACY_REMOVAL_VERSION}",
                    stale_warning,
                ),
            )
        if var.default is not None:
            return Resolved(name, var.default, "default", stale_warning)
        return Resolved(name, None, "unset", stale_warning)

    @staticmethod
    def _stale_warning(var: EnvVar, env: Mapping[str, str]) -> str | None:
        """The tombstone warning for `var`, from key presence alone: a removed name's value
        is never read, so an unexpanded placeholder in one is still a name the operator's
        configuration sets, and is reported."""
        stale = [n for n in var.removed if n in env]
        if not stale:
            return None
        verb = "is" if len(stale) == 1 else "are"
        return (
            f"{', '.join(stale)} {verb} set but not read since "
            f"{SIBLING_ALIASES_REMOVED_IN}; amicus reads {var.name}"
        )

    def report(self, environ: Mapping[str, str] | None = None) -> EnvReport:
        env = os.environ if environ is None else environ
        rep = EnvReport()
        for var in self.vars:
            if is_env_placeholder(env.get(var.name)):
                rep.placeholders.append(var.name)
            try:
                resolved = self.resolve(var.name, env)
            except EnvConflictError as exc:
                rep.errors.append(str(exc))
                # The conflict is between names that are read; a tombstone beside them is
                # still reported, since resolve() raised before it could carry the warning.
                stale = self._stale_warning(var, env)
                if stale:
                    rep.warnings.append(stale)
                continue
            if resolved.warning:
                rep.warnings.append(resolved.warning)
        return rep
