# Copilot code review instructions

Review guidance for GitHub Copilot code review in this repository.
`AGENTS.md` holds the rules every contributor and reviewer works under; this file adds what a reviewer needs on top of it and does not restate it.
Rule numbers below refer to the numbered list under "Rules" in `AGENTS.md`.
Copilot reads this file from a pull request's head branch, so the pull request that changes it is reviewed under the changed version.

## Rules

1. When a comment enforces a numbered `AGENTS.md` rule, name the rule number.
   A convention that only the surrounding code establishes needs no citation; describe the pattern the change breaks instead.
2. Never ask a pull request to change a tool name, parameter, description, error code, value enum or result envelope as a review fix.
   Those categories are listed in `FINGERPRINT_COVERS` (`src/amicus/schemas/fingerprint.py`); a change there moves `FINGERPRINT` and needs its own pin-regeneration commit (rule 10).
   Never ask for a change to the persisted result shape as a review fix either; that moves `RESULT_FORMAT` in the same file, and its snapshot is regenerated in the same commit as the bump (rule 11).
   Both are decided in a milestone plan or by the maintainer (rule 7): state the concern and say that it needs a decision, instead of proposing the change.
3. Never propose a hand edit to a generated pin: the `*_snapshot.json` and `*_differentials.json` files under `tests/fixtures/`, or `uv.lock`.
   The test that guards each pin names the command that regenerates it; if a pin looks wrong, say which source of truth it disagrees with.
   `tests/fixtures/fakebackend/` is source for the wheel-seam test and is edited by hand.
4. Never flag a use of one of rule 18's exemptions as a violation: a backend's disclosed carrier (Kimi's handshake file, Codex's `-c developer_instructions` argv token), or prompt text that a test or capture script assembles entirely from its own literals, including the `build_*_prompt` output in `tests/fixtures/*_differentials.json`.
   Flag every path rule 18 does not exempt, and treat text copied, derived or replayed from a prompt anyone sent as never exempt.
5. For every defect, give a concrete input or sequence that produces the wrong outcome; if you cannot, label the comment a question.
6. Do not comment on what the gate already checks (listed under Context), unless the pull request changes the gate itself.
7. Put one issue in each comment, and say whether it blocks merging or is optional.
8. When a test is added or changed, check that its assertion can fail: name the change to the code under test that would turn it red, and flag the test if there is none.
9. When prose describes code (a tool description, a docstring, a README section, `CHANGELOG.md`, an ADR), check the claim against the source in the same pull request and flag any claim the code does not bear out.
10. Under `docs/`, flag a prose paragraph that wraps one sentence across several lines (rule 16).
11. Under `.github/workflows/`, flag any `uses:` that is not pinned to a full commit SHA (rule 14), any `pull_request_target` trigger (rule 15), and any change that weakens the `verify` job or moves a check into the `pypi` job (rule 22).

## Context

### What the gate already checks

Rule 2 in `AGENTS.md` is the gate's single definition, and CI runs exactly its commands; anything one of those commands would report is not a review finding.
Nothing in the gate reads Markdown, so rule 16, stale prose and drift between documentation and code are reviewer work.

### Where the risk concentrates

- Prompt inputs (`INPUT_FIELDS` in `src/amicus/request.py`) reach a worker over stdin or over a carrier that rule 18 discloses, and through nothing else (rule 18).
  Any new log line, error message, argv construction, fixture or committed capture that can carry one of those values is the highest-value place to look.
- `src/amicus/jobs/delivery.py` is the chokepoint through which every stored result is delivered; a schema gap there reaches every client.
- `scripts/check_release_state.py`, `scripts/record_live_gate_evidence.py`, `.github/workflows/publish.yml` and `docs/RELEASING.md` implement rules 19 to 24; check that a change to one keeps the others true.
- Unit tests never reach a real backend binary: `tests/conftest.py` makes the binaries unreachable (rule 6) and `tests/support/fake_codex.py` stands in.
  A test that would only pass with a real `codex`, `kimi` or `claude` on `PATH` is a defect.
