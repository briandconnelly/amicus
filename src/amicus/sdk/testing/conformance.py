"""Adapter conformance: does a backend implementation honor its contract?

Structural conformance (``isinstance(backend, AgentBackend)``) only proves the
members exist; these checks probe the INVARIANTS that made the protocol
necessary. Each returns violation strings (empty = pass).

What a clean result is evidence of, and what it is not (#127):

* ``check_contract`` proves the contract is self-consistent. It cannot prove a
  declaration true: ``effort_silently_ignored_upstream`` is a fact about the CLI
  that only a run against that CLI can establish, and the kit takes it as given.
* ``check_backend`` proves the adapter behaves as its declarations require, with
  no CLI spawned. The effort probe follows ``effort_validation``: it runs whenever
  the contract makes pre-spend validation mandatory (upstream silently ignores a
  bad effort) or declares ``shape_only`` validation, and it checks the refusal's
  code. It probes only a backend that accepts a plain request: one that refuses
  every request pre-spend is reporting its own state, which is not a fault, so the
  probes are skipped rather than failed, and a clean result then says nothing
  about its effort gate; the same holds when the configured default effort is
  itself invalid. The inspector probe proves tolerance, not accuracy.
  It runs at registry load, so it stays synchronous and stages nothing.
* ``check_prepared_run`` proves that one request's ``prepare()`` carries the flags
  the caller names, drops only help-gated ones, and cleans its staging up. Which
  flags a request must carry is the plugin's own knowledge (the always-send set is
  conditional on the request: a schema flag rides only with a schema, a mode flag
  only in its mode), so a plugin's offline tests call it per request shape, with a
  help probe that advertises nothing so a dropped flag is really dropped. It is
  not called at registry load: it stages artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from amicus.sdk.backend.protocol import (
    AgentBackend,
    ClassifiedFailure,
    OutcomeInspector,
    PreparedRun,
    RunOutcome,
    RunRequest,
)
from amicus.sdk.core.runtime import TIMED_OUT, CommandRun
from amicus.sdk.testing.surface_honesty import find_contract_self_contradictions

if TYPE_CHECKING:
    from collections.abc import Iterable

    from amicus.sdk.backend.contract import BackendContract

# The probe prompt is a literal of this module, never caller text.
_PROBE_PROMPT = "conformance probe"
# A control character fails every backend's transport shape, whatever its vocabulary.
_MALFORMED_EFFORT = "not a real\x00effort"
# Well formed, and in no backend's vocabulary; enumerated and catalog validation refuse it.
_UNKNOWN_EFFORT = "not-a-real-effort-level"
_EFFORT_CODE = "invalid_reasoning_effort"


def check_contract(contract: BackendContract) -> list[str]:
    """Static invariants a contract must satisfy on its own."""
    out: list[str] = []
    out.extend(
        find_contract_self_contradictions(
            contract.forbidden_surface_phrases,
            {
                "readonly_honesty_statement": contract.readonly_honesty_statement,
                "implicit_context_disclosure": contract.implicit_context_disclosure,
            },
        )
    )
    overlap = set(contract.always_send_flags) & set(contract.help_gated_flags)
    if overlap:
        out.append(
            f"flags {sorted(overlap)} are both always-send and help-gated; a flag has "
            "exactly one gating class"
        )
    if (
        contract.limits.max_argv_prompt_chars is not None
        and contract.limits.max_argv_prompt_chars <= 0
    ):
        out.append("max_argv_prompt_chars must be positive when set")
    if "usage_accounting" in contract.supported_features and not contract.usage_event_markers:
        out.append(
            "contract declares usage_accounting but lists no usage_event_markers to extract it from"
        )
    if contract.effort_silently_ignored_upstream and contract.effort_validation == "shape_only":
        out.append(
            "contract declares that upstream silently ignores a bad reasoning_effort but only "
            "shape_only validation; a well-formed unknown level would be paid for at the "
            "default effort, so the validation must be enumerated or token_floor_plus_catalog"
        )
    return out


def _effort_probe(effort: str | None) -> RunRequest:
    return RunRequest(
        kind="consult",
        prompt=_PROBE_PROMPT,
        cwd=".",
        timeout_seconds=1,
        reasoning_effort=effort,
    )


def _check_effort_validation(contract: BackendContract, backend: AgentBackend) -> list[str]:
    """The pre-spend effort gate, as the contract declares it. A backend whose CLI
    silently ignores a bad effort would otherwise burn money on a default-effort
    answer, so the gate is the only protection; a ``shape_only`` declaration is
    still a declaration, and is held to the shape."""
    out: list[str] = []
    why = (
        "upstream silently ignores a bad effort"
        if contract.effort_silently_ignored_upstream
        else f"the contract declares {contract.effort_validation} effort validation"
    )
    if backend.validate_request(_effort_probe(None)) is not None:
        # A backend may refuse every request pre-spend by design: Codex refuses a relative
        # CODEX_HOME, and any adapter refuses an omitted effort when the CONFIGURED default
        # it resolves to is invalid (an operator's typo). That is its state, not a fault,
        # and this runs at registry load, so it must not keep such a backend from loading:
        # the probes are skipped, since a refusal of the bogus effort would then say
        # nothing. The kit knows no level valid for every backend, so it cannot probe past
        # the refusal; a plugin's own tests, which know one, can.
        return out
    probes = [("malformed", _MALFORMED_EFFORT)]
    if contract.effort_validation != "shape_only":
        probes.append(("unknown", _UNKNOWN_EFFORT))
    for label, value in probes:
        failure = backend.validate_request(_effort_probe(value))
        if failure is None:
            out.append(
                f"{why}, but validate_request accepted a bogus reasoning_effort ({label}) — "
                "pre-spend validation is mandatory for this backend"
            )
        elif failure.code != _EFFORT_CODE:
            out.append(
                f"validate_request refused a {label} reasoning_effort as {failure.code!r}, "
                f"not {_EFFORT_CODE!r}; a caller cannot tell the effort was the problem"
            )
    return out


def check_backend(contract: BackendContract, backend: object) -> list[str]:
    """Behavioral invariants, probed without spawning the real CLI. The backend
    under test may be the real adapter with its subprocess seams stubbed, or a
    fake standing in for one during protocol development. Runs at registry load,
    so nothing here stages a run; see ``check_prepared_run`` for that."""
    out: list[str] = []
    if not isinstance(backend, AgentBackend):
        out.append("backend does not structurally implement AgentBackend")
        return out

    if contract.effort_silently_ignored_upstream or contract.effort_validation == "shape_only":
        out.extend(_check_effort_validation(contract, backend))

    if isinstance(backend, OutcomeInspector):
        # The inspector runs on EVERY completed process, including ones whose
        # stdout is empty or not JSON. One that raises there turns a classifiable
        # run into a consumer crash, so tolerance is the invariant, not accuracy.
        probe = RunRequest(kind="consult", prompt=_PROBE_PROMPT, cwd=".", timeout_seconds=1)
        # Each outcome carries nothing but the process result — no events, no
        # artifact_texts — because that is what a consumer has when the process
        # never produced them. Returning a ClassifiedFailure for these is fine;
        # raising is the violation.
        hostile = (
            RunOutcome(run=CommandRun("", "", 0, 1, False)),
            RunOutcome(run=CommandRun("not json", "", 0, 1, False)),
            RunOutcome(run=CommandRun("{", "", 0, 1, False)),
            # Timed out is still "completed"; this is the shape run_async returns.
            RunOutcome(run=CommandRun("", TIMED_OUT, -9, 1, True)),
        )
        for outcome in hostile:
            label = f"stdout {outcome.run.stdout!r}" + (
                ", timed out" if outcome.run.timed_out else ""
            )
            try:
                result = backend.inspect_outcome(outcome, probe)
            except Exception as exc:
                out.append(
                    f"inspect_outcome raised {type(exc).__name__} on {label}; "
                    "it must return None or a ClassifiedFailure"
                )
                continue
            # Reachable only when a plugin violates its own annotation; a type
            # checker may call this branch unreachable. Keep it — third-party
            # plugins are exactly who this probe exists for.
            if result is not None and not isinstance(result, ClassifiedFailure):
                out.append(
                    f"inspect_outcome returned {type(result).__name__} on {label}; "
                    "it must return None or a ClassifiedFailure"
                )
    return out


def option_tokens(argv: Iterable[str]) -> frozenset[str]:
    """The option names on an argv, by position: every token after the program that
    starts with ``-``, cut at ``=``. A value that happens to start with ``-`` is read as
    an option too, which errs toward reporting a flag present, never absent; a flag's
    value is never read as the flag (``-c key=value`` names ``-c``, not ``key``)."""
    names = set()
    for token in list(argv)[1:]:
        if token.startswith("-"):
            names.add(token.partition("=")[0])
    return frozenset(names)


async def check_prepared_run(
    contract: BackendContract,
    backend: AgentBackend,
    request: RunRequest,
    *,
    required_flags: Iterable[str] = (),
    forbidden_flags: Iterable[str] = (),
) -> list[str]:
    """Stage ``request`` through ``backend.prepare`` and hold the result to the contract,
    without spawning anything. Violations: a required flag absent from argv or reported
    dropped; a forbidden one present; a dropped flag the contract does not gate on help
    (a guarantee-bearing flag may never be dropped); a flag both on argv and dropped;
    a named artifact path that ``artifacts`` does not enumerate, or a staged path that
    survives the context, on a normal exit or an exceptional one (a second pass raises
    inside it); a cwd that is not the request's; an argv or env of the wrong shape.

    ``required_flags`` is the plugin's statement of which of its always-send flags this
    request must carry, because that set is conditional on the request. Call it with a
    help probe that advertises no flags: then a help-gated flag is really dropped and
    ``dropped_flags`` is exercised, where a probe that failed to parse keeps every flag
    and proves nothing about dropping."""
    out: list[str] = []
    required = tuple(required_flags)
    forbidden = tuple(forbidden_flags)
    staged: tuple[str, ...] = ()
    staging_dir: str | None = None
    async with backend.prepare(request) as prepared:
        if not isinstance(prepared, PreparedRun):
            out.append(f"prepare yielded {type(prepared).__name__}, not a PreparedRun")
            return out
        argv = prepared.argv
        if not isinstance(argv, tuple) or not argv or not all(isinstance(t, str) for t in argv):
            out.append("argv must be a non-empty tuple of str")  # a bare str iterates as str
            return out
        if prepared.cwd != request.cwd:
            out.append(f"prepared cwd {prepared.cwd!r} is not the request's {request.cwd!r}")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in prepared.env.items()):
            out.append("env must map str to str")
        options = option_tokens(argv)
        dropped = tuple(prepared.dropped_flags)
        stray = sorted(set(dropped) - set(contract.help_gated_flags))
        if stray:
            out.append(
                f"dropped_flags {stray} are not help-gated; only a help-gated flag may be "
                "dropped, a guarantee-bearing one never"
            )
        both = sorted(options & set(dropped))
        if both:
            out.append(f"flags {both} are on argv and reported dropped at once")
        for flag in required:
            if flag in dropped:
                out.append(f"required flag {flag} was dropped")
            elif flag not in options:
                out.append(f"required flag {flag} is not an option on argv")
        for flag in forbidden:
            if flag in options:
                out.append(f"forbidden flag {flag} is an option on argv")
        # An artifact may be an output path the CLI has yet to write (Codex's last
        # message), so existence inside the context is not an invariant; survival past
        # it is, since the protocol promises cleanup however the run ended.
        staged = tuple(prepared.artifacts)
        staging_dir = prepared.staging_dir
        unlisted = sorted(set(prepared.artifact_paths.values()) - set(staged))
        if unlisted:
            out.append(f"artifact_paths names {len(unlisted)} path(s) that artifacts does not list")
    out.extend(_survivors(staged, staging_dir, "the prepare context"))
    # The protocol promises cleanup however the run ended, and a cleanup written after the
    # yield with no finally passes the exit above, so a second pass leaves by exception.
    staged = ()
    staging_dir = None
    raised_through = False
    try:
        async with backend.prepare(request) as prepared:
            staged = tuple(prepared.artifacts)
            staging_dir = prepared.staging_dir
            raise _ProbeExit
    except _ProbeExit:
        raised_through = True
    if not raised_through:
        out.append("prepare swallowed the exception raised inside its context")
    out.extend(_survivors(staged, staging_dir, "an exceptional exit from the prepare context"))
    return out


class _ProbeExit(Exception):
    """Raised inside ``prepare`` by ``check_prepared_run``'s second pass; never a run."""


def _survivors(staged: tuple[str, ...], staging_dir: str | None, exit_kind: str) -> list[str]:
    out: list[str] = []
    leftover = [p for p in staged if Path(p).exists()]
    if leftover:
        out.append(f"{len(leftover)} staged artifact path(s) survived {exit_kind}")
    if staging_dir is not None and Path(staging_dir).exists():
        out.append(f"staging_dir survived {exit_kind}")
    return out
