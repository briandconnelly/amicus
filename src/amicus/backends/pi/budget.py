"""pi's spend cap, enforced by amicus (#454): pi 1.5 has no budget flag of its own.

The probe reads pi's `--mode json` stream as it arrives and sums each assistant
`message_end`'s provider-reported cost. It only ever stops pi BEFORE another model call: a
message whose `stopReason` ends the run is let through, since its spend is already incurred
and stopping would only throw its answer away. So, like claude's own cap, it is a stop
threshold checked between model calls, not a ceiling, and a run can exceed it by one call.

It fails closed. A cost pi did not get from the provider (`totalFromProvider` not true: pi
priced it from its own table, or not at all) cannot be measured against the cap, so a run
that would continue past such a message is stopped as `unverifiable`; so is one whose
`message_end` line was cut at the capture cap, since its cost and stop reason are lost."""

from __future__ import annotations

import json
from dataclasses import dataclass

from amicus.sdk.core import streamcap

BUDGET = "budget"
UNVERIFIABLE = "budget_unverifiable"
REASONS = frozenset({BUDGET, UNVERIFIABLE})

# pi-ai's StopReason values that end a run. Anything else ("toolUse", "pending",
# "deferred", or a value a later pi adds) means pi may call the model again.
_TERMINAL_STOPS = frozenset({"stop", "length", "error", "aborted"})
# Every `message_end` event carries this; a line without it cannot be one, so the probe
# parses only the lines that might matter. The gate is worth keeping: pi streams a
# `message_update` per delta, each repeating the message so far, so parsing every line would
# be quadratic in the answer. A pi that renamed the event would break normalize too, and
# its pinned stream fixtures would say so.
_MESSAGE_END = '"message_end"'


@dataclass
class SpendProbe:
    """One run's running spend; a fresh instance per run (`PreparedRun.stop_on_line`)."""

    cap_usd: float
    spent_usd: float = 0.0
    unverified: bool = False

    def __call__(self, line: str) -> str | None:
        if streamcap.is_loss_marker(line):
            # A line cut at the capture cap may have been a message_end, whose cost and stop
            # reason are now unknowable. Cut lines are rare (one line past the whole cap).
            return UNVERIFIABLE
        if _MESSAGE_END not in line:
            return None
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            return None
        if not isinstance(event, dict) or event.get("type") != "message_end":
            return None
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return None
        self._count(message.get("usage"))
        if message.get("stopReason") in _TERMINAL_STOPS:
            return None
        if self.unverified:
            return UNVERIFIABLE
        return BUDGET if self.spent_usd >= self.cap_usd else None

    def _count(self, usage: object) -> None:
        cost = usage.get("cost") if isinstance(usage, dict) else None
        total = cost.get("total") if isinstance(cost, dict) else None
        if (
            isinstance(cost, dict)
            and cost.get("totalFromProvider") is True
            and isinstance(total, int | float)
            and not isinstance(total, bool)
        ):
            self.spent_usd += total
        else:
            self.unverified = True
