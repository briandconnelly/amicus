# ADR 0013: Publish `amicus` to PyPI without trademark clearance

**Status:** Accepted (2026-09-08, before the 0.1.0 release)

## Context

The name was chosen for its meaning.
*Amicus curiae* — "friend of the court" — is an outside party who submits an independent brief that the decision-maker reads and is **not bound by**.
That is the product's safety property stated in one word: a second opinion from a model that is not the actor, advisory rather than authoritative.
`docs/2026-09-04-naming-and-scoping-notes.md` records the reasoning and the alternatives that lost.

Name availability was checked on 2026-09-04 against PyPI, the npm registry, and GitHub search.
`amicus` was free on PyPI, taken on npm, and the top GitHub hit was a dormant Middleman template unrelated to AI tooling.
**Trademark registries were explicitly not checked**, and those same notes record the reason it matters: "Amicus" has commercial use in legal practice-management software.
The notes left it as an open item requiring "a real trademark search before committing to it".

That search has not been performed.
Publishing to pypi.org is the point at which the name stops being provisional: PyPI names are not meaningfully recyclable, and once users install and pin `amicus`, a rename becomes their breakage rather than only ours.
TestPyPI already carries the name, which is low-visibility and not the commitment; pypi.org is.

## Decision

Publish to pypi.org without trademark clearance, as a deliberate decision rather than an unresolved item.

The maintainer weighed the alternatives — a self-run search of USPTO, EUIPO and WIPO records; a lawyer's opinion; renaming before publication — and chose to proceed.
This ADR exists so that choice is legible as a choice.

## Consequences

Accepted, in full:

- A trademark holder could later object and demand a rename.
- By then the cost falls on users who have pinned the package, not only on this project.
- A rename is not a package rename. `amicus_consult`, `amicus_review_changes`, `amicus_delegate` and the rest are the agent-visible tool surface — which is what `FINGERPRINT` exists to track. Renaming moves every tool name, the `AMICUS_*` environment prefix, both plugin manifests, the `.mcp.json` pin, and the fingerprint itself.
- The risk is smallest while the project is MIT-licensed, non-commercial, and in a different field from the known legal-software use. Each of those changing raises it.

## What would reopen this

- A demand letter or any contact from a mark holder.
- Commercial use of amicus, or use under an entity where the exposure is not personal.
- A decision to register a mark, which requires the search this ADR declines.

## Alternatives not taken

- **A self-run search** of the public registries. Free and roughly an hour, and it converts an unknown into a known risk — but it is a search, not clearance, and does not produce defensibility.
- **A lawyer's opinion.** The only path producing genuine clearance, and disproportionate to a personal open-source project at 0.1.0.
- **Renaming now.** Cheapest it will ever be, and rejected because the name is a good fit for the product's central property, not an arbitrary label.
