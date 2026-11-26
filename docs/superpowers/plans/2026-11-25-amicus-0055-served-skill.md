# Served skill (ADR 0055) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve `collaborating-with-amicus` over `io.modelcontextprotocol/skills` when `AMICUS_SERVE_SKILL=1`, and never from a plugin's server.

**Architecture:** A new module `amicus.skill` selects the skill's files, validates them, and builds one `fastmcp.Skill` with `Skill.from_files`, reading from the wheel (force-included under `amicus/_skill/`) or, in a checkout, from `skills/`.
`create_app` adds a `SkillCatalogProvider` for it when `Settings.serve_skill` is true.
A new console entry point `cli()` parses `--no-serve-skill`, which forces `serve_skill` off whatever the environment holds; the plugin's `.mcp.json` passes it.

**Tech Stack:** Python, FastMCP ≥ 4.2.0 (`fastmcp.skills`), hatchling, pytest.

**Spec:** `docs/adr/0055-the-server-serves-the-skill-only-where-the-plugin-cannot.md`

## Global Constraints

- Served file set: `SKILL.md` plus every regular file under `references/`, recursively, skipping any path with a component starting with `.` and any name ending `~`, `.swp`, `.bak` or `.orig`; a symlink or special file is an error, not a skip.
  Nothing under `tests/` is served.
- Every served file is byte-identical to its copy under `skills/collaborating-with-amicus/`.
- Claude Code limits: no text file over 102400 bytes, the skill over 409600 bytes in all.
- Default off: unset, or any value not in `config._TRUE`, serves nothing, and the default surface stays byte-identical (every existing fingerprint, surface-digest and manifest pin unchanged).
- `--no-serve-skill` outranks `AMICUS_SERVE_SKILL=1`.
  Unknown argv is ignored with a stderr warning, as v0.16.0 ignored all argv.
- `.mcp.json`'s `--from` remains rule 19's literal; the flag goes after `amicus-mcp`. v0.16.0's `main()` reads no argv (checked on the tag), so the flag is harmless before the release that reads it.
- No `.github/**`, `AGENTS.md` or `CLAUDE.md` change (rule 9).
  `RESULT_FORMAT` unchanged.
- Focused test runs use `--no-cov` (the coverage floor is project-wide); every task ends with the full rule-2 gate.

## Fingerprint decision

Default-profile pins stay the fingerprint baseline and do not move; `FINGERPRINT_COVERS` gains nothing.
The enabled app has its own live `surface_digest`, because `surface.py` hashes the provider's resource records; that is expected, and no test pins it: the Task 4 tests check only that it differs from the default and that the served resource URIs match.
If any default pin moves during implementation, stop: this decision is wrong and goes back to the maintainer.

## Review Focus

1. `AMICUS_SERVE_SKILL=1` inherited by a plugin's server: serves nothing (Task 5 installed-wheel test).
2. Installed from the wheel, run from a cwd outside any checkout: resolves from `amicus/_skill/` (Task 5).
3. A reference added later that breaks a size limit: the gate fails (Task 2).
4. Hidden, backup, nested, symlinked or `tests/` files in the skill folder: exact set behaviour (Task 2).
5. Enabled with a missing or partial skill (no `references/`, unreadable file, bad frontmatter): server starts, `amicus_backends` reports one config error, no skill advertised (Task 4).

---

### Task 1: Raise the FastMCP floor

**Files:** `pyproject.toml:31,55`, `uv.lock`

- [ ] **Step 1:** Change both `fastmcp>=4.1.4,<4.3` and `fastmcp[tasks]>=4.1.4,<4.3` to `>=4.2.0,<4.3`; update the comment at lines 26–30 to say 4.2.0 is the first release with `fastmcp.skills` (needed by ADR 0055).
- [ ] **Step 2: Run** `uv lock` then the gate — expected: PASS.
- [ ] **Step 3: Commit** `build(deps): require fastmcp 4.2 for the skills extension`

### Task 2: Select and build the skill

**Files:** Create `src/amicus/skill.py`; modify `pyproject.toml` (add `amicus.skill` to the `amicus.sdk` contract's `forbidden_modules`, line ~136); test `tests/test_served_skill.py`.

**Interfaces — Produces:**
- `SKILL_NAME = "collaborating-with-amicus"`
- `class SkillUnavailable(Exception)`
- `skill_root() -> Traversable | None`
- `served_files(root: Traversable) -> dict[str, bytes]` — raises `SkillUnavailable` on a missing `SKILL.md`, a missing or empty `references/`, a symlink or special file, or an `OSError`.
- `build_skill() -> fastmcp.Skill` — raises `SkillUnavailable` (wrapping FastMCP's validation errors too).

- [ ] **Step 1: Write the failing tests**

```python
REPO_SKILL = REPO_ROOT / "skills" / "collaborating-with-amicus"

def _expected(root):  # independent derivation, kept deliberately naive
    out = {"SKILL.md"}
    for p in (root / "references").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not any(c.startswith(".") for c in p.relative_to(root).parts) \
                and not rel.endswith(("~", ".swp", ".bak", ".orig")):
            out.add(rel)
    return out

def test_served_set_is_exactly_skill_md_and_references():
    assert set(served_files(REPO_SKILL)) == _expected(REPO_SKILL)

def test_served_bytes_match_the_plugin_copy():
    for path, data in served_files(REPO_SKILL).items():
        assert data == (REPO_SKILL / path).read_bytes()

def test_selection_skips_hidden_and_backups_and_recurses(tmp_path): ...
    # SKILL.md, references/a.md, references/sub/b.md, references/.DS_Store,
    # references/a.md.swp, references/a.md~, tests/x.md
    # -> {"SKILL.md", "references/a.md", "references/sub/b.md"}

def test_symlink_is_rejected(tmp_path): ...       # pytest.raises(SkillUnavailable)
def test_missing_references_is_rejected(tmp_path): ...  # pytest.raises(SkillUnavailable)

def test_served_skill_fits_claude_code_limits():
    files = served_files(REPO_SKILL)
    assert max(map(len, files.values())) <= 102_400
    assert sum(map(len, files.values())) <= 409_600

def test_checkout_fallback_works_from_a_foreign_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert build_skill().name == SKILL_NAME
```

- [ ] **Step 2: Run** `uv run pytest tests/test_served_skill.py --no-cov -v` — expected: FAIL (module missing).
- [ ] **Step 3: Implement.** `skill_root()` returns `importlib.resources.files("amicus") / "_skill" / SKILL_NAME` when it holds `SKILL.md`; otherwise `Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME` only if `parents[2] / "pyproject.toml"` declares `name = "amicus"`; otherwise `None`.
      Walk with `Traversable`; detect symlinks only where the root is a real `Path`.
- [ ] **Step 4: Run** the same — expected: PASS; then the gate.
- [ ] **Step 5: Commit** `feat(skills): select and build the served skill`

### Task 3: `AMICUS_SERVE_SKILL`, `cli()` and `--no-serve-skill`

**Files:** `src/amicus/config/__init__.py`; `src/amicus/server.py`; `pyproject.toml:42` (`amicus-mcp = "amicus.server:cli"`); `.mcp.json`; `docs/MIGRATION.md` (row and the inventory prose near line 57); `docs/CONFIGURATION.md` (regenerated); `tests/test_packaging.py`; `tests/test_served_skill.py`.

**Interfaces — Produces:** `Settings.serve_skill: bool`; `main(argv: Sequence[str] = ()) -> None` (existing callers of `main()` keep working); `cli() -> None` = `main(sys.argv[1:])`; module mode calls `cli()`.

- [ ] **Step 1: Write the failing tests** (reuse the `clean_env` and `restored_signal_handlers` fixtures)

```python
def test_serve_skill_defaults_off(clean_env):
    assert config.settings().serve_skill is False

def test_serve_skill_reads_the_env(clean_env, monkeypatch):
    monkeypatch.setenv("AMICUS_SERVE_SKILL", "1")
    assert config.settings().serve_skill is True

def test_the_flag_outranks_the_env(clean_env, restored_signal_handlers, monkeypatch):
    monkeypatch.setenv("AMICUS_SERVE_SKILL", "1")
    seen = []
    def fake_create_app(settings):
        seen.append(settings)
        return SimpleNamespace(run=lambda: None)
    monkeypatch.setattr(server, "create_app", fake_create_app)
    server.main(["--no-serve-skill"])
    assert seen[0].serve_skill is False

def test_unknown_argv_is_ignored(...): ...  # main(["--bogus"]) runs; stderr names it

def test_console_script_points_at_server_cli(): ...  # replaces ..._points_at_server_main

def test_mcp_json_argv_shape():
    args = _read(".mcp.json")["mcpServers"]["amicus"]["args"]
    assert args[args.index("--from") + 2:] == ["amicus-mcp", "--no-serve-skill"]
```

Change `tests/test_packaging.py:175` and `:330` from `args[-1] == "amicus-mcp"` to the same shape check; add `AMICUS_SERVE_SKILL` to `EXPECTED_ENV_VARS` in sorted position.

- [ ] **Step 2: Run** `uv run pytest tests/test_served_skill.py tests/test_packaging.py tests/test_server.py --no-cov -v` — expected: new tests FAIL.
- [ ] **Step 3: Implement.** `EnvVar("AMICUS_SERVE_SKILL", "`1` to serve the collaborating-with-amicus skill over the MCP skills extension; ignored under `--no-serve-skill`.", "0")` beside `AMICUS_TASKS`.
      `argparse.ArgumentParser(add_help=False)` with `parse_known_args`, so `--help` keeps its current behaviour; `dataclasses.replace(settings, serve_skill=False)` under the flag.
      Update `.mcp.json` (env list sorted, argv).
      Add the MIGRATION row (no former names, default `0`).
      Run `uv run python scripts/render_configuration_doc.py --write`.
- [ ] **Step 4: Run** the same, then the gate — expected: PASS.
- [ ] **Step 5: Commit** `feat(config): add AMICUS_SERVE_SKILL and the plugin's --no-serve-skill flag`

### Task 4: Serve it from `create_app`

**Files:** `src/amicus/server.py` (`create_app`); `tests/test_served_skill.py`.

**Interfaces — Consumes:** `build_skill`, `SkillUnavailable` (Task 2); `Settings.serve_skill` (Task 3).

- [ ] **Step 1: Write the failing tests.** Every client is `Client(app, extensions=[SkillsClientExtension()])` on a modern connection.

```python
async def test_enabled_server_advertises_and_serves_the_whole_skill(settings_with):
    async with skills_client(settings_with(serve_skill=True)) as c:
        assert "io.modelcontextprotocol/skills" in c.server_capabilities.extensions
        (entry,) = await c.list_skills()
        assert entry.frontmatter.name == SKILL_NAME
        served = await c.read_skill(entry.uri)
    assert {p: f for p, f in served.files.items()} == {
        p: (REPO_SKILL / p).read_bytes() for p in _expected(REPO_SKILL)}

async def test_enabled_resource_set_is_pinned(settings_with):
    # exact skill:// resource URIs, including the generated _manifest record

async def test_default_surface_has_no_skill_trace(settings_with):
    # no skill:// resource, no extension in capabilities, and surface_digest equals
    # the existing default pin

async def test_unavailable_skill_is_a_config_error(settings_with, monkeypatch):
    monkeypatch.setattr(amicus.skill, "build_skill", _raise(SkillUnavailable("x")))
    # app starts; amicus_backends.config_errors has exactly one entry naming
    # AMICUS_SERVE_SKILL; capabilities carry no skills extension
```

Adjust names to FastMCP 4.2.5's client (`fastmcp/client/mixins/skills.py`) where they differ; the assertions stay.

- [ ] **Step 2: Run** `uv run pytest tests/test_served_skill.py --no-cov -v` — expected: new tests FAIL.
- [ ] **Step 3: Implement.** After `resources.register_resources`: if `settings.serve_skill`, try `app.add_provider(SkillCatalogProvider([build_skill()]))`; on `SkillUnavailable`, append `f"AMICUS_SERVE_SKILL=1 but the skill could not be served: {exc}"` to `state.config_errors`.
      `CAPABILITY_SUMMARY` and the tool catalog do not change.
- [ ] **Step 4: Run** the gate — expected: PASS with every existing pin unchanged.
- [ ] **Step 5: Commit** `feat(server): serve the skill when AMICUS_SERVE_SKILL=1`

### Task 5: Ship it in the wheel and prove both launch modes

**Files:** `pyproject.toml` (`[tool.hatch.build.targets.wheel.force-include]`); `tests/test_packaging.py` (slow).

- [ ] **Step 1: Write the failing slow tests.** Build into `tmp_path` with `uv build --wheel --out-dir`; assert the archive's `amicus/_skill/collaborating-with-amicus/` members equal `_expected(REPO_SKILL)` with identical bytes.
      Extend the installed-wheel smoke (around line 304): from a cwd outside the checkout, with `AMICUS_SERVE_SKILL=1`, connect a modern Skills client and assert (a) launched with `--no-serve-skill`, no extension and no `skill://` resource; (b) launched without it, the whole skill is served.
- [ ] **Step 2: Run** `uv run pytest tests/test_packaging.py -m slow --no-cov -v` — expected: FAIL.
- [ ] **Step 3: Implement**

```toml
[tool.hatch.build.targets.wheel.force-include]
"skills/collaborating-with-amicus/SKILL.md" = "amicus/_skill/collaborating-with-amicus/SKILL.md"
"skills/collaborating-with-amicus/references" = "amicus/_skill/collaborating-with-amicus/references"
```

If the member-set test fails on an out-of-policy file, switch to per-file mappings generated from `served_files`.
- [ ] **Step 4: Run** the same, then the gate — expected: PASS.
- [ ] **Step 5: Commit** `build(packaging): ship the served skill in the wheel`

### Task 6: Document it

**Files:** `README.md`; `CHANGELOG.md`; `docs/adr/0055-…md`.

- [ ] **Step 1:** README "Any other MCP client": keep the example's argv identical to the pin (no flag, no env), and add prose that from the first release after 0.16.0 `AMICUS_SERVE_SKILL=1` in the client's `env` serves the skill, on Claude Code v2.1.331+ in public beta and not on Codex, with ADR 0055's host caveats; say triggering on the host is not yet measured.
- [ ] **Step 2:** `CHANGELOG.md` `## [Unreleased]` → `### Added`: the variable, the flag, and the FastMCP 4.2 floor.
- [ ] **Step 3:** ADR 0055: Status Accepted with the date; name `--no-serve-skill`; add the Fingerprint decision above in one or two sentences.
- [ ] **Step 4: Run** the gate — expected: PASS.
- [ ] **Step 5: Commit** `docs(skills): document the served skill`

## After the tasks

Open one draft PR (rule 7); rule-19 literals and the marketplace pointer stay untouched.
Follow-ups outside this PR: a host capture of the served skill on Claude Code, and, if `--help` behaviour ever changes, the stale comment in `.github/workflows/publish.yml:29` in its own governance PR (rule 9).
