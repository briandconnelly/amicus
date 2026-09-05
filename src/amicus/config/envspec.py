"""Declared environment variables with a legacy-name shim.

Every variable this server reads is declared once (name, description, default, legacy
names). The shim reads a legacy name only when the amicus name is unset and reports it
as a warning naming the removal version; a legacy value that disagrees with the amicus
value, or two legacy values that disagree, is an error. `${VAR}` placeholders an MCP
host failed to expand are detected and treated as unset.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

LEGACY_REMOVAL_VERSION = "0.3.0"

_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def is_env_placeholder(value: str | None) -> bool:
    """True when an env value is a literal, unexpanded `${...}` placeholder."""
    return value is not None and bool(_PLACEHOLDER_RE.match(value.strip()))


class EnvConflictError(ValueError):
    """Two names for one setting carry different values."""


@dataclass(frozen=True)
class EnvVar:
    name: str
    description: str
    default: str | None = None
    legacy: tuple[str, ...] = ()
    secret: bool = False


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
            return Resolved(name, own, "env", warning)
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
                f"{name} read from legacy {legacy_name}; rename it — legacy names are "
                f"removed in {LEGACY_REMOVAL_VERSION}",
            )
        if var.default is not None:
            return Resolved(name, var.default, "default")
        return Resolved(name, None, "unset")

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
                continue
            if resolved.warning:
                rep.warnings.append(resolved.warning)
        return rep
