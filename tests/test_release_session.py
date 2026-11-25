"""`scripts/release.py session`: RELEASING step 3 in one command, asking before it spends.

The fixture is real git: a bare `origin` that carries the release PR's head as
`refs/pull/42/head` the way GitHub does, and a main checkout with that branch checked out, as
the maintainer has it after step 2. Everything else is stubbed: `gh`, the installs, the
checks and the evidence script, whose stub writes a record instead of spending anything.
Nothing here can reach a backend.

The positive control runs first, so a broken fixture cannot make a refusal pass vacuously.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from tests.support.releasefixture import NEXT
from tests.support.releasefixture import git as _git

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")

PR = 42
BRANCH = f"chore/release-{NEXT}"
MODEL = "openrouter/moonshotai/kimi-k3"
PHRASE = f"spend {NEXT}"
UPDATES = [
    {"backend": "codex", "version": "0.172.0", "argv": ["npm", "i", "-g", "c@0.172.0"], "env": {}},
    {
        "backend": "claude",
        "version": "2.1.331",
        "argv": ["claude", "install", "2.1.331"],
        "env": {"DISABLE_AUTOUPDATER": "1"},
    },
    {"backend": "pi", "version": "1.6.0", "argv": ["npm", "i", "-g", "p@1.6.0"], "env": {}},
]
EVIDENCE = ["uv", "run", "python", release.EVIDENCE_SCRIPT, "--version", NEXT]
POLICY = ["uv", "run", "python", "scripts/release.py", "policy"]
PREFLIGHT = ["uv", "run", "python", "scripts/release.py", "preflight", "--pr", str(PR)]
PREFLIGHT += ["--version", NEXT]
PRICING = list(release.PI_PRICING_COMMAND)
GH_FIELDS = "headRefOid,headRefName,state,baseRefName,isCrossRepository"


class Repo:
    def __init__(self, tmp_path: Path):
        self.origin = tmp_path / "origin.git"
        self.main = tmp_path / "amicus"
        self.worktree = tmp_path / f"amicus-wt-release-{NEXT.replace('.', '-')}"
        self.home = tmp_path / "home"
        self.first = ""
        self.head = ""


@pytest.fixture
def repo(tmp_path) -> Repo:
    r = Repo(tmp_path)
    r.home.mkdir()
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(r.origin))
    r.main.mkdir()
    _git(r.main, "init", "-q", "-b", "main")
    (r.main / ".gitignore").write_text(".release-evidence/\n", encoding="utf-8")
    (r.main / "README.md").write_text("amicus\n", encoding="utf-8")
    _git(r.main, "add", "-A")
    _git(r.main, "commit", "-q", "-m", "work")
    r.first = _git(r.main, "rev-parse", "HEAD")
    _git(r.main, "remote", "add", "origin", str(r.origin))
    _git(r.main, "push", "-q", "origin", "main")
    _git(r.main, "switch", "-q", "-c", BRANCH)
    (r.main / "README.md").write_text(f"amicus {NEXT}\n", encoding="utf-8")
    _git(r.main, "commit", "-q", "-am", f"chore(release): {NEXT}")
    r.head = _git(r.main, "rev-parse", "HEAD")
    _git(r.main, "push", "-q", "origin", BRANCH, f"HEAD:refs/pull/{PR}/head")
    return r


class FakeRun:
    """`gh pr view`, the session's commands and the evidence stub; anything else fails."""

    def __init__(self, head: str, *, version: str = NEXT, fix: bool = False, **returncodes: int):
        self.calls: list[tuple[list[str], dict]] = []
        flag = ["--fix"] if fix else []
        self.updates_command = [*release.UPDATES_COMMAND, *flag]
        self.preflight = [*PREFLIGHT[:-1], version, *flag]
        self.evidence = [*EVIDENCE[:-1], version]
        self.pr = {
            "headRefOid": head,
            "headRefName": BRANCH,
            "state": "OPEN",
            "baseRefName": "main",
            "isCrossRepository": False,
        }
        self.updates: object = {"updates": UPDATES, "failed": []}
        # What the second `print-updates`, just before the spend prompt, reports; the first
        # plan's when None.
        self.replan: object = None
        self.plans = 0
        self.returncodes = returncodes

    def _done(self, cmd, name: str, stdout: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, self.returncodes.get(name, 0), stdout, "boom\n")

    def __call__(self, cmd, *args, **kwargs):
        cmd = [str(part) for part in cmd]
        self.calls.append((cmd, kwargs))
        if cmd[:3] == ["gh", "pr", "view"]:
            return self._done(cmd, "gh", json.dumps(self.pr))
        if cmd == self.updates_command:
            self.plans += 1
            plan = self.replan if self.plans > 1 and self.replan is not None else self.updates
            return self._done(cmd, "updates", json.dumps(plan))
        if cmd in [u["argv"] for u in UPDATES]:
            return self._done(cmd, cmd[0] if cmd[0] == "claude" else "npm")
        if cmd == POLICY:
            return self._done(cmd, "policy")
        if cmd == self.preflight:
            return self._done(cmd, "preflight")
        if cmd == PRICING:
            return self._done(cmd, "pricing")
        if cmd == self.evidence:
            record = {
                "recorded_at": "2026-11-24T20:00:00+00:00",
                "commit": self.pr["headRefOid"],
                "backends": {
                    "codex": {"cli_version": "codex-cli 0.172.0"},
                    "claude": {"cli_version": "2.1.331 (Claude Code)"},
                    "pi": {"cli_version": "1.6.0"},
                },
            }
            path = Path(kwargs["cwd"]) / release.EVIDENCE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record), encoding="utf-8")
            return self._done(cmd, "evidence")
        raise AssertionError(f"unexpected command {cmd!r}")

    def commands(self) -> list[list[str]]:
        return [cmd for cmd, _ in self.calls]

    def kwargs(self, cmd: list[str]) -> dict:
        (found,) = [kw for c, kw in self.calls if c == cmd]
        return found


class Answers:
    """The maintainer's typed answers, in order; a question past the script fails the test."""

    def __init__(self, *answers: str | type[BaseException]):
        self.answers = list(answers)
        self.questions: list[str] = []

    def __call__(self, question: str) -> str:
        self.questions.append(question)
        assert self.answers, f"asked {question!r} with no answer scripted"
        answer = self.answers.pop(0)
        if isinstance(answer, type):
            raise answer
        return answer


def _session(
    r: Repo, run: FakeRun, ask: Answers, *, interactive=True, environ=None, extra=(), version=NEXT
):
    env = {"PATH": os.environ.get("PATH", ""), release.PI_MODEL_ENV: MODEL}
    ctx = release.Context(
        repo_root=r.main,
        run=run,
        ask=ask,
        interactive=lambda: interactive,
        environ=env if environ is None else environ,
        home=lambda: r.home,
    )
    return release.main(["session", "--pr", str(PR), "--version", version, *extra], context=ctx)


# --- positive control ------------------------------------------------------------------


def test_session_runs_step_3_in_order_and_spends_only_after_the_typed_phrase(repo, capsys):
    run = FakeRun(repo.head)
    ask = Answers("y", "y", PHRASE)
    assert _session(repo, run, ask) == 0
    out = capsys.readouterr()
    assert out.err == ""
    # The worktree sits beside the checkout, detached at the PR's head as GitHub reports it.
    assert _git(repo.worktree, "rev-parse", "HEAD") == repo.head
    assert _git(repo.worktree, "branch", "--show-current") == ""
    assert run.commands() == [
        ["gh", "pr", "view", str(PR), "--json", GH_FIELDS],
        list(release.UPDATES_COMMAND),
        *[u["argv"] for u in UPDATES],
        POLICY,
        PREFLIGHT,
        PRICING,
        list(release.UPDATES_COMMAND),
        EVIDENCE,
    ]
    for cmd, kwargs in run.calls[1:]:
        assert Path(kwargs["cwd"]) == repo.worktree.resolve(), cmd
    assert run.kwargs(UPDATES[1]["argv"])["env"]["DISABLE_AUTOUPDATER"] == "1"
    assert "DISABLE_AUTOUPDATER" not in run.kwargs(UPDATES[0]["argv"])["env"]
    assert run.kwargs(EVIDENCE)["env"]["AMICUS_REQUIRE_LIVE"] == "1"
    assert run.kwargs(EVIDENCE)["env"][release.PI_MODEL_ENV] == MODEL
    # The confirmation names the version, and the re-check names what the evidence vouches for.
    assert ask.questions[1].startswith(f"Is the re-check for these versions in PR #{PR}'s")
    assert "codex 0.172.0, claude 2.1.331, pi 1.6.0" in out.out
    assert f"`{PHRASE}`" in ask.questions[2]
    # The PR note, then the rest of the release with this commit filled in.
    assert (
        f"- Live-gate evidence recorded 2026-11-24T20:00:00+00:00 for `{repo.head}` on codex "
        "`codex-cli 0.172.0`, claude `2.1.331 (Claude Code)`, pi `1.6.0`."
    ) in out.out
    assert (
        f"- pi `models.json` for the pi gate's `{MODEL}`: absent at `~/.pi/agent/models.json`"
        in out.out
    )
    # Each block moves into the worktree first: its checks read the record there, and the shell
    # that ran the session is still in the checkout it started from.
    worktree = repo.worktree.resolve()
    enter = f"cd {shlex.quote(str(worktree))}"
    for block in release.next_steps(worktree, NEXT, PR, repo.head):
        assert "  " + " &&\\\n  ".join([enter, *block]) in out.out
    assert out.out.count(f"  {enter} &&\\\n") == len(
        release.next_steps(worktree, NEXT, PR, repo.head)
    )
    assert "never tags,\nmerges or pushes" in out.out


# --- what it asks, and what an answer other than yes does -------------------------------


@pytest.mark.parametrize("answer", ["spend it", "yes", f" spend {NEXT}x", EOFError])
def test_anything_but_the_exact_phrase_never_spends(repo, capsys, answer):
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers("y", "y", answer)) == 1
    assert EVIDENCE not in run.commands()
    err = capsys.readouterr().err
    assert "you did not confirm the evidence run" in err
    assert "Nothing was spent." in err


def test_declined_installs_are_skipped_and_the_preflight_still_decides(repo, capsys):
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers("n", "y", PHRASE)) == 0
    assert not any(u["argv"] in run.commands() for u in UPDATES)
    assert "Skipped. The preflight below fails if a CLI is not at npm's latest." in (
        capsys.readouterr().out
    )
    assert PREFLIGHT in run.commands()


@pytest.mark.parametrize("answer", ["n", "", EOFError])
def test_no_carrier_re_check_in_the_pr_stops_before_any_check(repo, capsys, answer):
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers("y", answer)) == 1
    assert POLICY not in run.commands()
    assert "write the carrier re-check into the release PR first" in capsys.readouterr().err


# --- refusals before anything is touched -----------------------------------------------


@pytest.mark.parametrize(
    ("interactive", "environ", "reason"),
    [
        (False, None, "runs only with stdin and stdout at a terminal"),
        (True, {release.PI_MODEL_ENV: MODEL, "CI": "true"}, "CI is set"),
        (True, {}, f"{release.PI_MODEL_ENV} is not set"),
    ],
)
def test_refusals_come_before_anything_runs(repo, capsys, interactive, environ, reason):
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers(), interactive=interactive, environ=environ) == 1
    assert run.calls == []
    assert not repo.worktree.exists()
    err = capsys.readouterr().err
    assert reason in err
    assert "Nothing was spent." in err


def test_a_version_that_is_not_x_y_z_is_refused(repo, capsys):
    ctx = release.Context(
        repo_root=repo.main,
        run=FakeRun(repo.head),
        ask=Answers(),
        interactive=lambda: True,
        environ={release.PI_MODEL_ENV: MODEL},
    )
    assert release.main(["session", "--pr", str(PR), "--version", "1.3"], context=ctx) == 1
    assert "version '1.3' is not X.Y.Z" in capsys.readouterr().err


def test_a_closed_pr_is_refused_before_the_worktree(repo, capsys):
    run = FakeRun(repo.head)
    run.pr["state"] = "MERGED"
    assert _session(repo, run, Answers()) == 1
    assert not repo.worktree.exists()
    assert f"PR #{PR} is MERGED, not OPEN" in capsys.readouterr().err


def test_a_pr_head_that_origin_does_not_carry_is_refused(repo, capsys):
    run = FakeRun(repo.first)  # GitHub's answer and origin's refs/pull disagree
    assert _session(repo, run, Answers()) == 1
    assert not repo.worktree.exists()
    err = capsys.readouterr().err
    assert f"origin's refs/pull/{PR}/head is {repo.head}" in err
    assert f"GitHub reports PR #{PR}'s head as {repo.first}" in err


# --- an existing worktree --------------------------------------------------------------


def test_a_clean_worktree_at_an_earlier_head_is_moved_to_the_pr_head(repo, capsys):
    _git(repo.main, "worktree", "add", "-q", "--detach", str(repo.worktree), repo.first)
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers("y", "y", PHRASE)) == 0
    assert _git(repo.worktree, "rev-parse", "HEAD") == repo.head
    assert f"from {repo.first} to PR #{PR}'s head {repo.head}" in capsys.readouterr().out


def test_a_worktree_already_at_the_head_is_used_as_it_is(repo, capsys):
    _git(repo.main, "worktree", "add", "-q", "--detach", str(repo.worktree), repo.head)
    assert _session(repo, FakeRun(repo.head), Answers("y", "y", PHRASE)) == 0
    assert "using the release worktree" in capsys.readouterr().out


def test_a_dirty_worktree_is_refused_and_left_alone(repo, capsys):
    _git(repo.main, "worktree", "add", "-q", "--detach", str(repo.worktree), repo.first)
    (repo.worktree / "notes.txt").write_text("mine\n", encoding="utf-8")
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers()) == 1
    assert _git(repo.worktree, "rev-parse", "HEAD") == repo.first
    assert "the tree is not clean (notes.txt)" in capsys.readouterr().err
    assert release.UPDATES_COMMAND not in [tuple(c) for c in run.commands()]


def test_a_path_that_is_not_a_worktree_of_this_repository_is_refused(repo, capsys):
    repo.worktree.mkdir()
    assert _session(repo, FakeRun(repo.head), Answers()) == 1
    assert f"{repo.worktree.resolve()} exists and is not a worktree of" in capsys.readouterr().err


def test_a_subdirectory_of_a_worktree_is_refused_and_the_worktree_stays_put(repo, capsys):
    _git(repo.main, "worktree", "add", "-q", "--detach", str(repo.worktree), repo.first)
    nested = repo.worktree / "sub"
    nested.mkdir()
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers(), extra=("--worktree", str(nested))) == 1
    assert "is not the top of a worktree" in capsys.readouterr().err
    assert _git(repo.worktree, "rev-parse", "HEAD") == repo.first
    assert release.UPDATES_COMMAND not in [tuple(c) for c in run.commands()]


def test_a_pr_from_a_fork_is_refused_before_anything_runs_from_it(repo, capsys):
    run = FakeRun(repo.head)
    run.pr["isCrossRepository"] = True
    assert _session(repo, run, Answers()) == 1
    assert "never comes from a fork" in capsys.readouterr().err
    assert not repo.worktree.exists()
    assert len(run.commands()) == 1


def test_a_pr_that_does_not_say_where_its_head_lives_is_refused(repo, capsys):
    run = FakeRun(repo.head)
    del run.pr["isCrossRepository"]
    assert _session(repo, run, Answers()) == 1
    assert "never comes from a fork" in capsys.readouterr().err


def test_npm_latest_moving_after_the_re_check_stops_before_the_spend_prompt(repo, capsys):
    run = FakeRun(repo.head)
    run.replan = {"updates": [*UPDATES[:2], {**UPDATES[2], "version": "1.6.1"}], "failed": []}
    ask = Answers("y", "y")
    assert _session(repo, run, ask) == 1
    err = capsys.readouterr().err
    assert "npm's latest moved from" in err
    assert "pi 1.6.1" in err
    assert EVIDENCE not in run.commands()
    assert len(ask.questions) == 2


def test_the_session_plans_an_install_for_every_backend_compat_checks():
    compat = _load("check_backend_compat")
    assert release.SESSION_BACKENDS == compat.BACKENDS


def test_the_main_checkout_is_never_the_release_worktree(repo, capsys):
    run = FakeRun(repo.head)
    assert _session(repo, run, Answers(), extra=("--worktree", str(repo.main))) == 1
    assert "is the main checkout, not a linked worktree" in capsys.readouterr().err


# --- failures stop at the first one ----------------------------------------------------


@pytest.mark.parametrize(
    ("failing", "last"),
    [
        ("npm", UPDATES[0]["argv"]),
        ("policy", POLICY),
        ("preflight", PREFLIGHT),
        ("pricing", PRICING),
    ],
)
def test_a_failing_step_stops_everything_after_it(repo, capsys, failing, last):
    run = FakeRun(repo.head, **{failing: 1})
    assert _session(repo, run, Answers("y", "y", PHRASE)) == 1
    assert run.commands()[-1] == last
    assert EVIDENCE not in run.commands()
    assert "Nothing was spent." in capsys.readouterr().err


def test_a_failed_evidence_run_says_not_to_tag(repo, capsys):
    run = FakeRun(repo.head, evidence=1)
    assert _session(repo, run, Answers("y", "y", PHRASE)) == 1
    err = capsys.readouterr().err
    assert f"Do not tag {NEXT}: the evidence did not pass." in err
    assert "Nothing was spent." not in err


def test_an_update_plan_from_a_failed_run_stops_the_session(repo, capsys):
    run = FakeRun(repo.head, updates=1)
    assert _session(repo, run, Answers()) == 1
    assert "failed (exit status 1)" in capsys.readouterr().err
    assert POLICY not in run.commands()


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"updates": [], "failed": ["pi: the latest release could not be read from npm"]}, "pi:"),
        ({"updates": [{"backend": "pi"}]}, "could not read"),
        ({"updates": [{**UPDATES[0], "argv": "npm i"}], "failed": []}, "malformed update"),
        ("not json", "could not read"),
        ({"updates": UPDATES[:2], "failed": []}, "not one each for"),
        ({"updates": [*UPDATES, UPDATES[0]], "failed": []}, "not one each for"),
        ({"updates": UPDATES, "failed": "none"}, "malformed failures"),
    ],
)
def test_an_update_plan_that_is_not_usable_stops_the_session(repo, capsys, payload, reason):
    run = FakeRun(repo.head)
    run.updates = payload
    assert _session(repo, run, Answers()) == 1
    assert reason in capsys.readouterr().err
    assert POLICY not in run.commands()


# --- the models.json note --------------------------------------------------------------


def _note(home: Path, data, **environ: str) -> str:
    folder = home / ".pi" / "agent"
    folder.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    (folder / "models.json").write_text(text, encoding="utf-8")
    return "\n".join(release.models_json_note({release.PI_MODEL_ENV: MODEL, **environ}, home))


def test_the_note_records_override_values_and_never_a_secret(tmp_path):
    data = {
        "providers": {
            "openrouter": {
                "apiKey": "sk-or-secret",
                "baseUrl": "https://user:pw@api.example.com/v1?key=abc",
                "headers": {"X-Title": "header-secret"},
                "models": [
                    {"id": "moonshotai/kimi-k3", "maxTokens": 8192, "api": "!cat api-secret"},
                    {"id": "other/model", "maxTokens": 1},
                ],
                "modelOverrides": {
                    "moonshotai/kimi-k3": {
                        "contextWindow": 131072,
                        "reasoning": True,
                        "input": ["text"],
                        "name": "Kimi",
                        "compat": {"supportsStore": False},
                    }
                },
            },
            "anthropic": {"apiKey": "$ANTHROPIC_SECRET"},
        }
    }
    note = _note(tmp_path, data)
    for secret in ("sk-or-secret", "user", "pw@", "/v1", "key=abc", "header-secret", "api-secret"):
        assert secret not in note, secret
    assert "ANTHROPIC" not in note and "Kimi" not in note and str(tmp_path) not in note
    assert "present at `~/.pi/agent/models.json`" in note
    assert (
        "provider `openrouter`: `apiKey` (value not recorded), "
        "`baseUrl` `https://api.example.com` (path not recorded), `headers` (value not recorded)"
    ) in note
    assert (
        "`models` entry `moonshotai/kimi-k3`: `api` (value not recorded), `maxTokens` `8192`"
        in note
    )
    assert (
        "`modelOverrides` entry `moonshotai/kimi-k3`: `compat` (value not recorded), "
        '`contextWindow` `131072`, `input` `["text"]`, `name` (value not recorded), '
        "`reasoning` `true`"
    ) in note


def test_the_note_reads_pi_coding_agent_dir_and_names_it_symbolically(tmp_path):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "models.json").write_text('{"providers": {}}', encoding="utf-8")
    note = release.models_json_note(
        {release.PI_MODEL_ENV: MODEL, "PI_CODING_AGENT_DIR": str(agent)}, tmp_path / "nohome"
    )
    assert note == [
        f"pi `models.json` for the pi gate's `{MODEL}`: present at "
        "`$PI_CODING_AGENT_DIR/models.json`, with no entry for provider `openrouter`."
    ]


@pytest.mark.parametrize("value", ["~", "~/agent"])
def test_the_note_expands_a_leading_tilde_as_pi_does(tmp_path, value):
    home = tmp_path / "home"
    agent = home / "agent" if value != "~" else home
    agent.mkdir(parents=True)
    (agent / "models.json").write_text('{"providers": {}}', encoding="utf-8")
    note = release.models_json_note(
        {release.PI_MODEL_ENV: MODEL, "PI_CODING_AGENT_DIR": value}, home
    )
    assert note == [
        f"pi `models.json` for the pi gate's `{MODEL}`: present at "
        "`$PI_CODING_AGENT_DIR/models.json`, with no entry for provider `openrouter`."
    ]


@pytest.mark.parametrize("value", ["agent", "./agent", "~other/agent"])
def test_the_note_cannot_tell_for_a_relative_pi_coding_agent_dir(tmp_path, monkeypatch, value):
    # A models.json at the relative path from here must not be read: amicus refuses the value.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "models.json").write_text('{"providers": {}}', encoding="utf-8")
    note = release.models_json_note(
        {release.PI_MODEL_ENV: MODEL, "PI_CODING_AGENT_DIR": value}, tmp_path / "home"
    )
    assert note == [
        f"pi `models.json` for the pi gate's `{MODEL}`: unknown, because "
        "`$PI_CODING_AGENT_DIR` is not absolute."
    ]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("{not json", "but not JSON, so which keys applied is unknown."),
        ([1, 2], "with no entry for provider `openrouter`."),
        ({"providers": {"openrouter": {}}}, "provider `openrouter`: no keys"),
        (
            {"providers": {"openrouter": {"models": "x"}}},
            "`models` entry `moonshotai/kimi-k3`: none",
        ),
    ],
)
def test_the_note_says_what_it_could_and_could_not_read(tmp_path, data, expected):
    assert expected in _note(tmp_path, data)


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("http://localhost:11434", "`http://localhost:11434`"),
        ("https://api.example.com/", "`https://api.example.com`"),
        ("$OPENROUTER_BASE", None),
        ("!echo https://x", None),
        ("not a url", None),
        ("https://api.example.com:notaport/v1", None),
    ],
)
def test_a_base_url_keeps_only_its_origin(url, shown):
    assert release._origin_only(url) == shown


def test_an_unreadable_record_still_lets_the_pr_note_print(tmp_path):
    (line,) = release._record_note(tmp_path)
    assert line.startswith(f"(could not read {release.EVIDENCE_PATH}")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("api", "/Users/someone/secret-path"),
        ("api", "sk-live-ABC123"),
        ("input", ["text", "/etc/passwd"]),
        ("input", ["sk-live-ABC123"]),
        ("api", "sk-live-example123"),
        ("api", "sk_live_example"),
        ("input", ["audio-secret"]),
        ("reasoning", "true"),
        ("contextWindow", "131072"),
        ("contextWindow", True),
        ("maxTokens", -1),
    ],
)
def test_a_recorded_key_with_a_value_of_the_wrong_shape_is_named_not_printed(tmp_path, key, value):
    data = {"providers": {"openrouter": {"models": [{"id": "moonshotai/kimi-k3", key: value}]}}}
    note = _note(tmp_path, data)
    assert f"`{key}` (value not recorded)" in note
    shown = value if isinstance(value, str) else json.dumps(value)
    assert shown not in note.replace(f"`{key}` (value not recorded)", "")


# --- a bug or security fix release (`--fix`) -------------------------------------------------

PATCH = "1.3.1"
HELD = {**UPDATES[0], "version": "0.171.1", "argv": ["npm", "i", "-g", "c@0.171.1"]}


def test_a_fix_session_plans_and_checks_with_fix_and_says_what_it_holds(repo, capsys):
    run = FakeRun(repo.head, version=PATCH, fix=True)
    run.updates = {"updates": [{**HELD, "held_below": "0.172.0"}, *UPDATES[1:]], "failed": []}
    ask = Answers("n", "y", f"spend {PATCH}")
    assert _session(repo, run, ask, extra=["--fix"], version=PATCH) == 0
    out = capsys.readouterr().out
    assert run.commands() == [
        ["gh", "pr", "view", str(PR), "--json", GH_FIELDS],
        run.updates_command,
        POLICY,
        run.preflight,
        PRICING,
        run.updates_command,
        run.evidence,
    ]
    assert run.updates_command[-1] == "--fix" and run.preflight[-1] == "--fix"
    assert "== 1. Backend CLIs for a fix release ==" in out
    assert "codex stays on 0.171.1: npm's latest 0.172.0 is outside the shipped contract" in out
    assert "Skipped. The preflight below fails if a CLI is not at these versions." in out
    assert "check_backend_compat.py release-brief --fix` drafts the re-check" in out
    assert "codex 0.171.1, claude 2.1.331, pi 1.6.0" in out


def test_a_fix_session_refuses_a_release_that_is_not_a_patch_before_anything_runs(repo, capsys):
    run = FakeRun(repo.head, fix=True)
    assert _session(repo, run, Answers(), extra=["--fix"]) == 1
    assert run.calls == []
    assert not repo.worktree.exists()
    assert "--fix is for a release that ships only bug" in capsys.readouterr().err


def test_an_update_plan_with_a_malformed_hold_stops_the_session(repo, capsys):
    run = FakeRun(repo.head)
    run.updates = {"updates": [{**UPDATES[0], "held_below": 172}, *UPDATES[1:]], "failed": []}
    assert _session(repo, run, Answers()) == 1
    assert "malformed update" in capsys.readouterr().err
