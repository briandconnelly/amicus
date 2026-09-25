# amicus milestone 3 (2026-09-24 audit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six open issues of GitHub milestone 3, "Agent-friendliness audit (2026-09-24)": #245, #246, #248, #249, #250 and the decision half of #247, as five ordered pull requests, each carrying one fingerprint bump.

**Architecture:** Each PR is a branch off `main` in its own worktree, executed after the previous PR merged, because every PR re-pins the same surface fixtures.
PR A fixes the error contract (#245, #246), PR B the stale client root (#248), PR C the six minor findings (#250), PR D job-list paging (#249), and PR E records the tools/list decision as an ADR and takes the reductions that need no deprecation window (#247).
The implementation of #247's sync/async merge is deferred to its own plan, written after the maintainer accepts that ADR, because a deprecation window's dates and the eleven shipped documents that name the `_async` tools depend on that acceptance.

**Tech Stack:** Python ≥3.11, `uv`, `ruff`, `ty`, `pytest` (95% branch coverage floor), `import-linter`, `prek`; runtime `fastmcp` 4.0.5, `mcp` 2.2.0, `pydantic` 2.

**Spec:** the six issue bodies (`gh issue view 245 246 247 248 249 250`) are the specification; each names its evidence, severity and remediation, and the sections below cite them as "#N".
Binding repo rules: `AGENTS.md`; execution rules: `docs/superpowers/plans/2026-09-04-amicus-execution-model.md`.

## Global Constraints

- Repo `/Users/bdc/projects/amicus`, `main` at `0695d59` (v0.6.0 plus #244), which declares version `0.6.0`, `FINGERPRINT = "amicus/0.1/schema-44"`, `RESULT_FORMAT = 9`, 18 tools, and `tests/test_discovery_cost.py` `MEASURED = {"all": 112683, "codex-kimi": 112691, "claude": 112683}`.
- One worktree per PR, created from an up-to-date `main` only after the previous PR merged:
  ```sh
  cd /Users/bdc/projects/amicus && git fetch origin && git checkout main && git pull --ff-only
  git worktree add /Users/bdc/projects/amicus-wt-<slug> -b <branch> main
  cd /Users/bdc/projects/amicus-wt-<slug> && uv sync && uv run prek install --prepare-hooks
  ```
  Never commit to `main` (rule 8); never merge or approve a PR (rule 8).
- Gate (rule 2), from the worktree, before every push:
  ```sh
  uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run lint-imports && uv run pytest
  ```
  Record each command's exit status separately; a pipe into `tail` reports `tail`'s status, not pytest's.
  The coverage floor is never lowered (rule 4).
- Any `pytest` run on a subset needs `--no-cov`, because `fail_under` applies to every run that measures coverage.
- Rule 10: every PR here changes a `FINGERPRINT_COVERS` category, so each PR bumps `FINGERPRINT` once, in its own commit, by Procedure F below.
  The numbers below assume the PRs merge in order (A → schema-45, B → 46, C → 47, D → 48, E → 49); if `main` already declares a higher number when you bump, use `main`'s number plus one.
  `RESULT_FORMAT` stays 9 in every PR: nothing here changes a stored `result.json` shape, and `error.details.reason` is plain `str` on the wire (ADR 0037).
- ADR numbers assume the same order (A → 0039 and 0040, C → 0041, D → 0042, E → 0043); if `docs/adr/` already holds that number, take the next free one and fix every cross-reference the task writes.
- Rule 18: never write a prompt input (`question`, `task`, `extra_context`, `instructions_append`, `focus`, `target`, `evidence`) to disk, argv or a log; no task here needs to.
- Rules 5 and 6: never run `-m integration`; never touch the guard in `tests/conftest.py`.
- Rule 9: never touch `.github/**`, `AGENTS.md` or `CLAUDE.md`.
- Spend: no task here makes a paid backend call.
  Procedure P asks for a Codex review through amicus only if the maintainer authorized one in the current session; otherwise skip that step and say so in the PR body.
- Commits: Conventional Commits (rule 12) with the types and scopes in `scripts/check_commit_message.py`; end every commit message body with the line `🤖 Generated with Claude Code`.
- Markdown under `docs/`: one sentence per line (rule 16).
  Check every file a task creates or edits under `docs/` with `uv run python scripts/check_sentence_per_line.py .` (it scans the whole `docs/` tree; exit 0 is the pass).
- Tooling traps:
  - `git diff` runs difftastic; pass `--no-ext-diff` whenever you read or pipe a diff.
  - A PostToolUse hook runs ruff's fixer on every edited Python file and deletes an import that has no usage yet, so write the usage before the import.
  - Commit before a mutation control, and undo the mutation with `git checkout -- <file>`; doing it the other way round destroys uncommitted work.
  - After a mutation loop, stale `.pyc` files can mask an edit; run `find . -name '__pycache__' -prune -exec rm -rf {} +` if a test result contradicts the source.
- `$SCRATCH` means your session scratchpad directory, outside the repository.

## Decisions

The issues' remediations are taken as written except where a recorded decision already rules; these are the plan's rulings on the open points:

1. **The `timeout` rule moves into `amicus.errors._LOCAL_RULES` for every backend (#245).**
   Claude's `repair_overrides` entry and its classifier's own `RepairHint` are removed; the classifier keeps `retryable=False` and its charged-run `detail`.
   Codex's capture-failed timeout, whose hint says to retry the same call once, sets `retryable=True` explicitly so its `temporary` matches its own prose.
   A backend-classified CLI timeout keeps the `timeout` code: it is the same condition as the server-side deadline (the worker applies the caller's `timeout_seconds` to the subprocess, so it is the one that fires in practice).
2. **`repair.tool` on a timeout is the verb's `_async` twin, with no `arguments` (#245), only where that twin can help.**
   As built (ADR 0039), a background run's timeout names no tool, and a sync run names the twin only when the job deadline is longer than the one that passed; a plugin's table cannot make the timeout temporary again.
   Arguments would echo prompt inputs (rule 18), and ADR 0021 already accepts a repair that names a tool without arguments when the correction is not unique; the prose says the arguments are the caller's own.
3. **The `backend` enum narrows per verb, not per profile (#246).**
   A per-profile enum would break the manifest control that the profiles differ only in annotations (`tests/test_manifest.py::test_tools_list_bytes_discriminates_one_byte_per_active_tool`), and `[3.strict-types]` asks that the enum equal the accepted set, which is per verb.
   The narrowing is in the Pydantic `Literal`, so the published enum, argument validation and `invalid_arguments.allowed_values` change together.
4. **The `feature_unsupported` repair becomes the unfiltered `amicus_backends` call (#246).**
   With the enum narrowed, an in-tree backend can no longer reach that code; it stays for a plugin that lacks the feature, and ADR 0021 forbids a repair whose `arguments` are not a complete call, which a prompt-input-bearing correction cannot be.
5. **A tool no enabled backend can serve stays listed (#246), and its description says so.**
   The tool set is the same in every profile by design (the manifest's 18-tool control, `[9.deterministic-order]`).
6. **A missing client root gets its own reason token, `root_not_a_directory` (#248), and a workspace that vanishes after resolution is `invalid_workspace_root` with the token of its source.**
   The correction differs (fix the client's roots, or pass `workspace_root`), so the token differs.
7. **#250 item 1 is declined and answered on the issue.**
   ADR 0021 decided that a free-form string is never echoed in `repair.arguments` (`[6.offending-value]`), and that decision was reached after Codex rejected exactly the `INPUT_FIELDS` denylist the issue proposes; `workspace_root` is a path, one of the values that ruling names.
8. **Static resource reads get the catalog TTL by re-registering the low-level `resources/read` handler (#250 item 2).**
   FastMCP 4.0.5 offers no per-resource TTL and `resources/read` must stay unhinted as a method (the template reads report live state, ADR 0018); a handler's own `ttl_ms` wins per field, so the wrapper stamps three URIs and no other.
   The mechanism was probed on this tree before the plan was written: `ttlMs: 300000` on `amicus://params`, `0` on `amicus://error-envelope` when only the first was stamped.
9. **The `logging` capability is dropped in both eras (#250 item 3).**
   amicus never sends a log message; the `logging/setLevel` handler stays registered, so a handshake-era client that still calls it is not broken.
10. **`_meta.fastmcp` is stripped by re-registering the three list handlers (#250 item 6, #247 item 3).**
    A transform or middleware cannot remove it: FastMCP adds the key in `to_mcp_tool` after both have run.
    Probed the same way as decision 8.
11. **`amicus_job_list` pages with an opaque `cursor` and returns `next_cursor` (#249); "omit `limit` for all" stays the default.**
    The whole list is bounded by `AMICUS_JOB_MAX_COUNT` (at most 1,000), so a bounded default page is not needed and the documented default does not change meaning.
    The cursor is `<started_epoch>:<job_id>`, and rows sort by that pair, so a page after a job that has since been consumed or evicted still resolves.
12. **#247's merge is decided in an ADR now and implemented in a later plan.**
    The measurable reductions that need no window are taken here: `timeout_seconds` and `detail` move under the `amicus://params` mechanism, and `_meta.fastmcp` goes (PR C).
    Output-schema prose kept by #38, #52 and #65 is not trimmed; the ADR says which two fields are branch-free and where their schema would live.

## Review Focus

- A client root that exists but is a file: `subprocess.run(cwd=<file>)` raises `NotADirectoryError`, not `FileNotFoundError`, and today escapes every git wrapper as an unstructured error; PR B Task B2's tests spawn against a file.
- A `cursor` whose anchor job was consumed between pages: the page after it must still be the jobs older than that anchor, never an error or a restart; PR D Task D2's test consumes the anchor before requesting the next page.
- `amicus://capabilities` must keep `ttlMs: 0` when the three static bodies gain a TTL, because it embeds the live env report and `surface_digest`; PR C Task C2's stdio test asserts it beside the volatile template read.

## Procedure F: the fingerprint bump

Run this once per PR, after every code and test commit of that PR is in and the gate fails only on surface drift.

- [ ] **F1.** In `src/amicus/schemas/fingerprint.py`, move `FINGERPRINT` to the next number (line 24), e.g. `FINGERPRINT = "amicus/0.1/schema-45"`.
- [ ] **F2.** Regenerate every pinned fixture:
  ```sh
  for p in all codex-kimi claude; do uv run python -m amicus.manifest --profile "$p" > "tests/fixtures/manifest_snapshot.$p.json"; done
  uv run python -m amicus.wire_shape_snapshot > tests/fixtures/wire_shape_snapshot.json
  uv run python -m amicus.result_format_snapshot > tests/fixtures/result_format_snapshot.json
  git --no-pager diff --no-ext-diff --stat
  ```
  Read the fixture diff: every hunk must be explained by this PR's changes.
  An unexplained hunk means a change leaked; stop and find it.
- [ ] **F3.** Compute the new pins and write them into the three test files:
  ```sh
  uv run python - <<'EOF'
  import asyncio
  from amicus import manifest, surface
  for p in sorted(manifest.PROFILES):
      app = manifest.app_for_profile(p)
      print(p, "manifest", asyncio.run(manifest.manifest_hash(app)))
      print(p, "digest", asyncio.run(surface.surface_digest(app)))
  EOF
  ```
  Put the `manifest` values into `EXPECTED_MANIFEST_HASH` (`tests/test_manifest.py`, lines 23-27), the `digest` values into `EXPECTED_SURFACE_DIGEST` (`tests/test_fingerprint.py`, lines 10-14), and the new literal into `tests/test_codes.py` line 83 (`assert fingerprint.FINGERPRINT == "amicus/0.1/schema-45"`).
- [ ] **F4.** Re-measure `tools/list` and move `MEASURED` and `BUDGET` together in `tests/test_discovery_cost.py` (lines 230 and 238):
  ```sh
  uv run python -m amicus.manifest --measure
  ```
  Add a paragraph at the end of that file's module docstring in the house style, for example: "The schema-44 -> schema-45 move (<±N> bytes on the `all` profile: 112683 -> <M>) is #245 and #246: <what moved and why>. Measured on the wire. MEASURED and BUDGET both move by the <N> bytes, so the budget keeps no headroom."
  Name each contributor and its byte count when there are several; measure a contributor alone (stash the other change) when its size is not obvious.
- [ ] **F5.** Run the gate; it must be green.
- [ ] **F6.** Commit the bump alone:
  ```sh
  git add src/amicus/schemas/fingerprint.py tests/fixtures tests/test_manifest.py tests/test_fingerprint.py tests/test_codes.py tests/test_discovery_cost.py
  git commit -m "chore(schemas): bump the fingerprint to schema-45 for <reason>" -m "🤖 Generated with Claude Code"
  ```
  If a later commit on the same branch moves the surface again, do not bump twice: regenerate and re-pin under the same number in a commit titled `chore(schemas): re-pin schema-45 after <change>`.

## Procedure P: open the draft PR

- [ ] **P1.** Run the gate and record the pytest summary line and coverage figure.
- [ ] **P2.** Push and open a draft PR (rule 7; memory: a draft signals unfinished work, undraft as soon as it is reviewable):
  ```sh
  git push -u origin <branch>
  gh pr create --draft --title "<type>(<scope>): <subject>" --body-file "$SCRATCH/pr-body.md"
  ```
  The body has these sections: `Closes #N.` lines; **What was wrong**; **What this does** (one bullet per behaviour change, the fingerprint move, and the tools/list byte move with its reason); **Verification** (the gate's pytest summary line, coverage, the new tests by name, and each mutation control run with the mutant and the test that killed it); the closing line `🤖 Generated with Claude Code`.
- [ ] **P3.** If the maintainer authorized a Codex review in this session, request it through amicus from the main checkout with `scope=commit` (a worktree is outside Codex's roots) and answer every finding on the PR; otherwise write "No Codex review: not authorized this session" in the body.
- [ ] **P4.** Wait for Copilot's review on the PR (it runs on push); fix or answer each comment in its thread, re-run the gate, push, and mark the PR ready for review.
- [ ] **P5.** Report to the maintainer: the PR URL, the fingerprint number, the byte move, and anything declined with its reason.

---

## PR A: the error contract (#245, #246)

PR A is executed: it is PR #253, and its task list is removed here because review changed what it built, so the steps as first written would reintroduce defects the code now prevents.
Do not re-execute it.
The record of what it decided is ADR 0039 and ADR 0040; the record of what it built is the code on its branch and the git log, including the plan's original PR A steps, which git history keeps.
Where decisions 1 and 2 above differ from that record, the ADRs and the code rule.

## PR B: a stale client root is refused, and a vanished workspace is named (#248)

Branch `fix/248-stale-root`, worktree `/Users/bdc/projects/amicus-wt-248`, fingerprint schema-46, no new ADR (ADR 0003 gains a consequence line).

### File Structure (PR B)

| Path | Change |
| --- | --- |
| `src/amicus/orchestration/workspace.py` | `is_dir()` on the chosen client root; `vanished_reason` (B1). |
| `src/amicus/schemas/params.py` | `WORKSPACE_REASONS["root_not_a_directory"]` (B1). |
| `src/amicus/orchestration/gitdiff.py`, `src/amicus/orchestration/gitproc.py` | `WorkspaceMissingError`, `_spawn_failure`, `NotADirectoryError` caught (B2). |
| `src/amicus/orchestration/review.py`, `src/amicus/tools/_prepare.py` | A vanished workspace maps to `invalid_workspace_root` with a reason (B2). |
| `tests/test_workspace.py`, `tests/sdk/test_workspace.py`, `tests/test_prepare.py`, `tests/test_lookup.py` | B1 tests. |
| `tests/sdk/test_gitdiff.py`, `tests/sdk/test_gitproc.py`, `tests/test_review.py`, `tests/test_prepare.py` | B2 tests. |
| `docs/adr/0003-workspace-resolution.md`, `CHANGELOG.md`, `docs/MIGRATION.md` | B3. |

### Task B1: the chosen client root must be a directory

**Files:**
- Modify: `src/amicus/orchestration/workspace.py:96-97` (and a new function after `resolve`)
- Modify: `src/amicus/schemas/params.py:142-148`
- Test: `tests/test_workspace.py:212-217`, `tests/sdk/test_workspace.py`, `tests/test_prepare.py`, `tests/test_lookup.py`

**Interfaces:**
- Produces: the reason token `root_not_a_directory`; `amicus.orchestration.workspace.vanished_reason(source: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_workspace.py`, inside `test_every_refusal_carries_a_published_reason_token`, add to the `cases` dict (after the `"outside_roots"` entry, line 216):

```python
        "root_not_a_directory": ws.resolve_workspace(None, [str(tmp_path / "gone")], None),
```

Append to `tests/sdk/test_workspace.py` (it imports `from amicus.orchestration import workspace`):

```python
def test_resolve_from_a_missing_root_is_refused_not_used(tmp_path):
    """#248: a client root that no longer exists never becomes the workspace; the refusal
    keeps first-root selection rather than silently trying a later root."""
    gone = tmp_path / "gone"
    live = tmp_path / "live"
    live.mkdir()
    res = workspace.resolve_workspace(None, [str(gone), str(live)], None)
    assert res.path is None and res.error_code == "invalid_workspace_root"
    assert res.reason == "root_not_a_directory" and "root" in (res.error_detail or "")
    assert workspace.resolve_workspace(None, [str(live)], None).source == "roots"
```

Append to `tests/test_prepare.py`:

```python
async def test_a_missing_client_root_is_refused_before_any_work(tmp_path, monkeypatch):
    """#248: a stale root is invalid_workspace_root with its own reason token and no repair,
    not a later git_unavailable from a subprocess that could not start in it."""

    async def roots(_ctx):
        return [str(tmp_path / "gone")], "client"

    monkeypatch.setattr(_prepare.ws, "roots_from_ctx", roots)
    out = await _prep(tmp_path, workspace_root=None)
    err = out["error"]
    assert err["code"] == "invalid_workspace_root" and "repair" not in err
    assert err["details"] == {
        "field": "workspace_root",
        "reason": "root_not_a_directory",
        "field_withheld": False,
    }
    assert out["meta"]["roots_source"] == "client"
```

Append to `tests/test_lookup.py`:

```python
async def test_a_missing_client_root_is_refused_on_the_job_path_too(tmp_path, monkeypatch):
    async def roots(_ctx):
        return [str(tmp_path / "gone")], "client"

    monkeypatch.setattr(lookup.ws, "roots_from_ctx", roots)
    *_, err = await lookup.resolve_job_workspace(_settings(tmp_path), object(), None)
    assert err["error"]["code"] == "invalid_workspace_root"
    assert err["error"]["details"]["reason"] == "root_not_a_directory"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_workspace.py tests/sdk/test_workspace.py tests/test_prepare.py tests/test_lookup.py --no-cov -q`
Expected: the new tests fail because the missing root resolves with `source == "roots"`, and `test_every_refusal_carries_a_published_reason_token` fails on `(res.path, res.reason) == (None, "root_not_a_directory")`.

- [ ] **Step 3: Implement**

`src/amicus/orchestration/workspace.py` lines 96-97 become:

```python
    if norm_roots:
        root = norm_roots[0]
        if not Path(root).is_dir():
            # Checked like an explicit path (#248): a stale root would otherwise become the
            # cwd of every git subprocess, which then fails as a missing executable. First-root
            # selection stands; a later root is never tried silently.
            return WorkspaceResolution(
                None,
                None,
                "invalid_workspace_root",
                f"the client's first file root is not an existing directory: {root}",
                "root_not_a_directory",
            )
        return WorkspaceResolution(root, "roots")
```

After `resolve` add:

```python
def vanished_reason(source: str | None) -> str:
    """The details.reason for a workspace that resolved and then disappeared before git
    could run in it (#248): the token names the source that supplied the directory, so
    the correction (fix the client's roots, or pass workspace_root) is the right one."""
    return "root_not_a_directory" if source == "roots" else "not_a_directory"
```

`src/amicus/schemas/params.py` `WORKSPACE_REASONS`: add after the `"not_a_directory"` entry

```python
    "root_not_a_directory": (
        "the client's first file root does not resolve to an existing directory; fix the "
        "advertised root or pass workspace_root"
    ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the Step 2 command; expected: pass.
`tests/test_manifest.py` and `tests/test_fingerprint.py` now fail on drift (the params resource text changed) until Procedure F.

- [ ] **Step 5: Commit**

```sh
git add src/amicus/orchestration/workspace.py src/amicus/schemas/params.py tests
git commit -m "fix(orchestration): refuse a client root that is not a directory before any work" -m "Part of #248: the first client root is checked with is_dir like an explicit workspace_root, and the refusal carries the new reason token root_not_a_directory." -m "🤖 Generated with Claude Code"
```

### Task B2: a git spawn failure names the cause it has

**Files:**
- Modify: `src/amicus/orchestration/gitdiff.py:90-95,192-193,256-257,446-447,487-488,867-868`
- Modify: `src/amicus/orchestration/gitproc.py:54-55,106-107`
- Modify: `src/amicus/orchestration/review.py:8-10,29-37,57-59`
- Modify: `src/amicus/tools/_prepare.py:8,260-266`
- Test: `tests/sdk/test_gitdiff.py`, `tests/sdk/test_gitproc.py`, `tests/test_review.py`, `tests/test_prepare.py`

**Interfaces:**
- Produces: `amicus.orchestration.gitdiff.WorkspaceMissingError(RuntimeError)`; `gitdiff._spawn_failure(cwd: str) -> Exception`.
- Consumes: `workspace.vanished_reason` from B1; `Meta.workspace_source`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/sdk/test_gitdiff.py` (it imports `gitdiff` and `pytest`):

```python
def test_a_vanished_workspace_is_not_reported_as_a_missing_git(tmp_path, monkeypatch):
    """#248: a spawn's FileNotFoundError names the cwd when the cwd is gone, and a cwd that
    is a file (NotADirectoryError) is the same case; the executable only when the
    directory is there."""
    gone = tmp_path / "gone"
    with pytest.raises(gitdiff.WorkspaceMissingError):
        gitdiff._git(str(gone), ["status"], 5)
    a_file = tmp_path / "f"
    a_file.write_text("x")
    with pytest.raises(gitdiff.WorkspaceMissingError):
        gitdiff._git(str(a_file), ["status"], 5)
    with pytest.raises(gitdiff.WorkspaceMissingError):
        gitdiff._resolve_commit(str(gone), "HEAD", 5)

    def boom(*_args, **_kwargs):
        raise gitdiff.gitproc.GitBinaryNotFound("nope")

    monkeypatch.setattr(gitdiff.gitproc, "run_lines", boom)
    with pytest.raises(gitdiff.WorkspaceMissingError):
        gitdiff._run_git_lines(["ls-files"], cwd=str(gone), env={}, timeout=5, sep="\n", consume=list)
    # Control: with the directory present the same failure is still the executable.
    with pytest.raises(gitdiff.GitUnavailableError):
        gitdiff._run_git_lines(["ls-files"], cwd=str(tmp_path), env={}, timeout=5, sep="\n", consume=list)
```

Append to `tests/sdk/test_gitproc.py` (it has `_ENV` and `_count_lines`):

```python
def test_run_lines_raises_binary_not_found_when_the_cwd_is_a_file(tmp_path):
    """A cwd that is a file makes the spawn raise NotADirectoryError; the caller maps the
    cause (#248), so this layer reports it as the same spawn failure."""
    a_file = tmp_path / "f"
    a_file.write_text("x")
    with pytest.raises(gitproc.GitBinaryNotFound):
        gitproc.run_lines(
            [sys.executable, "-c", "print(1)"],
            cwd=str(a_file),
            env=_ENV,
            timeout=30,
            max_line_bytes=1 << 20,
            consume=_count_lines,
        )
```

(add `import sys` if the file lacks it.)

Append to `tests/test_review.py`:

```python
def test_gitdiff_error_maps_a_vanished_workspace_to_its_source_token():
    """#248: the token names the source that supplied the directory, and the code carries
    no repair (ADR 0021)."""
    from amicus.orchestration.gitdiff import WorkspaceMissingError
    from amicus.schemas.envelope import Meta

    for source, reason in (("roots", "root_not_a_directory"), ("param", "not_a_directory")):
        out = review.gitdiff_error(
            WorkspaceMissingError("gone"), Meta(workspace_source=source), fakeplugin.make_plugin()
        )
        assert out["error"]["code"] == "invalid_workspace_root"
        assert out["error"]["details"]["reason"] == reason
        assert out["error"]["details"]["field"] == "workspace_root"
        assert "repair" not in out["error"]
```

Append to `tests/test_prepare.py`:

```python
async def test_delegate_preflight_names_a_workspace_that_vanished(tmp_path, monkeypatch):
    """#248: the directory passed resolution and was deleted before git ran; that is
    invalid_workspace_root (reason not_a_directory for an explicit root), not git_unavailable."""
    import shutil

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()

    def vanish(repo, *, timeout):
        shutil.rmtree(repo)
        raise FileNotFoundError(2, "No such file or directory", repo)

    monkeypatch.setattr(worktree, "ensure_repo_with_head", vanish)
    out = await _prep(
        tmp_path, verb="delegate", tool_name="amicus_delegate", task="t", question=None,
        workspace_root=str(ws_dir),
    )
    assert out["error"]["code"] == "invalid_workspace_root"
    assert out["error"]["details"]["reason"] == "not_a_directory"
    assert "repair" not in out["error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/sdk/test_gitdiff.py tests/sdk/test_gitproc.py tests/test_review.py tests/test_prepare.py --no-cov -q`
Expected: `AttributeError: ... has no attribute 'WorkspaceMissingError'`, `GitUnavailableError` raised where `WorkspaceMissingError` is expected, `NotADirectoryError` escaping `run_lines`, and `git_unavailable` where `invalid_workspace_root` is expected.

- [ ] **Step 3: Implement**

`src/amicus/orchestration/gitdiff.py`: after `GitUnavailableError` (line 91) add

```python
class WorkspaceMissingError(RuntimeError):
    """The directory git was to run in no longer exists, or is not a directory (#248): it
    passed workspace resolution and vanished before the spawn, which raises the same
    FileNotFoundError a missing git executable does."""


def _spawn_failure(cwd: str) -> Exception:
    """The error for a git spawn that raised FileNotFoundError or NotADirectoryError: the
    directory, when it is gone, else the executable."""
    if not os.path.isdir(cwd):
        return WorkspaceMissingError(f"workspace directory no longer exists: {cwd}")
    return GitUnavailableError("git executable not found")
```

and change the five mapping sites:

- `_git` (lines 192-193): `except (FileNotFoundError, NotADirectoryError) as exc:` / `raise _spawn_failure(cwd) from exc`
- `_run_git_lines` (lines 256-257): `except gitproc.GitBinaryNotFound as exc:` / `raise _spawn_failure(cwd) from exc`
- `_global_excludes_flags` (lines 446-447): the same two lines as `_run_git_lines`
- `_resolve_commit` (lines 487-488): the same two lines as `_git`
- `_stream_redacted_diff` (lines 867-868): the same two lines as `_git`

`src/amicus/orchestration/gitproc.py` line 106: `except (FileNotFoundError, NotADirectoryError) as exc:`; line 55 docstring: `"""The git executable could not be launched, or the cwd is missing or not a directory (spawn raised ``FileNotFoundError`` or ``NotADirectoryError``); the caller tells the two apart (#248)."""`.

`src/amicus/orchestration/review.py`: add `from amicus.orchestration import workspace as ws` after line 9, add `gitdiff.WorkspaceMissingError: ("invalid_workspace_root", "workspace_root"),` to `_GITDIFF_ERRORS`, and replace lines 57-59 with

```python
    reason = ws.vanished_reason(meta.workspace_source) if code == "invalid_workspace_root" else None
    details = (
        ErrorDetail(field=offending, allowed_values=allowed, reason=reason)
        if (offending or allowed)
        else None
    )
```

`src/amicus/tools/_prepare.py`: add `import os` beside `import subprocess`, and replace lines 260-266 with

```python
        except (FileNotFoundError, NotADirectoryError) as exc:
            if not os.path.isdir(resolution.path):
                # The directory passed resolution and vanished before git ran (#248).
                return error_envelope(
                    "invalid_workspace_root",
                    "the workspace directory no longer exists",
                    meta,
                    plugin=plugin,
                    details=ErrorDetail(
                        field="workspace_root", reason=ws.vanished_reason(resolution.source)
                    ),
                )
            return error_envelope(
                "git_unavailable",
                redaction.sanitize_echo_prose(str(exc))[:300],
                meta,
                plugin=plugin,
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the Step 2 command, then `uv run pytest tests/sdk tests/test_dry_run.py tests/test_review.py --no-cov -q`.
Expected: pass.

- [ ] **Step 5: Mutation control**

Commit (Step 6), then in `_spawn_failure` make the first line `if False:` and run `uv run pytest tests/sdk/test_gitdiff.py --no-cov -q -k vanished`; it must fail; restore with `git checkout -- src/amicus/orchestration/gitdiff.py`.

- [ ] **Step 6: Commit**

```sh
git add src/amicus/orchestration src/amicus/tools/_prepare.py tests
git commit -m "fix(orchestration): tell a vanished workspace from a missing git executable" -m "Part of #248: every git spawn wrapper checks the cwd when the spawn fails, a missing or non-directory cwd is WorkspaceMissingError, and review and the delegate preflight report it as invalid_workspace_root with the reason token of the workspace's source." -m "🤖 Generated with Claude Code"
```

- [ ] **Step 7: Procedure F** (schema-46; the reason names #248 and the new token in the `amicus://params` contract).

### Task B3: docs, CHANGELOG, MIGRATION, PR

**Files:**
- Modify: `docs/adr/0003-workspace-resolution.md` (append a Consequences line), `CHANGELOG.md`, `docs/MIGRATION.md` (the `## Upgrading from 0.6.0` section PR A created)

- [ ] **Step 1: Edit**

ADR 0003, after line 19, add:

```markdown
- A client root is checked with `is_dir()` like an explicit path (issue #248): a root the client still advertises after the directory is gone is refused as invalid_workspace_root with reason `root_not_a_directory`, first-root selection stands, and a workspace that vanishes after resolution is reported with the token of its source rather than as a missing git executable.
```

CHANGELOG `### Fixed` under `[Unreleased]`, add:

```markdown
- **Surface.** A client file root that no longer exists is refused before any work as
  `invalid_workspace_root` with the new `details.reason` token `root_not_a_directory`, where it
  was accepted as the workspace and every git-based call then failed as `git_unavailable`,
  steering the agent to install git (#248). Only handshake-era clients advertise roots. A
  workspace that vanishes after resolution is now `invalid_workspace_root` too, with the token of
  its source (`root_not_a_directory` or `not_a_directory`), from every git wrapper and the
  delegate preflight; a cwd that is a file is handled the same way. The token list in the
  `workspace_root` contract at `amicus://params` grew by one.
```

MIGRATION, append to `## Upgrading from 0.6.0`:

```markdown
**A stale client root is refused as `invalid_workspace_root`, reason `root_not_a_directory` (#248).**
A handshake-era client whose advertised first root no longer exists used to get `git_unavailable` from the first git-based call; it now gets the workspace refusal, with no repair, before any work.
Fix the root the client advertises, or pass `workspace_root`.

```

- [ ] **Step 2: Check and commit**

`uv run python scripts/check_sentence_per_line.py .` (exit 0), then

```sh
git add docs CHANGELOG.md
git commit -m "docs(orchestration): record the stale-root refusal and its migration" -m "🤖 Generated with Claude Code"
```

Procedure P with title `fix(orchestration): refuse a stale client root before any work` and `Closes #248.`.

---

## PR C: the six minor contract findings (#250)

Branch `fix/250-minor-contract-findings`, worktree `/Users/bdc/projects/amicus-wt-250`, fingerprint schema-47, ADR 0041.

### File Structure (PR C)

| Path | Change |
| --- | --- |
| `src/amicus/server.py` | `"logging": None` in the capability filter (C1); `STATIC_READ_TTL_URIS`, `_install_static_read_ttl` (C2); `_install_meta_strip` (C5). |
| `src/amicus/tools/resources.py` | Explicit one-line template descriptions (C3). |
| `src/amicus/jobs/lifecycle.py` | Progress reports elapsed against the deadline (C4). |
| `src/amicus/tools/discovery.py`, `src/amicus/schemas/results.py` | `tool_details[].stability` is the effective tier (C5). |
| `tests/test_cache_hints.py`, `tests/test_manifest.py`, `tests/test_resources.py`, `tests/test_lifecycle.py`, `tests/test_discovery.py` | Tests. |
| `docs/adr/0041-static-resource-reads-carry-the-catalog-ttl.md`, `docs/adr/0018-the-catalog-carries-a-ttl-and-resource-reads-do-not.md`, `CHANGELOG.md` | C6. |

### Task C1: stop advertising the `logging` capability

**Files:**
- Modify: `src/amicus/server.py:149-179` (`_filter_capabilities`)
- Test: `tests/test_cache_hints.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cache_hints.py`:

```python
async def test_the_logging_capability_is_not_advertised_in_either_era():
    """#250: amicus never sends a log message and `logging` is deprecated at 2026-07-28, so
    neither era advertises it; the handler stays registered for a client that still calls
    logging/setLevel."""
    async with Client(_stdio(), mode="legacy") as legacy:
        assert "logging" not in _caps(legacy.initialize_result.capabilities)
    async with Client(_stdio()) as modern:
        assert "logging" not in _caps(modern.session.discover_result.capabilities)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cache_hints.py --no-cov -q -k logging`
Expected: FAIL, `"logging"` is present.

- [ ] **Step 3: Implement**

In `_filter_capabilities`, change the `update` line to

```python
        update: dict[str, Any] = {"prompts": None, "logging": None, "extensions": filtered or None}
```

and add to its docstring the sentence `Null the logging capability too (#250): amicus sends no log message, the capability is deprecated at 2026-07-28, and the logging/setLevel handler stays registered so a handshake-era client that calls it is not broken.`

- [ ] **Step 4: Run the tests**

Run the Step 2 command: PASS.
`test_the_manifest_pins_the_capabilities_the_shipped_transport_sends` and the manifest tests fail on drift until Procedure F.

- [ ] **Step 5: Commit**

```sh
git add src/amicus/server.py tests/test_cache_hints.py
git commit -m "fix(server): stop advertising the logging capability" -m "Part of #250 (item 3)." -m "🤖 Generated with Claude Code"
```

### Task C2: static resource reads carry the catalog TTL

**Files:**
- Modify: `src/amicus/server.py` (new constant and installer beside `_install_cache_hints`, lines 62-66 comment, `create_app` line 209)
- Test: `tests/test_cache_hints.py:128-138`, `tests/test_manifest.py:143-160`

**Interfaces:**
- Produces: `amicus.server.STATIC_READ_TTL_URIS: frozenset[str]`; `_install_static_read_ttl(app)`.

- [ ] **Step 1: Write the failing tests**

Replace `test_resource_reads_carry_no_ttl_static_or_volatile` (lines 128-138 of `tests/test_cache_hints.py`) with

```python
async def test_static_reads_carry_the_catalog_ttl_and_volatile_reads_none():
    """`resources/read` is unhinted as a METHOD, because the template reads report live
    state and the SDK chooses a hint per method; the three static bodies change only with
    the fingerprint, so their reads carry the catalog TTL per URI (#250, ADR 0041).
    `amicus://capabilities` embeds the live env report and stays uncached."""
    cached = {
        "resultType": "complete",
        "ttlMs": server.CATALOG_CACHE_TTL_MS,
        "cacheScope": server.CATALOG_CACHE_SCOPE,
    }
    uncached = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}
    async with Client(_stdio()) as client:
        for uri in sorted(server.STATIC_READ_TTL_URIS):
            assert _envelope(await client.read_resource_mcp(uri)) == cached, uri
        for uri in ("amicus://capabilities", VOLATILE_RESOURCE_URI):
            assert _envelope(await client.read_resource_mcp(uri)) == uncached, uri
    assert server.STATIC_READ_TTL_URIS == set(STATIC_RESOURCE_URIS) - {"amicus://capabilities"}
```

In `tests/test_manifest.py` replace lines 157-160 with

```python
    assert "resources/read" in server.UNCACHED_CACHEABLE_METHODS
    assert set(env["resources/read"]) == set(manifest.STATIC_RESOURCE_URIS)
    assert server.STATIC_READ_TTL_URIS == set(manifest.STATIC_RESOURCE_URIS)
    for uri, fields in env["resources/read"].items():
        assert fields == cached, uri
```

and change that test's docstring to `"""The list methods carry the catalog TTL; `resources/read` is unhinted as a method and the three static reads carry the TTL per URI (ADR 0018, ADR 0041); the manifest pins the emitted values so a framework change is reviewed, not silent."""`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_cache_hints.py tests/test_manifest.py --no-cov -q -k "static_reads or cache_policy"`
Expected: `AttributeError: module 'amicus.server' has no attribute 'STATIC_READ_TTL_URIS'`.

- [ ] **Step 3: Implement**

In `src/amicus/server.py` add `from mcp.types import ReadResourceResult` to the imports, replace the comment block at lines 62-66 with

```python
# `resources/read` is cacheable and deliberately unhinted as a METHOD. The SDK picks a hint
# per method while the client keys its cache per URI, so a method hint would put
# `amicus://backends/{backend}` and `amicus://models/{backend}`, which report live install,
# auth and model-catalog state, under one window. The three static bodies get the TTL per
# URI instead (`_install_static_read_ttl`, ADR 0041); `amicus://capabilities` embeds the
# live env report and surface_digest, so it stays at the SDK default.
UNCACHED_CACHEABLE_METHODS: frozenset[str] = frozenset({"resources/read"})
STATIC_READ_TTL_URIS: frozenset[str] = frozenset(
    {"amicus://error-envelope", "amicus://result-meta", "amicus://params"}
)
```

and after `_install_cache_hints` add

```python
def _install_static_read_ttl(app: FastMCP) -> None:
    """Re-register `resources/read` with a wrapper that stamps `CATALOG_CACHE_TTL_MS` on the
    three static bodies (#250, ADR 0041). A handler's own `ttl_ms` wins per field over any
    method hint, and `resources/read` has none, so every other URI stays at `ttlMs: 0`.
    FastMCP 4.0.5 offers no per-resource hint, so the low-level entry is wrapped, which is
    where the SDK invokes it (`mcp.server.lowlevel.Server.add_request_handler` replaces the
    entry for a method)."""
    lowlevel = app._mcp_server
    entry = lowlevel._request_handlers["resources/read"]
    original = entry.handler

    async def read(ctx: Any, params: Any) -> Any:
        result = await original(ctx, params)
        if str(params.uri) in STATIC_READ_TTL_URIS and isinstance(result, ReadResourceResult):
            return result.model_copy(
                update={"ttl_ms": CATALOG_CACHE_TTL_MS, "cache_scope": CATALOG_CACHE_SCOPE}
            )
        return result

    lowlevel.add_request_handler("resources/read", entry.params_type, read)
```

In `create_app`, after `_install_cache_hints(app)` (line 209) add `_install_static_read_ttl(app)`.

- [ ] **Step 4: Run the tests**

Run the Step 2 command, then `uv run pytest tests/test_cache_hints.py tests/test_resources.py --no-cov -q`: PASS (the manifest golden and hash tests keep failing on drift until Procedure F).

- [ ] **Step 5: Commit**

```sh
git add src/amicus/server.py tests/test_cache_hints.py tests/test_manifest.py
git commit -m "feat(server): give the three static resource reads the catalog ttl" -m "Part of #250 (item 2): per URI on the read result, because a method hint would also cover the volatile template reads (ADR 0018)." -m "🤖 Generated with Claude Code"
```

### Task C3: explicit one-line template descriptions

**Files:**
- Modify: `src/amicus/tools/resources.py:165-197`
- Test: `tests/test_resources.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_resources.py` (it has `_app`, `Client` and `resources`):

```python
async def test_template_descriptions_are_one_line_and_name_no_internals():
    """#250: the wire carries a written description, not a wrapped docstring; the old
    models text also claimed a resource read has no repair carrier, which error.data.repair
    on resource_not_found disproves."""
    async with Client(_app()) as c:
        by_uri = {t.uri_template: t.description for t in await c.list_resource_templates()}
    assert by_uri == {
        "amicus://backends/{backend}": resources.BACKEND_TEMPLATE_DESC,
        "amicus://models/{backend}": resources.MODELS_TEMPLATE_DESC,
    }
    for text in by_uri.values():
        assert "\n" not in text and "BACKEND_IDS" not in text and "repair carrier" not in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_resources.py --no-cov -q -k template_descriptions`
Expected: `AttributeError: ... has no attribute 'BACKEND_TEMPLATE_DESC'`.

- [ ] **Step 3: Implement**

In `src/amicus/tools/resources.py`, after `TEMPLATE_URIS` (line 35) add

```python
# Written descriptions for the two templates (#250): a docstring reaches the wire with its
# line breaks, and the old models text named internals and claimed a resource read carries
# no repair, which `error.data.repair` on resource_not_found disproves.
BACKEND_TEMPLATE_DESC = (
    "One backend's amicus_backends entry at detail=full, disclosures included; an unknown "
    "backend id is resource_not_found."
)
MODELS_TEMPLATE_DESC = (
    "One backend's amicus_models payload. Unlike the tool, a known but unavailable backend "
    "returns the informational available=false payload rather than a backend_unavailable "
    "error; only an unknown backend id is resource_not_found."
)
```

Pass `description=BACKEND_TEMPLATE_DESC,` in the `@app.resource("amicus://backends/{backend}", ...)` decorator and `description=MODELS_TEMPLATE_DESC,` in the `@app.resource("amicus://models/{backend}", ...)` decorator, and shorten the two docstrings to one line each: `"""See BACKEND_TEMPLATE_DESC; a single-backend read never takes the summary projection."""` and `"""See MODELS_TEMPLATE_DESC."""`.

- [ ] **Step 4: Run the tests**

Run `uv run pytest tests/test_resources.py --no-cov -q`: PASS.

- [ ] **Step 5: Commit**

```sh
git add src/amicus/tools/resources.py tests/test_resources.py
git commit -m "fix(resources): give the two templates written one-line descriptions" -m "Part of #250 (item 4)." -m "🤖 Generated with Claude Code"
```

### Task C4: progress reports elapsed time against the deadline

**Files:**
- Modify: `src/amicus/jobs/lifecycle.py:392-394,406-407,421-439`
- Test: `tests/test_lifecycle.py:349-379`

- [ ] **Step 1: Write the failing test**

Replace lines 355-357 and 378-379 of `test_progress_is_reported_throttled_while_running` so the fake and the assertions read

```python
    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            reports.append((progress, total, message))
    ...
    assert out["ok"] is True
    assert reports, "no progress was reported"
    for progress, total, message in reports:
        # #250: elapsed seconds against the deadline, so a host can show a fraction; the
        # backend event count rides the message, and there is no phase to report.
        assert total is not None and 0.0 <= progress <= total
        assert message and "deadline" in message and "events" in message
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_lifecycle.py --no-cov -q -k progress_is_reported`
Expected: FAIL, `total is None`.

- [ ] **Step 3: Implement**

In `await_job_result`, change the docstring sentence `Throttled progress rides ctx.report_progress when the caller gave a progress token (a no-op otherwise).` to `Throttled progress rides ctx.report_progress when the caller gave a progress token (a no-op otherwise): elapsed seconds against the deadline, with the backend event count in the message; the job record has no phase to report (#250).`, delete `last_events = -1` (line 407), and replace lines 421-439 with

```python
            events = rec.get("events_seen", 0)
            now = time.monotonic()
            if ctx is not None and now - last_progress_at >= SYNC_PROGRESS_THROTTLE_S:
                last_progress_at = now
                elapsed_s = rec.get("elapsed_ms", 0) / 1000
                total_s = float(rec.get("deadline_seconds") or timeout)
                with contextlib.suppress(Exception):
                    # asyncio.TimeoutError is an Exception subclass on 3.11+, so a hung
                    # report_progress is bounded and still swallowed here, not left to
                    # stall the poll loop past the job's own deadline.
                    await asyncio.wait_for(
                        ctx.report_progress(
                            progress=min(elapsed_s, total_s),
                            total=total_s,
                            message=(
                                f"running: {elapsed_s:.0f}s of the {total_s:.0f}s deadline; "
                                f"backend events: {events}"
                            ),
                        ),
                        timeout=SYNC_PROGRESS_REPORT_TIMEOUT_S,
                    )
```

- [ ] **Step 4: Run the tests**

Run `uv run pytest tests/test_lifecycle.py --no-cov -q`: PASS (the hanging-report test still passes: its fake accepts `total`).

- [ ] **Step 5: Commit**

```sh
git add src/amicus/jobs/lifecycle.py tests/test_lifecycle.py
git commit -m "fix(jobs): report sync progress as elapsed seconds against the deadline" -m "Part of #250 (item 5)." -m "🤖 Generated with Claude Code"
```

### Task C5: the effective stability tier on every row, and no framework meta on the wire

**Files:**
- Modify: `src/amicus/tools/discovery.py:47-56,540,656-658`, `src/amicus/schemas/results.py:597-599,644`
- Modify: `src/amicus/server.py` (`_install_meta_strip`, `create_app`)
- Test: `tests/test_discovery.py:87-96,375`, `tests/test_cache_hints.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_discovery.py` change line 96 to `assert len(tiers) == 43, sorted(tiers)` and lines 94-95's comment to `# 43 = 24 lifecycle records + capabilities.stability + 18 tool_details rows: every row now carries its effective tier rather than a null override (#250).`; change line 375 to `assert entry["stability"] == "experimental"`.

Append to `tests/test_cache_hints.py`:

```python
async def test_no_catalog_record_carries_the_framework_meta_key():
    """#250: FastMCP stamps `_meta.fastmcp = {"tags": []}` on every record; the digest and the
    manifest already ignore it, and now the wire does not carry it either. The lifecycle key
    on the same records is the positive control that `_meta` itself still arrives."""
    async with Client(_stdio()) as client:
        records = [
            *(await client.list_tools_mcp()).tools,
            *(await client.list_resources_mcp()).resources,
            *(await client.list_resource_templates_mcp()).resource_templates,
        ]
    assert len(records) == 24
    for record in records:
        meta = record.model_dump(mode="json", by_alias=True).get("_meta") or {}
        assert "fastmcp" not in meta, record
        assert "dev.bconnelly.amicus/lifecycle" in meta, record
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_discovery.py tests/test_cache_hints.py --no-cov -q -k "stability_tier or capabilities_summary or framework_meta"`
Expected: `25 != 43`, `None != "experimental"`, and `"fastmcp" in meta`.

- [ ] **Step 3: Implement**

`src/amicus/tools/discovery.py`: in the `from amicus.tools._meta import (...)` block replace `TOOL_STABILITY` with `tool_stability` (run `grep -n TOOL_STABILITY src/amicus/tools/discovery.py` first; if another use remains, keep both names), change line 540 to `stability=tool_stability(name),`, and delete the `else:` branch at lines 656-658 (the `setdefault("stability", None)`).

`src/amicus/schemas/results.py`: lines 597-599 become

```python
_TOOL_STABILITY_DESC = (
    "The tool's effective maturity tier: its own override, else the top-level `stability`."
)
```

and line 644 becomes `stability: ToolStability = Field(description=_TOOL_STABILITY_DESC)`.

`src/amicus/server.py`: add after `_install_static_read_ttl`

```python
_FASTMCP_META_KEY = "fastmcp"
_LIST_RECORD_FIELDS: tuple[tuple[str, str], ...] = (
    ("tools/list", "tools"),
    ("resources/list", "resources"),
    ("resources/templates/list", "resource_templates"),
)


def _install_meta_strip(app: FastMCP) -> None:
    """Re-register the three catalog list methods with wrappers that drop FastMCP's own
    `_meta.fastmcp` block (`{"tags": []}` on every record) from the wire (#250). The digest
    (`surface._clean`) and the manifest (`manifest._canonicalize`) already ignore it, so only
    the byte count moves. A transform or middleware cannot do this: FastMCP adds the key in
    `to_mcp_tool` after both have run."""
    lowlevel = app._mcp_server
    for method, field in _LIST_RECORD_FIELDS:
        entry = lowlevel._request_handlers[method]
        lowlevel.add_request_handler(method, entry.params_type, _stripping(entry.handler, field))


def _stripping(original: Any, field: str) -> Any:
    async def handler(ctx: Any, params: Any) -> Any:
        result = await original(ctx, params)
        records = getattr(result, field, None)
        if not isinstance(records, list):
            return result
        cleaned = [
            record.model_copy(
                update={
                    "meta": {k: v for k, v in (record.meta or {}).items() if k != _FASTMCP_META_KEY}
                    or None
                }
            )
            for record in records
        ]
        return result.model_copy(update={field: cleaned})

    return handler
```

and call `_install_meta_strip(app)` in `create_app` right after `_install_static_read_ttl(app)`.

- [ ] **Step 4: Run the tests**

Run the Step 2 command, then `uv run pytest tests/test_discovery.py tests/test_cache_hints.py tests/test_manifest.py::test_canonicalize tests/test_results.py --no-cov -q`: PASS.

- [ ] **Step 5: Commit**

```sh
git add src/amicus/tools/discovery.py src/amicus/schemas/results.py src/amicus/server.py tests
git commit -m "fix(server): publish each tool's effective tier and drop the framework meta key" -m "Part of #250 (item 6)." -m "🤖 Generated with Claude Code"
```

- [ ] **Step 6: Procedure F** (schema-47; the docstring paragraph names each item's bytes: the enum-free capability change is not on tools/list, the `_meta.fastmcp` strip is about 22 bytes per tool record, and `_TOOL_STABILITY_DESC` rides `amicus_capabilities`'s outputSchema).

### Task C6: decline item 1 on the issue, ADR 0041, CHANGELOG, PR

**Files:**
- Create: `docs/adr/0041-static-resource-reads-carry-the-catalog-ttl.md`
- Modify: `docs/adr/0018-the-catalog-carries-a-ttl-and-resource-reads-do-not.md`, `CHANGELOG.md`

- [ ] **Step 1: Post the decline on #250**

```sh
gh issue comment 250 --body-file "$SCRATCH/250-item-1.md"
```

with this body:

```markdown
Item 1 (`repair.arguments` for `amicus_job_list` with `workspace_root`) is declined; items 2 to 6 are in the PR that references this issue.

ADR 0021 decided that a free-form string is never echoed in `repair.arguments` (`[6.offending-value]`): every surviving value must be null, a bool, a number, an enum member or an object of those, and anything else suppresses the arguments. That decision was reached after Codex rejected the first design, which denylisted exactly `INPUT_FIELDS` as this item proposes; paths, `idempotency_key` and model slugs are as free-form as a prompt input, and `workspace_root` is a path. `tests/test_middleware.py` pins the suppression on a surviving path. Rule 18 is a separate, narrower bound.

The difference the item observed is real but is the policy working: `amicus_backends` declares nothing free-form, so its corrected call is always `{}`; `amicus_job_list` carries `workspace_root`, and the correction is suppressed whenever it is present. Reopening the echo policy is a decision of its own, not a minor fix.
```

- [ ] **Step 2: Write ADR 0041**

```markdown
# ADR 0041: static resource reads carry the catalog TTL

**Status:** Accepted (2026-09-24)

Amends [ADR 0018](0018-the-catalog-carries-a-ttl-and-resource-reads-do-not.md): its "resources/read carries no hint at all" clause is superseded; the rest stands.

## Context

ADR 0018 left `resources/read` unhinted because the SDK chooses a hint per method and two template reads report live install, auth and model-catalog state.
`amicus://error-envelope`, `amicus://result-meta` and `amicus://params` change only when the fingerprint moves, yet every read of them said `ttlMs: 0` while `resources/list` said `300000` (#250 item 2, `[8.cacheable-results]`).
The SDK applies a method hint only to the fields a handler did not set, so a hint can be stamped per URI on the read result; FastMCP 4.0.5 offers no per-resource hint of its own.

## Decision

**The three static bodies carry `CATALOG_CACHE_TTL_MS` on their read results, per URI.**
`server._install_static_read_ttl` re-registers the low-level `resources/read` handler with a wrapper that stamps the TTL and scope on those three URIs and passes every other result through.
`resources/read` stays out of the method hint map, so `amicus://capabilities`, which embeds the live env report and `surface_digest`, and the two templates keep `ttlMs: 0`.

**The set is written out.**
`STATIC_READ_TTL_URIS` names the three; a test holds it equal to the manifest's static URIs, and the stdio test asserts the TTL on each of them and its absence on the capabilities and template reads.

## Consequences

- `modern_result_envelopes` moves for the three reads, so `FINGERPRINT` moves (with the rest of #250, to `schema-47`).
- A host that honours `ttlMs` re-reads the three bodies at most every five minutes; a fingerprint move within that window is visible on `amicus_capabilities`, which is not cached.
- The same handler re-registration is how `_meta.fastmcp` is stripped from the three list results (`_install_meta_strip`), because FastMCP adds that key after every transform and middleware has run.
```

Add to ADR 0018 after its status line: `The `resources/read` clause is superseded by [ADR 0041](0041-static-resource-reads-carry-the-catalog-ttl.md); the rest stands.`

- [ ] **Step 3: CHANGELOG**

Under `[Unreleased]` `### Changed` add:

```markdown
- **Surface.** Six minor contract findings of the 2026-09-24 audit (#250). Reads of
  `amicus://error-envelope`, `amicus://result-meta` and `amicus://params` carry the catalog
  TTL (`ttlMs: 300000`) where they said `0`; `amicus://capabilities` and the two templates
  still say `0` (ADR 0041). The `logging` capability is no longer advertised: amicus sends no
  log message. The two resource templates carry written one-line descriptions, and the models
  template no longer claims a resource read has no repair carrier. A sync call's progress
  notifications report elapsed seconds against the deadline as `progress`/`total`, with the
  backend event count in the message. `amicus_capabilities.tool_details[].stability` is each
  tool's effective tier rather than `null`, so the two stability surfaces agree. Every tool,
  resource and template record on the wire no longer carries FastMCP's `_meta.fastmcp` block.
  Item 1 of the issue, echoing `workspace_root` in `repair.arguments`, was declined under ADR
  0021.
```

- [ ] **Step 4: Check, commit, PR**

`uv run python scripts/check_sentence_per_line.py .` (exit 0), then

```sh
git add docs CHANGELOG.md
git commit -m "docs(server): record ADR 0041 and the minor contract changes" -m "🤖 Generated with Claude Code"
```

Procedure P with title `fix(server): resolve the six minor contract findings of the audit` and `Closes #250.`.

---

## PR D: `amicus_job_list` pages by an opaque cursor (#249)

Branch `feat/249-job-list-cursor`, worktree `/Users/bdc/projects/amicus-wt-249`, fingerprint schema-48, ADR 0042.

### File Structure (PR D)

| Path | Change |
| --- | --- |
| `src/amicus/jobs/store.py:1084` | Sort by `(started_epoch, job_id)` (D1). |
| `src/amicus/schemas/params.py`, `src/amicus/schemas/results.py:428-432`, `src/amicus/tools/jobs.py`, `src/amicus/tools/discovery.py:392` | `cursor`, `next_cursor`, the description (D2). |
| `tests/sdk/test_jobs.py`, `tests/test_job_tools.py`, `tests/test_discovery.py:420` | Tests. |
| `docs/adr/0042-amicus-job-list-pages-by-an-opaque-cursor.md`, `CHANGELOG.md` | D3. |

### Task D1: a total order for the listing

**Files:**
- Modify: `src/amicus/jobs/store.py:1084`
- Test: `tests/sdk/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/sdk/test_jobs.py`:

```python
def test_list_orders_equal_epochs_by_job_id(tmp_path):
    """#249: a cursor needs a total order, and started_epoch alone can tie (time.time()
    resolution), so job_id breaks the tie; both descend. The tie is written into each
    record rather than by patching time.time, which store.py reaches through the global
    `time` module, so a patch there would move the whole process's clock."""
    store = _store(tmp_path)
    cwd = str(tmp_path)
    ids = []
    for _ in range(4):
        jid, _ = store.start(_factory(_WRITE_DONE), cwd, kind="k")
        _wait_terminal(store, cwd, jid)
        ids.append(jid)
    for jd in store._job_dirs(store._ws_dir(cwd)):
        meta = store._read_meta(jd)
        assert meta is not None
        meta["started_epoch"] = 1_700_000_000.0
        store._write_meta(jd, meta)
    listed = [j["job_id"] for j in store.list_jobs(cwd)]
    assert listed == sorted(ids, reverse=True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/sdk/test_jobs.py --no-cov -q -k equal_epochs`
Expected: FAIL, because a stable sort on a tied key keeps `iterdir` order, which is not id order.
If it passes by accident (four random ids that `iterdir` happened to list in descending order), run it again; a second pass on fresh ids means the instrument cannot see order, so stop and report it rather than continuing.

- [ ] **Step 3: Implement**

Line 1084 becomes `summaries.sort(key=lambda s: (s["started_epoch"], s["job_id"]), reverse=True)  # newest first, id breaks ties (#249)`.

- [ ] **Step 4: Run the tests**

`uv run pytest tests/sdk/test_jobs.py --no-cov -q`: PASS.

- [ ] **Step 5: Commit**

```sh
git add src/amicus/jobs/store.py tests/sdk/test_jobs.py
git commit -m "fix(jobs): order equal start epochs by job id in the listing" -m "Part of #249: a cursor needs a total order." -m "🤖 Generated with Claude Code"
```

### Task D2: `cursor` in, `next_cursor` out

**Files:**
- Modify: `src/amicus/schemas/params.py` (after `JobLimitParam`, line 496), `src/amicus/schemas/results.py:428-432`, `src/amicus/tools/jobs.py:1-48,209-269`, `src/amicus/tools/discovery.py:392`
- Test: `tests/test_job_tools.py`, `tests/test_discovery.py:420`

**Interfaces:**
- Produces: `amicus.schemas.params.JobCursorParam`; `JobListResult.next_cursor: str | None`; cursor text `f"{started_epoch!r}:{job_id}"`.
- Consumes: `store.list_jobs` rows with `started_epoch` and `job_id` (D1).

- [ ] **Step 1: Write the failing tests**

In `tests/test_discovery.py` line 420 add `"cursor"` to the set.
Append to `tests/test_job_tools.py` (it has `Client`, `_schemas`, `_start`, `_wait_done`, and the `app`, `store`, `settings` fixtures):

```python
async def test_list_pages_by_cursor_and_survives_a_consumed_anchor(app, store, tmp_path):
    """#249: limit=1 walks three jobs in three pages; the second page still resolves after
    its anchor (the first page's last job) was consumed, because the cursor is the anchor's
    (started_epoch, job_id) rather than a position; the last page carries no cursor."""
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        ids = []
        for _ in range(3):
            job_id = await _start(c, tmp_path)
            await _wait_done(store, tmp_path, job_id)
            ids.append(job_id)
        first = (await c.call_tool("amicus_job_list", {"limit": 1, **ws})).structured_content
        schemas["amicus_job_list"].validate(first)
        assert [j["job_id"] for j in first["jobs"]] == [ids[2]]
        assert first["truncated"] is True and first["next_cursor"]
        assert "cursor" in first["truncation_hint"]
        await c.call_tool("amicus_job_consume_result", {"job_id": ids[2], **ws})
        second = (
            await c.call_tool("amicus_job_list", {"limit": 1, "cursor": first["next_cursor"], **ws})
        ).structured_content
        assert [j["job_id"] for j in second["jobs"]] == [ids[1]] and second["truncated"] is True
        third = (
            await c.call_tool("amicus_job_list", {"limit": 1, "cursor": second["next_cursor"], **ws})
        ).structured_content
        assert [j["job_id"] for j in third["jobs"]] == [ids[0]]
        assert third["truncated"] is False and third["next_cursor"] is None
        assert third["truncation_hint"] is None
        # A cursor with a filter keeps the filter; omitting limit after a cursor returns the rest.
        rest = (
            await c.call_tool("amicus_job_list", {"cursor": first["next_cursor"], **ws})
        ).structured_content
        assert [j["job_id"] for j in rest["jobs"]] == [ids[1], ids[0]]
        filtered = (
            await c.call_tool(
                "amicus_job_list", {"cursor": first["next_cursor"], "status": "running", **ws}
            )
        ).structured_content
        assert filtered["jobs"] == [] and filtered["next_cursor"] is None


async def test_list_rejects_a_cursor_it_did_not_issue(app, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        for bad in ("nope", "1.5:short", "x:" + "a" * 32, ":" + "a" * 32):
            res = await c.call_tool(
                "amicus_job_list", {"cursor": bad, **ws}, raise_on_error=False
            )
            err = res.structured_content["error"]
            assert err["code"] == "invalid_arguments", bad
            assert err["details"]["field"] == "cursor" and err["repair"]["tool"] == "amicus_job_list"
            assert "cursor" in err["repair"]["alternative"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_job_tools.py tests/test_discovery.py --no-cov -q -k "cursor or filters_are_advertised"`
Expected: `invalid_arguments` (unknown argument `cursor`) where a page is expected, and the property-set assertion fails.

- [ ] **Step 3: Implement**

`src/amicus/schemas/params.py`, after `JobLimitParam`:

```python
JobCursorParam = Annotated[
    str | None,
    Field(
        description=(
            "Opaque page cursor: a previous result's next_cursor, with the same filters. "
            "Omit to start from the newest job."
        ),
        max_length=80,
        pattern=CONTROL_CHAR_FREE_PATTERN,
    ),
]
```

`src/amicus/schemas/results.py`, `JobListResult` (lines 428-432):

```python
_NEXT_CURSOR_DESC = (
    "Pass as `cursor` with the same filters for the jobs after this page; null when this "
    "page is the last."
)
publish.KEPT_DESCRIPTIONS.add(_NEXT_CURSOR_DESC)


class JobListResult(SuccessBase):
    jobs: list[JobSummary]
    workspace: Workspace
    truncated: bool = False
    truncation_hint: str | None = None
    next_cursor: str | None = Field(default=None, description=_NEXT_CURSOR_DESC)
```

`src/amicus/tools/jobs.py`: add `import re` and `from amicus.errors import error_envelope`, `from amicus.schemas.envelope import InvalidArgument`, and `JobCursorParam` to the params import; after `_RETENTION` add

```python
# A cursor is the anchor row's own (started_epoch, job_id), which is the listing's sort key
# (#249, ADR 0042): a page after it is every row that sorts below it, so an anchor that has
# since been consumed or evicted still resolves. Opaque to callers; this tool alone mints it.
_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")


def _cursor_for(row: dict[str, Any]) -> str:
    return f"{row['started_epoch']!r}:{row['job_id']}"


def _parse_cursor(cursor: str) -> tuple[float, str] | None:
    """(started_epoch, job_id) from a cursor this tool issued, else None."""
    epoch, sep, job_id = cursor.partition(":")
    if not sep or not _JOB_ID_RE.fullmatch(job_id):
        return None
    try:
        return float(epoch), job_id
    except ValueError:
        return None
```

Change the tool's description (lines 215-220) to

```python
        description=(
            f"{FREE_MARKER} List the jobs known for this workspace, newest first, across all "
            "backends; narrow with `backend`, `status`, or `task_id` (no match is an empty "
            "list). Only an explicit `limit` truncates (truncated: true; pass next_cursor as "
            "`cursor` with the same filters for the page after it). The whole list is bounded "
            f"by AMICUS_JOB_MAX_COUNT. {_RETENTION}"
        ),
```

add the parameter `cursor: JobCursorParam = None,` after `limit` in the signature, and change the body from line 235 on to

```python
        assert cwd is not None
        anchor: tuple[float, str] | None = None
        if cursor is not None:
            anchor = _parse_cursor(cursor)
            if anchor is None:
                reason = "not a cursor amicus_job_list issued"
                return error_envelope(
                    "invalid_arguments",
                    f"amicus_job_list: 1 invalid argument(s): cursor — {reason}",
                    lookup.job_meta(settings, cwd, source, roots_source),
                    repair_tool="amicus_job_list",
                    repair_alternative=(
                        "Pass the previous page's next_cursor as `cursor` unchanged, or omit "
                        "it to start from the newest job."
                    ),
                    invalid_arguments=[InvalidArgument(field="cursor", reason=reason)],
                )
        rows = await asyncio.to_thread(store().list_jobs, cwd)
        tasks = lookup.task_map(settings).entries()
        # First association wins, as TaskJobMap.task_for does: a keyed replay from another
        # task adds a forward entry for recovery, and the job's own task_id is the first
        # task that named it on every surface (ADR 0020). "First" is record order, not
        # proof of creation: a creator and a replayer record concurrently, and an untasked
        # creator records nothing.
        task_by_job: dict[str, str] = {}
        for task, job in tasks.items():
            task_by_job.setdefault(job, task)
        rows = [r for r in rows if lookup.backend_of(r) is not None]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if backend is not None:
            rows = [r for r in rows if lookup.backend_of(r) == backend]
        if task_id is not None:
            wanted = tasks.get(task_id)
            rows = [r for r in rows if wanted is not None and r["job_id"] == wanted]
        if anchor is not None:
            rows = [r for r in rows if (r["started_epoch"], r["job_id"]) < anchor]
        truncated = limit is not None and len(rows) > limit
        if limit is not None:
            rows = rows[:limit]
        result = JobListResult(
            jobs=[lookup.summary_model(r, task_by_job.get(r["job_id"])) for r in rows],
            workspace=lookup.workspace_of(cwd, source),
            truncated=truncated,
            truncation_hint=(
                f"showing the {limit} newest of more matching jobs; pass next_cursor as "
                "`cursor` with the same filters for the next page, or narrow with `status`, "
                "`backend` or `task_id`"
                if truncated
                else None
            ),
            next_cursor=_cursor_for(rows[-1]) if truncated else None,
            meta=lookup.job_meta(settings, cwd, source, roots_source),
        ).model_dump(mode="json")
        return result
```

`src/amicus/tools/discovery.py` line 392: `"amicus_job_list": ([], ["workspace_root", "limit", "cursor", "status", "backend", "task_id"]),`.

- [ ] **Step 4: Run the tests**

Run the Step 2 command, then `uv run pytest tests/test_job_tools.py tests/test_discovery.py tests/test_results.py --no-cov -q`: PASS (manifest, fingerprint, wire-shape and result-format snapshots fail on drift until Procedure F).

- [ ] **Step 5: Mutation control**

Commit (Step 6); then change `< anchor` to `<= anchor` and run `uv run pytest tests/test_job_tools.py --no-cov -q -k cursor`: the paging test must fail (the anchor row reappears); restore with `git checkout -- src/amicus/tools/jobs.py`.

- [ ] **Step 6: Commit**

```sh
git add src/amicus/schemas src/amicus/tools tests
git commit -m "feat(jobs): page amicus_job_list by an opaque cursor" -m "Closes #249: a truncated page carries next_cursor, cursor returns the jobs after that anchor under the same filters, and an anchor that was consumed still resolves." -m "🤖 Generated with Claude Code"
```

- [ ] **Step 7: Procedure F** (schema-48; `RESULT_FORMAT` stays 9, since a job list is never stored).

### Task D3: ADR 0042, CHANGELOG, PR

- [ ] **Step 1: Write `docs/adr/0042-amicus-job-list-pages-by-an-opaque-cursor.md`**

```markdown
# ADR 0042: amicus_job_list pages by an opaque cursor

**Status:** Accepted (2026-09-24)

## Context

`amicus_job_list` could not page: omitting `limit` returned every retained match, and setting it truncated to the newest N with `truncated: true` and no way to reach an older job except fetching them all (#249, `[8.house-pagination]`).
The 2026-09-07 review judged house pagination unnecessary because no tool returned an unbounded list; the list is bounded by `AMICUS_JOB_MAX_COUNT`, which an operator may raise to 1,000.

## Decision

**A truncated page carries `next_cursor`, and `cursor` returns the jobs after it under the same filters.**
The cursor is the last returned row's `started_epoch` and `job_id`, joined by a colon; the listing sorts by that pair, newest first, so a page after an anchor is every row that sorts below it, and an anchor that was consumed or evicted between pages still resolves.
The text is opaque to callers: only this tool mints it, and one it did not issue is `invalid_arguments` on `cursor` with a repair naming the tool.

**"Omit `limit` for all" stays the default.**
The list is bounded by the per-workspace cap, so a bounded default page would change a documented default for no protection; the description now says what bounds it.

## Consequences

- `JobListResult` gains `next_cursor`, the tool gains `cursor`, and the listing's sort gains a tiebreak, so `FINGERPRINT` moves to `schema-48`; `RESULT_FORMAT` stays 9, since a job list is never stored.
- The `truncation_hint` names the cursor rather than "omit `limit`".
- `amicus_capabilities.tool_details` lists `cursor` among the tool's optional parameters.
```

- [ ] **Step 2: CHANGELOG**

Under `[Unreleased]`, add a `### Added` section above `### Changed`:

```markdown
### Added

- **Surface.** `amicus_job_list` pages (#249, ADR 0042). A truncated page carries
  `next_cursor`; pass it as `cursor` with the same filters for the jobs after it, and a
  cursor whose job has since been consumed still resolves, because it names the anchor's
  start time and id rather than a position. A cursor the tool did not issue is
  `invalid_arguments`. Omitting `limit` still returns every retained match, bounded by
  `AMICUS_JOB_MAX_COUNT`; the description now says so.
```

- [ ] **Step 3: Check, commit, PR**

`uv run python scripts/check_sentence_per_line.py .` (exit 0), then

```sh
git add docs CHANGELOG.md
git commit -m "docs(jobs): record ADR 0042 for job-list paging" -m "🤖 Generated with Claude Code"
```

Procedure P with title `feat(jobs): page amicus_job_list by an opaque cursor` and `Closes #249.`.

---

## PR E: the tools/list decision, and the reductions that need no window (#247)

Branch `perf/247-tools-list`, worktree `/Users/bdc/projects/amicus-wt-247`, fingerprint schema-49, ADR 0043 (status Proposed until the maintainer accepts it).

This PR does not close #247; it records the decision the issue asks for and takes items 2 and 3 as far as recorded decisions allow.
The merge itself (item 1) is implemented in a follow-up plan, written once ADR 0043 is accepted, because the deprecation window's dates depend on the release it ships in and eleven shipped documents name the `_async` tools.

### File Structure (PR E)

| Path | Change |
| --- | --- |
| `docs/adr/0043-each-paid-verb-is-one-tool-with-a-wait-flag.md` | The decision (E1). |
| `src/amicus/schemas/params.py:151-281,369-389` | `timeout_seconds` and `detail` become `ParamContract`s (E2). |
| `tests/test_params.py`, `tests/test_discovery_cost.py` | E2 tests and the re-measure. |
| `CHANGELOG.md` | E3. |

### Task E1: ADR 0043

- [ ] **Step 1: Write `docs/adr/0043-each-paid-verb-is-one-tool-with-a-wait-flag.md`**

```markdown
# ADR 0043: each paid verb is one tool with a `wait` flag

**Status:** Proposed (2026-09-24)

## Context

`tools/list` is 112,683 bytes on the `all` profile, 27,975 o200k tokens, for 18 tools, and a preloading host (Codex CLI, `docs/host-captures/install-smoke/codex/0.153.4/transcript.md`) pays it per session (#247).
Output schemas are 46% of it; the four `_async` records are 26,513 bytes, each carrying an input schema that repeats its sync twin's minus two parameters, and a byte-identical 1,959-byte `JobStarted` output schema.
The sync and `_async` twins carry identical annotations in every profile, and every sync call already runs as a detached job that the sync tail awaits (`jobs.lifecycle.run_sync` is `start_job` plus `await_job_result`), so the twin is the sync call without the wait.
ADR 0028 keeps the dry-run tools separate because their `readOnlyHint: true` is the reason they exist; nothing like that separates a twin from its sync tool.
The prose kept on the output schemas by #38, #52 and #65 guards specific misreadings and is not repetition; #41 already compressed the repeated parameter prose behind `amicus://params`.

## Decision

**Each paid verb becomes one tool, its sync tool, with a `wait: bool = true` parameter.**
`wait: false` takes exactly the `_async` twin's path today: `prepare_run` with no `timeout_seconds` and `background=True`, then `lifecycle.start_async`, returning the `JobStarted` handle; `timeout_seconds` and `detail` are ignored on that path and the parameter description says so.
The output schema is `published_schema(<Result>, JobStarted)`, a union of the verb's result and the handle behind the existing `ok` discriminator; a caller branches on top-level `job_id` (a handle) against `tool` (a result).
A keyed `wait: false` start and a keyed `wait: true` call share the `(tool, key)` reservation, because both run under the sync tool's name, so a caller can start in the background and later attach with the same key; the `idempotency_key` contract's sentence that sync and `_async` never share a key becomes "the `_async` twins, while they last, never share a key with the merged tool".

**The four `_async` tools are deprecated under the published policy and removed at the end of the window.**
They keep their whole records, gain the lifecycle marker with `replaced_by` naming the sync tool and a migration that says to pass `wait: false`, lead their descriptions with the deprecation, and move to the end of `ACTIVE_TOOLS` so each sits last in its group (ADR 0028's placement rule; the wire order of the other tools is unchanged).
`since` is the next minor release and `removal_at_or_after` is two minors later, written as constants when the follow-up plan is executed; `scripts/check_release_state.py` and `tests/test_meta.py` hold the window.
The byte win, about 26.5 KB on the `all` profile, lands at removal; during the window `tools/list` grows by the four markers and the `wait` parameter, and `tests/test_discovery_cost.py` records both moves with their reasons.

**What is taken now, before the window.**
`timeout_seconds` and `detail`, the two sync-only parameters, join the `amicus://params` mechanism as `ParamContract`s, and `_meta.fastmcp` is stripped from every catalog record (done in #250).
The output-schema prose #38, #52 and #65 chose to keep is not trimmed.
Two fields are never branched on, `raw_response` and `context_summary`; making them opaque needs a home for their schema, and none of the existing resources is it, so that is left to the follow-up plan as an `amicus_capabilities` `include_schemas` value.

## Consequences

- The follow-up plan implements the merge and the deprecation, sweeps the skill, the commands, the README and `docs/MIGRATION.md` (fifteen files name the `_async` tools), and updates the design spec's tool table and parameter matrix; `tests/test_params.py` gains `wait` in `SYNC_ONLY_PARAMS`.
- Until removal, `amicus_capabilities` still lists 18 tools; after it, 14.
- `FINGERPRINT` moves at each step; `RESULT_FORMAT` does not, since the stored result shapes are unchanged.
```

- [ ] **Step 2: Check and commit**

`uv run python scripts/check_sentence_per_line.py .` (exit 0), then

```sh
git add docs/adr/0043-each-paid-verb-is-one-tool-with-a-wait-flag.md
git commit -m "docs(tools): propose ADR 0043, one tool per paid verb with a wait flag" -m "Part of #247." -m "🤖 Generated with Claude Code"
```

Open the draft PR now (Procedure P steps P1-P2 with title `perf(tools): record the tools/list decision and compress the sync-only parameters`, body naming `Part of #247`), so the maintainer can read the ADR while E2 proceeds.

### Task E2: `timeout_seconds` and `detail` under `amicus://params`

**Files:**
- Modify: `src/amicus/schemas/params.py` (`PARAMETER_CONTRACTS`, lines 151-281; `TimeoutSecondsParam` and `DetailParam`, lines 369-389)
- Test: `tests/test_params.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_params.py` (it imports `amicus.schemas.params as p`):

```python
def test_the_sync_only_parameters_have_contracts_and_short_inline_summaries():
    """#247 item 3: timeout_seconds and detail ride four and six tools; their inline text is
    one line plus the amicus://params pointer, and the elaboration lives in `full`."""
    for name in ("timeout_seconds", "detail"):
        contract = p.PARAMETER_CONTRACTS[name]
        assert contract.name == name
        assert p.PARAMS_RESOURCE_URI in contract.summary and "\n" not in contract.summary
        assert len(contract.summary) < len(contract.full)
    assert "keyed" in p.PARAMETER_CONTRACTS["timeout_seconds"].full
    assert "job record keeps" in p.PARAMETER_CONTRACTS["detail"].full
    assert "10-600" in p.PARAMETER_CONTRACTS["timeout_seconds"].summary
    assert "raw_response" in p.PARAMETER_CONTRACTS["detail"].summary
```

`test_selection_time_facts_cover_every_contract` requires every contract to have a row in `SELECTION_TIME_FACTS` (`tests/test_params.py`, line 145), whose values are tuples of substrings the inline summary must keep; add these two rows to it:

```python
    "timeout_seconds": ("10-600", "Keyed"),
    "detail": ("raw_response", "Delivery only"),
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_params.py --no-cov -q`
Expected: `KeyError: 'timeout_seconds'`.

- [ ] **Step 3: Implement**

Add to `PARAMETER_CONTRACTS`:

```python
    "timeout_seconds": ParamContract(
        name="timeout_seconds",
        summary=(
            f"Deadline in seconds, clamped to {MIN_TIMEOUT_SECONDS}-{MAX_TIMEOUT_SECONDS}; omit "
            f"for the server default. Keyed calls: {PARAMS_RESOURCE_URI}."
        ),
        full=(
            "Omitted, the server default AMICUS_TIMEOUT_SECONDS applies. An unkeyed sync call "
            "past its deadline is terminated and its partial work lost; prefer the _async "
            "twin for work that can exceed it. For a keyed call (idempotency_key) this only "
            "bounds the wait: the run gets the job deadline (AMICUS_JOB_MAX_SECONDS) and the "
            "timeout envelope says how to fetch it."
        ),
    ),
    "detail": ParamContract(
        name="detail",
        summary=(
            "summary (default) omits raw_response.text; full includes it. Delivery only: "
            f"{PARAMS_RESOURCE_URI}."
        ),
        full=(
            "The shape is the same either way. detail selects what the call delivers, not "
            "what is kept: the job record keeps the whole answer whichever you ask for, until "
            "it expires, the per-workspace cap evicts it once returned, or "
            "amicus_job_consume_result removes it."
        ),
    ),
```

and change the two aliases to

```python
TimeoutSecondsParam = Annotated[
    int | None, Field(description=PARAMETER_CONTRACTS["timeout_seconds"].summary)
]
DetailParam = Annotated[Detail, Field(description=PARAMETER_CONTRACTS["detail"].summary)]
```

`MIN_TIMEOUT_SECONDS` and `MAX_TIMEOUT_SECONDS` are defined at line 85, above `PARAMETER_CONTRACTS`, so the f-string resolves.

- [ ] **Step 4: Run the tests**

`uv run pytest tests/test_params.py tests/test_paid_tools.py tests/test_job_tools.py --no-cov -q`: PASS (the two `detail` parameters on `amicus_job_result` and `amicus_job_consume_result` change text too; that is intended).

- [ ] **Step 5: Commit, then Procedure F** (schema-49; the docstring paragraph gives the byte drop per parameter copy: four `timeout_seconds` and six `detail` copies).

```sh
git add src/amicus/schemas/params.py tests/test_params.py
git commit -m "perf(schemas): move timeout_seconds and detail under the amicus://params contracts" -m "Part of #247 (item 3)." -m "🤖 Generated with Claude Code"
```

### Task E3: CHANGELOG and PR

- [ ] **Step 1: CHANGELOG**

Under `[Unreleased]` `### Changed` add:

```markdown
- **Surface.** `timeout_seconds` and `detail` carry a one-line summary and an `amicus://params`
  pointer on every tool that declares them, with the keyed-call and retention elaboration in
  the resource's `full` text (#247, part). `tools/list` on the `all` profile is <N> bytes
  (<-M> since 0.6.0's 112,683, o200k <T> tokens). ADR 0043 proposes merging each sync tool
  with its `_async` twin behind a `wait` flag; that change, and the deprecation of the twins,
  is not in this release.
```

Fill `<N>`, `<M>` and `<T>` from `uv run python -m amicus.manifest --measure --tokens` (`uv sync --group measure` first for the tokenizer).

- [ ] **Step 2: Check, commit, PR**

`uv run python scripts/check_sentence_per_line.py .` (exit 0), then

```sh
git add CHANGELOG.md
git commit -m "docs(tools): record the tools/list moves of #247" -m "🤖 Generated with Claude Code"
```

Finish Procedure P (P3-P5).
In the report to the maintainer, ask for a decision on ADR 0043; the follow-up plan for the merge is written only after it is accepted.

---

## Self-review notes

- Spec coverage: #245 (A1, A3), #246 (A2, A3), #248 (B1-B3), #249 (D1-D3), #250 items 2-6 (C1-C5) and item 1 declined on record (C6), #247 item 3 (E2) and the `_meta` strip (C5), #247 items 1 and 2 decided in ADR 0043 (E1) and implemented in a follow-up plan.
- Types and names used across tasks: `TIMEOUT_ALTERNATIVE`, `async_twin_for`, `render_failure(..., kind=)` (A1); `VERB_BACKENDS`, `DelegateBackendParam`, `AdversarialBackendParam` (A2); `root_not_a_directory`, `vanished_reason` (B1) consumed by B2; `WorkspaceMissingError`, `_spawn_failure` (B2); `STATIC_READ_TTL_URIS`, `_install_static_read_ttl` (C2), `_install_meta_strip` (C5); `BACKEND_TEMPLATE_DESC`, `MODELS_TEMPLATE_DESC` (C3); `JobCursorParam`, `next_cursor`, `_cursor_for`, `_parse_cursor` (D2).
- Review Focus: each line names the task whose test pins it (B2, D2, A1, A2, C2).
