"""The committed fingerprint pins (#373), read by the tests that compare live artifacts to them.

`tests/fixtures/fingerprint_pins.json` holds the values a `FINGERPRINT` bump moves that are not
files of their own: the fingerprint string, each profile's full-manifest hash and each
profile's `surface_digest`. The tests render the live surface independently and compare it to
these committed values; nothing here computes a pin. `scripts/regenerate_fingerprint_pins.py`
writes this file and the snapshots beside it, and is never run by a test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PINS_PATH = Path(__file__).parent.parent / "fixtures" / "fingerprint_pins.json"

REGEN_COMMAND = "uv run python scripts/regenerate_fingerprint_pins.py"

# What a failure message teaches: rule 10's whole procedure, with the one command in it.
REGEN_STEPS = (
    "if the change is intended and touches a FINGERPRINT_COVERS category, bump FINGERPRINT "
    "(schema-N) in src/amicus/schemas/fingerprint.py, run "
    f"`{REGEN_COMMAND}` (it refuses unless FINGERPRINT advanced past the base branch), review "
    "the diff it prints, and commit the regenerated pins in their own commit (AGENTS.md rule 10)"
)


def load_pins() -> dict[str, Any]:
    return json.loads(PINS_PATH.read_text(encoding="utf-8"))
