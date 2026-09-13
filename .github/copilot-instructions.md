# Copilot code review instructions

Review guidance for GitHub Copilot code review in this repository.
`AGENTS.md` holds the rules every contributor and reviewer works under; this file adds what a reviewer needs on top of it and does not restate it.
Rule numbers below refer to the numbered list under "Rules" in `AGENTS.md`.
Copilot reads this file from a pull request's head branch, so the pull request that changes it is reviewed under the changed version.

## Rules

1. When a comment enforces a repository convention, name the `AGENTS.md` rule number it enforces.
2. Never ask a pull request to change a tool name, parameter, description, error code, value enum, result envelope or stored result shape as a review fix.
   Those categories are listed in `FINGERPRINT_COVERS` (`src/amicus/schemas/fingerprint.py`); a change there moves `FINGERPRINT` or `RESULT_FORMAT`, needs its own pin-regeneration commit (rules 10 and 11), and is decided in a milestone plan or by the maintainer (rule 7).
   State the concern and say that it needs a decision, instead of proposing the change.
3. Never propose a hand edit to a file under `tests/fixtures/` or to `uv.lock`; they are regenerated.
   If a pin looks wrong, say which source of truth it disagrees with.
4. Never flag a backend's disclosed prompt carrier as a rule-18 violation: Kimi's handshake file and Codex's `-c developer_instructions` argv token are the two exemptions rule 18 names.
   Flag every other path that writes a prompt input to disk, to argv or to a log.
5. For every defect, give a concrete input or sequence that produces the wrong outcome; if you cannot, label the comment a question.
6. Do not comment on what the gate already checks (listed under Context), unless the pull request changes the gate itself.
7. Put one issue in each comment, and say whether it blocks merging or is optional.
8. When a test is added or changed, check that its assertion can fail: name the change to the code under test that would turn it red, and flag the test if there is none.
9. When prose describes code (a tool description, a docstring, a README section, `CHANGELOG.md`, an ADR), check the claim against the source in the same pull request and flag any claim the code does not bear out.
10. Under `docs/`, flag a prose paragraph that wraps one sentence across several lines (rule 16).
11. Under `.github/workflows/`, flag any `uses:` that is not pinned to a full commit SHA (rule 14), any `pull_request_target` trigger (rule 15), and any change that weakens the `verify` job or moves a check into the `pypi` job (rule 22).

## Context

### What the gate already checks

The gate (rule 2) runs `ruff check`, `ruff format --check`, `ty check`, `lint-imports` and `pytest` with a coverage floor, on every supported Python version in CI.
A commit-message hook enforces Conventional Commits, and a pre-commit hook enforces workflow SHA pinning.
Formatting, import order, unused imports, type errors, layer-boundary violations and coverage drops are therefore not review findings.
Nothing in the gate reads Markdown, so rule 16, stale prose and drift between documentation and code are reviewer work.

### Where the risk concentrates

- Prompt inputs (`INPUT_FIELDS` in `src/amicus/request.py`) must reach a worker only over stdin (rule 18).
  Any new log line, error message, argv construction, fixture or committed capture that can carry one of those values is the highest-value place to look.
- `src/amicus/jobs/delivery.py` is the chokepoint through which every stored result is delivered; a schema gap there reaches every client.
- `scripts/check_release_state.py`, `scripts/record_live_gate_evidence.py`, `.github/workflows/publish.yml` and `docs/RELEASING.md` implement rules 19 to 24; check that a change to one keeps the others true.
- Unit tests never reach a real backend binary: `tests/conftest.py` makes the binaries unreachable (rule 6) and `tests/support/fake_codex.py` stands in.
  A test that would only pass with a real `codex`, `kimi` or `claude` on `PATH` is a defect.
