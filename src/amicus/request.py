"""RunSpec: the one serializable description of a paid run, split into a PUBLIC half
(spec.json in the job record) and an INPUT half that only ever travels over the worker's
stdin, so amicus itself never persists a prompt. The keyed-dedup identity (ADR 0008) is
the public half minus per-connection fields plus a digest of the input half."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from pontonier.core import idempotency

from amicus.schemas import instructions
from amicus.schemas.envelope import Meta

INPUT_FIELDS: tuple[str, ...] = (
    "question",
    "task",
    "extra_context",
    "instructions_append",
    "focus",
    "target",
    "evidence",
)
# Public fields that describe HOW a call was resolved, not WHAT it asks for: the index is
# already keyed by tool and workspace, and the rest is per-connection (a reconnect must
# replay, not conflict).
IDENTITY_EXCLUDE: frozenset[str] = frozenset(
    {"cwd", "workspace_source", "roots_source", "host_name", "kind", "tool"}
)


@dataclass(frozen=True)
class RunSpec:
    backend: str
    kind: str
    tool: str
    cwd: str
    workspace_source: str | None
    roots_source: str
    host_name: str
    timeout_seconds: int
    model: str | None = None
    reasoning_effort: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    scope: str | None = None
    base: str | None = None
    commit: str | None = None
    paths: list[str] | None = None
    untracked: str = "explicit_only"
    git_timeout: int = 60
    max_input_bytes: int = 200_000
    max_diff_bytes: int = 200_000
    max_output_bytes: int = 10 * 1024 * 1024
    # --- inputs: never persisted, never on argv ---
    question: str | None = None
    task: str | None = None
    extra_context: str | None = None
    instructions_append: str | None = None
    focus: str | None = None
    target: str | None = None
    evidence: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            f.name: getattr(self, f.name)
            for f in dataclasses.fields(self)
            if f.name not in INPUT_FIELDS
        }

    def inputs(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in INPUT_FIELDS}

    def inputs_json(self) -> str:
        return json.dumps(self.inputs())

    def identity(self) -> dict[str, Any]:
        """The effective run inputs a keyed start is deduplicated on. Prompt text never
        enters it; only a sha256 of the canonical inputs JSON does."""
        ident = {k: v for k, v in self.public().items() if k not in IDENTITY_EXCLUDE}
        digest = hashlib.sha256(idempotency.canonical_json(self.inputs()).encode("utf-8"))
        ident["inputs_digest"] = digest.hexdigest()
        return ident

    def arg_hash(self) -> str:
        return idempotency.arg_hash(self.identity())

    @classmethod
    def from_parts(cls, public: dict[str, Any], inputs: dict[str, Any]) -> RunSpec:
        """Rebuild from a persisted public half plus the streamed inputs; keys a later
        release added default, so an older record still parses."""
        known = {f.name for f in dataclasses.fields(cls)}
        merged = {k: v for k, v in public.items() if k in known and k not in INPUT_FIELDS}
        merged.update({k: inputs.get(k) for k in INPUT_FIELDS})
        return cls(**merged)


def meta_for(spec: RunSpec) -> Meta:
    """The envelope Meta a run starts from; the loop stamps elapsed/exit/usage later."""
    from amicus.orchestration.workspace import workspace_warning_for  # noqa: PLC0415

    fp = None
    if spec.instructions_append is not None:
        text = instructions.normalize(spec.instructions_append)
        if text is not None:
            fp = instructions.fingerprint(text)
    return Meta(
        backend=spec.backend,
        cwd=spec.cwd,
        workspace_source=spec.workspace_source,  # ty: ignore[invalid-argument-type]
        workspace_warning=workspace_warning_for(spec.workspace_source, spec.cwd),
        roots_source=spec.roots_source,  # ty: ignore[invalid-argument-type]
        model=spec.model,
        reasoning_effort=spec.reasoning_effort,
        timeout_seconds=spec.timeout_seconds,
        instructions_append=fp,
        backend_details=dict(spec.options) or None,
    )
