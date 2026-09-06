<!-- Keep PRs focused: one milestone plan or one logical change. Conventions: AGENTS.md. -->

## What & why

<!-- One or two sentences: what this changes and the motivation. Milestone PRs link the plan. -->

## Checklist

- [ ] Conventional Commit title (`feat(scope): subject`; types and scopes in `scripts/check_commit_message.py`).
- [ ] The gate passes locally (AGENTS.md → Rules, item 2); CI is authoritative.
- [ ] If the agent-visible surface changed (any `FINGERPRINT_COVERS` category in `src/amicus/schemas/fingerprint.py`): `FINGERPRINT` bumped and the pins under `tests/fixtures/` regenerated in their own commit.
- [ ] If a job record's stored shape changed: `RESULT_FORMAT` bumped.
- [ ] Milestone PRs: the gate result and the perturbation check recorded below; live-gate outcome and spend noted.

## Notes for reviewers

<!-- Deviations from the spec or the sibling, trade-offs, things to look at closely. -->
