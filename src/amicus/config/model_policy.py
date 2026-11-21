"""The operator's model denylist, `AMICUS_DENY_MODELS` (#547).

A comma-separated list of `backend:glob` entries, where backend is an in-tree backend id or
`*`. Each entry splits on its first colon; both halves are trimmed and case-folded, and the
glob is matched with `fnmatchcase` against the whole case-folded selector, so `*` crosses `/`.
The check covers the selector amicus sends, never the model a CLI ends up running.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase

from amicus.schemas.codes import BACKEND_IDS

ENV_NAME = "AMICUS_DENY_MODELS"
ANY_BACKEND = "*"


@dataclass(frozen=True)
class ModelPolicy:
    """Parsed deny rules as (backend-or-*, glob) pairs, in the operator's order."""

    rules: tuple[tuple[str, str], ...] = ()

    def patterns_for(self, backend: str) -> tuple[str, ...]:
        key = backend.casefold()
        return tuple(glob for b, glob in self.rules if b in (key, ANY_BACKEND))

    def denied_by(self, backend: str, selector: str) -> str | None:
        """The first pattern that denies `selector` on `backend`, or None."""
        folded = selector.strip().casefold()
        return next((g for g in self.patterns_for(backend) if fnmatchcase(folded, g)), None)


def parse(raw: str | None) -> ModelPolicy | str:
    """The policy, or a diagnostic naming the variable, the 1-based entry and the reason.
    The diagnostic never echoes the value: it is operator text of unbounded length."""
    if raw is None or not raw.strip():
        return ModelPolicy()
    rules: list[tuple[str, str]] = []
    for index, entry in enumerate(raw.split(","), start=1):
        if not entry.strip():
            continue
        backend, sep, glob = entry.partition(":")
        backend, glob = backend.strip().casefold(), glob.strip().casefold()
        if "${" in entry:
            reason = "holds an unexpanded ${...} placeholder"
        elif not sep:
            reason = "has no ':' between a backend and a model glob"
        elif backend not in (*BACKEND_IDS, ANY_BACKEND):
            reason = f"names no backend (use one of {', '.join(BACKEND_IDS)} or '*')"
        elif not glob:
            reason = "has an empty model glob"
        else:
            rules.append((backend, glob))
            continue
        return f"{ENV_NAME} entry {index} {reason}"
    return ModelPolicy(tuple(rules))
