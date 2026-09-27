"""The process-global state a unit test may not leave behind (issue #152).

pytest runs this suite in declaration order, so a test that leaks global state breaks only a
test declared after it, and only if that later test happens to observe it. #146 leaked the
`amicus` logger's `propagate = False` and policy handlers from every in-process worker test,
and the full suite passed on four Python versions. `tests/conftest.py` snapshots this state
before each test's fixtures are set up and compares it after every one of them is torn down,
so the test that leaks fails at teardown, whoever would have tripped over it.

What is compared, and why each is here:

- The working directory and `sys.path`: a test that changes either changes every later
  relative path and import.
- `os.environ`, minus `PYTEST_CURRENT_TEST`, which pytest itself sets and clears per phase:
  `monkeypatch` undoes its own writes, so what remains is a direct write.
- The handlers of the signals a process running amicus installs or a test arms.
- Every logger that existed before the test: level, `propagate`, `disabled`, handlers and
  filters; and every `amicus.*` logger the test created, against a fresh logger's defaults.
  A logger another library creates and configures on first use (FastMCP's `to_client`
  clamp) is not a leak, so a new logger outside amicus's namespace is not compared.
- `obs._configured`, FastMCP's settings, and the worker's held job-lock descriptors.

pytest's own capture handlers are excluded: pytest adds and removes them per phase.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fastmcp

from amicus import _worker, obs

# pytest sets this on entering each phase and deletes it after teardown.
_PYTEST_ENV = frozenset({"PYTEST_CURRENT_TEST"})

_SIGNALS = tuple(
    getattr(signal, name)
    for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGALRM")
    if hasattr(signal, name)
)

_GONE = "<cwd no longer exists>"
_MISSING = object()


def _is_pytest_handler(handler: logging.Handler) -> bool:
    return type(handler).__module__.startswith("_pytest")


def _logger_state(target: logging.Logger) -> tuple[Any, ...]:
    return (
        target.level,
        target.propagate,
        target.disabled,
        tuple(h for h in target.handlers if not _is_pytest_handler(h)),
        tuple(target.filters),
    )


_FRESH_LOGGER = _logger_state(logging.Logger("fresh"))


def _loggers() -> dict[str, logging.Logger]:
    found = {
        name: target
        for name, target in list(logging.Logger.manager.loggerDict.items())
        if isinstance(target, logging.Logger)
    }
    found["<root>"] = logging.getLogger()
    return found


def _is_owned(name: str) -> bool:
    return name == obs.ROOT_LOGGER_NAME or name.startswith(obs.ROOT_LOGGER_NAME + ".")


def _cwd() -> str:
    try:
        return str(Path.cwd())
    except FileNotFoundError:
        return _GONE


@dataclass(frozen=True)
class Snapshot:
    cwd: str
    sys_path: tuple[str, ...]
    environ: dict[str, str]
    signals: dict[int, Any]
    loggers: dict[str, tuple[Any, ...]]
    logging_disable: int
    obs_configured: bool
    fastmcp_settings: dict[str, Any]
    held_locks: tuple[int, ...]


def snapshot() -> Snapshot:
    return Snapshot(
        cwd=_cwd(),
        sys_path=tuple(sys.path),
        environ={k: v for k, v in os.environ.items() if k not in _PYTEST_ENV},
        signals={int(signum): signal.getsignal(signum) for signum in _SIGNALS},
        loggers={name: _logger_state(target) for name, target in _loggers().items()},
        logging_disable=logging.root.manager.disable,
        obs_configured=obs._configured,
        fastmcp_settings=fastmcp.settings.model_dump(),
        held_locks=tuple(_worker._held_locks),
    )


def _changed_keys(before: dict[Any, Any], after: dict[Any, Any]) -> list[Any]:
    return sorted(
        (
            k
            for k in before.keys() | after.keys()
            if before.get(k, _MISSING) != after.get(k, _MISSING)
        ),
        key=str,
    )


def leaks(before: Snapshot, after: Snapshot) -> list[str]:
    """Name each piece of state that differs between two snapshots; empty when none does.
    Values are not echoed: an environment value can be a credential."""
    found: list[str] = []
    if before.cwd != after.cwd:
        found.append(f"working directory: {before.cwd} -> {after.cwd}")
    if before.sys_path != after.sys_path:
        found.append("sys.path changed")
    found += [f"os.environ[{k!r}] changed" for k in _changed_keys(before.environ, after.environ)]
    found += [
        f"handler for {signal.Signals(k).name} changed"
        for k in _changed_keys(before.signals, after.signals)
    ]
    for name, state in sorted(after.loggers.items()):
        if name in before.loggers:
            baseline = before.loggers[name]
        elif _is_owned(name):
            baseline = _FRESH_LOGGER
        else:
            continue
        if state != baseline:
            found.append(
                f"logger {name!r} changed: level, propagate, disabled, handlers or filters"
            )
    if before.logging_disable != after.logging_disable:
        found.append("logging.disable level changed")
    if before.obs_configured != after.obs_configured:
        found.append("obs._configured changed")
    found += [
        f"fastmcp.settings.{k} changed"
        for k in _changed_keys(before.fastmcp_settings, after.fastmcp_settings)
    ]
    if before.held_locks != after.held_locks:
        found.append("_worker._held_locks changed (a job-lock descriptor left open)")
    return found
