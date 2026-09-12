"""Wire-size ratchet for tools/list, per profile.

The least-capable realistic client preloads every tool definition, so the serialized
catalog is a per-session token tax. The budget is a ceiling; the target is the last
deliberate measurement so a failure message shows the drift. Raising a budget is a
reviewed decision — say why in the PR body.

What this ratchet does and does not cover, scoped against captured host evidence rather
than assumed. It bounds the TOKEN COST of discovery. It is not a measure of first-call
success, and a green run here is no evidence that an agent picks the right tool.

The preloading client this budget is written for is real but is not universal. Codex CLI
0.153.4 preloads the catalog, so the tax is paid per session there. Claude Code 2.1.263
does not: it defers MCP tool definitions behind a ToolSearch lookup, so the wire size is a
smaller tax on that host than the budget assumes
(docs/host-captures/install-smoke/claude-code/2.1.263/notes.md). The budget stays the
worst-case ceiling for the clients that do preload.

Measured 2026-09-12 at schema-17 (18 tools; every model result carries
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
"""

from __future__ import annotations

import pytest
from tests.conftest import spawned_server_env

from amicus import manifest

MEASURED: dict[str, int] = {"all": 95011, "codex-kimi": 95019, "claude": 95011}
BUDGET: dict[str, int] = {p: ((n // 1000) + 1) * 1000 for p, n in MEASURED.items()}


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
