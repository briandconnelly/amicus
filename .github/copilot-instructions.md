# Copilot code review instructions

Review guidance for GitHub Copilot code review in this repository.
`AGENTS.md` holds the rules every contributor and reviewer works under; this file adds what a reviewer needs on top of it and does not restate it.
Rule numbers below refer to the numbered list under "Rules" in `AGENTS.md`.
Copilot reads this file from a pull request's head branch, so the pull request that changes it is reviewed under the changed version.

## Rules

1. When a comment enforces a numbered `AGENTS.md` rule, name the rule number.
   A convention that only the surrounding code establishes needs no citation; describe the pattern the change breaks instead.
2. Never propose a new or widened contract as a review fix: a tool name, parameter, description claim, error code, value enum or result envelope the pull request did not already change, or a change to the persisted result shape.
   The surface categories are listed in `FINGERPRINT_COVERS` (`src/amicus/schemas/fingerprint.py`); a change there moves `FINGERPRINT` (rule 10), and a persisted-shape change moves `RESULT_FORMAT` (rule 11); the test that guards each pin states the commit shape it requires.
   A new contract is a design decision, made in a milestone plan or by the maintainer, so state the concern and say that it needs a decision.
   Do ask that a contract the pull request changes match its implementation, its plan and its stated intent; that is a correction, and it still moves the version it touches.
3. Never propose a hand edit to a generated pin: the `*_snapshot.json` and `*_differentials.json` files under `tests/fixtures/`, or `uv.lock`.
   The test that guards each pin names the command that regenerates it; if a pin looks wrong, say which source of truth it disagrees with.
   `tests/fixtures/fakebackend/` is source for the wheel-seam test and is edited by hand.
4. Before flagging a rule-18 violation, read rule 18's exemptions from `AGENTS.md` itself and check the path against them; never flag a use of one of those exemptions, and flag every path rule 18 does not exempt.
5. For every defect, give a concrete input or sequence that produces the wrong outcome; if you cannot, label the comment a question.
6. Do not report what a gate command reports on its own: a lint, format, type, import-boundary or test failure, or a Markdown claim that a test pins (see Context).
7. Put one issue in each comment, and say whether it blocks merging or is optional.
8. When a test is added or changed, check that its assertion can fail: name the change to the code under test that would turn it red, and flag the test if there is none.
9. When prose describes code (a tool description, a docstring, a README section, `CHANGELOG.md`, an ADR), check the claim against the source in the same pull request and flag any claim the code does not bear out.
10. Under `docs/`, flag a prose paragraph that wraps one sentence across several lines (rule 16).
11. Under `.github/workflows/`, check the change against rules 14, 15 and 22 and name the one it breaks.

## Context

### What the gate already checks

Rule 2 in `AGENTS.md` defines the gate; CI runs it, preceded by the Actions-pinning check (rule 3).
Some tests pin Markdown surfaces against the code, for example `docs/MIGRATION.md`'s tool and parameter names and the README install pin; a claim one of those tests pins is gate-covered.
Nothing in the gate checks prose style, so rule 16, stale claims no test pins and unpinned drift between documentation and code are reviewer work.

### Where the risk concentrates

- Rule 18 governs every path a prompt input (`INPUT_FIELDS` in `src/amicus/request.py`) can take.
  Any new log line, error message, argv construction, fixture or committed capture that can carry one of those values is the highest-value place to look.
- `src/amicus/jobs/delivery.py` is the chokepoint through which every stored result is delivered; a schema gap there reaches every client.
- `scripts/check_release_state.py`, `scripts/record_live_gate_evidence.py`, `.github/workflows/publish.yml` and `docs/RELEASING.md` implement rules 19 to 24; check that a change to one keeps the others true.
- `tests/conftest.py` carries the rule-6 guard and `tests/support/fake_codex.py` stands in for the real CLI, so a test that would only pass with a real `codex`, `kimi` or `claude` on `PATH` is a defect.
