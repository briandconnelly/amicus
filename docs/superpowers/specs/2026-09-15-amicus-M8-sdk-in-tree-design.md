# amicus M8: the backend SDK moves in-tree

- Date: 2026-09-15
- Milestone: M8, shipping in 0.4.0
- Status: design approved by the maintainer on 2026-09-15, including decision 6 and changes 1 and 6 below.
- Review: Codex reviewed the first draft (commit `f40ecaf`) and its three factual findings are fixed; the maintainer approved this written form on 2026-09-15, and M8 was planned and executed from it.
- Decides issue #13 (separate repositories or one uv workspace): neither.

## Why

pontonier was created so that codex-in-claude, moonbridge and claude-in-codex could share one core.
Those three were combined into amicus, which is now the only consumer still being developed.
Keeping the core in its own repository costs a second release process, an exact pin (`pontonier==0.9.0`) and a version bump for every SDK change amicus needs.
This milestone moves pontonier's code into amicus, so an SDK change becomes an ordinary amicus change.

## Decisions

These were settled with the maintainer while brainstorming, and the plan does not reopen them.

1. **pontonier stays published for the siblings.**
   amicus drops the dependency, but pontonier is not archived: it stays feature-frozen at 0.9.0 and is maintained only for the three siblings until they are archived.
2. **Move first, dissolve later.**
   M8 copies the code mechanically into one subpackage.
   Merging its modules into the amicus packages that own each concern is follow-up work, one small PR per issue.
3. **A plain copy, not a history merge.**
   Files are copied from the `v0.9.0` tag, commit `185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d`, which is also pontonier's `main`.
   History and blame stay reachable in pontonier's repository.
4. **The subpackage is `amicus.sdk`.**
5. **It ships in 0.4.0.**
   The approved design branches M8 after the 0.3.0 release so the move never sits inside a release window; 0.3.0 shipped on 2026-09-15, so that precondition is met.
6. **`PLUGIN_API_VERSION` moves from 1 to 2.**
   M8 changes which types a plugin must hand amicus, from pontonier's classes to `amicus.sdk`'s, and the version is the registry's declared compatibility gate (`src/amicus/registry.py:61-66`).
   The bump rejects only a plugin that pins `api_version=1`, because `BackendPlugin.api_version` defaults to the running amicus's own constant (`src/amicus/plugin.py:107`); fixing that default is #115, outside M8.

## Changes from the design approved in chat

Writing this spec meant checking the chat design against the tree.
Three of its premises did not hold, and three consequences had not been considered.
The first item changed a choice the maintainer had approved, and the sixth reads an existing ADR anew; the maintainer confirmed both on 2026-09-15.

1. **`backend/classify.py` moves too.**
   The approved design left it behind because nothing imports it.
   That holds for `src/`, but pontonier's `tests/test_conformance_fakes.py` imports it: its three fake backends implement `classify_failure` with `classify.classify`, and `tests/test_run_request.py` imports those fakes.
   Leaving it behind would turn the move into a rewrite of the conformance fakes, so it moves with its tests and its removal joins the follow-ups.
2. **The conformance kit stays in the wheel.**
   The approved follow-ups moved "the test kit out of the wheel".
   `src/amicus/registry.py:15` imports `pontonier.testing.conformance` and runs `check_contract` and `check_backend` on every plugin it loads, so conformance is runtime code.
   So is `surface_honesty`, because `check_contract` calls its `find_contract_self_contradictions` (pontonier `src/pontonier/testing/conformance.py:20`).
   Only `pair_parity`, which nothing under `src/` reaches, can leave.
3. **The moved tests need a second rewrite.**
   The approved design expected a package marker to be enough for the moved suite.
   The suite imports its helpers by bare module name (`from conftest import run_git`, `from test_contract import ...`, `from tests.test_conformance_fakes import ...`), and inside amicus `conftest` resolves to amicus's own `tests/conftest.py`.
   Eleven moved modules fail to collect until those imports name `tests.sdk.*` explicitly (rule R2 below).
4. **Third-party plugins change their imports.**
   A backend distribution registered through the `amicus.backends` entry-point group builds on pontonier's types, as `tests/fixtures/fakebackend` does.
   After M8 it imports them from `amicus.sdk`, because a pontonier class is a different class from its amicus copy.
   The server never loads a third-party plugin today, because `AMICUS_BACKENDS` rejects any id outside `BACKEND_IDS` (`src/amicus/config/__init__.py:169`), so only a direct `BackendRegistry.load` call, as in the wheel-seam tests, reaches one.
   The change therefore breaks no running deployment; the CHANGELOG still says so, and the fixture is rewritten.
   Decision 6 marks the change by bumping `PLUGIN_API_VERSION`.
5. **The capture scripts keep importing pontonier.**
   `scripts/capture_codex_differentials.py` and `scripts/capture_kimi_differentials.py` import `pontonier.core.runtime.CommandRun` to feed a sibling's own finalizers, and they run inside that sibling's virtualenv.
   They must use the sibling's pontonier, so no rewrite touches `scripts/`.
6. **ADR 0005's repair vocabulary moves in with the code.**
   ADR 0005 says a `RepairStep` comes from pontonier's `REPAIR_STEPS` and "is added upstream, never invented here".
   After M8 that vocabulary is `amicus.sdk.conventions.envelope.REPAIR_STEPS`, so adding a step becomes an amicus change.
   This unblocks #103, which waits on briandconnelly/pontonier#30; ADR 0029 records the reading.

## 1. Package shape

`src/amicus/sdk/` holds pontonier's four layers, `core`, `backend`, `conventions` and `testing`, with every file name kept: 26 files and 8,144 lines at the tag.

The move allows these edits and no others:

- **R1, imports.**
  `pontonier.<layer>` becomes `amicus.sdk.<layer>` and `from pontonier import` becomes `from amicus.sdk import`, in code and in dotted references inside docstrings.
- **R2, test helpers.**
  In the moved tests, `from conftest import` becomes `from tests.sdk.conftest import`, and `from test_<name> import` and `from tests.test_<name> import` become `from tests.sdk.test_<name> import`.
  This matches amicus's own `from tests.conftest import` convention.
- **R3, import order.**
  `ruff check --fix` re-sorts the rewritten imports.
- **R4, the package root.**
  `amicus/sdk/__init__.py` gets a docstring naming the origin tag and commit, and loses `__version__` with its `importlib.metadata` lookup, which raises `PackageNotFoundError` once pontonier is not installed.
- **R5, prose.**
  Under `src/amicus/`, prose that presents pontonier as a library amicus depends on is reworded, both in the moved files and in amicus's own docstrings and comments (for example "the frozen pontonier contract" in each backend's `__init__.py`).

After R5, a grep for `pontonier` under `src/` finds only two kinds of hit.
The first is provenance: the origin note, and issue links such as `briandconnelly/pontonier#29`.
The second is four literal defaults in `core/worktree.py`: `WORKTREE_PREFIX = "pontonier-worktree-"`, the identity pair `"pontonier"` and `"pontonier@local"`, and the `"pontonier-nohooks-"` temporary-directory prefix.
amicus passes its own prefix and identity (`src/amicus/orchestration/isolation.py:19-21`), so the first three never take effect.
The nohooks prefix is not configurable and names a directory amicus really creates.
Renaming any of the four changes behaviour, so all four wait for a follow-up.
That follow-up was #123: the defaults are amicus's own values now, `isolation.py` no longer overrides anything, and the only hit left under `src/` is the first kind.

Not moved: pontonier's docs, scripts, README, CHANGELOG and `pyproject.toml`, and its `tests/test_version.py`, which tests the lookup R4 removes.

## 2. Boundaries and dependencies

- **Import contracts.**
  Two import-linter contracts join the three in `pyproject.toml`.
  "the sdk never imports the rest of amicus" forbids `amicus.sdk` from importing any other top-level `amicus` module.
  "sdk core is a leaf layer" forbids `amicus.sdk.core` from importing `amicus.sdk.backend`, `amicus.sdk.conventions` or `amicus.sdk.testing`, porting pontonier's only contract.
  `tests/test_import_contracts.py:17` pins the kept-contract count, which moves from 3 to 5.
- **Dependencies.**
  `pontonier==0.9.0` leaves `[project] dependencies` and `uv.lock` is regenerated, leaving `anyio`, `fastmcp`, `mcp` and `pydantic`; `anyio` is already a direct dependency.
  `tests/test_packaging.py` pinned that set twice, as the name list on line 60 and the `pontonier==0.9.0` requirement string on line 61; the name list changes and the requirement-string assertion goes.
- **Plugin API version.**
  `src/amicus/plugin.py:27` becomes `PLUGIN_API_VERSION = 2` (decision 6), and `tests/test_plugin.py:13`, which pins 1, changes with it.
  The constant appears only in `plugin.py` and `registry.py`, on no wire surface, so it moves no `FINGERPRINT_COVERS` category.
- **Logging.**
  `obs.py` drops `LIBRARY_LOGGER_NAME` and its entry in `configure()`.
  An `amicus.sdk.*` logger descends from `amicus`, which stops propagation and carries the policy handlers, so in a process that has called `obs.configure` its records reach the same `PolicyStreamHandler`, `PolicyFileHandler` and `PolicyFormatter` that the separate `pontonier` logger had.
  The job worker never calls `obs.configure`, before or after M8, so there SDK records fall through to `logging.lastResort` and the worker's `stderr.log`; #128 tracks that, and M8 leaves the routing as it was.
  The tests that name the `pontonier` logger (`tests/test_obs.py:19`, `tests/test_log_redaction.py:35` and `tests/test_fastmcp_argument_log.py:329`, `:337` and `:413`) instead show that a record logged on an `amicus.sdk.*` logger passes through the policy.
  Their mutation control sets `propagate = False` on `amicus.sdk` and watches them fail.
- **Fingerprint and result format.**
  `FINGERPRINT` and `RESULT_FORMAT` do not move, and rule 10 does not apply.
  No category in `FINGERPRINT_COVERS` covers a dependency or a module path.
  The job store writes JSON, and the tag's `src/` contains `pontonier` only in docstrings and the four defaults above, so no stored record carries a pontonier-named value and records written by 0.3.0 stay readable.
  The pinned manifest, wire-shape and fixture tests pass unchanged, and they are the control that shows it.
- **Provenance check.**
  A plan step rebuilds the move from the tag, reading `~/projects/pontonier` with `git show v0.9.0:<path>` (rule 17 permits reading), applies R1 to R3 with the Ruff version `uv.lock` pins, and diffs the result against the move commit.
  The verbatim copy with R1 to R3 lands in a commit of its own, so the expected diff is empty; R4, R5 and the amicus-side wiring land in later commits, outside the comparison.
  That lets review check one empty diff instead of reading 8,000 lines.
  The check runs once and its output goes in the PR body; it is not a committed test, because CI has no pontonier checkout.

## 3. Tests

- pontonier's suite lands under `tests/sdk/`: its `conftest.py` (autouse git-environment isolation, `run_git`, `scrubbed_git_env`, `GIT_ISOLATION_VARS` and `make_run`), 29 test modules, and an empty `__init__.py`.
- That package marker lets the five basenames the two suites share (`conftest.py`, `test_envelope.py`, `test_fingerprint.py`, `test_prompts.py` and `test_workspace.py`) import under distinct names.
- The autouse guards in amicus's root `tests/conftest.py` apply to `tests/sdk/` unchanged, so rule 6 holds without touching the guard.
- After R3 the moved tests trip no ruff rule, because amicus's `tests/**` per-file ignores already cover what they need.
- `fail_under` stays at 95; the combined suite measured 96.66% in the probe below.
- `tests/fixtures/fakebackend` gets R1.
  The wheel-seam tests keep proving that a separately installed distribution loads, and now also prove that the amicus wheel carries `amicus.sdk` and installs without pontonier.

## 4. Docs and governance

- **ADR 0029** records the decision.
  One consumer is left, so the SDK lives in-tree.
  It names what moved and the tag and commit it came from, explains why pontonier stays published, and states the divergence policy below and the ADR 0005 reading above.
  It answers #13; the AGENTS.md update that completes #13's definition of done lands in the governance PR (rule 9), so the M8 PR references #13 without closing it.
- **ADR 0023** gets a one-line note that the separate `pontonier` logger is gone, since its lines 10, 45 and 53 name it.
  Every other ADR that names pontonier stays as written, as history.
- **The design spec** (`docs/superpowers/specs/2026-09-04-amicus-design.md`) keeps its pontonier paragraph, reuse table and M-1 row as history.
  Its import-rule sentence, which lets `backends/*` import "... and pontonier", states current policy, so it names `amicus.sdk` instead.
  Its plugin sketch's `PLUGIN_API_VERSION = 1` (line 181) becomes 2, and its Milestones table gains an M8 row.
- **`docs/MIGRATION.md:210`** ("not pontonier's 10 s") is reworded.
- **`docs/DEPRECATING-SIBLINGS.md`** is reworded where it says amicus depends on pontonier (line 15) and where it describes pontonier's release gate (lines 54 to 57).
- **The README's Development table** lists this spec beside the design spec.
- **`CHANGELOG.md`** gets an Unreleased entry.
  It says that amicus no longer depends on pontonier, that a third-party backend imports the SDK types from `amicus.sdk`, and that the plugin API version is now 2.
  It carries no Breaking or Surface label, because the fingerprint does not move.
- **`scripts/check_commit_message.py`** gains an `sdk` scope in the same PR (rule 13).
- **AGENTS.md** changes in a governance PR of its own after M8 merges (rule 9): its "built on FastMCP and the pontonier backend SDK" sentence and its Siblings paragraph.
  Rule 17 keeps naming `~/projects/pontonier`, which is still a sibling checkout.

## 5. Divergence policy

- From the merge on, amicus's copy is authoritative for amicus.
- pontonier stays published and is maintained only for the three siblings, feature-frozen at 0.9.0.
- Nothing keeps the two copies aligned.
  When an SDK fix in amicus also affects a sibling's pinned pontonier, backporting it is the maintainer's decision and the maintainer's work, since rule 17 keeps agents out of that checkout.
- Five open pontonier issues describe behaviour amicus ships.
  They are #27 and #28 (partial and failed deletes in `JobStore._rmtree`), #30 (no repair step for fetching a finished job's result), #31 (no safe discard of a terminal-error record) and #15 (a clean conformance result reads as stronger evidence than it is).
  Each gets an amicus issue that cites it, except #30, which amicus #103 already tracks.
  The pontonier originals stay open for the siblings.
- The other open pontonier issues are not mirrored.
  #29 (the 10 s poll cap) is already worked around in `src/amicus/jobs/polling.py` (#95).
  #5 to #8 are redaction test and matcher enhancements with no defect visible in amicus.

## 6. Sequencing and follow-ups

- M8 was one plan, which was executed and then deleted as the execution model requires (git history keeps it), and one PR, #129, from `feat/m8-sdk-in-tree`.
- The plan ends by filing the dissolution issues, one per concern:
  1. `core.jobs`, `core.idempotency` and `core.jsoncache` into `amicus.jobs`, folding in the poll-cap workaround.
  2. `core.worktree`, `core.gitdiff`, `core.runtime` and `core.workspace` into `amicus.orchestration`.
  3. The `conventions` vocabulary (`envelope`, `annotations` and `fingerprint`) into `amicus.schemas`.
  4. `testing.pair_parity` out of the wheel into `tests/support`, with `testing.conformance` and `testing.surface_honesty` staying because the registry runs conformance and conformance calls `surface_honesty`.
  5. `backend/classify.py` retired: the conformance fakes stop using it and it is deleted.
  6. The four pontonier-named defaults retired, of which only the nohooks prefix changes anything on disk.
ADR 0030 supersedes both the list above and the "Modules no issue names" bullet below, because three of those moves would each have broken an import boundary.
Two break the backend one: a backend may not import `amicus.orchestration` (#119's destination for `core.runtime`) or `amicus.jobs` (#118's for `core.jsoncache`).
The third breaks the sdk's own: `sdk.backend.protocol` needs `conventions.envelope`, and the sdk may not import `amicus.schemas`, which is where #120 would have put it.
So `core.runtime`, `core.jsoncache`, `conventions.envelope` and `conventions.annotations` stay in `amicus.sdk`; `core.gitproc` moved to `amicus.orchestration` with the rest of the git layer; and `conventions.prompts` joined issue 3's scope.

- Modules no issue names (`backend.protocol`, `backend.contract`, `core.redaction`, `core.gitproc`, `core.streamcap`, `conventions.preflight` and `conventions.prompts`) stay in `amicus.sdk` until an issue argues otherwise.
  `backend.protocol` and `backend.contract` are what a plugin imports, so moving either changes every plugin's imports again.
- The only step in pontonier's repository is optional and the maintainer's: noting in its README that amicus no longer consumes it.

## Out of scope

- Any change to behaviour, the wire, stored records or the four pontonier-named defaults.
- The dissolution itself.
- Any edit to the pontonier repository or another sibling checkout (rule 17).
- AGENTS.md and anything under `.github/` (rule 9).

## Evidence

The design's feasibility was probed on 2026-09-15 against a scratch copy of amicus `7c11499`.
The probe moved pontonier `v0.9.0` in with R1 to R3, removed `pontonier==0.9.0` from the dependencies, and added the two contracts.
It put an import stub for `pontonier` that raises `ImportError` first on `sys.path`, so any import that still reached pontonier would fail.
It ran the tools from amicus's virtualenv rather than through `uv run`.
Nothing from the probe is committed.

| Check | Result |
| --- | --- |
| `import pontonier` or `from pontonier` left under `src/` and `tests/` after R1 and R2 | none |
| `ruff check` before R3 | 96 findings, all `I001`, all auto-fixable |
| `ruff check` after R3, and `ruff format --check` | pass; 295 files already formatted |
| `ty check` | pass |
| `lint-imports` with the two new contracts | 5 kept, 0 broken |
| Mutation control: `amicus.sdk.core.jsoncache` imports `amicus.errors` | both new contracts broken |
| `pytest tests/sdk` after R1 only | 11 collection errors, from bare-name helper imports resolving to amicus's `conftest` |
| `pytest tests/sdk` after R2 | 1,483 passed |
| Full `pytest` with coverage | 2,992 passed, 5 failed, 1 skipped; total coverage 96.66% |
| The five failures, re-run after R4 and the `test_packaging.py:61` edit | 4 pass; the fifth is the pinned contract count |

The five failures were:

- `tests/test_packaging.py::test_runtime_dependencies_are_exactly_the_spec_set` asserted `"pontonier==0.9.0"` on line 61, an edit M8 makes.
- `tests/test_packaging.py::test_the_committed_manifest_command_starts_a_real_server` and both `tests/test_wheel_seam.py` tests failed because the server and the installed wheel died on `_version("pontonier")` in the moved `__init__.py`, which is R4's reason to exist.
- `tests/test_import_contracts.py::test_import_linter_contracts_hold` first failed because it requires `uv run`; with `lint-imports` on `PATH` it failed on its pinned `Contracts: 3 kept, 0 broken`, which M8 changes to 5.
