"""Shared failure-classification skeleton, driven by contract signature tables.

The precedence order is the part every bridge must agree on — a rate-limit
message that also mentions auth must classify the same way everywhere. The
backend hook runs FIRST because some backends carry structured evidence the
regexes cannot see (Claude's stdout JSON envelope names its own error states);
a hook that returns None falls through to the shared order:

    binary missing → timeout → contract drift → auth → rate limit →
    invalid model → nonzero exit

Detail text passed in must already be sanitized/redacted by the caller; this
module only decides the code.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from amicus.sdk.backend.protocol import ClassifiedFailure

if TYPE_CHECKING:
    from collections.abc import Callable

    from amicus.sdk.backend.contract import BackendContract
    from amicus.sdk.backend.protocol import RunOutcome, RunRequest


def classify(
    contract: BackendContract,
    outcome: RunOutcome,
    request: RunRequest,
    *,
    detail: str,
    backend_hook: Callable[[RunOutcome, RunRequest], ClassifiedFailure | None] | None = None,
) -> ClassifiedFailure:
    """Map a failed run to a taxonomy code (see module docstring for order)."""
    if backend_hook is not None:
        classified = backend_hook(outcome, request)
        if classified is not None:
            return classified

    run = outcome.run
    b = contract.backend_id
    if run.binary_missing:
        return ClassifiedFailure(code=f"{b}_not_found", detail=detail)
    if run.timed_out:
        return ClassifiedFailure(code="timeout", detail=detail)

    sigs = contract.failure_signatures
    text = run.stderr or ""
    if _matches(sigs.contract_drift, text):
        return ClassifiedFailure(code="cli_contract_changed", detail=detail)
    if _matches(sigs.auth, text):
        return ClassifiedFailure(code=f"{b}_auth_required", detail=detail)
    if _matches(sigs.rate_limited, text):
        return ClassifiedFailure(
            code=f"{b}_rate_limited",
            detail=detail,
            retry_after_ms=parse_retry_after_ms(sigs.retry_after_ms, text),
        )
    if _matches(sigs.invalid_model, text):
        return ClassifiedFailure(code="invalid_model", detail=detail)
    return ClassifiedFailure(code="nonzero_exit", detail=detail)


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def parse_retry_after_ms(pattern: str | None, text: str) -> int | None:
    """Extract a retry delay from diagnostics via the contract's single-group
    pattern. Returns None on no match, a malformed number, or a value that
    cannot be a sane delay (negative)."""
    if pattern is None:
        return None
    m = re.search(pattern, text)
    if m is None:
        return None
    try:
        value = int(m.group(1))
    except (IndexError, ValueError):
        return None
    return value if value >= 0 else None
