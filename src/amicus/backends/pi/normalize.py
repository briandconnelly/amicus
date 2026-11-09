"""Read pi's `--mode json` JSONL event stream tolerantly.
The answer is the text of the last assistant `message_end`; `turn_end` and `agent_end` repeat
messages and are never counted. An event-schema change degrades metadata rather than breaking
a run. The stream echoes the system prompt and user message, so it is held in memory only."""

from __future__ import annotations

import json

from amicus.schemas.structured import classify_structured
from amicus.sdk.backend.protocol import Usage
from amicus.sdk.core import streamcap


def _event(raw_line: str) -> dict | None:
    line = raw_line.strip()
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return event if isinstance(event, dict) else None


def _events(events: str):
    for raw_line in events.splitlines():
        event = _event(raw_line)
        if event is not None:
            yield event


def _assistant_message(event: dict) -> dict | None:
    if event.get("type") != "message_end":
        return None
    message = event.get("message")
    if isinstance(message, dict) and message.get("role") == "assistant":
        return message
    return None


def _assistant_messages(events: str):
    for event in _events(events):
        message = _assistant_message(event)
        if message is not None:
            yield message


def final_assistant(events: str) -> dict | None:
    """The `message` of the last assistant `message_end`, or None."""
    found: dict | None = None
    for message in _assistant_messages(events):
        found = message
    return found


def extract_final_message(events: str) -> str | None:
    """The final assistant message's `text` parts joined; None when it has none."""
    message = final_assistant(events)
    if message is None:
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    texts = [
        part["text"]
        for part in content
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    joined = "\n".join(texts).strip()
    return joined or None


FAILED_STOP_REASONS = frozenset({"error", "aborted"})


def failed_stop(events: str) -> str | None:
    """The final assistant message's `stopReason` when it marks a failure ("error" or
    "aborted"), whether or not an `errorMessage` came with it; else None. The stop reason,
    not the message, is pi's failure signal."""
    message = final_assistant(events)
    reason = message.get("stopReason") if message else None
    return reason if reason in FAILED_STOP_REASONS else None


def stopped_at_length(events: str) -> bool:
    """Whether the final assistant message's `stopReason` is "length": the provider cut the
    response off at its output-token limit, so the text, even text that parses as complete
    JSON, is not the whole answer. It is not a failure code: the run itself succeeded."""
    message = final_assistant(events)
    return message is not None and message.get("stopReason") == "length"


def final_error(events: str) -> str | None:
    """The final assistant message's `errorMessage` when its `stopReason` is "error"."""
    message = final_assistant(events)
    if message is None or message.get("stopReason") != "error":
        return None
    error = message.get("errorMessage")
    return error.strip() if isinstance(error, str) and error.strip() else None


def thinking_level(events: str) -> str | None:
    message = final_assistant(events)
    level = message.get("thinkingLevel") if message else None
    return level if isinstance(level, str) and level else None


def lost_after_final_message(events: str) -> bool:
    """Whether a capture loss marker sits after the last assistant `message_end`, or anywhere
    when there is none (#198): the final message may then be the one that was evicted."""
    lost = False
    for raw_line in events.splitlines():
        if streamcap.is_loss_marker(raw_line):
            lost = True
        elif (event := _event(raw_line)) is not None and _assistant_message(event) is not None:
            lost = False
    return lost


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_event_metadata(events: str) -> tuple[Usage | None, str | None]:
    """(usage, session_id), either None when the stream did not carry it. Never raises."""
    session_id: str | None = None
    for event in _events(events):
        if event.get("type") == "session":
            found = event.get("id")
            if isinstance(found, str) and found:
                session_id = session_id or found
    return _usage(events), session_id


def _usage(events: str) -> Usage | None:
    counted = 0
    sums = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}
    seen = dict.fromkeys(sums, False)
    cost = 0.0
    cost_ok = True
    for message in _assistant_messages(events):
        blob = message.get("usage")
        if not isinstance(blob, dict):
            continue
        counted += 1
        for key in ("input", "output", "cacheRead", "cacheWrite"):
            value = _int(blob.get(key))
            if value is not None:
                sums[key] += value
                seen[key] = True
        total = _int(blob.get("totalTokens"))
        if total is None:
            total = (_int(blob.get("input")) or 0) + (_int(blob.get("output")) or 0)
        sums["total"] += total
        seen["total"] = True
        blob_cost = blob.get("cost")
        total_cost = blob_cost.get("total") if isinstance(blob_cost, dict) else None
        from_provider = isinstance(blob_cost, dict) and blob_cost.get("totalFromProvider") is True
        if (
            from_provider
            and isinstance(total_cost, int | float)
            and not isinstance(total_cost, bool)
        ):
            cost += total_cost
        else:
            cost_ok = False
    if counted == 0:
        return None

    def _sum(key: str) -> int | None:
        return sums[key] if seen[key] else None

    return Usage(
        input_tokens=_sum("input"),
        output_tokens=_sum("output"),
        total_tokens=sums["total"],
        cost_usd=cost if cost_ok else None,
        cached_input_tokens=_sum("cacheRead"),
        cache_creation_input_tokens=_sum("cacheWrite"),
    )


def parse_structured(text: str | None) -> dict | None:
    """The answer as a JSON object (code fence tolerated), else None (prose)."""
    status, parsed = classify_structured(text)
    return parsed if status == "ok" else None
