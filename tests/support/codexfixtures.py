"""Shared helpers for the codex plugin tests: the sibling fixture, pinned flag support, a
backend built from an explicit environ, and the temp-path normalizer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pontonier.conventions.preflight import FlagSupport, HelpProbe

from amicus.backends import codex as codex_pkg
from amicus.backends.codex import contract
from amicus.backends.codex.adapter import CodexBackend

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "codex_differentials.json").read_text()
)
ALL_FLAGS = FlagSupport(
    supported=frozenset(contract.ALWAYS_SEND_FLAGS | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)


def make_backend(environ: dict | None = None, flags: FlagSupport = ALL_FLAGS):
    """(plugin, backend) with the help probe pinned and the binary pinned to /CODEX."""
    env = {"AMICUS_CODEX_BIN": "/CODEX", **(environ or {})}
    plugin = codex_pkg.plugin(env)
    probe: HelpProbe = plugin.help_probe
    probe.flag_support = lambda force=False: flags  # type: ignore[method-assign]
    backend = plugin.backend
    assert isinstance(backend, CodexBackend)
    return plugin, backend


def normalize_argv(argv) -> list[str]:
    return [re.sub(r"/[^\s]*amicus-codex-[^/]+/", "/TMP/", tok) for tok in argv]
