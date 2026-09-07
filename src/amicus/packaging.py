"""Derive packaging artifacts from the env declarations.

`.mcp.json`'s `env_vars` and `docs/MIGRATION.md`'s env table are both generated here so
neither can drift from `config/envspec.py`. Pure functions, no I/O: the tests compare a
committed file against what these return."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from amicus.config import GLOBAL_ENV
from amicus.schemas.codes import BACKEND_IDS

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config.envspec import EnvNamespace, EnvVar


def _backend_namespaces() -> list[EnvNamespace]:
    namespaces: list[EnvNamespace] = []
    for backend_id in BACKEND_IDS:
        module = importlib.import_module(f"amicus.backends.{backend_id}.config")
        namespaces.append(module.ENV)
    return namespaces


def declared_env_names() -> tuple[str, ...]:
    """Every AMICUS_* name this server reads, across the global and per-backend namespaces."""
    names = set(GLOBAL_ENV.names())
    for namespace in _backend_namespaces():
        names.update(namespace.names())
    return tuple(sorted(names))


def vendor_auth_env_names() -> tuple[str, ...]:
    """Vendor credential names a backend needs passed through.

    Read defensively: codex and kimi authenticate through their own CLI login and declare
    no credential env vars, so a missing attribute is normal, not an error."""
    names: set[str] = set()
    for backend_id in BACKEND_IDS:
        try:
            contract = importlib.import_module(f"amicus.backends.{backend_id}.contract")
        except ModuleNotFoundError:  # pragma: no cover - every in-tree backend has one
            continue
        names.update(getattr(contract, "LOGIN_CREDENTIAL_ENV_VARS", ()))
    return tuple(sorted(names))


def env_vars_list() -> list[str]:
    """The `env_vars` passthrough list for `.mcp.json`."""
    return sorted(set(declared_env_names()) | set(vendor_auth_env_names()))


def declared_vars() -> tuple[EnvVar, ...]:
    """Every declared EnvVar, global first then per backend, for the migration table."""
    collected = list(GLOBAL_ENV.vars)
    for namespace in _backend_namespaces():
        collected.extend(namespace.vars)
    return tuple(collected)
