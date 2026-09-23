"""Wire-size ratchet for tools/list, per profile.

The least-capable realistic client preloads every tool definition, so the serialized
catalog is a per-session token tax. The budget is a ceiling equal to the last deliberate
measurement, so any growth fails; the measurement is kept beside it so a failure message
shows the drift. Raising a budget is a reviewed decision — say why in the PR body, and in
a paragraph below.

What this ratchet does and does not cover, scoped against captured host evidence rather
than assumed. It bounds the TOKEN COST of discovery. It is not a measure of first-call
success, and a green run here is no evidence that an agent picks the right tool.

The preloading client this budget is written for is real but is not universal. Codex CLI
0.153.4 preloads the catalog, so the tax is paid per session there. Claude Code 2.1.263
does not: it defers MCP tool definitions behind a ToolSearch lookup, so the wire size is a
smaller tax on that host than the budget assumes
(docs/host-captures/install-smoke/claude-code/2.1.263/notes.md). The budget stays the
worst-case ceiling for the clients that do preload.

Measured 2026-09-12 at schema-18 (18 tools; every model result carries
findings_diagnostics, both review tools publish what `confidence` means, the published
stability tier is inside the closed set, both review tools and the dry run carry
`coverage`, and the repeated parameter prose is compressed): see MEASURED.

What is measured: the `tools/list` result body a real `amicus.server` stdio subprocess
writes for a handshake-era (2025-11-25) client, byte for byte (`manifest.tools_list_wire`
takes the `result` text straight off the response line, never re-serialized). That era is
the one both captured hosts negotiate, so this is the body they receive: the plain result,
with no cache envelope and no serverInfo `_meta`; the 2026-07-28 body adds those (~150
bytes) and orders keys differently, and is not measured. Until schema-17 the instrument
re-encoded the bare tool records in-process with ASCII escaping, which was ~130 bytes off
and, being a re-serialization, ordered keys differently from the wire; the pre-change
figure below is on the current instrument, so the two are comparable. The ratchet stays in
bytes so CI never depends on a tokenizer. The token figures are reference-encoding counts
of that same wire text from `python -m amicus.manifest --measure --tokens` (tiktoken
0.14.0; `uv sync --group measure`), NOT the count any host or backend bills: neither
encoding is Claude Code's or Codex CLI's tokenizer. They replace the byte/4 proxy this
file used to assert, which was arithmetically the byte assertion again (ceil(size/4) <=
ceil(budget/4) whenever size <= budget) and measured nothing.

The schema-8 -> schema-9 raise (+5160 bytes) is deliberate, and most of it is prose. The
`findings_diagnostics` object itself costs ~1250 bytes across four paid tools' output
schemas, which the published schemas inline rather than $ref. The rest is the semantics
of the field, kept through _strip_schema_noise on purpose: `dropped: 0` does not mean
nothing was lost, and `dropped: null` means the count was unknowable. An MCP-only caller
has no skill file to read, so a field whose whole purpose is to prevent a misreading has
to carry that meaning on the wire or it will be misread (issue #38).

The schema-9 -> schema-10 raise (+1130 bytes) is the same trade on a smaller field. Adding
`unknown` to the confidence enum costs a dozen bytes; the rest is one description carried
byte-identically on both review tools, which is the duplication issue #41 is about. It is
kept because `confidence` is now two things - the backend's own rating, and the `low` amicus
substitutes where it also withholds the verdict - and it has two misreadings to prevent, both
of which invert the value: `unknown` read as a low rating, and a high rating read as evidence
that coverage was complete (issue #53).

The schema-11 -> schema-12 raise (+106 bytes) buys interpretability, not prose. 63 of it is
the tier name itself: nine tools carried `alpha`, seven bytes shorter than the `experimental`
that replaced it, and a tier outside the closed set is one an agent cannot filter on at all
(issue #43). The other 43 are `amicus_capabilities`'s output schema, which now publishes
`stability` as the three-value enum instead of a bare string, so a caller reads the legal set
off the schema rather than inferring it from one observed value.

The schema-15 -> schema-16 raise (+6560 bytes over the last MEASURED, 151 of which predates
it on main) is the `coverage` object, on exactly the three tools that return it: +2065 each
for amicus_review_changes and amicus_adversarial_review, and +2279 for amicus_dry_run, which
also gained `focus` and `max_input_bytes`. About 2660 bytes is structure - the object, its
RedactionSummary and their constraints, inlined per tool - and about 3750 is prose, after
compaction had already removed 3806 bytes. What remains guards specific misreadings: that
`complete` means every line was examined, that `focused` or `tree_changed_during_gather`
withheld something, that the tree-change signal's absence proves the tree held still, and
that a null `redaction` beside `redacted` means nothing was redacted (issue #65).

The schema-16 -> schema-17 DROP (-10474 bytes on the `all` profile: 105485 -> 95011; o200k_base
26046 -> 23800 tokens, cl100k_base 25151 -> 22915) is issue #41. Almost all of it is
repetition rather than removed meaning; the rest is narrowing, not removal. Each tool's schema
is self-contained on the wire, so the six parameter contracts in schemas/params.py were paid
once per tool that declares them (workspace_root fifteen times, reasoning_effort and
backend_options ten each): their inline summaries are now one line plus the amicus://params
pointer, and the elaboration moved into the `full` text there, which was already the
authoritative contract. The selection-time facts each summary must keep are pinned in
tests/test_params.py. `default: null`, which pydantic stamps on every optional parameter and
which said nothing beyond the parameter's absence from `required`, is stripped at list time
(compaction.py; ~2 KB). The two pointer descriptions on every outputSchema are one clause
each. The narrowing: the four async tools' `follow_up` is a JobFollowUp with `const`
next_step/tool instead of the whole RepairStep enum, which is not repetition but the
withdrawal of advertised values the field never carried. Nothing the earlier paragraphs chose
to keep was touched: the findings_diagnostics, confidence and coverage prose is intact.

The schema-17 -> schema-18 raise (+1744 bytes on the `all` profile: 95011 -> 96755) buys a
parameter, not prose. `idempotency_key` reached the four sync paid tools (#66): four more
copies of the same one-line summary plus its schema property are about 1000 bytes, the
irreducible cost of the per-tool summary shape #41 chose. The rest is the keyed-wait
qualification on `timeout_seconds` and the two server-instructions sentences that used to say
categorically that a sync timeout terminates the run and that cancelling a task cancels its
job; both are now false for a keyed call, and a description that stays categorical would
misdirect the agent that reads it; the `timeout_seconds` sentence also says that for a keyed
call it bounds only the wait, because the run gets the job deadline. Three error codes were
added to each sync tool's catalog, which lives in amicus_capabilities and not on this wire.

The schema-21 -> schema-22 raise (+1517 bytes on the `all` profile: 96886 -> 98403) buys a
concise default on the two free discovery tools (#46), and is paid back on the first call to
either: the default amicus_capabilities result fell from 27,842 to 14,864 bytes and the default
amicus_backends result from 17,250 to 4,000, both carriers. On this wire it is two new
parameters, amicus_backends' `detail` and amicus_capabilities' `include_tool_details`, each
with the one-line description that says what the projection leaves out; the four disclosure
fields on amicus_backends' outputSchema, which now carry one short description each so a
reader of the schema knows an absent key means "not requested" and a null means no loaded
plugin declares one;
the new `omitted_fields` property that names the projection in-band; and the two tool
descriptions, which now say to read detail=full before the first paid call.

The schema-22 -> schema-23 raise (+5825 bytes on the `all` profile: 98403 -> 104228) is
`lists_diagnostics` on the three tools whose prose lists are parsed from backend output
(#52), the same trade #38 made for `findings_diagnostics` and about the same size. About 1750
bytes is prose: one description per tool, carried on the field rather than on each member's
`reasons`, where the first draft inlined it nine times for 2400 bytes more. The rest is
structure - the object, its three nullable members and their `dropped`/`reasons` shape, inlined
per tool. The prose guards the misreadings the field exists to prevent: that a null member
beside an empty list means the backend said none, and that `dropped: 0` under
`number_stringified` means nothing was lost. amicus_delegate does not carry the field, so it
pays nothing. 644 of the bytes are one clause on both diagnostics' descriptions, on every
tool that carries them, naming the case Copilot's review found undocumented: on a `not_run`
review no backend ran, both are null, and `review_status` is the signal.

The schema-26 -> schema-27 raise (+9042 bytes on the `all` profile: 104676 -> 113718) is the
deprecation window for `amicus_dry_run`, and it is temporary (#98, ADR 0028). The review preview
now ships under its own name, `amicus_review_changes_dry_run`, and the old name stays listed as
a deprecated alias until 0.5.0, so almost all of the bytes are the alias's record. It keeps the
whole record: the same input schema, so callers keep working; the same outputSchema byte for
byte, because [3.output-schema] binds every data-bearing tool; and the replacement's description
behind a one-sentence deprecation lead, because a host may never show `_meta` to the model and
the sentence saying a preview does not bound what the backend reads has to survive on either
name. A lean alias without the outputSchema would have cost about 4 KB less and was rejected
for that reason. The bytes come back when the alias is removed. The 448 bytes between the last
MEASURED and 104676 predate this change: they accumulated on main inside the old budget.

The schema-28 -> schema-29 raise (+953 bytes on the `all` profile: 113730 -> 114683) makes the
job hint honest about terminal jobs (#101). A replayed keyed `_async` start can hand back a job
that has already finished, whose `poll_after_ms` is now null. All 953 bytes are tool records.
The field gains a null branch on the four `_async` outputSchemas, 28 bytes each. It gains a
one-line description, 112 bytes on each of the six outputSchemas that carry it: the four
`_async` tools, amicus_job_status and amicus_job_cancel. Without it, a schema-only reader sees
an integer-or-null with no rule for the null. The four `_async` descriptions gain 29 bytes each
and amicus_job_status's gains 53, so that every instruction to wait on the hint says it applies
only while the job runs. The 12 bytes between the last MEASURED and 113730 predate this change:
they accumulated on main inside the old budget.

The schema-31 -> schema-32 raise (+832 bytes on every profile: all 114780 -> 115612) delivers a
review whose answer amicus could not read instead of discarding it (#139). It adds the
`unstructured` value to `review_status` and says what it means where a caller reads that field
and the diagnostics beside it, on amicus_review_changes and amicus_adversarial_review. About 530
bytes are the enum value and one sentence each on `findings_diagnostics` and `lists_diagnostics`
saying what they report when nothing was parsed. About 300 are a one-sentence `review_status`
description naming where the unparsed answer is, cut from a 606-byte draft that also restated
`completed` and `not_run`.

The schema-32 -> schema-33 raise (+704 bytes on every profile: all 115612 -> 116316) stops
`max_budget_usd` from reading as a ceiling (#158). All 704 bytes are the option's description,
64 bytes longer on each of the eleven input schemas that inline `backend_options`: "per-call
best-effort spend cap" becomes "per-call stop threshold ... checked only between model calls, so
the estimated cost can exceed it". A recorded budget stop carried the cost 4.972 times past the
threshold on one tiny call, and a caller who reads the field as a cap budgets on it; the
sentence that prevents that has to be on the wire, since the field is where it is read. It states
the mechanism and no overshoot bound.

The schema-33 -> schema-34 move (-7 bytes on every profile: all 116316 -> 116309) is the
`amicus_backends` description saying "env warnings" where it said "legacy-env warnings" (#176):
the sibling env names are no longer read, so there is no legacy-env warning to name, and the
retired-name warning the tombstones add is an env warning like any other. Nothing else on the
wire moves. MEASURED and BUDGET both move down by the 7 bytes, so the budget keeps no headroom.

The schema-34 -> schema-35 raise (+2976 bytes on every profile: all 116309 -> 119285) is the
retention disclosure of #163 (ADR 0035): 321 bytes of `tools/_resolve.RECORD_RETENTION` on each
of the eight paid tools, sync and async, saying the job record keeps the backend's whole answer,
best-effort secret-redacted and able to quote the caller's inputs, whatever `detail` delivered
it, and what ends it (expiry, removed lazily on a later job call; the cap; consume); plus 68
bytes on each of the six `detail` parameters saying `detail` shapes delivery only. The record
has kept the answer since M2; what was missing was the sentence where the spend is. MEASURED
and BUDGET both move by the 2976 bytes, so the budget keeps no headroom.

The schema-35 -> schema-36 raise (+888 bytes, 119285 -> 120173 on "all") is #140's new
`findings_diagnostics` reason, `backend_artifact_reference_removed`: the enum value and one
sentence of `_REASONS_DESC`, inlined once per tool that carries findings, sync and async. A
first draft cost 1344; the sentence was cut to what a caller needs (what was cleared, that
nothing openable was lost) and a second mention in `dropped`'s description was removed.
MEASURED and BUDGET both move by the 888 bytes, so the budget keeps no headroom.

The schema-37 -> schema-38 raise (+1456 bytes, 120173 -> 121629 on "all") is #103 and #178,
each measured alone on the wire rather than estimated. #103 gives the async handle a second
`follow_up` shape, `JobResultFollowUp`, so a terminal handle can say fetch rather than poll:
1384 bytes, 346 on each of the four `_async` tools, for a shape with no description at all. It
has to be a second correlated shape rather than two widened literals, which would admit a
mismatched step/tool pair, so that is the floor. #178's corrected `idempotency_key` summary is
9 bytes longer on each of the eight paid tools (72). schema-37 itself moved nothing here:
error codes do not ride tools/list.
MEASURED and BUDGET both move by the 1456 bytes, so the budget keeps no headroom.

The schema-38 -> schema-39 DROP (-9076 bytes, 121629 -> 112553 on "all") is #204: the
deprecated `amicus_dry_run` alias is removed at the end of its window. It carried the review
preview's whole input schema and outputSchema a second time, plus its deprecation marker and
the deprecation sentence at the head of its description, which is the temporary cost the
schema-27 paragraph above said would come back at removal (ADR 0028). Measured on the wire,
not computed. MEASURED and BUDGET both move down by the 9076 bytes, so the budget keeps no
headroom.

The schema-39 -> schema-40 DROP (-2 bytes, 112553 -> 112551 on "all") is #213:
`amicus_job_consume_result` and `amicus_job_cancel` now carry `destructiveHint: true`, one
byte shorter than `false` on each. The `annotations_reading` sentence that explains it is
on `amicus_capabilities`'s result, not on tools/list. Measured on the wire. MEASURED and
BUDGET both move down by the 2 bytes, so the budget keeps no headroom.
"""

from __future__ import annotations

import pytest
from tests.conftest import spawned_server_env

from amicus import manifest

MEASURED: dict[str, int] = {"all": 112551, "codex-kimi": 112559, "claude": 112551}
# The budget is a literal, not MEASURED rounded up to the next kilobyte as it was until
# 2026-09-14. The rounding left up to 1 KB of growth per bucket that no PR had to own, and
# this file records three such accumulations (448 and 12 bytes in the paragraphs above, and
# the 97 bytes between the schema-29 measurement and 114780, the consume-result wording of
# #94 that landed after it), each noticed only when the next deliberate raise re-measured.
# Any growth now fails until a PR raises BUDGET and says why; a shrink passes and shows as
# drift against MEASURED. Raising one means re-measuring and moving both.
BUDGET: dict[str, int] = {"all": 112551, "codex-kimi": 112559, "claude": 112551}


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
def test_tools_list_wire_size_budget(profile):
    size = manifest.tools_list_bytes(profile, env=spawned_server_env())
    assert size <= BUDGET[profile], (
        f"[{profile}] tools/list is {size} bytes (target {MEASURED[profile]}), over the "
        f"{BUDGET[profile]} budget. Compact a description or schema, or raise the budget "
        "deliberately."
    )


def test_measured_values_are_real():
    assert all(n > 0 for n in MEASURED.values())


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
def test_the_budget_admits_no_unreviewed_growth(profile):
    """The negative control for the ratchet: one byte over the last deliberate measurement
    is over budget. A budget above MEASURED is exactly the unreviewed headroom the old
    rounding gave away, so raising one means re-measuring and moving both."""
    assert BUDGET[profile] == MEASURED[profile], (
        f"[{profile}] BUDGET {BUDGET[profile]} leaves {BUDGET[profile] - MEASURED[profile]} "
        f"bytes of headroom over MEASURED {MEASURED[profile]}"
    )
    assert MEASURED[profile] + 1 > BUDGET[profile]
