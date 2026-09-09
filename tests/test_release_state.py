"""The release predicate `scripts/check_release_state.py` enforces in the publish workflow.

Two kinds of check live in that script and they are worth different amounts, so they are
tested separately here:

- The tree checks prove facts. A green `check_tree` means the literals, the changelog section
  and `uv.lock` really do agree, on this tree.
- `check_tag` proves only that a well-formed evidence record naming this commit exists. It
  cannot prove the live gates ran. The tests below assert the shape of that check, never that
  it establishes more than it does.

Every rejection path is exercised, because a predicate that cannot fail would be exactly the
false confidence issue #25 was filed about. The positive control -- the fixture passing
unmodified -- runs first, so a broken fixture cannot make the negative controls pass
vacuously.

Two layers, deliberately. Most checks below call the predicate functions directly against a
fixture tree, which is where the many rejection paths are cheap to cover. The last section
drives `main()` against a REAL git repository with real annotated and lightweight tags,
because that is the only thing that exercises what the workflow actually depends on: `git
cat-file -t`, peeling the tag to its commit, and reading the message back out. Injected values
cannot fail those commands.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_release_state.py"
_spec = importlib.util.spec_from_file_location("check_release_state", _SCRIPT)
assert _spec is not None and _spec.loader is not None
release_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_state)

VERSION = "1.2.3"
COMMIT = "a" * 40
BATCH = "b" * 32

BACKENDS = ("codex", "kimi", "claude")


def _record(**overrides):
    record = {
        "batch_id": BATCH,
        "recorded_at": "2026-09-08T12:00:00+00:00",
        "commit": COMMIT,
        "tree_clean": True,
        "backends": {
            name: {
                "test_file": f"tests/test_{name}_live.py",
                "exit_status": 0,
                "cli_version": f"{name}-cli 1.0.0",
                "batch_id": BATCH,
            }
            for name in BACKENDS
        },
    }
    record.update(overrides)
    return record


CHANGELOG = f"""# Changelog

## [Unreleased]

## [{VERSION}] - 2026-09-08

### Added

- A thing.
"""


@pytest.fixture
def repo(tmp_path):
    """A minimal tree carrying every file the release predicate reads."""
    (tmp_path / "src" / "amicus").mkdir(parents=True)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".codex-plugin").mkdir()

    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "amicus"\nversion = "{VERSION}"\n', encoding="utf-8"
    )
    (tmp_path / "src" / "amicus" / "__init__.py").write_text(
        f'"""amicus."""\n\n__version__ = "{VERSION}"\n', encoding="utf-8"
    )
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        (tmp_path / manifest).write_text(
            json.dumps({"name": "amicus", "version": VERSION}) + "\n", encoding="utf-8"
        )
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "amicus": {
                        "command": "uvx",
                        "args": [
                            "--from",
                            f"git+https://github.com/briandconnelly/amicus.git@v{VERSION}",
                            "amicus-mcp",
                        ],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    return tmp_path


def _lock_ok(*args, **kwargs):
    return subprocess.CompletedProcess(args=["uv", "lock", "--check"], returncode=0, stdout="")


def _lock_stale(*args, **kwargs):
    return subprocess.CompletedProcess(
        args=["uv", "lock", "--check"],
        returncode=2,
        stdout="",
        stderr="error: The lockfile is not up-to-date with pyproject.toml\n",
    )


# --- positive control ------------------------------------------------------------------


def test_the_unmodified_fixture_satisfies_the_tree_predicate(repo):
    """The instrument can report a pass. Every negative control below depends on this."""
    assert release_state.check_tree(VERSION, repo_root=repo, run=_lock_ok) == []


# --- version literals ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "mutate"),
    [
        ("pyproject.toml", lambda text: text.replace(VERSION, "9.9.9")),
        ("src/amicus/__init__.py", lambda text: text.replace(VERSION, "9.9.9")),
        (".claude-plugin/plugin.json", lambda text: text.replace(VERSION, "9.9.9")),
        (".codex-plugin/plugin.json", lambda text: text.replace(VERSION, "9.9.9")),
        (".mcp.json", lambda text: text.replace(f"@v{VERSION}", "@v9.9.9")),
    ],
)
def test_a_literal_left_behind_is_rejected(repo, path, mutate):
    target = repo / path
    target.write_text(mutate(target.read_text(encoding="utf-8")), encoding="utf-8")
    problems = release_state.check_version_literals(VERSION, repo_root=repo)
    assert any(path.split("/")[-1] in problem or path in problem for problem in problems), problems


def test_an_init_without_a_version_line_is_rejected(repo):
    (repo / "src" / "amicus" / "__init__.py").write_text('"""amicus."""\n', encoding="utf-8")
    problems = release_state.check_version_literals(VERSION, repo_root=repo)
    assert any("__version__" in problem for problem in problems), problems


# --- changelog -------------------------------------------------------------------------


def test_a_changelog_without_a_dated_section_is_rejected(repo):
    (repo / "CHANGELOG.md").write_text(
        CHANGELOG.replace(f"## [{VERSION}] - 2026-09-08", "## [0.0.9] - 2026-01-01"),
        encoding="utf-8",
    )
    problems = release_state.check_changelog(VERSION, repo_root=repo)
    assert any("no dated" in problem for problem in problems), problems


def test_an_unreleased_stub_that_was_never_rolled_over_is_rejected(repo):
    """The release PR must roll `Unreleased` into a dated section; an un-rolled file fails."""
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n", encoding="utf-8"
    )
    problems = release_state.check_changelog(VERSION, repo_root=repo)
    assert any("no dated" in problem for problem in problems), problems


def test_two_dated_sections_for_one_version_are_rejected(repo):
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(
        text + f"\n## [{VERSION}] - 2026-09-07\n\n- A duplicate.\n", encoding="utf-8"
    )
    problems = release_state.check_changelog(VERSION, repo_root=repo)
    assert any("expected 1" in problem for problem in problems), problems


def test_a_missing_unreleased_heading_is_rejected(repo):
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(text.replace("## [Unreleased]\n\n", ""), encoding="utf-8")
    problems = release_state.check_changelog(VERSION, repo_root=repo)
    assert any("Unreleased" in problem for problem in problems), problems


def test_an_unreleased_heading_below_the_release_is_rejected(repo):
    (repo / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{VERSION}] - 2026-09-08\n\n- A thing.\n\n## [Unreleased]\n",
        encoding="utf-8",
    )
    problems = release_state.check_changelog(VERSION, repo_root=repo)
    assert any("below" in problem for problem in problems), problems


# --- uv.lock ---------------------------------------------------------------------------


def test_a_stale_lockfile_is_rejected(repo):
    problems = release_state.check_lock(repo_root=repo, run=_lock_stale)
    assert any("uv lock --check" in problem for problem in problems), problems


def test_a_missing_uv_binary_is_reported_rather_than_skipped(repo):
    def run(*args, **kwargs):
        raise FileNotFoundError("uv")

    problems = release_state.check_lock(repo_root=repo, run=run)
    assert any("could not run" in problem for problem in problems), problems


# --- the tag and the evidence it carries -----------------------------------------------


def _check_tag(**overrides):
    kwargs = {
        "commit": COMMIT,
        "object_type": "tag",
        "peeled_commit": COMMIT,
        "message": json.dumps(_record(), indent=2),
    }
    kwargs.update(overrides)
    return release_state.check_tag(f"v{VERSION}", **kwargs)


def test_an_annotated_tag_carrying_a_complete_record_is_accepted():
    assert _check_tag() == []


def test_a_lightweight_tag_is_rejected():
    problems = _check_tag(object_type="commit")
    assert any("lightweight" in problem for problem in problems), problems


def test_a_tag_pointing_at_another_commit_is_rejected():
    problems = _check_tag(peeled_commit="c" * 40)
    assert any("points at" in problem for problem in problems), problems


def test_an_empty_tag_message_is_rejected():
    problems = _check_tag(message="   \n")
    assert any("empty" in problem for problem in problems), problems


def test_a_prose_tag_message_is_rejected():
    problems = _check_tag(message="Release 1.2.3\n")
    assert any("not the JSON evidence record" in problem for problem in problems), problems


def test_a_json_message_that_is_not_an_object_is_rejected():
    problems = _check_tag(message="[1, 2, 3]")
    assert any("not an object" in problem for problem in problems), problems


def test_a_record_naming_another_commit_is_rejected():
    problems = _check_tag(message=json.dumps(_record(commit="c" * 40)))
    assert any("commit" in problem for problem in problems), problems


def test_a_record_with_a_failed_suite_is_rejected():
    record = _record()
    record["backends"]["kimi"]["exit_status"] = 1
    problems = _check_tag(message=json.dumps(record))
    assert any("exit_status" in problem for problem in problems), problems


def test_a_record_missing_a_backend_is_rejected():
    record = _record()
    del record["backends"]["claude"]
    problems = _check_tag(message=json.dumps(record))
    assert any("claude" in problem for problem in problems), problems


def test_a_record_taken_on_a_dirty_tree_is_rejected():
    problems = _check_tag(message=json.dumps(_record(tree_clean=False)))
    assert any("dirty" in problem for problem in problems), problems


def test_a_signed_tag_keeps_its_record_readable():
    """Rule 20 does not require a signature, and must not break on one either."""
    message = (
        json.dumps(_record(), indent=2)
        + "\n-----BEGIN PGP SIGNATURE-----\nnot-a-real-signature\n-----END PGP SIGNATURE-----\n"
    )
    assert _check_tag(message=message) == []


def test_freshness_is_deliberately_not_checked_after_tagging():
    """An old but otherwise valid record still publishes.

    A tag is immutable. If queue time or a slow deployment approval could age a record past a
    window, a legitimate tag would become permanently unpublishable. Freshness is enforced
    locally, before the tag exists, by `record_live_gate_evidence.validate`.
    """
    stale = _record(recorded_at="2020-01-01T00:00:00+00:00")
    assert _check_tag(message=json.dumps(stale)) == []


# --- the tag name ----------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2", "release-1.2.3", "v1.2.3-rc1"])
def test_a_tag_that_is_not_vX_Y_Z_is_rejected(tag):
    version, problems = release_state.version_for_tag(tag)
    assert version is None
    assert problems


def test_a_well_formed_tag_yields_its_version():
    assert release_state.version_for_tag("v1.2.3") == ("1.2.3", [])


# --- this repository -------------------------------------------------------------------


def test_this_repository_s_version_literals_all_agree():
    """The literals must agree on every commit, so this runs against the real tree.

    Deliberately NOT the whole tree predicate. `check_changelog` does not hold on an ordinary
    commit and is not supposed to: `docs/RELEASING.md` step 2 rolls `## [Unreleased]` into a
    dated section in the release PR, so between releases there is no dated section for the
    version `pyproject.toml` declares. Asserting the full predicate here would either fail on
    `main` or force the changelog to be rolled over early, which is the state the release PR
    exists to create. `check_lock` is excluded for a different reason: `uv lock --check` is
    already a pre-commit hook, and re-running it here would spend a resolver call per test
    run to re-prove what that hook proves.
    """
    repo_root = Path(__file__).resolve().parent.parent
    version = release_state.declared_version(repo_root)
    problems = release_state.check_version_literals(version, repo_root=repo_root)
    assert problems == [], "; ".join(problems)


# --- the real git path the workflow depends on -----------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def git_repo(repo, monkeypatch):
    """The fixture tree, as a real git repository with one commit.

    `check_lock` is stubbed out for this layer only: the fixture has no `uv.lock`, and running
    a real resolver here would test uv rather than the tag handling these tests exist for.
    The lock check has its own negative controls above, with an injected runner.
    """
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release commit")
    monkeypatch.setattr(release_state, "check_lock", lambda **kwargs: [])
    return repo


def _tag_annotated(repo: Path, tag: str, record: dict, ref: str = "HEAD") -> None:
    message = repo / f".{tag}.json"
    message.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _git(repo, "tag", "-a", tag, "-F", str(message), "--cleanup=verbatim", ref)
    message.unlink()


def test_main_accepts_a_real_annotated_tag_carrying_the_record(git_repo, tmp_path):
    head = _git(git_repo, "rev-parse", "HEAD")
    _tag_annotated(git_repo, f"v{VERSION}", _record(commit=head))
    summary = tmp_path / "summary.md"

    rc = release_state.main(
        ["--tag", f"v{VERSION}", "--commit", head, "--summary", str(summary)],
        repo_root=git_repo,
    )

    assert rc == 0
    text = summary.read_text(encoding="utf-8")
    assert "PASSED" in text
    # The summary must never let a reviewer read the record as proof the suites ran.
    assert "not an attestation" in text


def test_main_rejects_a_real_lightweight_tag(git_repo, capsys):
    """A lightweight tag has no message, so it can carry no evidence at all."""
    head = _git(git_repo, "rev-parse", "HEAD")
    _git(git_repo, "tag", f"v{VERSION}", "HEAD")

    assert release_state.main(["--tag", f"v{VERSION}", "--commit", head], repo_root=git_repo) == 1
    assert "lightweight tag" in capsys.readouterr().err


def test_main_rejects_a_real_tag_whose_message_is_prose(git_repo, capsys):
    head = _git(git_repo, "rev-parse", "HEAD")
    _git(git_repo, "tag", "-a", f"v{VERSION}", "-m", f"Release {VERSION}", "HEAD")

    assert release_state.main(["--tag", f"v{VERSION}", "--commit", head], repo_root=git_repo) == 1
    assert "not the JSON evidence record" in capsys.readouterr().err


def test_main_rejects_a_real_tag_left_on_an_earlier_commit(git_repo, capsys):
    """The PR branch gained a commit after the evidence was taken."""
    head = _git(git_repo, "rev-parse", "HEAD")
    _tag_annotated(git_repo, f"v{VERSION}", _record(commit=head))
    _git(git_repo, "commit", "-q", "--allow-empty", "-m", "a later commit")
    later = _git(git_repo, "rev-parse", "HEAD")

    assert release_state.main(["--tag", f"v{VERSION}", "--commit", later], repo_root=git_repo) == 1
    err = capsys.readouterr().err
    assert "points at" in err, err
    assert "does not match HEAD" in err, err


def test_main_rejects_a_tag_that_does_not_exist(git_repo, capsys):
    head = _git(git_repo, "rev-parse", "HEAD")

    assert release_state.main(["--tag", "v9.9.9", "--commit", head], repo_root=git_repo) == 1
    assert "could not read tag" in capsys.readouterr().err


def test_main_checks_the_tree_alone_when_no_tag_is_given(git_repo):
    """The form `docs/RELEASING.md` step 3 runs, before the tag exists."""
    assert release_state.main([], repo_root=git_repo) == 0


def test_a_real_tag_message_survives_git_cleanup_verbatim(git_repo):
    """The exact tagging command the runbook prescribes must round-trip the JSON.

    `git tag -F` applies a cleanup mode to the message. If it stripped or reflowed anything,
    the record would not parse back and every release would fail at `verify`.
    """
    head = _git(git_repo, "rev-parse", "HEAD")
    record = _record(commit=head)
    _tag_annotated(git_repo, f"v{VERSION}", record)

    message = _git(git_repo, "tag", "-l", "--format=%(contents)", f"v{VERSION}")
    assert json.loads(message) == record
