"""The env declarations, shaped for the packaging artifacts that must agree with them.

This module RENDERS NOTHING. It is the declaration side of a pair of equality checks:
`.mcp.json`'s `env_vars` list and `docs/MIGRATION.md`'s env table are hand-maintained
files, and `tests/test_packaging.py` and `tests/test_migration_doc.py` parse each committed
file and assert it equals what these pure functions return. So the guarantee is
"declaration-validated", not "generated": drift is caught, it is not repaired.

There is no generator and no regeneration command. To change either artifact, edit
`config/envspec.py` (or the backend's `config.ENV`) and then edit the committed file by
hand until the tests pass; their failure messages name the exact variable and value that
disagree. Do not go looking for a script -- one was used once, during M6, and was not
committed, so it is not a thing a contributor can run."""

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
