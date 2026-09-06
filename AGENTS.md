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
7. Write one implementation plan per milestone and open one draft PR per plan.
8. Never merge a PR, never approve your own PR, and never commit to `main`; the maintainer merges.
9. Never change `.github/**`, `AGENTS.md` or `CLAUDE.md` inside a milestone plan; those change only in a PR of their own.
10. When a change touches a category in `FINGERPRINT_COVERS` (`src/amicus/schemas/fingerprint.py`), bump `FINGERPRINT` and regenerate the pins under `tests/fixtures/` in their own commit.
11. When a stored job result's shape changes, bump `RESULT_FORMAT` in the same file.
12. Write commit messages and PR titles as Conventional Commits, `type(scope): subject`, with an imperative lowercase subject and no trailing period, using only the types and scopes in `scripts/check_commit_message.py`.
13. When a change needs a new commit scope, extend `scripts/check_commit_message.py` in that same change.
14. Pin every `uses:` in a workflow to a full commit SHA with the version in a trailing comment.
15. Never add a `pull_request_target` workflow.
16. Under `docs/`, write Markdown with one sentence per line.
17. Never edit a sibling checkout (`~/projects/codex-in-claude`, `~/projects/moonbridge`, `~/projects/claude-in-codex`, `~/projects/pontonier`).
18. Never write a prompt input (`question`, `task`, `extra_context`, `instructions_append`, `focus`) to disk, to a worker's argv or to a log; it travels over the worker's stdin.

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
The execution model, `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`, is the source of rules 7 to 9.
Each milestone is planned as `docs/superpowers/plans/YYYY-MM-DD-amicus-M<n>-<slug>.md` and executed task by task in a sibling worktree (`~/projects/amicus-wt-<slug>`) on a `feat/` branch.
Decisions with lasting consequences are ADRs under `docs/adr/`.
The README's "Where things are" table indexes the rest.

### Siblings

The sibling checkouts named in rule 17 are read for porting, and their virtualenvs are used to capture differential fixtures (`scripts/capture_codex_differentials.py` runs inside codex-in-claude's).

### Local hooks

`prek.toml` mirrors the gate as Git hooks; install once with `uv run prek install --prepare-hooks`.
Pre-commit runs file hygiene, ruff, ty, import-linter, the Actions-pinning check and `uv lock --check`; pre-push runs pytest; commit-msg runs the Conventional Commits check.

### Spend

`amicus_consult`, `amicus_review_changes` and `amicus_delegate` spend the selected backend's quota on every call, and so does the live gate in `tests/test_codex_live.py`.
Unit tests drive `tests/support/fake_codex.py` instead of the real CLI.
