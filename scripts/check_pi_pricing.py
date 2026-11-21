"""Check, without spending, that amicus still reads model prices from the installed pi.

The prices on ``amicus_models`` come from pi's RPC ``get_available_models`` reply (ADR 0051),
which ``pi --help`` does not describe, so ``scripts/check_backend_compat.py`` cannot see a pi
release that changed it. A reply amicus can no longer read costs nothing visible: the
listing keeps its rows and loses its prices.

This script gives pi a scratch agent directory holding one provider with two models, one
with a known price and one with none, reads the catalog through the pi plugin exactly as
``amicus_models`` does, and compares what comes back with what was written. Asking for a
known price is the point: a count of priced rows in the maintainer's own catalog cannot tell
a broken reply from a catalog that has no priced model, and looking at pi's raw output cannot
tell whether amicus still parses it.

It sends no prompt and makes no model call. The scratch directory holds a made-up API key
for a provider at an unroutable address, and no credential of the maintainer's is read.

Usage::

    uv run python scripts/check_pi_pricing.py

Exit status 0 with an ``OK`` line when both rows came back as written, 1 with a ``FAIL`` line
naming what differed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from amicus.backends import pi
from amicus.backends.pi import config as pi_config
from amicus.plugin import ModelEntry, ModelPricing, PricingTier

PROVIDER = "amicus-pricing-probe"
PRICED = f"{PROVIDER}/priced"
UNPRICED = f"{PROVIDER}/unpriced"
CONTEXT_TOKENS = 123_456
MAX_OUTPUT_TOKENS = 7_890
PRICING = ModelPricing(
    input=1.25,
    output=2.5,
    cache_read=0.125,
    cache_write=0.375,
    tiers=(PricingTier(1_000, 2.75, 5.5, 0.25, 0.75),),
)
MODELS_JSON = {
    "providers": {
        PROVIDER: {
            # Port 9 (discard) on loopback: nothing listens, and nothing is ever sent.
            "baseUrl": "http://127.0.0.1:9/v1",
            "api": "openai-completions",
            "apiKey": "made-up-key-for-the-amicus-pricing-probe",
            "models": [
                {
                    "id": "priced",
                    "contextWindow": CONTEXT_TOKENS,
                    "maxTokens": MAX_OUTPUT_TOKENS,
                    "cost": {
                        "input": PRICING.input,
                        "output": PRICING.output,
                        "cacheRead": PRICING.cache_read,
                        "cacheWrite": PRICING.cache_write,
                        "tiers": [
                            {
                                "inputTokensAbove": tier.input_tokens_above,
                                "input": tier.input,
                                "output": tier.output,
                                "cacheRead": tier.cache_read,
                                "cacheWrite": tier.cache_write,
                            }
                            for tier in PRICING.tiers
                        ],
                    },
                },
                {"id": "unpriced"},
            ],
        }
    }
}


def prepare(workdir: Path) -> dict[str, str]:
    """Write the scratch agent directory under `workdir` and return the environment that
    points pi and amicus at it. pi's child process inherits this process's environment, so
    the caller must put these in `os.environ` before calling `verify`."""
    agent_dir = workdir / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "models.json").write_text(json.dumps(MODELS_JSON), encoding="utf-8")
    state_dir = workdir / "state"
    state_dir.mkdir()
    return {pi_config.AGENT_DIR_VAR: str(agent_dir), "AMICUS_STATE_DIR": str(state_dir)}


def verify() -> list[str]:
    """What differs from what `prepare` wrote; empty when amicus read both rows back."""
    listing = pi.plugin(dict(os.environ)).models.read(force=True)
    if listing.source == "none":
        return ["amicus could not read pi's model table at all (is pi installed and on PATH?)"]
    rows: dict[str, ModelEntry] = {entry.slug: entry for entry in listing.models}
    problems: list[str] = []
    priced = rows.get(PRICED)
    if priced is None:
        problems.append(f"pi's table does not list {PRICED}, the scratch model with a price")
    elif priced.pricing is None:
        problems.append(
            f"{PRICED} came back with no price: amicus could not read pi's "
            "get_available_models reply, or no longer finds `cost` in it"
        )
    else:
        if priced.pricing != PRICING:
            problems.append(f"{PRICED} price is {priced.pricing}, expected {PRICING}")
        limits = (priced.context_tokens, priced.max_output_tokens)
        if limits != (CONTEXT_TOKENS, MAX_OUTPUT_TOKENS):
            problems.append(
                f"{PRICED} limits are {limits}, expected the exact "
                f"{(CONTEXT_TOKENS, MAX_OUTPUT_TOKENS)}"
            )
    unpriced = rows.get(UNPRICED)
    if unpriced is None:
        problems.append(f"pi's table does not list {UNPRICED}, the scratch model with no price")
    elif unpriced.pricing is not None:
        problems.append(
            f"{UNPRICED} has no cost configured but came back priced as {unpriced.pricing}"
        )
    return problems


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="amicus-pi-pricing-") as scratch:
        os.environ.update(prepare(Path(scratch)))
        problems = verify()
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print(
        f"OK  : amicus read {PRICED}'s price, tier and exact limits from the installed pi, "
        f"and reported {UNPRICED} as unpriced."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
