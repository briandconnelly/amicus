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
18. Never write a prompt input — every field in `INPUT_FIELDS` (`src/amicus/request.py`): `question`, `task`, `extra_context`, `instructions_append`, `focus`, `target`, `evidence` — to disk, to a worker's argv or to a log; it travels over the worker's stdin.
    This binds amicus's own handling and everything it commits, including host captures and eval prompt bodies, which are recorded as an id and a `sha256` instead.
    A backend's own native carrier is exempt where that backend offers no alternative and the carrier is disclosed in its `CARRIERS` string and surfaced on `amicus_backends`; the two that exist today are Kimi's handshake file, because kimi ignores stdin, and Codex's `-c developer_instructions` argv token.
    Prompt text that a test or capture script assembles entirely from its own literals is exempt, including the `build_*_prompt` output committed in `tests/fixtures/*_differentials.json`; it stays verbatim, because a differential must show what changed and a hash cannot.
    No exemption reaches text that was copied, derived or replayed from a prompt anyone sent: that stays bound however it is later stored or relabelled.
19. Release in two PRs: the work lands with the version literals untouched, then a `chore(release):` PR moves them together and rolls `## [Unreleased]` in `CHANGELOG.md` into a dated section.
    The literals are `pyproject.toml`, `src/amicus/__init__.py`, `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`.
    `.mcp.json`'s pin is NOT one of them; rule 24 governs it, and a release must not touch it.
    `uv.lock` mirrors the version rather than declaring it: regenerate it in that same PR with `uv lock`, or the `uv lock --check` hook fails.
    Only the maintainer merges that PR, and only the maintainer pushes the tag.
    Push the matching tag before any other work follows that merge: until it exists, `main` declares a version that has no release.
20. Never push a `v*` tag unless the three live gates — `tests/test_codex_live.py`, `tests/test_kimi_live.py` and `tests/test_claude_live.py`, run under rule 5 — have all PASSED on that exact commit, with those passing outcomes recorded.
    The record is `.release-evidence/live-gates.json`, written by `scripts/record_live_gate_evidence.py`, naming that commit, each suite and its outcome; a terminal transcript or a recollection is not a record.
    A record showing a failed suite does not satisfy this rule; it is a reason not to tag.
    Push it as an annotated tag whose message is that record verbatim — `git tag -a vX.Y.Z -F .release-evidence/live-gates.json --cleanup=verbatim <release-sha>` — because `.release-evidence/` is gitignored and the tag is the only carrier that reaches the publish workflow.
21. Never push a `v*` tag unless a repository ruleset restricts creation, update and deletion of `v*` tags, with no agent identity permitted to bypass it.
22. Never weaken the `verify` job in `.github/workflows/publish.yml`, and never let the `pypi` job stop depending on it.
    Never move a release check into the `pypi` job: GitHub holds every step of an environment job behind that environment's required reviewer, so a check placed there runs only after the approval it exists to inform.
23. Never describe the rule-20 record, in any document or output, as proof that the live gates ran.
    It is the maintainer's assertion, machine-checked for shape and for naming the tagged commit; the runs happen on the maintainer's machine and the record is written there.
24. `.mcp.json`'s `--from` pin names a release that is already published, never the one being released, and it may never name a version newer than the one the tree declares.
    A release PR under rule 19 leaves it untouched; move it to the new tag in its own `chore(release):` PR after that tag is published and its install has been checked.
    That PR is not a release: it needs no rule-20 evidence, because it moves a pointer to a tag that already exists.

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

`.mcp.json` pins `git+https://github.com/briandconnelly/amicus.git@v{version}`, and that pin is what a fresh plugin install actually fetches: users add this repository as a marketplace, so the manifest they read is the one on `main`.
Rule 24 therefore keeps it naming a release that is already published rather than the one being released.
A manifest on `main` cannot name an artifact that only exists after `main` has moved, and pinning the version under release meant every release broke a fresh install for the interval between the release merge and the tag push.
Rule 24 removes that interval rather than shortening it.
Two facts decided the shape, and both were established by probe rather than argued: a commit SHA resolves over the same git transport a tag does, so the install path can be rehearsed before any tag exists; and `uvx` reuses a cached tool environment without querying any index, so the version in the requirement string is what makes an existing user pick up a new release — which is why an unpinned source was rejected rather than adopted.
0.1.0 was the bootstrap, tagged and published on 2026-09-09; it named the tag it created because no earlier release existed, and that case cannot recur.
Rule 20 is a local pre-tag gate rather than a CI job: hosted runners have no authenticated `codex`, `kimi` or `claude`, so the evidence is recorded on the maintainer's machine against the exact commit to be tagged.
That evidence is an honest-mistake guard, not an attestation; it is a local file its author can write by hand.
Rule 21 covers creation as well as update and deletion because pushing a `v*` tag is by itself what triggers `.github/workflows/publish.yml`: an identity that can create one can publish a release without rules 19 and 20 ever being satisfied, and a moved tag silently changes what users install under a version they already trust.
That ruleset now exists — `release tags`, active, covering `refs/tags/v*` and restricting creation, update and deletion — and 0.1.0 was tagged under it.
Its bypass list is the part an agent here cannot check: the ruleset response seen from this repository's agent token carries no `bypass_actors` key at all.
GitHub omits that key from responses to requesters without sufficient permission on the ruleset rather than returning an empty list, so its absence is not evidence that nobody may bypass, and must never be reported as though it were.
`docs/RELEASING.md` reads that back with the maintainer's own token rather than assuming it.
The executable procedure — preconditions, the evidence run, the environment approval pause and the post-tag checks — is `docs/RELEASING.md`.

Rules 20, 22 and 23 are shaped by what a CI job can and cannot establish, which is the subject of ADR 0014 and of issue #25 before it.
The `verify` job runs `scripts/check_release_state.py` on the tagged commit, and the two halves of that script are worth different amounts.
Its release-state coherence half **proves** what it reports: every version literal rule 19 names, the dated `CHANGELOG.md` section, and `uv.lock` are all facts of the tagged tree.
Its live-gate half checks only that the record carried on the tag is well formed, names this commit and asserts three passing suites — never that those suites ran, which is why rule 23 forbids saying otherwise.
Everything else rule 19 requires is a convention no CI job can prove: two PRs, an ordinary merge commit rather than a squash, the maintainer merging rather than an agent, and the tag pushed promptly after the merge.
Those are held by the platform controls around the release — rule 21's ruleset and the `pypi` environment's required reviewer — and by whoever runs the procedure, and this repository states that plainly rather than implying the workflow checks it.

### Siblings

The sibling checkouts named in rule 17 are read for porting, and their virtualenvs are used to capture differential fixtures (`scripts/capture_codex_differentials.py` runs inside codex-in-claude's).

### Local hooks

`prek.toml` mirrors the gate as Git hooks; install once with `uv run prek install --prepare-hooks`.
Pre-commit runs file hygiene, ruff, ty, import-linter, the Actions-pinning check and `uv lock --check`; pre-push runs pytest; commit-msg runs the Conventional Commits check.

### Spend

`amicus_consult`, `amicus_review_changes` and `amicus_delegate` spend the selected backend's quota on every call, and so does the live gate in `tests/test_codex_live.py`.
Unit tests drive `tests/support/fake_codex.py` instead of the real CLI.
