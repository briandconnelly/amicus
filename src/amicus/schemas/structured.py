"""Backend-neutral structured-output parsing.

Every backend's structured answer is finalized through this one loop
(orchestration/finalize.py), so the code-fence stripping and strict
ok/invalid_json/schema_violation classification live here rather than in any
one backend package."""

from __future__ import annotations

import json
from typing import Any


def _reject_repeated_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """`object_pairs_hook`: an object that repeats a key does not denote one value. Plain
    `json.loads` keeps the last member silently, which would let `"findings": [...]`
    followed by `"findings": []` reach `coerce_findings` as empty with nothing for the
    loss diagnostics to see (#51), so the parse fails instead."""
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"repeated key {key!r}")
        obj[key] = value
    return obj


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


def _loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_reject_repeated_keys)


def _enclosed_object(text: str) -> dict | None:
    """The one object an answer wraps in prose or a fence mid-message (#139): the span from
    the first `{` to the last `}`, parsed whole. Starting at the first `{`, the span cannot
    start inside a larger object, so a lone finding of a truncated answer is never promoted
    to the answer, and two objects never parse as one. A `{` in the prose before the object
    or a `}` after it lands inside the span and refuses it; a `}` before or a `{` after lies
    outside and is ignored with the rest of the prose. A `[` before and a `]` after refuse it
    too, since they may wrap it in an array. A repeated key still refuses (#51)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    # An array can hold an object with no `{` before it, so a `[` before the span and a `]`
    # after it may be a structural wrapper: `[{...}]` is not an object answer, and is refused.
    if "[" in text[:start] and "]" in text[end + 1 :]:
        return None
    try:
        parsed = _loads(text[start : end + 1])
    except ValueError:  # JSONDecodeError is a ValueError, as is a repeated key
        return None
    return parsed if isinstance(parsed, dict) else None


def classify_structured(
    last_message: str | None, *, enclosed: bool = False
) -> tuple[str, dict | None]:
    """("ok", dict) | ("invalid_json", None) | ("schema_violation", None): absent or
    unparseable vs parseable-but-not-an-object. An object that repeats a key at any depth
    is unparseable here: there is no one value to deliver. With `enclosed`, an answer that
    is not JSON as a whole is still read when it encloses exactly one object in prose; only
    the review path asks for that, because a consult's prose answer is itself its result
    (ADR 0024) and must not be narrowed to an object inside it (ADR 0033)."""
    if not last_message or not last_message.strip():
        return ("invalid_json", None)
    text = _strip_code_fence(last_message)
    try:
        parsed = _loads(text)
    except ValueError:
        found = _enclosed_object(text) if enclosed else None
        return ("ok", found) if found is not None else ("invalid_json", None)
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
