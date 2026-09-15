"""Feature-detect which backend CLI flags exist, by parsing its --help once.

Only HELP_GATED flags (depth/cosmetic) are gated on this probe: dropping one
when absent keeps the server working across a minor upstream change. The
guarantee-bearing ALWAYS_SEND flags are never gated here — their removal is
caught loudly at run time (cli_contract_changed), not silently pre-empted,
because ``--help`` parsing is fuzzy and a false negative must never drop a
safety/isolation flag.

Everything degrades, nothing crashes: any probe failure yields
``help_parsed=False``, which makes ``is_supported()`` return True for every
flag (fail open).

The probing rules are shared; the probe target is not. Each bridge constructs a
:class:`HelpProbe` from its contract (binary, help argv, TTL, always-send set)
and keeps its own instance — the cache lives on the instance, so two backends
in one process never share probe results.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from amicus.sdk.core import runtime

_LONG_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]+")


@dataclass(frozen=True)
class FlagSupport:
    supported: frozenset[str]
    help_parsed: bool  # False => probe failed; callers must fail open


def parse_supported(help_text: str) -> frozenset[str]:
    """Extract long-flag names from help text. Deliberately tolerant: this only
    governs HELP_GATED flags, where a stray/missing match drops a harmless flag."""
    return frozenset(_LONG_FLAG_RE.findall(help_text))


def is_supported(flag: str, fs: FlagSupport) -> bool:
    """Whether ``flag`` may be sent. Fails OPEN: when the probe could not run
    (``help_parsed=False``) every flag is treated as supported."""
    return (not fs.help_parsed) or (flag in fs.supported)


@dataclass
class HelpProbe:
    """Cached ``--help`` prober for one backend CLI.

    ``help_argv`` is the full probe command (binary first). ``always_send_flags``
    is the guarantee-bearing set used only for the advisory
    :meth:`missing_expected_flags` diagnostic.
    """

    help_argv: tuple[str, ...]
    always_send_flags: tuple[str, ...] = ()
    cache_ttl_seconds: float = 300.0
    probe_timeout_seconds: int = 10
    _cache: tuple[float, FlagSupport] | None = field(default=None, repr=False)

    def _probe_help(self) -> str:
        """The probe's raw help text, or "" on any failure (callers fail open)."""
        run = runtime.run_sync_capture(
            list(self.help_argv), timeout_seconds=self.probe_timeout_seconds
        )
        if run.binary_missing:
            return ""
        return f"{run.stdout}\n{run.stderr}"

    def flag_support(self, force: bool = False) -> FlagSupport:
        """Cached FlagSupport for the installed CLI. ``force=True`` bypasses the
        cache; the cache also expires after ``cache_ttl_seconds`` so a long-lived
        MCP server notices an in-place CLI upgrade."""
        now = time.monotonic()
        if not force and self._cache is not None:
            stamped, value = self._cache
            if now - stamped < self.cache_ttl_seconds:
                return value
        help_text = self._probe_help()
        if not help_text.strip():
            value = FlagSupport(supported=frozenset(), help_parsed=False)
        else:
            value = FlagSupport(supported=parse_supported(help_text), help_parsed=True)
        self._cache = (now, value)
        return value

    def reset_cache(self) -> None:
        """Drop the cached probe (used by tests)."""
        self._cache = None

    def missing_expected_flags(self, fs: FlagSupport) -> list[str]:
        """Guarantee-bearing ALWAYS_SEND flags that ``--help`` did not list. Empty
        when the probe could not run. Diagnostic only — surfaced by a status tool,
        it does NOT gate execution."""
        if not fs.help_parsed:
            return []
        return sorted(f for f in self.always_send_flags if f not in fs.supported)
