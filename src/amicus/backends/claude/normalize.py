"""Parse a `claude -p --output-format json` envelope tolerantly (ported from claude-in-codex
`normalize.py`/`backend.py`). Everything lives on stdout: answer (`result`), the failure
flags (`is_error`, `subtype`), cost and usage, the session id and any permission denials.
CLI drift degrades metadata rather than breaking a run; the failure DECISION is the
adapter's (inspect_outcome), this module only reads."""

from __future__ import annotations

import json
from typing import Any

from pontonier.backend.protocol import Usage
from pontonier.core import redaction

from amicus.backends.claude import contract
from amicus.schemas.structured import classify_structured


def parse_envelope(stdout: str) -> dict[str, Any] | None:
    """The envelope as a dict, or None when stdout is not a JSON object."""
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def is_failure_envelope(env: dict[str, Any]) -> bool:
    """`is_error` truthy, or a `subtype` other than success (an absent subtype is the
    legacy success shape). The sibling's rule at normalize.py:527."""
    return bool(env.get("is_error")) or env.get("subtype") not in contract.SUCCESS_SUBTYPES


def extract_answer(env: dict[str, Any]) -> str:
    """`result` when it is a string, else "" (drift can put an object or a number there)."""
    raw = env.get("result")
    return raw if isinstance(raw, str) else ""


def _int(blob: dict[str, Any], name: str) -> int | None:
    value = blob.get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def extract_usage(env: dict[str, Any]) -> Usage | None:
    """Usage with Claude's cache counters mapped onto the shared fields; None when the
    envelope reports neither tokens nor cost. total_tokens is left None: Claude's input
    count excludes cached tokens, so a sum would be a claim the envelope does not make."""
    raw = env.get("usage")
    blob = raw if isinstance(raw, dict) else {}
    cost_raw = env.get("total_cost_usd")
    cost = (
        float(cost_raw)
        if isinstance(cost_raw, (int, float)) and not isinstance(cost_raw, bool)
        else None
    )
    if not blob and cost is None:
        return None
    return Usage(
        input_tokens=_int(blob, "input_tokens"),
        output_tokens=_int(blob, "output_tokens"),
        total_tokens=None,
        cost_usd=cost,
        cached_input_tokens=_int(blob, "cache_read_input_tokens"),
        cache_creation_input_tokens=_int(blob, "cache_creation_input_tokens"),
    )


def extract_session_id(env: dict[str, Any]) -> str | None:
    value = env.get("session_id")
    return value if isinstance(value, str) and value else None


def extract_denials(env: dict[str, Any]) -> list[Any]:
    """`permission_denials`, sanitized: denied tool calls are model-derived and may carry
    secrets in their inputs (sibling #66), and a control character can split a secret past
    the redactor, so sanitize each string then redact the tree."""
    raw = env.get("permission_denials")
    if not isinstance(raw, list):
        return []
    return [redaction.redact_tree(_sanitize_strings(item)) for item in raw]


def _sanitize_strings(node: Any) -> Any:
    if isinstance(node, str):
        return redaction.sanitize_echo_prose(node)
    if isinstance(node, dict):
        return {str(k): _sanitize_strings(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_sanitize_strings(v) for v in node]
    return node


def parse_structured(text: str | None) -> dict[str, Any] | None:
    """The answer as a JSON object (code fence tolerated), else None (prose)."""
    status, parsed = classify_structured(text)
    return parsed if status == "ok" else None
