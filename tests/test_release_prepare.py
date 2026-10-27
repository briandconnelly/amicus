"""`scripts/release.py prepare`: the rule-19 release PR's edits, made by one command (#374).

The fixture is a real git repository with real history: a previous release `PREVIOUS`, its
annotated tag, and a later commit whose marketplace pointer names that tag by `ref` and `sha`,
which is what `main` looks like after a pointer PR. `prepare` runs against it with real `git`,
so the branch and clean-tree refusals and the marketplace consistency check exercise the
commands they depend on. Only `uv` is stubbed: `uv lock` would resolve against an index.

The positive control runs first, so a broken fixture cannot make a refusal pass vacuously.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: `dataclasses` resolves a module's string annotations through it.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")
release_state = release.release_state

PREVIOUS = "1.2.2"
NEXT = "1.3.0"
TODAY = dt.date(2026, 10, 27)
REPO_URL = "https://github.com/briandconnelly/amicus"
PIN = "git+https://github.com/briandconnelly/amicus.git@v{}"

UNRELEASED_BODY = """### Added

- A new thing.

### Fixed

- A broken thing.
"""

# Formatted the way no JSON serializer would write it, so any rewrite of the file shows.
MARKETPLACE = """{"name": "amicus",   "owner": {"name": "someone"},
  "plugins": [ {"name": "amicus", "description": "a plugin",
    "source": {"source": "url", "url": "https://github.com/briandconnelly/amicus.git",
               "ref": "v%s", "sha": "%s"} } ]}"""


def _changelog(unreleased: str) -> str:
    return f"""# Changelog

Some lead text.

## [Unreleased]
{unreleased}
## [{PREVIOUS}] - 2026-09-01

### Added

- An earlier thing.

[Unreleased]: {REPO_URL}/compare/v{PREVIOUS}...HEAD
[{PREVIOUS}]: {REPO_URL}/releases/tag/v{PREVIOUS}
"""


def _readme(version: str) -> str:
    return f"""# amicus

```json
{{"args": ["--from", "{PIN.format(version)}", "amicus-mcp"]}}
```

## Status and known limits

{PREVIOUS} is the current release.
"""


def _manifest(version: str) -> str:
    return f'{{\n  "name": "amicus",\n  "version": "{version}",\n  "skills": "./skills/"\n}}\n'


def _mcp(version: str) -> str:
    return json.dumps(
        {"mcpServers": {"amicus": {"command": "uvx", "args": ["--from", PIN.format(version)]}}},
        indent=2,
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """`PREVIOUS` released and tagged, the pointer moved to it, unreleased work on a branch."""
    repo = tmp_path / "amicus"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(
        repo,
        "pyproject.toml",
        f'[project]\nname = "amicus"\nversion = "{PREVIOUS}"\n\n'
        '[tool.ruff]\ntarget-version = "py311"\n',
    )
    _write(repo, "src/amicus/__init__.py", f'"""amicus."""\n\n__version__ = "{PREVIOUS}"\n')
    for manifest in release.PLUGIN_MANIFESTS:
        _write(repo, manifest, _manifest(PREVIOUS))
    _write(repo, ".mcp.json", _mcp(PREVIOUS))
    _write(repo, "README.md", _readme(PREVIOUS))
    _write(repo, "CHANGELOG.md", _changelog("\n"))
    _write(repo, release.MARKETPLACE_PATH, MARKETPLACE % ("0.0.1", "0" * 40))
    _write(repo, release_state.DEPRECATIONS_PATH, "DEPRECATED_TOOLS: dict = {}\n")
    _write(repo, release_state.LEGACY_ENV_SPEC_PATH, 'LEGACY_REMOVAL_VERSION = "9.0.0"\n')
    _write(repo, release_state.GLOBAL_ENV_PATH, "")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"release {PREVIOUS}")
    _git(repo, "tag", "-a", f"v{PREVIOUS}", "-m", "evidence")
    released = _git(repo, "rev-parse", "HEAD")

    _write(repo, release.MARKETPLACE_PATH, MARKETPLACE % (PREVIOUS, released))
    _write(repo, "CHANGELOG.md", _changelog("\n" + UNRELEASED_BODY))
    _git(repo, "commit", "-q", "-am", "work after the release")
    _git(repo, "switch", "-q", "-c", f"chore/release-{NEXT}")
    return repo


class FakeUv:
    """`uv lock` and `uv lock --check`, recorded; any other command fails the test loudly."""

    def __init__(self, *, lock_returncode: int = 0, on_lock=None):
        self.calls: list[list[str]] = []
        self.lock_returncode = lock_returncode
        self.on_lock = on_lock

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        if cmd == ["uv", "lock"]:
            if self.on_lock is not None:
                self.on_lock()
            return subprocess.CompletedProcess(
                cmd, self.lock_returncode, stdout="", stderr="error: resolution failed\n"
            )
        if cmd == ["uv", "lock", "--check"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command {cmd!r}")


def _context(repo: Path, uv: FakeUv | None = None):
    return release.Context(repo_root=repo, run=uv or FakeUv(), today=lambda: TODAY)


def _snapshot(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in sorted(repo.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


def _prepare(repo: Path, *argv: str, uv: FakeUv | None = None) -> int:
    return release.main(["prepare", *argv], context=_context(repo, uv))


# --- positive control ------------------------------------------------------------------


def test_prepare_yields_a_tree_the_pre_tag_checks_accept(repo, capsys):
    uv = FakeUv()
    assert _prepare(repo, NEXT, uv=uv) == 0, capsys.readouterr().err
    assert ["uv", "lock"] in uv.calls
    assert release_state.check_tree_pre_tag(NEXT, repo_root=repo, run=uv) == []
    out = capsys.readouterr().out
    assert "release-state checks hold" in out
    assert "README.md's prose" in out


def test_the_only_release_check_left_is_the_tag_that_does_not_exist_yet(repo):
    assert _prepare(repo, NEXT) == 0
    problems = release_state.check_tree(NEXT, repo_root=repo, run=FakeUv())
    assert len(problems) == 1
    assert f".mcp.json pins v{NEXT}, which does not exist" in problems[0]
    # ...and that one clears once RELEASING step 3 creates the tag.
    _git(repo, "tag", "-a", f"v{NEXT}", "-m", "evidence")
    assert release_state.check_tree(NEXT, repo_root=repo, run=FakeUv()) == []


def test_every_literal_moves_and_nothing_else_in_those_files(repo):
    assert _prepare(repo, NEXT) == 0
    assert (repo / "pyproject.toml").read_text() == (
        f'[project]\nname = "amicus"\nversion = "{NEXT}"\n\n[tool.ruff]\ntarget-version = "py311"\n'
    )
    assert (repo / "src/amicus/__init__.py").read_text().endswith(f'__version__ = "{NEXT}"\n')
    for manifest in release.PLUGIN_MANIFESTS:
        assert (repo / manifest).read_text() == _manifest(NEXT)
    assert (repo / ".mcp.json").read_text() == _mcp(NEXT)


def test_readme_moves_its_install_pin_but_not_its_prose(repo, capsys):
    assert _prepare(repo, NEXT) == 0
    readme = (repo / "README.md").read_text()
    assert PIN.format(NEXT) in readme
    assert PIN.format(PREVIOUS) not in readme
    assert f"{PREVIOUS} is the current release." in readme
    assert "review README.md's prose" in capsys.readouterr().out


def test_the_changelog_rolls_with_a_fresh_unreleased_and_footer_links(repo):
    assert _prepare(repo, NEXT) == 0
    assert (
        (repo / "CHANGELOG.md").read_text()
        == f"""# Changelog

Some lead text.

## [Unreleased]

## [{NEXT}] - 2026-10-27

{UNRELEASED_BODY}
## [{PREVIOUS}] - 2026-09-01

### Added

- An earlier thing.

[Unreleased]: {REPO_URL}/compare/v{NEXT}...HEAD
[{NEXT}]: {REPO_URL}/compare/v{PREVIOUS}...v{NEXT}
[{PREVIOUS}]: {REPO_URL}/releases/tag/v{PREVIOUS}
"""
    )
    assert release_state.check_changelog(NEXT, repo_root=repo) == []


def test_a_first_release_links_to_its_tag():
    text = f"# Changelog\n\n## [Unreleased]\n\n- A thing.\n\n[Unreleased]: {REPO_URL}/commits\n"
    rolled = release.roll_changelog(text, "0.1.0", TODAY)
    assert rolled == (
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-10-27\n\n- A thing.\n\n"
        f"[Unreleased]: {REPO_URL}/compare/v0.1.0...HEAD\n"
        f"[0.1.0]: {REPO_URL}/releases/tag/v0.1.0\n"
    )


def test_the_marketplace_is_byte_identical(repo):
    before = (repo / release.MARKETPLACE_PATH).read_bytes()
    assert _prepare(repo, NEXT) == 0
    assert (repo / release.MARKETPLACE_PATH).read_bytes() == before


def test_a_marketplace_changed_during_prepare_is_reported(repo, capsys):
    """The script's own byte-identity assertion can fail: something rewriting the pointer
    mid-run (here, the `uv lock` step) is caught rather than passed."""
    target = repo / release.MARKETPLACE_PATH

    def touch():
        target.write_text(target.read_text() + "\n", encoding="utf-8")

    assert _prepare(repo, NEXT, uv=FakeUv(on_lock=touch)) == 1
    assert "rule 24 forbids" in capsys.readouterr().err


# --- the date is UTC -------------------------------------------------------------------


def test_the_date_is_the_utc_date_not_the_local_one():
    pacific = dt.timezone(dt.timedelta(hours=-7))
    evening = dt.datetime(2026, 10, 27, 18, 30, tzinfo=pacific)  # 01:30 UTC on the 28th
    assert release.utc_date(evening) == dt.date(2026, 10, 28)


def test_a_naive_datetime_has_no_utc_date():
    with pytest.raises(ValueError, match="aware"):
        release.utc_date(dt.datetime(2026, 10, 27, 18, 30))


def test_the_default_clock_reads_utc():
    assert release.Context().today() == dt.datetime.now(dt.UTC).date()


def test_the_injected_clock_dates_the_section(repo):
    context = release.Context(repo_root=repo, run=FakeUv(), today=lambda: dt.date(2027, 1, 2))
    assert release.main(["prepare", NEXT], context=context) == 0
    assert f"## [{NEXT}] - 2027-01-02" in (repo / "CHANGELOG.md").read_text()


# --- --check ---------------------------------------------------------------------------


def test_check_prints_the_plan_and_writes_nothing(repo, capsys):
    before = _snapshot(repo)
    uv = FakeUv()
    assert _prepare(repo, NEXT, "--check", uv=uv) == 0
    assert _snapshot(repo) == before
    assert uv.calls == []
    out = capsys.readouterr().out
    assert f'+version = "{NEXT}"' in out
    assert f"+## [{NEXT}] - 2026-10-27" in out
    assert f"+[{NEXT}]: {REPO_URL}/compare/v{PREVIOUS}...v{NEXT}" in out
    assert release.MARKETPLACE_PATH not in out


# --- refusals --------------------------------------------------------------------------


def _assert_refused(repo, capsys, *argv: str, reason: str) -> None:
    before = _snapshot(repo)
    uv = FakeUv()
    assert _prepare(repo, *argv, uv=uv) == 1
    assert reason in capsys.readouterr().err
    assert _snapshot(repo) == before
    assert uv.calls == []


@pytest.mark.parametrize("version", [PREVIOUS, "1.2.1", "0.9.9"])
def test_a_version_not_ahead_of_the_declared_one_is_refused(repo, capsys, version):
    _assert_refused(repo, capsys, version, reason="not greater than the declared")


@pytest.mark.parametrize("flag", [(), ("--check",)])
def test_refusals_hold_under_check_too(repo, capsys, flag):
    _assert_refused(repo, capsys, PREVIOUS, *flag, reason="not greater than the declared")


def test_versions_compare_numerically(repo):
    assert _prepare(repo, "1.2.10") == 0  # "1.2.10" < "1.2.2" as strings


@pytest.mark.parametrize("version", ["1.3", "v1.3.0", "1.3.0rc1"])
def test_a_malformed_version_is_refused(repo, capsys, version):
    _assert_refused(repo, capsys, version, reason="is not X.Y.Z")


@pytest.mark.parametrize("flag", [(), ("--check",)])
@pytest.mark.parametrize("version", [f"{NEXT}\n", f"{NEXT}\r\n", f"\n{NEXT}", f" {NEXT}"])
def test_a_version_with_surrounding_whitespace_is_refused(repo, capsys, version, flag):
    """A `$`-anchored `match` accepts a trailing newline, which would then be written into
    TOML, Python and JSON literals; the version must be X.Y.Z and nothing else."""
    _assert_refused(repo, capsys, version, *flag, reason="is not X.Y.Z")


def test_main_is_refused(repo, capsys):
    _git(repo, "switch", "-q", "main")
    _assert_refused(repo, capsys, NEXT, reason="on branch main")


@pytest.mark.parametrize(
    "dirty",
    [
        lambda repo: (repo / "stray.txt").write_text("x"),
        lambda repo: (repo / "README.md").write_text("edited\n"),
    ],
    ids=["untracked", "modified"],
)
def test_a_dirty_tree_is_refused(repo, capsys, dirty):
    dirty(repo)
    _assert_refused(repo, capsys, NEXT, reason="not clean")


def test_an_untracked_file_is_refused_even_when_status_hides_untracked_files(repo, capsys):
    """`git status --porcelain` honours `status.showUntrackedFiles=no`; the refusal must not."""
    _git(repo, "config", "status.showUntrackedFiles", "no")
    (repo / "stray.txt").write_text("x")
    assert _git(repo, "status", "--porcelain") == "", "known positive: config hides it"
    _assert_refused(repo, capsys, NEXT, reason="not clean")


@pytest.mark.parametrize("body", ["\n", "\n\n   \n\n"])
def test_an_empty_unreleased_section_is_refused(repo, capsys, body):
    _write(repo, "CHANGELOG.md", _changelog(body))
    _git(repo, "commit", "-q", "-am", "empty")
    _assert_refused(repo, capsys, NEXT, reason="`## [Unreleased]` section is empty")


def test_an_existing_link_for_the_new_version_is_refused(repo, capsys):
    text = (repo / "CHANGELOG.md").read_text() + f"[{NEXT}]: {REPO_URL}/x\n"
    _write(repo, "CHANGELOG.md", text)
    _git(repo, "commit", "-q", "-am", "stale link")
    _assert_refused(repo, capsys, NEXT, reason=f"already defines a `[{NEXT}]:` link")


def test_a_failed_uv_lock_is_reported(repo, capsys):
    assert _prepare(repo, NEXT, uv=FakeUv(lock_returncode=1)) == 1
    assert "`uv lock` failed: error: resolution failed" in capsys.readouterr().err


LOCK = 'version = 1\nrevision = 5\n\n[[package]]\nname = "amicus"\nversion = "{}"\n'


def _commit_lock(repo: Path) -> Path:
    path = repo / "uv.lock"
    path.write_text(LOCK.format(PREVIOUS), encoding="utf-8")
    _git(repo, "add", "uv.lock")
    _git(repo, "commit", "-q", "-m", "lock")
    return path


def test_a_lock_that_moves_only_amicus_version_raises_no_warning(repo, capsys):
    path = _commit_lock(repo)
    uv = FakeUv(on_lock=lambda: path.write_text(LOCK.format(NEXT), encoding="utf-8"))
    assert _prepare(repo, NEXT, uv=uv) == 0
    assert "warning" not in capsys.readouterr().err


def test_lock_churn_beyond_the_version_line_is_warned_about(repo, capsys):
    """uv 0.13 rewrote a revision-3 lock as revision 5 when 0.11.1 was prepared."""
    path = _commit_lock(repo)
    churned = LOCK.format(NEXT).replace("revision = 5", "revision = 6")
    uv = FakeUv(on_lock=lambda: path.write_text(churned, encoding="utf-8"))
    assert _prepare(repo, NEXT, uv=uv) == 0
    assert "beyond amicus's own version line" in capsys.readouterr().err


def test_a_subcommand_is_required():
    with pytest.raises(SystemExit) as raised:
        release.main([])
    assert raised.value.code == 2
