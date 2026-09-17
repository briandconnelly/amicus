# ADR 0032: a Claude review defaults to readonly access

**Status:** Accepted (2026-09-17)

## Context

Every Claude verb defaulted to `backend_options.access = "toolless"`, which grants the model no tools at all.
Issue #116 reported that `amicus_review_changes` on that default does not produce a review.
Asked to judge a diff, the model decided it needed to read the surrounding file, had no tool to do it with, and wrote tool-call markup into its answer instead of the review object.
amicus reported `invalid_json`, and under the verb's default `config_mode = "inherit"` the same run went on to the budget stop instead, at $3.36 against a $1.00 cap.
Holding everything else fixed, the reporter's `readonly` run was the only one of three that produced a review, and it was also the fastest and the cheapest.

`amicus_adversarial_review` already ran structured on the same default because its `target` and `evidence` are self-contained, and because its `--append-system-prompt` carries `OUTPUT_GUARDRAILS`, which tells the model to use only the tools this run has and never to simulate a tool call.
A review received only the critic guardrails.

`toolless` is not the safer choice in every respect.
`readonly` grants `Read`, `Grep` and `Glob`, which let Claude read files itself, bypassing the redaction applied to the gathered diff, and `Read` accepts absolute paths outside the workspace.
That trade is already disclosed on `amicus_backends` as `readonly_honesty`.
Neither mode is an OS sandbox, and under `inherit` or `scoped` the workspace's hooks run outside the tool allowlist whatever `access` says.

## Decision

**`amicus_review_changes` on Claude defaults to `access = "readonly"` while `AMICUS_CLAUDE_ACCESS` is unset.**
`amicus_consult` and `amicus_adversarial_review` keep `toolless`.
A consult that answers in prose is still a valid result, and a critique's inputs are self-contained, so neither verb has the failure this fixes.
The shape is the one `config_mode` already has for adversarial reviews: two option records with disjoint verbs, so discovery reports `default_by_verb`, the dry run echoes the resolved value, and the adapter resolves an omitted `access` the same way for a caller that skips the tool layer.

**A set `AMICUS_CLAUDE_ACCESS` binds every verb, reviews included.**
An operator who configured `toolless` chose to deny tools, and a per-verb default must not quietly widen that choice.
An invalid value counts as set: the existing fallback to `toolless` with a warning then applies to reviews too, so a mistyped restriction never loosens into the review default.
An empty value or an unresolved `${...}` placeholder counts as unset, as it already does for every other `AMICUS_CLAUDE_*` setting.
This deliberately differs from the adversarial `config_mode` default, which applies even when `inherit` is configured: that default narrows what a run loads, whereas this one widens what a run can read, so the operator's word decides.

**A structured review also carries `OUTPUT_GUARDRAILS`.**
A review stays reachable on `toolless`, by the operator's setting or a per-call override, so it receives the same instruction a critique does rather than relying on the default alone.
Consult does not, for the reason above.

## Consequences

A Claude review that omits `access` can now read files in and outside the workspace, and can send what it reads to Anthropic, where it previously could read nothing.
That is a change to what the default permits, disclosed in the CHANGELOG, in `choosing-a-backend.md`, in the `backend_options` contract on `amicus://params`, and in the `AMICUS_CLAUDE_ACCESS` description; `readonly_honesty` already states what `readonly` allows.
The budget overshoot and the zero token counts on the budget-stop path, which the same report observed, are separate defects, tracked as #158.
The `retry_then_report` repair on an `invalid_json` that will not change on retry is issue #139's concern, not this record's.
