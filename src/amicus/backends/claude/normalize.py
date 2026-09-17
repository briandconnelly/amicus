"""Parse a `claude -p --output-format json` envelope tolerantly (ported from claude-in-codex
`normalize.py`/`backend.py`). Everything lives on stdout: answer (`result`), the failure
flags (`is_error`, `subtype`), cost and usage, the session id and any permission denials.
CLI drift degrades metadata rather than breaking a run; the failure DECISION is the
adapter's (inspect_outcome), this module only reads."""

from __future__ import annotations

import json
from typing import Any

from amicus.backends.claude import contract
from amicus.schemas.structured import classify_structured
from amicus.sdk.backend.protocol import Usage
from amicus.sdk.core import redaction


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


# Usage field -> key under each `modelUsage` entry, and -> key in the top-level `usage` block.
_MODEL_USAGE_KEYS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cached_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}
_USAGE_BLOCK_KEYS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cached_input_tokens": "cache_read_input_tokens",
    "cache_creation_input_tokens": "cache_creation_input_tokens",
}


def _model_entries(env: dict[str, Any]) -> list[dict[str, Any]]:
    raw = env.get("modelUsage")
    if not isinstance(raw, dict):
        return []
    return [entry for entry in raw.values() if isinstance(entry, dict)]


def _sum_across(entries: list[dict[str, Any]], name: str) -> int | None:
    """The sum over every entry, or None as soon as one entry does not state an int: a partial
    sum would read as a whole-run total."""
    total = 0
    for entry in entries:
        value = _int(entry, name)
        if value is None:
            return None
        total += value
    return total


def extract_usage(env: dict[str, Any]) -> Usage | None:
    """Usage from `modelUsage` when the envelope has a dict-shaped entry under it, else from
    the top-level `usage` block; None when the envelope reports neither tokens nor cost.

    claude's result schema (2.1.274) calls the top-level block "main agent loop only ...
    prefer modelUsage for token/cost accounting", and a budget stop prints that block zeroed
    beside a nonzero `total_cost_usd` while `modelUsage` carries the real counts (#158,
    `tests/fixtures/claude_budget_stop_envelope.json`). The two blocks count different
    scopes, so a field comes from one of them, never from both: a `modelUsage` field one
    entry leaves out is None rather than the block's number. Cost is `total_cost_usd`, the
    cumulative estimate that covers the same calls as `modelUsage`. total_tokens is left
    None: Claude's input count excludes cached tokens, so a sum would be a claim the
    envelope does not make."""
    cost_raw = env.get("total_cost_usd")
    cost = (
        float(cost_raw)
        if isinstance(cost_raw, (int, float)) and not isinstance(cost_raw, bool)
        else None
    )
    entries = _model_entries(env)
    if entries:
        counts = {field: _sum_across(entries, key) for field, key in _MODEL_USAGE_KEYS.items()}
    else:
        raw = env.get("usage")
        blob = raw if isinstance(raw, dict) else {}
        if not blob and cost is None:
            return None
        counts = {field: _int(blob, key) for field, key in _USAGE_BLOCK_KEYS.items()}
    return Usage(total_tokens=None, cost_usd=cost, **counts)


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
