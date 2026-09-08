# Agent working conventions

Rules for any agent or human working in this repository.
The rules bind; the context after them explains and points elsewhere.

## Rules

1. Use `uv` for every project and package operation (`uv sync`, `uv run <cmd>`); never pip, poetry or conda.
2. A change is done only when the gate passes:

   ```sh
   uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest
   ```

3. If you touched `.github/workflows/`, also run `uv run python scripts/check_github_actions_pinning.py` before you push.
4. Never lower the coverage floor (`fail_under` in `pyproject.toml`).
5. Never run `-m integration` tests unless the maintainer asked for it in the current session; when asked, run them as `AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov`.
6. Never weaken the guard in `tests/conftest.py` that makes the real backend binaries unreachable for unit tests.
7. Write one implementation plan per milestone and open one draft PR per plan; work that is not a milestone needs no plan, which covers a governance PR under rule 9 and a release PR under rule 19.
8. Unless you are the maintainer, never merge a PR and never approve your own PR; never commit to `main`.
9. Never change `.github/**`, `AGENTS.md` or `CLAUDE.md` inside a milestone plan; those change only in a PR of their own.
10. When a change touches a category in `FINGERPRINT_COVERS` (`src/amicus/schemas/fingerprint.py`), bump `FINGERPRINT` and regenerate the pins under `tests/fixtures/` in their own commit.
11. When a stored job result's shape changes, bump `RESULT_FORMAT` in the same file.
12. Write commit messages and PR titles as Conventional Commits, `type(scope)?!?: subject` (scope optional, `!` marks a breaking change), with an imperative lowercase subject and no trailing period, using only the types and scopes in `scripts/check_commit_message.py`.
13. When a change needs a new commit scope, extend `scripts/check_commit_message.py` in that same change.
14. Pin every `uses:` in a workflow to a full commit SHA with the version in a trailing comment.
15. Never add a `pull_request_target` workflow.
16. Under `docs/`, write Markdown with one sentence per line.
17. Never edit a sibling checkout (`~/projects/codex-in-claude`, `~/projects/moonbridge`, `~/projects/claude-in-codex`, `~/projects/pontonier`).
18. Never write a prompt input (`question`, `task`, `extra_context`, `instructions_append`, `focus`) to disk, to a worker's argv or to a log; it travels over the worker's stdin.
    This binds every prompt that was or could be sent to a backend or a host, including committed captures and eval prompt bodies, which are recorded as an id and a `sha256` instead.
    It does not bind a literal that a test or capture script defines for itself to exercise prompt construction, such as `"Why?"` and `"DIFF TEXT"` in `scripts/capture_*_differentials.py`; those stay verbatim, because a differential must show what changed and a hash cannot.
    A literal qualifies only if it was never copied, derived or replayed from a prompt anyone sent; text that originated in a real backend or host request stays bound however it is later stored or relabelled.
19. Release in two PRs: the work lands with the version literals untouched, then a `chore(release):` PR moves them together and rolls `## [Unreleased]` in `CHANGELOG.md` into a dated section.
    The literals are `pyproject.toml`, `src/amicus/__init__.py`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` and the `.mcp.json` tag pin.
    Only the maintainer merges that PR, and only the maintainer pushes the tag.
    Push the matching tag immediately after that merge, before any other work: the interval in which `main` names a tag that does not yet exist cannot be made zero, so closing it is the only task that may follow the merge.
20. Never push a `v*` tag from a commit whose three live gates — `tests/test_codex_live.py`, `tests/test_kimi_live.py` and `tests/test_claude_live.py`, run under rule 5 — have not all been run and recorded on that exact commit.
    The record is `.release-evidence/live-gates.json`, naming that commit, each suite and its outcome; a terminal transcript or a recollection is not a record.

## Context

### What this is

One MCP server for every second-opinion model: a verb-first tool surface with the backend as a parameter, built on FastMCP and the [pontonier](https://github.com/briandconnelly/pontonier) backend SDK.
The package is `amicus` under `src/`; each backend is a plugin under `src/amicus/backends/<id>/` behind the `BackendPlugin` seam in `src/amicus/plugin.py`.
Import boundaries between layers are enforced by the import-linter contracts in `pyproject.toml`.
A backend's own prompt carriers (for Codex, the developer-instructions argv token and the stdin prompt) are disclosed on `amicus_backends`.

### The gate

Rule 2 is the gate's single definition; other documents link here rather than restating it.
CI (`.github/workflows/test.yml`) runs exactly those commands on every supported Python version and is authoritative; the local hooks below are a convenience.
`pytest` excludes `-m integration` by default (`addopts` in `pyproject.toml`), so the gate never spends quota.

### How work is organized

The design spec is `docs/superpowers/specs/2026-09-04-amicus-design.md`; its "Milestones" table defines each milestone's scope and gate.
The execution model, `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`, is the source of rules 7 and 8; rule 9 widens its rule 6 (workflows, CODEOWNERS, AGENTS.md) to the whole `.github/` tree and `CLAUDE.md`, so every governance file changes the same way.
Each milestone is planned as `docs/superpowers/plans/YYYY-MM-DD-amicus-M<n>-<slug>.md` and executed task by task in a sibling worktree (`~/projects/amicus-wt-<slug>`) on a `feat/` branch.
Decisions with lasting consequences are ADRs under `docs/adr/`.
The README's "Where things are" table indexes the rest.

### Releases

Rules 19 and 20 exist because `.mcp.json` pins `git+https://github.com/briandconnelly/amicus.git@v{version}`.
The moment that pin lands on `main` the matching tag must exist, or a plugin install from `main` fails on an unresolvable ref.
Merging the release PR immediately before pushing the tag is what closes that window.
`main` carries exactly that unresolvable pin today, because 0.1.0 has never been tagged; the first release closes it, and rule 19's last clause is what stops it recurring.
Rule 20 is a local pre-tag gate rather than a CI job: hosted runners have no authenticated `codex`, `kimi` or `claude`, so the evidence is recorded on the maintainer's machine against the exact commit to be tagged.
That evidence is an honest-mistake guard, not an attestation; it is a local file its author can write by hand.
`v*` tags must be protected against update and deletion by a repository ruleset, because the tag is the plugin's installation source and a moved tag silently changes what users install under a version they already trust.
No such ruleset exists yet; creating it is a maintainer prerequisite of the first release, and `docs/RELEASING.md` reads it back rather than assuming it.
The executable procedure — preconditions, the evidence run, the environment approval pause and the post-tag checks — is `docs/RELEASING.md`.

### Siblings

The sibling checkouts named in rule 17 are read for porting, and their virtualenvs are used to capture differential fixtures (`scripts/capture_codex_differentials.py` runs inside codex-in-claude's).

### Local hooks

`prek.toml` mirrors the gate as Git hooks; install once with `uv run prek install --prepare-hooks`.
Pre-commit runs file hygiene, ruff, ty, import-linter, the Actions-pinning check and `uv lock --check`; pre-push runs pytest; commit-msg runs the Conventional Commits check.

### Spend

`amicus_consult`, `amicus_review_changes` and `amicus_delegate` spend the selected backend's quota on every call, and so does the live gate in `tests/test_codex_live.py`.
Unit tests drive `tests/support/fake_codex.py` instead of the real CLI.
