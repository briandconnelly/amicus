"""pi's spend cap, enforced by amicus (#454): pi 1.5 has no budget flag of its own.

The probe reads pi's `--mode json` stream as it arrives and sums the provider-reported cost
of every model call pi reports: each assistant `message_end`, and each `compaction_end`,
whose summarization calls produce no message of their own. It stops pi only at a point
where pi is about to call a model again:

- an assistant `message_end` whose `stopReason` is anything but "stop", "error" or
  "aborted" ("toolUse", "length", which pi may recover from by continuing, or a value a
  later pi adds);
- `auto_retry_start`, pi retrying a failed call (an "error" message is let through, since
  stopping there would race pi's own exit and hide the real provider error);
- `compaction_start`, which precedes the compaction's own model calls.

A "stop" message is let through, since its spend is already incurred and stopping would
only throw its answer away. So, like claude's own cap, it is a stop threshold checked
between model calls, not a ceiling, and a run can exceed it by one call.

It fails closed. A cost pi did not get from the provider (`totalFromProvider` not true: pi
priced it from its own table, or not at all) cannot be measured against the cap, so a run
that would continue past such a call is stopped as `unverifiable`; so is one with a stream
line cut at the capture cap, since what it held is lost."""

from __future__ import annotations

import json
from dataclasses import dataclass

from amicus.sdk.core import streamcap

BUDGET = "budget"
UNVERIFIABLE = "budget_unverifiable"
REASONS = frozenset({BUDGET, UNVERIFIABLE})

# Stop reasons after which pi will not call the model again on its own; a retry after
# "error" is announced by `auto_retry_start`, which is a gate below.
_FINAL_STOPS = frozenset({"stop", "error", "aborted"})
# Events that announce another model call.
_GATES = frozenset({"auto_retry_start", "compaction_start"})
# The probe parses only lines naming an event it acts on. The gate is worth keeping: pi
# streams a `message_update` per delta, each repeating the message so far, so parsing every
# line would be quadratic in the answer. A pi that renamed these events would break
# normalize too, and its pinned stream fixtures would say so.
_NEEDLES = ('"message_end"', '"compaction_end"', *(f'"{g}"' for g in sorted(_GATES)))


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
        if not any(needle in line for needle in _NEEDLES):
            return None
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            return None
        if not isinstance(event, dict):
            return None
        kind = event.get("type")
        if kind in _GATES:
            return self._verdict()
        if kind == "compaction_end":
            result = event.get("result")
            if isinstance(result, dict) and "usage" in result:
                self._count(result.get("usage"))
            return None
        if kind != "message_end":
            return None
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return None
        self._count(message.get("usage"))
        if message.get("stopReason") in _FINAL_STOPS:
            return None
        return self._verdict()

    def _verdict(self) -> str | None:
        """Whether pi may make its next model call."""
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
