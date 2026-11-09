"""Shared helpers for the pi plugin tests: a backend built from an explicit environ with the
binary pinned to /PI, the provider's auth state pinned, and the model catalog pinned, plus
synthetic `--mode json` event streams in the #423 probe's shape. Nothing here spawns pi."""

from __future__ import annotations

import json
from typing import Literal

from amicus.backends.pi import contract
from amicus.backends.pi.adapter import PiBackend
from amicus.backends.pi.binary import PiBinary
from amicus.backends.pi.config import load_config
from amicus.backends.pi.models import PiModels
from amicus.plugin import ModelEntry, ModelListing
from amicus.sdk.conventions.preflight import HelpProbe

MODEL = "openrouter/moonshotai/kimi-k3"
NO_THINKING = "openrouter/plain/no-think"
CATALOG = ModelListing(
    models=(
        ModelEntry(slug=MODEL, supported_reasoning_efforts=contract.EFFORTS),
        ModelEntry(slug=NO_THINKING, supported_reasoning_efforts=("off",)),
    ),
    source="live",
)


def make_backend(
    environ: dict | None = None,
    catalog: ModelListing | Literal["unreadable"] = CATALOG,
    auth: str = "ready",
    calls: list | None = None,
) -> PiBackend:
    """A PiBackend whose binary resolves to /PI (unless `environ` overrides AMICUS_PI_BIN),
    whose `pi auth check` answers `auth`, and whose `pi --list-models <model>` answers with
    the rows of `catalog` (or cannot be read, for "unreadable"). Each probe appends
    `("auth", binary, model)` or `("lookup", model)` to `calls` when given."""
    env = {"AMICUS_PI_BIN": "/PI", **(environ or {})}
    cfg = load_config(env)
    binary = PiBinary(cfg)
    if cfg.bin_override == "/PI":
        binary.resolve = lambda: "/PI"  # type: ignore[method-assign]
    models = PiModels(cfg, binary)
    listing = ModelListing(models=(), source="none") if catalog == "unreadable" else catalog

    def lookup(model: str):
        if calls is not None:
            calls.append(("lookup", model))
        if catalog == "unreadable":
            return "unreadable"
        return next((e for e in catalog.models if e.slug == model), None)

    models.read = lambda force=False: listing  # type: ignore[method-assign]
    models.lookup = lookup  # type: ignore[method-assign]
    help_probe = HelpProbe(help_argv=("/PI", *contract.HELP_ARGS), probe_cwd=lambda: "/probe-cwd")
    backend = PiBackend(cfg, binary, help_probe, models)

    def auth_status(binary_path: str, model: str | None):
        if calls is not None:
            calls.append(("auth", binary_path, model))
        return auth

    backend._auth_status = auth_status  # type: ignore[method-assign]
    return backend


# --- synthetic event streams ---------------------------------------------------------------


def line(obj: dict) -> str:
    return json.dumps(obj) + "\n"


def usage(inp: int = 10, out: int = 5) -> dict:
    return {
        "input": inp,
        "output": out,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": inp + out,
        "cost": {"total": 0.001, "totalFromProvider": True},
    }


def assistant_end(
    text: str | None, *, stop: str = "stop", thinking: str = "medium", **extra
) -> str:
    content = [] if text is None else [{"type": "text", "text": text}]
    message = {
        "role": "assistant",
        "content": content,
        "thinkingLevel": thinking,
        "stopReason": stop,
        "usage": usage(),
        **extra,
    }
    return line({"type": "message_end", "message": message})


SESSION = line({"type": "session", "id": "sess-1", "version": 3, "cwd": "/w"})


def stream(text: str | None = "the answer", **kw) -> str:
    return SESSION + assistant_end(text, **kw)
