"""`check_backend_compat.py watch` (#378), with `gh`, npm and PyPI all stubbed.

Nothing here reaches the network or a real `gh`: the lookups and the `gh` runner are
replaced on the module, and a stub that is not replaced fails the test rather than
falling through to the real one."""

from __future__ import annotations

import http.client
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from amicus.backends.kimi import contract as kimi_contract

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_backend_compat.py"
_spec = importlib.util.spec_from_file_location("check_backend_compat", _SCRIPT)
assert _spec is not None and _spec.loader is not None
compat = importlib.util.module_from_spec(_spec)
sys.modules["check_backend_compat"] = compat
_spec.loader.exec_module(compat)

_PYPROJECT = """\
[project]
name = "x"
dependencies = [
    "anyio>=4",
    "fastmcp>=4.0,<4.1",
    "mcp>=2.1,<2.3",
]

[dependency-groups]
dev = ["fastmcp[tasks]>=4.0,<9.9"]
"""
_NEWEST_KIMI = max(kimi_contract.SUPPORTED_VERSIONS)
_UNSUPPORTED_KIMI = f"{_NEWEST_KIMI[0]}.{_NEWEST_KIMI[1] + 1}.0"
_SUPPORTED_KIMI = f"{_NEWEST_KIMI[0]}.{_NEWEST_KIMI[1]}.9"

# Upstream as each test sees it unless it says otherwise: every stream has an update.
_NPM_AHEAD = {"kimi": _UNSUPPORTED_KIMI, "claude": "2.1.400"}
_PYPI_AHEAD = {"fastmcp": "4.1.4", "mcp": "2.3.0"}
_TITLES = [
    f"chore(backends): track kimi {_NEWEST_KIMI[0]}.{_NEWEST_KIMI[1] + 1}",
    "chore(backends): track claude 2.1.400",
    "chore(deps): track fastmcp 4.1 past the cap",
    "chore(deps): track mcp 2.3 past the cap",
]


class FakeGh:
    """A repository's issues, newest first, behind the subset of `gh issue` the watch uses.
    It honours `--state` and `--limit` (gh's default limit is 30). `indexed` False models
    GitHub's search index lagging a just-created issue."""

    def __init__(self, issues: list[dict] | None = None, *, indexed: bool = True) -> None:
        self.issues = list(issues or [])
        self.indexed = indexed
        self.created: list[list[str]] = []
        self.edited: list[list[str]] = []
        self.comments: list[list[str]] = []
        self.fail: str | None = None  # "list", "create", "edit" or "comment" exits 1

    def __call__(self, args: list[str]) -> tuple[int, str]:
        assert args[0] == "issue", args
        if self.fail == args[1]:
            return 1, ""
        if args[1] == "list":
            state = args[args.index("--state") + 1] if "--state" in args else "open"
            limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 30
            rows = [i for i in self.issues if state == "all" or i["state"] == state.upper()]
            if "--search" in args:
                rows = rows if self.indexed else []
                phrase = args[args.index("--search") + 1]
                assert phrase.startswith('in:title "') and phrase.endswith('"'), phrase
                words = phrase[len('in:title "') : -1].lower().split()
                # GitHub matches words, not the exact string: a near title comes back too.
                rows = [i for i in rows if all(w in i["title"].lower() for w in words)]
            return 0, json.dumps(rows[:limit])
        if args[1] == "create":
            self.created.append(args)
            number = 1000 + len(self.issues)
            title = args[args.index("--title") + 1]
            body = args[args.index("--body") + 1]
            self.issues.insert(0, {"title": title, "number": number, "state": "OPEN", "body": body})
            return 0, f"https://github.com/o/r/issues/{number}\n"
        if args[1] == "edit":
            self.edited.append(args)
            (issue,) = [i for i in self.issues if i["number"] == int(args[2])]
            issue["title"] = args[args.index("--title") + 1]
            issue["body"] = args[args.index("--body") + 1]
            return 0, ""
        if args[1] == "comment":
            self.comments.append(args)
            return 0, ""
        raise AssertionError(args)


def _no_real_lookups(monkeypatch, npm: dict, pypi: dict, gh: FakeGh) -> None:
    monkeypatch.setattr(compat, "latest_upstream", npm.get)
    monkeypatch.setattr(compat, "latest_pypi", pypi.get)
    monkeypatch.setattr(compat, "run_gh", gh)


@pytest.fixture
def roots(tmp_path):
    docs = tmp_path / "docs"
    folder = docs / "claude-help" / "2.1.308"
    folder.mkdir(parents=True)
    (folder / "claude-help.txt").write_text("help\n")
    # A higher name that is not a capture (no help file) is not the baseline.
    (docs / "claude-help" / "2.1.999").mkdir()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_PYPROJECT)
    return ["--docs-root", str(docs), "--pyproject", str(pyproject)]


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    code = compat.main(["watch", *argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_watch_is_a_subcommand():
    assert compat.SUBCOMMANDS["watch"] is compat.watch_main


def test_first_run_files_one_issue_per_stream_and_a_rerun_files_none(monkeypatch, roots, capsys):
    gh = FakeGh()
    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 0, out
    assert [f["stream"] for f in out["findings"]] == ["kimi", "claude", "fastmcp", "mcp"]
    assert [f["status"] for f in out["findings"]] == ["update"] * 4
    assert [f["action"] for f in out["filings"]] == ["filed"] * 4
    assert [a[a.index("--title") + 1] for a in gh.created] == _TITLES
    for args in gh.created:
        body = args[args.index("--body") + 1]
        assert "available upstream" in body and "is not supported" in body, body
        labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
        assert labels == ["dependencies", "chore"], labels

    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 0, out
    assert len(gh.created) == 4, "a re-run must file nothing"
    assert [f["action"] for f in out["filings"]] == ["exists"] * 4
    assert [f["number"] for f in out["filings"]] == [1000, 1001, 1002, 1003]


def test_a_rerun_files_none_even_before_search_indexes_the_first_run(monkeypatch, roots, capsys):
    gh = FakeGh(indexed=False)
    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
    _run([*roots, "--file-issues"], capsys)
    assert len(gh.created) == 4
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 0 and len(gh.created) == 4, out


def test_a_closed_issue_with_the_exact_title_suppresses_filing(monkeypatch, roots, capsys):
    closed = {"title": _TITLES[2], "number": 7, "state": "CLOSED"}
    # A title that only CONTAINS the words is not a match: search returns it, the compare drops it.
    near = {"title": _TITLES[3] + " (superseded)", "number": 8, "state": "CLOSED"}
    gh = FakeGh([closed, near])
    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 0, out
    actions = {f["stream"]: (f["action"], f["number"]) for f in out["filings"]}
    assert actions["fastmcp"] == ("exists", 7)
    assert actions["mcp"][0] == "filed", "a near title must not suppress filing"
    assert len(gh.created) == 3


def test_a_lookup_failure_is_unknown_files_nothing_and_fails(monkeypatch, roots, capsys):
    gh = FakeGh()
    _no_real_lookups(monkeypatch, {}, {}, gh)
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 1, out
    assert [f["status"] for f in out["findings"]] == ["unknown"] * 4
    assert out["filings"] == [] and gh.created == []

    # One stream unknown: it files nothing and fails the run; the others still file.
    gh = FakeGh()
    _no_real_lookups(monkeypatch, {"claude": "2.1.400"}, _PYPI_AHEAD, gh)
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 1, out
    assert out["findings"][0]["status"] == "unknown"
    assert [a[a.index("--title") + 1] for a in gh.created] == _TITLES[1:]


def test_nothing_past_the_baselines_files_nothing(monkeypatch, roots, capsys):
    gh = FakeGh()
    npm = {"kimi": _SUPPORTED_KIMI, "claude": "2.1.308"}
    _no_real_lookups(monkeypatch, npm, {"fastmcp": "4.0.9", "mcp": "2.2.1"}, gh)
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 0, out
    assert [f["status"] for f in out["findings"]] == ["current"] * 4
    assert out["filings"] == [] and gh.created == []


def test_claude_compares_versions_as_numbers_against_the_newest_capture(roots):
    docs = Path(roots[1])
    for latest, status in [("2.1.308", "current"), ("2.1.99", "current"), ("2.1.309", "update")]:
        finding = compat.watch_claude({"claude": latest}.get, docs)
        assert finding.status == status, (latest, finding)
    assert compat.watch_claude({"claude": "2.1.309"}.get, docs).key == "2.1.309"
    missing = compat.watch_claude({"claude": "2.1.309"}.get, docs / "nowhere")
    assert missing.status == "unknown", "no capture is unknown, never current"
    major = compat.watch_claude({"claude": "3.0.0"}.get, docs)
    assert major.status == "update" and "outside the shipped set" in major.baseline


def test_a_gh_failure_files_nothing_and_fails(monkeypatch, roots, capsys):
    for failing in ("list", "create"):
        gh = FakeGh()
        gh.fail = failing
        _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
        code, out = _run([*roots, "--file-issues"], capsys)
        assert code == 1, (failing, out)
        assert [f["action"] for f in out["filings"]] == ["failed"] * 4
        assert gh.created == []


def test_dry_run_reads_but_never_creates(monkeypatch, roots, capsys):
    gh = FakeGh([{"title": _TITLES[0], "number": 5, "state": "OPEN"}])
    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
    code, out = _run([*roots, "--file-issues", "--dry-run"], capsys)
    assert code == 0, out
    assert [f["action"] for f in out["filings"]] == ["exists", *["would_file"] * 3]
    assert gh.created == []
    with pytest.raises(SystemExit):
        compat.main(["watch", *roots, "--dry-run"])


def test_without_file_issues_gh_is_never_called(monkeypatch, roots, capsys):
    def gh(_args):
        raise AssertionError("gh must not run without --file-issues")

    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, FakeGh())
    monkeypatch.setattr(compat, "run_gh", gh)
    assert compat.main(["watch", *roots]) == 0
    text = capsys.readouterr().out
    assert "available upstream" in text and "supported;" not in text
    assert "title: chore(deps): track mcp 2.3 past the cap" in text


def test_the_cap_is_read_from_runtime_dependencies_only(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_PYPROJECT)
    assert compat.pyproject_cap(pyproject, "fastmcp") == (4, 1)
    assert compat.pyproject_cap(pyproject, "mcp") == (2, 3)
    assert compat.pyproject_cap(pyproject, "anyio") is None
    assert compat.pyproject_cap(tmp_path / "missing.toml", "mcp") is None
    uncapped = compat.watch_pypi("anyio", {"anyio": "9.0.0"}.get, pyproject)
    assert uncapped.status == "unknown", "a missing cap is unknown, never current"
    real = Path(__file__).parent.parent / "pyproject.toml"
    assert compat.pyproject_cap(real, "fastmcp") and compat.pyproject_cap(real, "mcp"), (
        "the watch reads these caps; keep them as `<X.Y` in [project].dependencies"
    )


def test_the_pypi_lookup_reads_the_final_release_or_says_unknown(monkeypatch):
    seen: list[str] = []

    def answer(payload: object):
        def urlopen(url, timeout):
            seen.append(url)
            if isinstance(payload, Exception):
                raise payload
            return io.BytesIO(json.dumps(payload).encode())

        monkeypatch.setattr(compat.urllib.request, "urlopen", urlopen)
        return compat.latest_pypi("fastmcp")

    assert answer({"info": {"version": "4.1.4"}}) == "4.1.4", "control"
    assert seen == ["https://pypi.org/pypi/fastmcp/json"]
    assert answer({"info": {"version": "4.2.0rc1"}}) is None
    assert answer({"info": {}}) is None
    assert answer([]) is None
    assert answer(OSError("offline")) is None


def test_an_exact_title_past_gh_default_page_is_still_found(monkeypatch, roots, capsys):
    """Codex on #387: `--search` without `--limit` returns 30 rows, so an old exact-title
    issue behind 30 newer near titles, and outside the newest 100, was missed."""
    old = {"title": _TITLES[2], "number": 1, "state": "CLOSED"}
    near = [
        {"title": f"{_TITLES[2]} follow-up {n}", "number": 2 + n, "state": "CLOSED"}
        for n in range(40)
    ]
    filler = [{"title": f"unrelated {n}", "number": 100 + n, "state": "OPEN"} for n in range(120)]
    gh = FakeGh([*filler, *reversed(near), old])
    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
    _code, out = _run([*roots, "--file-issues"], capsys)
    actions = {f["stream"]: (f["action"], f["number"]) for f in out["filings"]}
    assert actions["fastmcp"] == ("exists", 1), actions


def test_a_search_that_may_be_truncated_fails_closed(monkeypatch, roots, capsys):
    near = [
        {"title": f"{_TITLES[2]} follow-up {n}", "number": 2 + n, "state": "CLOSED"}
        for n in range(5)
    ]
    gh = FakeGh(near)
    _no_real_lookups(monkeypatch, _NPM_AHEAD, _PYPI_AHEAD, gh)
    monkeypatch.setattr(compat, "SEARCH_LIMIT", 5)
    code, out = _run([*roots, "--file-issues"], capsys)
    assert code == 1, out
    actions = {f["stream"]: f["action"] for f in out["filings"]}
    assert actions["fastmcp"] == "failed", actions
    assert all(a[a.index("--title") + 1] != _TITLES[2] for a in gh.created)


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"{"),
        http.client.RemoteDisconnected("gone"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
    ],
)
def test_a_pypi_read_error_is_unknown_and_the_other_streams_still_run(
    monkeypatch, roots, capsys, error
):
    """Codex on #387: `IncompleteRead` is an `HTTPException`, not an `OSError`, and escaped."""

    class Response(io.BytesIO):
        def read(self, *_a):
            raise error

    monkeypatch.setattr(compat.urllib.request, "urlopen", lambda url, timeout: Response())
    monkeypatch.setattr(compat, "latest_upstream", _NPM_AHEAD.get)
    monkeypatch.setattr(compat, "run_gh", FakeGh())
    code, out = _run(roots, capsys)
    assert code == 1, out
    assert [f["status"] for f in out["findings"]] == ["update", "update", "unknown", "unknown"]


def test_an_npm_output_that_cannot_be_decoded_is_unknown(monkeypatch):
    def run(*_a, **_k):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    monkeypatch.setattr(compat.subprocess, "run", run)
    assert compat.latest_upstream("kimi") is None
    assert compat.run_gh(["issue", "list"])[0] != 0
