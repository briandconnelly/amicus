"""`check_backend_compat.py release-brief` and `print-updates --json`, with git and npm stubbed.

Nothing here reaches the network, origin or a real tag: git is a table of answers that fails
the test on any command it does not know, and npm's lookups are plain functions. The
versions a test calls supported are read from the shipped contracts, so the tests do not
go stale when a support PR moves them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from amicus.backends.codex import contract as codex_contract
from amicus.backends.pi import contract as pi_contract

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_backend_compat.py"
_spec = importlib.util.spec_from_file_location("check_backend_compat", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
compat = importlib.util.module_from_spec(_spec)
sys.modules["check_backend_compat"] = compat
_spec.loader.exec_module(compat)

TAG = "v1.2.2"
TAG_SHA = "1" * 40
CODEX_OLD = "{}.{}.0".format(*max(codex_contract.SUPPORTED_VERSIONS))
CODEX_NEW = "99.0.0"  # outside every shipped contract
PI = "{}.{}.0".format(*max(pi_contract.SUPPORTED_VERSIONS))
CLAUDE_OLD, CLAUDE_NEW = "2.1.330", "2.1.331"


def _record(**versions: str) -> str:
    return json.dumps(
        {
            "recorded_at": "2026-11-22T15:29:44+00:00",
            "commit": "2" * 40,
            "backends": {b: {"cli_version": v} for b, v in versions.items()},
        },
        indent=2,
    )


def _cat_file(message: str) -> str:
    return (
        f"object {'2' * 40}\ntype commit\ntag {TAG}\ntagger M <m@example.com> 0 +0000\n\n{message}"
    )


RECORD = _record(codex=f"codex-cli {CODEX_OLD}", claude=f"{CLAUDE_OLD} (Claude Code)", pi=PI)


class FakeGit:
    """Answers the git commands it is given; anything else fails the test."""

    def __init__(self, answers: dict[tuple[str, ...], tuple[int, str]]):
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(list(args))
        if tuple(args) not in self.answers:
            raise AssertionError(f"unexpected git {args!r}")
        return self.answers[tuple(args)]


LS_REMOTE = ("ls-remote", "--tags", "origin", "refs/tags/v*")


def _git(*, message: str = RECORD, extra: dict | None = None) -> FakeGit:
    listing = "\n".join(
        [
            f"{'0' * 40}\trefs/tags/v1.2.1",
            f"{TAG_SHA}\trefs/tags/{TAG}",
            f"{'2' * 40}\trefs/tags/{TAG}^{{}}",
            f"{'3' * 40}\trefs/tags/v1.2.2-rc1",
        ]
    )
    answers = {
        LS_REMOTE: (0, listing),
        ("cat-file", "tag", f"refs/tags/{TAG}"): (0, _cat_file(message)),
    }
    answers.update(extra or {})
    return FakeGit(answers)


LATEST = {"codex": CODEX_NEW, "claude": CLAUDE_NEW, "pi": PI}
PUBLISHED = {
    "codex": [CODEX_OLD, "98.0.0-alpha.1", CODEX_NEW, "99.0.1"],
    "claude": ["2.1.329", CLAUDE_OLD, "2.1.331-next.1", CLAUDE_NEW],
    "pi": [PI],
}


def _capture(root: Path, backend: str, version: str, flags: list[str], findings=False) -> None:
    folder = root / f"{backend}-help" / version
    folder.mkdir(parents=True)
    rows = "\n".join(f"  {flag} <value>  does a thing" for flag in flags)
    (folder / f"{backend}-help.txt").write_text(f"Usage: {backend}\n\nOptions:\n{rows}\n")
    if findings:
        (folder / "FINDINGS.md").write_text("# findings\n")


@pytest.fixture
def docs(tmp_path) -> Path:
    root = tmp_path / "docs"
    _capture(root, "codex", CODEX_OLD, ["--model", "--sandbox"])
    _capture(root, "claude", "2.1.325", ["--print"])
    _capture(root, "claude", CLAUDE_OLD, ["--print", "--effort"])
    _capture(root, "claude", CLAUDE_NEW, ["--print", "--effort", "--brief"], findings=True)
    _capture(root, "pi", PI, ["--no-session"], findings=True)
    return root


def _brief(docs: Path, git: FakeGit | None = None, **kwargs):
    return compat.release_brief(
        docs,
        git=git or _git(),
        latest=kwargs.pop("latest", LATEST.get),
        versions=kwargs.pop("versions", PUBLISHED.get),
        **kwargs,
    )


# --- positive control ------------------------------------------------------------------


def test_brief_reads_the_previous_tag_and_compares_every_backend(docs):
    brief = _brief(docs)
    assert brief.tag == TAG  # the newest X.Y.Z tag; the rc and the peeled line are skipped
    assert brief.recorded_at == "2026-11-22T15:29:44+00:00"
    codex, claude, pi = brief.rows
    assert (codex.previous, codex.latest) == (CODEX_OLD, CODEX_NEW)
    # Stable releases after the previous one, up to latest: no prerelease, nothing past it.
    assert codex.published == [CODEX_NEW]
    assert claude.published == [CLAUDE_NEW]
    assert pi.published == []
    assert codex.blocks and not codex.supported
    assert claude.supported and not claude.blocks
    assert pi.supported and not pi.blocks
    # Flags between the capture at the previous version and the capture of latest.
    assert claude.baseline == CLAUDE_OLD
    assert claude.capture == (docs / "claude-help" / CLAUDE_NEW).as_posix()
    assert (claude.flags_added, claude.flags_removed) == (["--brief"], [])
    assert codex.capture is None
    # Findings committed after the previous version only.
    assert claude.findings == [(docs / "claude-help" / CLAUDE_NEW / "FINDINGS.md").as_posix()]
    assert pi.findings == []
    assert brief.problems == [
        f"codex: npm's latest {CODEX_NEW} is outside the shipped contract's supported "
        "versions, so preflight fails until support for it merges in its own PR, and so does "
        "the evidence run"
    ]


def test_the_markdown_draft_leaves_only_the_codex_verdict_to_a_reader(docs):
    text = "\n".join(compat.describe_brief(_brief(docs)))
    assert f"### Backend CLIs since {TAG}" in text
    assert "It installed and ran nothing." in text
    assert (
        f"| codex | {CODEX_OLD} | {CODEX_NEW} | {CODEX_NEW} | "
        "**not supported: blocks the evidence run** | none yet |"
    ) in text
    assert f"| pi | {PI} | {PI} | none | supported |" in text
    assert f"claude: from {CLAUDE_OLD} to {CLAUDE_NEW}, added `--brief`." in text
    assert f"pi: still {PI}, so nothing to compare." in text
    assert f"no capture of {CODEX_NEW} is committed yet" in text
    assert f"`{(docs / 'claude-help' / CLAUDE_NEW / 'FINDINGS.md').as_posix()}`" in text
    assert "### Rule-18 carrier re-check (draft)" in text
    assert f"recorded on codex {CODEX_NEW}, claude {CLAUDE_NEW} and pi {PI}" in text
    assert text.count(compat.TO_WRITE) == 1
    (codex_line,) = [line for line in text.splitlines() if line.startswith(f"- codex {CODEX_NEW}")]
    assert "`-c developer_instructions` on argv" in codex_line
    assert codex_line.endswith(f"Verdict: {compat.TO_WRITE}.")
    assert f"- pi {PI}: holds no carrier exemption" in text


def test_release_brief_main_prints_the_draft_and_fails_on_a_blocker(docs, monkeypatch, capsys):
    monkeypatch.setattr(compat, "run_git", _git())
    monkeypatch.setattr(compat, "latest_upstream", LATEST.get)
    monkeypatch.setattr(compat, "published_versions", PUBLISHED.get)
    assert compat.main(["release-brief", "--docs-root", str(docs)]) == 1
    out = capsys.readouterr()
    assert "### Rule-18 carrier re-check (draft)" in out.out
    assert f"FAIL codex: npm's latest {CODEX_NEW}" in out.err


def test_release_brief_json_carries_every_row_and_whether_it_blocks(docs, monkeypatch, capsys):
    monkeypatch.setattr(compat, "run_git", _git())
    monkeypatch.setattr(compat, "latest_upstream", {**LATEST, "codex": CODEX_OLD}.get)
    monkeypatch.setattr(compat, "published_versions", PUBLISHED.get)
    assert compat.main(["release-brief", "--docs-root", str(docs), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tag"] == TAG
    assert payload["problems"] == []
    assert [(b["backend"], b["blocks"]) for b in payload["backends"]] == [
        ("codex", False),
        ("claude", False),
        ("pi", False),
    ]


# --- reading the previous release ------------------------------------------------------


def test_a_tag_that_is_not_local_is_fetched_into_fetch_head_never_as_a_local_tag(docs):
    git = _git(
        extra={
            ("cat-file", "tag", f"refs/tags/{TAG}"): (128, ""),
            ("rev-parse", "--is-shallow-repository"): (0, "true\n"),
            ("fetch", "--quiet", "--no-tags", "--depth=1", "origin", f"refs/tags/{TAG}"): (0, ""),
            ("cat-file", "tag", TAG_SHA): (0, _cat_file(RECORD)),
        }
    )
    brief = _brief(docs, git)
    assert [row.previous for row in brief.rows] == [CODEX_OLD, CLAUDE_OLD, PI]
    (fetch,) = [call for call in git.calls if call[0] == "fetch"]
    assert not any(":" in part for part in fetch), "a refspec with a destination makes a tag"


def test_a_complete_clone_fetches_the_tag_without_making_itself_shallow(docs):
    git = _git(
        extra={
            ("cat-file", "tag", f"refs/tags/{TAG}"): (128, ""),
            ("rev-parse", "--is-shallow-repository"): (0, "false\n"),
            ("fetch", "--quiet", "--no-tags", "origin", f"refs/tags/{TAG}"): (0, ""),
            ("cat-file", "tag", TAG_SHA): (0, _cat_file(RECORD)),
        }
    )
    assert _brief(docs, git).rows[0].previous == CODEX_OLD


def test_since_names_the_tag_and_a_local_one_is_read_when_origin_cannot_be(docs):
    git = _git(extra={LS_REMOTE: (128, "")})
    brief = _brief(docs, git, since=TAG)
    assert brief.tag == TAG
    assert [row.previous for row in brief.rows] == [CODEX_OLD, CLAUDE_OLD, PI]
    assert brief.problems[0] == "could not list origin's tags (`git ls-remote --tags origin`)"


def test_a_tag_that_cannot_be_read_anywhere_is_a_problem_not_a_guess(docs):
    git = _git(
        extra={
            ("cat-file", "tag", f"refs/tags/{TAG}"): (128, ""),
            ("rev-parse", "--is-shallow-repository"): (0, "false\n"),
            ("fetch", "--quiet", "--no-tags", "origin", f"refs/tags/{TAG}"): (128, ""),
        }
    )
    brief = _brief(docs, git)
    assert f"could not read the annotated tag {TAG} locally or from origin" in brief.problems
    assert [row.previous for row in brief.rows] == [None, None, None]
    assert all(row.published is None for row in brief.rows)


def test_a_message_that_is_not_the_record_is_reported(docs):
    brief = _brief(docs, _git(message="release 1.2.2\n"))
    assert any(
        p.startswith(f"{TAG}: the tag message is not the JSON evidence record")
        for p in brief.problems
    )


def test_a_record_missing_a_backend_says_so(docs):
    message = _record(codex=f"codex-cli {CODEX_OLD}", pi=PI)
    brief = _brief(docs, _git(message=message))
    assert f"claude: {TAG}'s evidence record names no version for it" in brief.problems
    assert brief.rows[1].published is None


def test_origin_without_a_release_tag_has_nothing_to_compare(docs):
    brief = _brief(docs, FakeGit({LS_REMOTE: (0, "")}))
    assert brief.tag is None
    assert "origin has no vX.Y.Z tag, so there is no previous release to compare" in brief.problems


def test_since_must_be_a_release_tag(capsys):
    with pytest.raises(SystemExit) as raised:
        compat.main(["release-brief", "--since", "1.2.2"])
    assert raised.value.code == 2
    assert "not a release tag" in capsys.readouterr().err


# --- npm -----------------------------------------------------------------------------


def test_a_failed_npm_lookup_is_unknown_and_fails(docs):
    brief = _brief(docs, latest={"codex": CODEX_OLD, "claude": CLAUDE_NEW}.get)
    assert "pi: the latest release could not be read from npm" in brief.problems
    text = "\n".join(compat.describe_brief(brief))
    assert "| pi | " + PI + " | unknown | unknown | unknown | none yet |" in text
    assert "pi: npm's latest could not be read, so the version to check is unknown." in text


def test_an_unreadable_version_list_is_unknown_and_fails(docs):
    brief = _brief(docs, versions={"codex": [CODEX_NEW], "pi": [PI]}.get)
    assert "claude: npm's list of published versions could not be read" in brief.problems


def test_many_releases_are_summarised_by_their_ends(docs):
    many = [f"2.1.{n}" for n in range(331, 341)]
    brief = _brief(
        docs, latest={**LATEST, "claude": "2.1.340"}.get, versions={**PUBLISHED, "claude": many}.get
    )
    assert compat._published_cell(brief.rows[1].published) == "10 (2.1.331 to 2.1.340)"


def test_a_deprecated_backend_behind_latest_does_not_block(docs, monkeypatch):
    monkeypatch.setattr(
        compat.in_tree, "backend_deprecation", lambda b: object() if b == "codex" else None
    )
    codex = _brief(docs).rows[0]
    assert codex.deprecated and not codex.blocks
    assert compat._contract_cell(codex) == "deprecated, frozen at its supported set"


def test_published_versions_reads_npms_list(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return compat.subprocess.CompletedProcess(cmd, 0, stdout='"1.0.0"\n', stderr="")

    monkeypatch.setattr(compat.subprocess, "run", run)
    assert compat.published_versions("pi") == ["1.0.0"]
    assert seen == [["npm", "view", compat.NPM_PACKAGES["pi"], "versions", "--json"]]
    assert compat.published_versions("kimi") is None


@pytest.mark.parametrize(
    ("returncode", "stdout"), [(1, "[]"), (0, "not json"), (0, "{}"), (0, "[1, 2]")]
)
def test_published_versions_is_none_when_npm_does_not_answer_a_list(
    monkeypatch, returncode, stdout
):
    def run(cmd, **kwargs):
        return compat.subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(compat.subprocess, "run", run)
    assert compat.published_versions("pi") is None


# --- print-updates --json ---------------------------------------------------------------


def test_print_updates_json_gives_each_install_as_argv_and_its_env(capsys, monkeypatch):
    latest = {"codex": "0.171.0", "claude": "2.1.330", "pi": "1.6.0"}
    monkeypatch.setattr(compat, "latest_upstream", latest.get)
    assert compat.main(["print-updates", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == []
    assert payload["updates"] == [
        {
            "backend": "codex",
            "version": "0.171.0",
            "argv": ["npm", "install", "-g", "@openai/codex@0.171.0"],
            "env": {},
        },
        {
            "backend": "claude",
            "version": "2.1.330",
            "argv": ["claude", "install", "2.1.330"],
            "env": {"DISABLE_AUTOUPDATER": "1"},
        },
        {
            "backend": "pi",
            "version": "1.6.0",
            "argv": ["npm", "install", "-g", "@earendil-works/pi-coding-agent@1.6.0"],
            "env": {},
        },
    ]


def test_print_updates_json_still_fails_on_a_lookup_it_could_not_make(capsys, monkeypatch):
    monkeypatch.setattr(compat, "latest_upstream", {"codex": "0.171.0"}.get)
    assert compat.main(["print-updates", "--json"]) == 1
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert [u["backend"] for u in payload["updates"]] == ["codex"]
    assert payload["failed"] == [
        "claude: the latest release could not be read from npm",
        "pi: the latest release could not be read from npm",
    ]
    assert "FAIL pi:" in out.err
