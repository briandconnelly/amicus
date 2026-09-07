"""Backend-neutral structured-output parsing.

Every backend's structured answer is finalized through this one loop
(orchestration/finalize.py), so the code-fence stripping and strict
ok/invalid_json/schema_violation classification live here rather than in any
one backend package."""

from __future__ import annotations

import json


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def classify_structured(last_message: str | None) -> tuple[str, dict | None]:
    """("ok", dict) | ("invalid_json", None) | ("schema_violation", None) for the strict
    review path: absent/unparseable vs parseable-but-not-an-object."""
    if not last_message or not last_message.strip():
        return ("invalid_json", None)
    try:
        parsed = json.loads(_strip_code_fence(last_message))
    except (json.JSONDecodeError, ValueError):
        return ("invalid_json", None)
    if not isinstance(parsed, dict):
        return ("schema_violation", None)
    return ("ok", parsed)


def schema_instruction(output_schema: dict) -> str:
    """The prompt-appended structured-output instruction for a backend with no schema flag
    (kimi, claude). One text, so both backends ask for the object the same way."""
    return (
        "\n\n# Required output format\n"
        "Reply with a single JSON object and nothing else — no prose, no code fence. "
        "It must validate against this JSON Schema:\n\n"
        f"{json.dumps(output_schema, indent=2)}\n"
    )
