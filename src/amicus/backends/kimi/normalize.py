"""Parse a `kimi -p` stream-json outcome tolerantly (ported from moonbridge `normalize.py`).
kimi has no --output-last-message: the final answer is the last assistant line with text (or,
for a write-capable run, the answer file the adapter reads). An event-schema change degrades
metadata rather than breaking a run."""

from __future__ import annotations

import json

from pontonier.backend.protocol import Usage

from amicus.backends.kimi import contract
from amicus.schemas.structured import classify_structured


def _events(events: str):
    for raw_line in events.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(event, dict):
            yield event


def parse_event_metadata(events: str) -> tuple[Usage | None, str | None]:
    """(usage, session_id), either None when the stream did not carry it. Never raises."""
    usage: Usage | None = None
    session_id: str | None = None
    for event in _events(events):
        session_id = session_id or _find_session_id(event)
        found = _find_usage(event)
        if found is not None:
            usage = found
    return usage, session_id


def extract_final_message(events: str) -> str | None:
    """The last `{"role":"assistant","content":...}` line with text; tool-call-only lines
    are the model calling a tool, not answering. None when nothing answered."""
    found: str | None = None
    for event in _events(events):
        # `goal.summary` lines carry no "role" at all, so read it tolerantly.
        if event.get(contract.ROLE_KEY) != contract.ROLE_ASSISTANT:
            continue
        content = event.get(contract.CONTENT_KEY)
        if isinstance(content, str) and content.strip():
            found = content.strip()
    return found


def extract_error_message(events: str) -> str | None:
    """A human-readable error from `error`/`*.failed` events on stdout; the message is
    sometimes itself a JSON blob ({"error": {"message": ...}}), unwrapped one level."""
    found: str | None = None
    for event in _events(events):
        marker = str(event.get(contract.TYPE_KEY) or "").lower()
        if "error" not in marker and "failed" not in marker:
            continue
        message = event.get("message")
        if isinstance(event.get("error"), dict):
            message = event["error"].get("message", message)
        if isinstance(message, str) and message:
            found = _unwrap_json_message(message)
    return found


def _unwrap_json_message(message: str) -> str:
    text = message.strip()
    if not text.startswith("{"):
        return text
    try:
        blob = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(blob, dict) and isinstance(blob.get("error"), dict):
        inner = blob["error"].get("message")
        if isinstance(inner, str) and inner:
            return inner
    return text


def _find_session_id(event: dict) -> str | None:
    for key in ("session_id", "sessionId", "thread_id", "threadId", "conversation_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    for nest in ("msg", "payload", "data"):
        inner = event.get(nest)
        if isinstance(inner, dict):
            found = _find_session_id(inner)
            if found:
                return found
    return None


def _find_usage(event: dict) -> Usage | None:
    marker = str(event.get(contract.TYPE_KEY) or event.get("msg") or "").lower()
    candidates: list[dict] = []
    if any(m.lower() in marker for m in contract.USAGE_EVENT_MARKERS):
        candidates.append(event)
    for key in ("usage", "token_usage", "tokens", "info"):
        inner = event.get(key)
        if isinstance(inner, dict):
            candidates.append(inner)
    for nest in ("msg", "payload", "data"):
        inner = event.get(nest)
        if isinstance(inner, dict):
            for key in ("usage", "token_usage", "tokens"):
                deep = inner.get(key)
                if isinstance(deep, dict):
                    candidates.append(deep)
    for blob in candidates:
        usage = _usage_from(blob)
        if usage is not None:
            return usage
    return None


def _usage_from(blob: dict) -> Usage | None:
    def _int(*names: str) -> int | None:
        for name in names:
            value = blob.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    input_tokens = _int("input_tokens", "prompt_tokens", "input")
    output_tokens = _int("output_tokens", "completion_tokens", "output")
    cached = _int("cached_input_tokens", "cache_read_input_tokens", "cached_tokens")
    total = _int("total_tokens", "total")
    if input_tokens is None and output_tokens is None and total is None:
        return None
    # kimi emits token_count without a total: derive it (cached is a subset of input).
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cached_input_tokens=cached,
    )


def parse_structured(text: str | None) -> dict | None:
    """The answer as a JSON object (code fence tolerated), else None (prose)."""
    status, parsed = classify_structured(text)
    return parsed if status == "ok" else None
