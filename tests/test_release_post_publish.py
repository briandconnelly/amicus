"""`scripts/release.py post-publish` and `pointer`: the post-tag checks and the pointer edit (#375).

The fixture is real git: a bare `origin` holding a published `NEXT`, tagged and annotated, and
a checkout on a fresh branch off `main` that has not fetched that tag yet, the way the pointer
PR starts. `git ls-remote`, the tag fetch and the release-state check all run for real against
it. Only the network is stubbed: PyPI's JSON (`Context.http_get`) and `uvx` (`Context.run`).

The positive controls run first, so a broken fixture cannot make a refusal pass vacuously. The
`network` tests at the bottom run the real thing against PyPI and GitHub and are excluded from
the gate (`addopts`); run them with `uv run pytest -m network --no-cov`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.support.releasefixture import (
    MARKETPLACE,
    NEXT,
    PREVIOUS,
    TODAY,
    build_released_repo,
)
from tests.support.releasefixture import git as _git
from tests.support.releasefixture import write as _write

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")

TAG = f"v{NEXT}"
NEGATIVE = release.NEGATIVE_CONTROL_REF


@dataclass
class Published:
    repo: Path
    origin: Path
    sha: str  # the release commit TAG peels to
    tag_object: str

    @property
    def marketplace(self) -> Path:
        return self.repo / release.MARKETPLACE_PATH


@pytest.fixture
def pub(tmp_path) -> Published:
    repo, origin = tmp_path / "amicus", tmp_path / "origin.git"
    build_released_repo(repo, release)
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))

    _git(repo, "switch", "-q", "-c", f"chore/release-{NEXT}")
    ctx = release.Context(repo_root=repo, today=lambda: TODAY)
    for edit in release.plan_prepare(ctx, NEXT):
        _write(repo, edit.path, edit.after)
    _git(repo, "commit", "-q", "-am", f"chore(release): {NEXT}")
    _git(repo, "tag", "-a", TAG, "--cleanup=verbatim", "-m", '{"commit": "evidence"}\n')
    sha = _git(repo, "rev-parse", "HEAD")
    tag_object = _git(repo, "rev-parse", f"refs/tags/{TAG}")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", f"chore/release-{NEXT}")
    _git(repo, "push", "-q", "origin", "main", f"refs/tags/v{PREVIOUS}", f"refs/tags/{TAG}")

    # The pointer PR's checkout: a fresh branch off main that has not fetched the new tag.
    _git(repo, "tag", "-d", TAG)
    _git(repo, "switch", "-q", "-c", "chore/pointer")
    return Published(repo, origin, sha, tag_object)


def _pypi(releases: dict) -> bytes:
    return json.dumps({"info": {"name": "amicus", "version": NEXT}, "releases": releases}).encode()


class FakePyPI:
    def __init__(self, releases: dict | None = None, error: Exception | None = None):
        self.releases = (
            {NEXT: [{"filename": f"amicus-{NEXT}.tar.gz"}]} if releases is None else releases
        )
        self.error = error
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return _pypi(self.releases)


def _reply(name: str = "amicus", version: str = NEXT) -> str:
    result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": name, "version": version}}
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) + "\n"


RESOLUTION_ERROR = (
    "error: Failed to resolve `--with` requirement\n"
    "  cause: Git operation failed\n"
    f"  cause: failed to fetch branch or tag `{NEGATIVE}`\n"
    f"         fatal: couldn't find remote ref refs/tags/{NEGATIVE}\n"
)


class FakeUvx:
    """`uvx --from git+...@REF amicus-mcp`, answered per ref; anything else fails loudly.

    `answers` maps a ref to a CompletedProcess's (returncode, stdout, stderr), or to an
    exception to raise. Every call's environment is checked for empty, distinct uv caches.
    """

    def __init__(self, answers: dict | None = None):
        self.answers = {TAG: (0, _reply(), "banner\n"), NEGATIVE: (1, "", RESOLUTION_ERROR)}
        self.answers.update(answers or {})
        self.calls: list[dict] = []

    def __call__(self, cmd, *args, **kwargs):
        assert Path(cmd[0]).name == "uvx", f"unexpected command {cmd!r}"
        assert cmd[1] == "--from" and cmd[3] == "amicus-mcp", cmd
        source = cmd[2]
        assert source.startswith("git+"), source
        ref = source.rsplit("@", 1)[1]
        env, cwd = kwargs["env"], Path(kwargs["cwd"])
        for key in ("UV_CACHE_DIR", "UV_TOOL_DIR", "TMPDIR"):
            assert list(Path(env[key]).iterdir()) == [], f"{key} is not empty"
        assert list(cwd.iterdir()) == []
        self.calls.append(
            {
                "ref": ref,
                "program": cmd[0],
                "source": source,
                "env": dict(env),
                "path": env["PATH"],
                "cache": env["UV_CACHE_DIR"],
                "tools": env["UV_TOOL_DIR"],
                "input": kwargs["input"],
                "timeout": kwargs["timeout"],
            }
        )
        answer = self.answers[ref]
        if isinstance(answer, Exception):
            raise answer
        returncode, stdout, stderr = answer
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def _context(pub: Published, *, pypi: FakePyPI | None = None, uvx: FakeUvx | None = None):
    return release.Context(
        repo_root=pub.repo,
        run=uvx or FakeUvx(),
        http_get=pypi or FakePyPI(),
        canonical_url=str(pub.origin),
    )


def _run(pub: Published, command: str, *, version: str = NEXT, **fakes) -> int:
    return release.main([command, "--version", version], context=_context(pub, **fakes))


def _post_publish_refused(pub: Published, capsys, *reasons: str, **fakes) -> str:
    assert _run(pub, "post-publish", **fakes) == 1
    err = capsys.readouterr().err
    assert f"post-publish checks for {NEXT} do NOT hold" in err
    for reason in reasons:
        assert reason in err
    return err


def _local_tag(pub: Published) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{TAG}"],
        cwd=pub.repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() or None


# --- post-publish: positive control -------------------------------------------------------


def test_post_publish_holds_for_a_published_release(pub, capsys):
    pypi, uvx = FakePyPI(), FakeUvx()
    assert _run(pub, "post-publish", pypi=pypi, uvx=uvx) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert f"post-publish checks hold for {NEXT}" in out.out
    assert pub.sha in out.out
    assert pypi.urls == [release.PYPI_JSON_URL]
    assert [call["ref"] for call in uvx.calls] == [TAG, NEGATIVE]
    # Each install gets its own empty caches: a shared one would let the control reuse a build.
    assert len({call["cache"] for call in uvx.calls}) == 2
    assert len({call["tools"] for call in uvx.calls}) == 2
    message = json.loads(uvx.calls[0]["input"])
    assert message["method"] == "initialize"
    assert message["id"] == 1
    assert _local_tag(pub) is None  # post-publish changes nothing in the checkout


def test_post_publish_finds_the_reply_among_other_output(pub, capsys):
    noisy = "not json\n" + json.dumps({"jsonrpc": "2.0", "method": "log"}) + "\n" + _reply()
    assert _run(pub, "post-publish", uvx=FakeUvx({TAG: (0, noisy, "")})) == 0


def test_the_timeout_reaches_both_installs(pub, capsys):
    uvx = FakeUvx()
    argv = ["post-publish", "--version", NEXT, "--timeout", "7"]
    assert release.main(argv, context=_context(pub, uvx=uvx)) == 0
    assert [call["timeout"] for call in uvx.calls] == [7.0, 7.0]


# --- post-publish: PyPI ------------------------------------------------------------------


def test_a_version_missing_from_pypi_fails(pub, capsys):
    pypi = FakePyPI({PREVIOUS: [{"filename": "x"}]})
    _post_publish_refused(pub, capsys, f"PyPI has no release {NEXT}", pypi=pypi)


def test_a_release_with_no_files_fails(pub, capsys):
    _post_publish_refused(pub, capsys, "with no files", pypi=FakePyPI({NEXT: []}))


def test_an_unreachable_pypi_fails(pub, capsys):
    error = urllib.error.HTTPError(release.PYPI_JSON_URL, 503, "unavailable", {}, None)  # type: ignore[arg-type]
    _post_publish_refused(pub, capsys, "could not read", pypi=FakePyPI(error=error))


def test_pypi_answering_without_a_releases_table_fails(pub, capsys):
    class NoReleases(FakePyPI):
        def __call__(self, url):
            return b'{"info": {}}'

    _post_publish_refused(pub, capsys, "no `releases` table", pypi=NoReleases())


# --- post-publish: the remote tag ---------------------------------------------------------


def test_a_tag_missing_from_origin_fails(pub, capsys):
    _git(pub.origin, "tag", "-d", TAG)
    _post_publish_refused(pub, capsys, f"origin has no tag {TAG}")


def test_a_failed_ls_remote_fails(pub, capsys):
    _git(pub.repo, "remote", "set-url", "origin", str(pub.origin.parent / "gone.git"))
    _post_publish_refused(pub, capsys, f"could not ask origin for {TAG}")


def test_a_lightweight_tag_on_origin_fails(pub, capsys):
    _git(pub.origin, "tag", "-d", TAG)
    _git(pub.origin, "tag", TAG, pub.sha)
    _post_publish_refused(pub, capsys, "lightweight tag")


# --- post-publish: the install ------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (_reply(name="someone-else"), "calls itself 'someone-else'"),
        (_reply(version=PREVIOUS), f"reports version '{PREVIOUS}', not '{NEXT}'"),
    ],
)
def test_an_initialize_reply_that_is_not_this_release_fails(pub, capsys, reply, reason):
    _post_publish_refused(pub, capsys, reason, uvx=FakeUvx({TAG: (0, reply, "")}))


def test_an_install_with_no_reply_fails(pub, capsys):
    uvx = FakeUvx({TAG: (1, "", "error: build failed\n")})
    _post_publish_refused(pub, capsys, "gave no `initialize` reply", "build failed", uvx=uvx)


def test_an_install_that_times_out_fails(pub, capsys):
    uvx = FakeUvx({TAG: subprocess.TimeoutExpired(["uvx"], 300)})
    _post_publish_refused(pub, capsys, "did not finish within", uvx=uvx)


def test_a_missing_uvx_fails(pub, capsys):
    uvx = FakeUvx({TAG: FileNotFoundError("uvx"), NEGATIVE: FileNotFoundError("uvx")})
    _post_publish_refused(pub, capsys, "could not run `uvx`", uvx=uvx)


# --- post-publish: the negative control ---------------------------------------------------


def test_a_negative_control_that_succeeds_fails(pub, capsys):
    uvx = FakeUvx({NEGATIVE: (0, _reply(), "")})
    _post_publish_refused(pub, capsys, "which cannot exist, succeeded", uvx=uvx)


def test_a_negative_control_that_times_out_fails(pub, capsys):
    uvx = FakeUvx({NEGATIVE: subprocess.TimeoutExpired(["uvx"], 300)})
    _post_publish_refused(pub, capsys, "timed out", "controls nothing", uvx=uvx)


@pytest.mark.parametrize(
    "stderr",
    [
        "error: No space left on device\n",
        # A resolution error, but for some other ref: not the control this run asked for.
        "  cause: failed to fetch branch or tag `v9.9.9`\n",
    ],
)
def test_a_negative_control_failing_for_another_reason_fails(pub, capsys, stderr):
    uvx = FakeUvx({NEGATIVE: (1, "", stderr)})
    _post_publish_refused(pub, capsys, "not with uv's resolution error", uvx=uvx)


def test_gits_missing_ref_diagnostic_alone_is_accepted(pub, capsys):
    only_git = f"fatal: couldn't find remote ref refs/tags/{NEGATIVE}\n"
    assert _run(pub, "post-publish", uvx=FakeUvx({NEGATIVE: (1, "", only_git)})) == 0


_UV_WRAPPER = (
    "error: Failed to resolve `--with` requirement\n"
    "  cause: Git operation failed\n"
    f"  cause: failed to fetch branch or tag `{NEGATIVE}`\n"
    "  cause: process didn't exit successfully: `git fetch ...` (exit status: 128)\n"
    "         --- stderr\n"
)


@pytest.mark.parametrize(
    "cause",
    [
        # Observed on uv 0.13.6 with an unresolvable host: the same wrapper as a missing ref.
        "fatal: unable to access 'https://github.com/briandconnelly/amicus.git/': "
        "Could not resolve host: github.com",
        "fatal: Authentication failed for 'https://github.com/briandconnelly/amicus.git/'",
        "fatal: unable to access 'https://github.com/briandconnelly/amicus.git/': "
        "SSL certificate problem: unable to get local issuer certificate",
    ],
    ids=["dns", "auth", "tls"],
)
def test_a_transport_failure_under_uvs_wrapper_is_no_control(pub, capsys, cause):
    """uv's `failed to fetch branch or tag` wraps every fetch failure, so it alone says
    nothing about whether the ref exists; only git's missing-ref diagnostic does."""
    uvx = FakeUvx({NEGATIVE: (1, "", _UV_WRAPPER + f"         {cause}\n")})
    _post_publish_refused(pub, capsys, "not with uv's resolution error", uvx=uvx)


class FallbackUvx(FakeUvx):
    """uv 0.13.6's behaviour when the package lacks the console script: it runs whatever
    `amicus-mcp` the PATH it was given finds (probed with a script-less package and an
    ambient `amicus-mcp` that answered instead)."""

    def __call__(self, cmd, *args, **kwargs):
        ref = cmd[2].rsplit("@", 1)[1]
        if ref == NEGATIVE:
            return super().__call__(cmd, *args, **kwargs)
        for entry in kwargs["env"]["PATH"].split(os.pathsep):
            if (Path(entry) / "amicus-mcp").exists():
                return subprocess.CompletedProcess(cmd, 0, stdout=_reply(), stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="An executable named `amicus-mcp` is not provided\n"
        )


def test_an_ambient_amicus_mcp_cannot_answer_for_the_tag(pub, capsys, tmp_path, monkeypatch):
    """A tag whose package lacks `amicus-mcp` must fail, even with an ambient one on PATH
    that reports the right version (`uv run` puts the checkout's `.venv/bin` there)."""
    ambient = tmp_path / "ambient-bin"
    ambient.mkdir()
    script = ambient / "amicus-mcp"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{ambient}{os.pathsep}{os.environ['PATH']}")
    _post_publish_refused(pub, capsys, "gave no `initialize` reply", uvx=FallbackUvx())


def test_the_install_path_holds_uv_and_git_and_no_amicus_mcp(pub, capsys):
    uvx = FakeUvx()
    assert _run(pub, "post-publish", uvx=uvx) == 0
    for call in uvx.calls:
        entries = call["path"].split(os.pathsep)
        assert all(not (Path(e) / "amicus-mcp").exists() for e in entries), entries
        assert Path(call["program"]).name == "uvx"


def test_a_malformed_version_is_refused_before_anything_runs(pub, capsys):
    pypi, uvx = FakePyPI(), FakeUvx()
    assert _run(pub, "post-publish", version="1.3", pypi=pypi, uvx=uvx) == 1
    assert "is not X.Y.Z" in capsys.readouterr().err
    assert pypi.urls == []
    assert uvx.calls == []


# --- pointer: positive control ------------------------------------------------------------


def test_pointer_writes_ref_and_peeled_sha_and_nothing_else(pub, capsys):
    before = pub.marketplace.read_text(encoding="utf-8")
    assert _run(pub, "pointer") == 0
    out = capsys.readouterr()
    assert "marketplace pointer check holds" in out.out
    assert f"chore(release): point the marketplace at {TAG}" in out.out
    after = pub.marketplace.read_text(encoding="utf-8")
    # The fixture's odd formatting survives: only the two values moved.
    assert before == MARKETPLACE % (
        PREVIOUS,
        _git(pub.repo, "rev-parse", f"v{PREVIOUS}^{{commit}}"),
    )
    assert after == MARKETPLACE % (NEXT, pub.sha)
    changed = _git(pub.repo, "status", "--porcelain", "--untracked-files=all")
    assert changed.splitlines() == [f"M {release.MARKETPLACE_PATH}"]  # `_git` strips
    # The tag was fetched exactly: annotated, origin's object, peeling to the sha written.
    assert _local_tag(pub) == pub.tag_object
    assert _git(pub.repo, "cat-file", "-t", TAG) == "tag"


def test_pointer_refreshes_origin_main_before_checking(pub, capsys):
    # The transition check compares with origin/main, so a stale one is fetched first.
    _git(pub.repo, "update-ref", "refs/remotes/origin/main", f"v{PREVIOUS}^{{commit}}")
    assert _run(pub, "pointer") == 0
    assert _git(pub.repo, "rev-parse", "refs/remotes/origin/main") == _git(
        pub.origin, "rev-parse", "main"
    )


def test_pointer_is_idempotent(pub, capsys):
    assert _run(pub, "pointer") == 0
    _git(pub.repo, "commit", "-q", "-am", "pointer")
    capsys.readouterr()
    assert _run(pub, "pointer") == 0
    assert "already points at" in capsys.readouterr().out


# --- pointer: refusals --------------------------------------------------------------------


def _pointer_refused(pub: Published, capsys, *reasons: str, **fakes) -> str:
    before = pub.marketplace.read_bytes()
    assert _run(pub, "pointer", **fakes) == 1
    err = capsys.readouterr().err
    assert f"pointer for {NEXT} refused" in err
    for reason in reasons:
        assert reason in err
    assert pub.marketplace.read_bytes() == before
    return err


def test_pointer_refuses_when_post_publish_fails(pub, capsys):
    pypi = FakePyPI({PREVIOUS: [{"filename": "x"}]})
    _pointer_refused(pub, capsys, "post-publish checks failed", "PyPI has no release", pypi=pypi)
    assert _local_tag(pub) is None  # refused before fetching anything


def test_pointer_refuses_when_the_negative_control_fails(pub, capsys):
    uvx = FakeUvx({NEGATIVE: (0, _reply(), "")})
    _pointer_refused(pub, capsys, "post-publish checks failed", uvx=uvx)


def test_pointer_fetches_a_missing_local_tag(pub, capsys):
    assert _local_tag(pub) is None
    assert _run(pub, "pointer") == 0
    assert _local_tag(pub) == pub.tag_object


def test_pointer_accepts_a_local_tag_identical_to_origins(pub, capsys):
    _git(pub.repo, "fetch", "-q", "origin", f"refs/tags/{TAG}:refs/tags/{TAG}")
    assert _run(pub, "pointer") == 0


def test_pointer_refuses_a_conflicting_local_tag(pub, capsys):
    _git(pub.repo, "tag", "-a", TAG, "-m", "another", f"v{PREVIOUS}^{{commit}}")
    local = _local_tag(pub)
    _pointer_refused(pub, capsys, f"could not fetch {TAG} from origin")
    assert _local_tag(pub) == local  # never overwritten


def test_pointer_refuses_a_local_tag_on_the_same_commit_with_another_message(pub, capsys):
    _git(pub.repo, "tag", "-a", TAG, "-m", "a different record", pub.sha)
    _pointer_refused(pub, capsys, f"could not fetch {TAG} from origin")


def test_pointer_refuses_a_local_lightweight_tag(pub, capsys):
    _git(pub.repo, "tag", TAG, pub.sha)
    _pointer_refused(pub, capsys, f"could not fetch {TAG} from origin")


def test_a_fetched_tag_must_be_what_origin_reported(pub):
    """Belt and braces after the fetch: annotated, origin's object, origin's peeled commit."""
    remote = release.RemoteTag(TAG, pub.tag_object, pub.sha)
    ctx = _context(pub)
    assert release._fetched_tag_problems(ctx, remote) == []
    moved = release.RemoteTag(TAG, "f" * 40, "e" * 40)
    problems = release._fetched_tag_problems(ctx, moved)
    assert any("tag object" in p for p in problems)
    assert any("peels to" in p for p in problems)


def test_a_fetched_lightweight_tag_is_refused(pub):
    _git(pub.origin, "tag", "-d", TAG)
    _git(pub.origin, "tag", TAG, pub.sha)
    remote = release.RemoteTag(TAG, pub.sha, pub.sha)
    problems = release._fetched_tag_problems(_context(pub), remote)
    assert problems and "not an annotated tag" in problems[0]


def test_pointer_puts_the_file_back_when_the_pull_request_check_fails(pub, capsys):
    # A tree declaring PREVIOUS cannot point at NEXT (rule 24: never newer than declared).
    pyproject = pub.repo / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace(NEXT, PREVIOUS), encoding="utf-8")
    _git(pub.repo, "commit", "-q", "-am", "declare the older version")
    err = _pointer_refused(pub, capsys, f"ahead of the declared {PREVIOUS}")
    assert "put back as it was" in err


def test_pointer_refuses_main(pub, capsys):
    _git(pub.repo, "switch", "-q", "main")
    uvx = FakeUvx()
    _pointer_refused(pub, capsys, "on branch main", uvx=uvx)
    assert uvx.calls == []


def test_pointer_refuses_a_dirty_tree(pub, capsys):
    (pub.repo / "stray.txt").write_text("x", encoding="utf-8")
    _pointer_refused(pub, capsys, "not clean")


def test_pointer_refuses_a_failed_main_refresh(pub, capsys):
    class FailingFetch:
        def __call__(self, cmd, *args, **kwargs):
            if cmd[:2] == ["git", "fetch"] and "+refs/heads/main:refs/remotes/origin/main" in cmd:
                return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: nope\n")
            kwargs.pop("check", None)
            return subprocess.run(cmd, *args, check=False, **kwargs)

    ctx = release.Context(
        repo_root=pub.repo,
        git=FailingFetch(),
        run=FakeUvx(),
        http_get=FakePyPI(),
        canonical_url=str(pub.origin),
    )
    assert release.main(["pointer", "--version", NEXT], context=ctx) == 1
    assert "origin/main may be stale" in capsys.readouterr().err


# --- pointer_text: the edit itself --------------------------------------------------------


def test_pointer_text_keeps_every_other_byte():
    text = MARKETPLACE % ("0.0.1", "0" * 40)
    edited = release.pointer_text(text, TAG, "a" * 40)
    assert edited == MARKETPLACE % (NEXT, "a" * 40)


def test_pointer_text_refuses_an_ambiguous_file():
    text = MARKETPLACE % ("0.0.1", "0" * 40)
    doubled = text.replace('"ref": "v0.0.1"', '"ref": "v0.0.1", "x": {"ref": "v0.0.2"}')
    with pytest.raises(release.Refusal, match='2 "ref" fields'):
        release.pointer_text(doubled, TAG, "a" * 40)


def test_pointer_text_refuses_the_pre_activation_source():
    text = '{"name": "amicus", "plugins": [{"source": "./", "ref": "v1.0.0", "sha": "x"}]}'
    with pytest.raises(release.Refusal, match="did not take"):
        release.pointer_text(text, TAG, "a" * 40)


# --- network: the real thing, outside the gate --------------------------------------------


def _published_version() -> str:
    """The release the committed pointer names: published, by rule 24."""
    text = (release.REPO_ROOT / release.MARKETPLACE_PATH).read_text(encoding="utf-8")
    return json.loads(text)["plugins"][0]["source"]["ref"].removeprefix("v")


@pytest.mark.network
def test_network_post_publish_holds_for_the_pointed_release(capsys):
    version = _published_version()
    assert release.main(["post-publish", "--version", version]) == 0, capsys.readouterr().err


@pytest.mark.network
def test_network_post_publish_fails_for_an_unpublished_version(capsys):
    assert release.main(["post-publish", "--version", "0.0.1"]) == 1
    err = capsys.readouterr().err
    assert "PyPI has no release 0.0.1" in err
    assert "origin has no tag v0.0.1" in err


# --- review fixes: the install's environment and the canonical repository ---------------


class PythonPathUvx(FakeUvx):
    """A tagged package whose entry point is broken unless something on PYTHONPATH supplies
    an importable `amicus`: Python searches PYTHONPATH before site-packages, so an inherited
    one pointing at a checkout's `src` rescues it and the server reports that version."""

    def __call__(self, cmd, *args, **kwargs):
        if cmd[2].endswith(f"@{NEGATIVE}"):
            return super().__call__(cmd, *args, **kwargs)
        super().__call__(cmd, *args, **kwargs)
        for entry in kwargs["env"].get("PYTHONPATH", "").split(os.pathsep):
            if entry and (Path(entry) / "amicus" / "__init__.py").exists():
                return subprocess.CompletedProcess(cmd, 0, stdout=_reply(), stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="ModuleNotFoundError: No module named 'amicus.server'\n"
        )


def test_an_ambient_pythonpath_cannot_rescue_a_broken_tag(pub, capsys, tmp_path, monkeypatch):
    ambient = tmp_path / "checkout-src"
    (ambient / "amicus").mkdir(parents=True)
    (ambient / "amicus" / "__init__.py").write_text('__version__ = "1.3.0"\n', encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(ambient))
    _post_publish_refused(pub, capsys, "gave no `initialize` reply", uvx=PythonPathUvx())


_PYTHON_OR_VENV = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "PYTHONSAFEPATH",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "UV_PROJECT",
    "UV_PROJECT_ENVIRONMENT",
    "UV_PYTHON",
    "UV_OFFLINE",
    "UV_INDEX_URL",
    "UV_CONFIG_FILE",
)


def test_the_install_environment_is_an_allowlist(pub, capsys, monkeypatch):
    for name in _PYTHON_OR_VENV:
        monkeypatch.setenv(name, "/ambient")
    monkeypatch.setenv("AMICUS_CODEX_BIN", "/ambient/codex")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    uvx = FakeUvx()
    assert _run(pub, "post-publish", uvx=uvx) == 0
    for call in uvx.calls:
        env = call["env"]
        leaked = sorted(k for k in env if k in _PYTHON_OR_VENV or k.startswith("AMICUS_"))
        assert leaked == []
        ours = {"PATH", "HOME", "TMPDIR", "UV_CACHE_DIR", "UV_TOOL_DIR"}
        ours |= {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"}
        extra = {k for k in env if k not in ours and k not in release.INSTALL_ENV_NAMES}
        assert all(k.startswith("LC_") for k in extra), sorted(extra)
        assert env["LANG"] == "en_US.UTF-8"
        assert env["TMPDIR"] != os.environ.get("TMPDIR")  # emptiness is checked in FakeUvx


def test_the_install_uses_the_canonical_repository(pub, capsys):
    uvx = FakeUvx()
    assert _run(pub, "post-publish", uvx=uvx) == 0
    assert uvx.calls[0]["source"] == f"git+{pub.origin}@{TAG}"


def _mirror(pub: Published, tmp_path: Path) -> Path:
    """A clone of the canonical repository for `origin` to point at instead."""
    mirror = tmp_path / "mirror.git"
    _git(tmp_path, "clone", "-q", "--mirror", str(pub.origin), str(mirror))
    _git(pub.repo, "remote", "set-url", "origin", str(mirror))
    return mirror


def test_an_identical_mirror_as_origin_holds(pub, capsys, tmp_path):
    _mirror(pub, tmp_path)
    assert _run(pub, "post-publish") == 0


def test_an_origin_whose_tag_object_differs_from_canonical_fails(pub, capsys, tmp_path):
    mirror = _mirror(pub, tmp_path)
    # Same commit, re-tagged with another message: a different tag object.
    _git(mirror, "tag", "-d", TAG)
    _git(mirror, "tag", "-a", TAG, "-m", "a mirror's own record", pub.sha)
    _post_publish_refused(pub, capsys, "does not match the canonical repository")


def test_an_origin_whose_tag_peels_elsewhere_fails(pub, capsys, tmp_path):
    mirror = _mirror(pub, tmp_path)
    _git(mirror, "tag", "-d", TAG)
    _git(mirror, "tag", "-a", TAG, "-m", "moved", f"v{PREVIOUS}^{{commit}}")
    _post_publish_refused(pub, capsys, "does not match the canonical repository")


def test_a_tag_missing_from_the_canonical_repository_fails(pub, capsys, tmp_path):
    _mirror(pub, tmp_path)
    _git(pub.origin, "tag", "-d", TAG)  # the canonical one loses it; the mirror keeps it
    _post_publish_refused(pub, capsys, f"the canonical repository {pub.origin} has no tag {TAG}")


def test_pointer_refuses_a_mismatching_origin(pub, capsys, tmp_path):
    mirror = _mirror(pub, tmp_path)
    _git(mirror, "tag", "-d", TAG)
    _git(mirror, "tag", "-a", TAG, "-m", "moved", f"v{PREVIOUS}^{{commit}}")
    _pointer_refused(pub, capsys, "does not match the canonical repository")
    assert _local_tag(pub) is None
