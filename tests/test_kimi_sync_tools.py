"""End to end, spend-free: MCP client → sync tool → detached worker → real kimi plugin →
the fake kimi executable → delivered envelope, a recoverable job record, and the discovery
tools reading the same fake."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.orchestration.isolation import NO_REPO_WARNING
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_kimi, monkeypatch):
    monkeypatch.setenv("AMICUS_KIMI_BIN", str(fake_kimi))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_KIMI_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_KIMI_PROMPT_FILE", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in (
        "FAKE_KIMI_EXIT",
        "FAKE_KIMI_STDERR",
        "FAKE_KIMI_ANSWER",
        "FAKE_KIMI_WRITE",
        "FAKE_KIMI_EVENTS",
        "FAKE_KIMI_EVENTS_FILE",
        "FAKE_KIMI_PROVIDERS",
        "FAKE_KIMI_SLEEP",
        "FAKE_KIMI_ANSWER_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    return server.create_app(settings, registry)


def _runs(tmp_path):
    """The recorded `--prompt` invocations (probes excluded)."""
    if not (tmp_path / "argv.jsonl").exists():
        return []
    lines = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    return [line for line in lines if "--prompt" in line["argv"]]


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.co")
    _git(r, "config", "user.name", "t")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


async def test_consult_end_to_end_in_a_repo(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "why?",
                "workspace_root": str(repo),
                "instructions_append": "Focus on locking.",
                "model": "k3",
                "reasoning_effort": "high",
            },
        )
    body = res.structured_content
    assert res.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    meta = body["meta"]
    assert meta["backend"] == "kimi" and meta["job_id"] and meta["session_id"] == "session-fake"
    assert meta.get("usage") is None and meta["backend_details"] == {"isolation": "inherit"}
    assert NO_REPO_WARNING not in meta.get("security_warnings", []) and meta["model"] == "k3"
    assert meta["instructions_append"]["bytes"] == 17 and "Focus on locking" not in json.dumps(body)
    prompt = (tmp_path / "prompt.txt").read_text()
    assert "Focus on locking." in prompt and "## Question\nwhy?" in prompt
    assert "TestHost" in prompt and "# Required output format" in prompt
    [run] = _runs(tmp_path)
    argv = run["argv"]
    assert argv[0] == "--prompt" and "--agent-file" in argv and "--add-dir" not in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--model") + 1] == "k3"
    assert run["env"] == {
        "KIMI_MODEL_THINKING_EFFORT": "high",
        "KIMI_MODEL_OUTPUT_FORMAT": "stream-json",
    }
    store = lifecycle.job_store(config.settings())
    rec, payload = store.result_payload(str(repo.resolve()), meta["job_id"])
    assert rec["status"] == "done" and rec["extra"]["backend"] == "kimi"
    spec_text = (store._job_dir(str(repo.resolve()), meta["job_id"]) / "spec.json").read_text()
    assert "why?" not in spec_text
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert listed.strip().count("\n") == 0


async def test_a_finding_citing_the_handshake_prompt_is_delivered_without_it(
    app, tmp_path, repo, monkeypatch
):
    """#140, end to end: the fake cites the REAL handshake path of its own run, in a
    finding's anchor, its prose, and the summary. None of it reaches the caller or the
    stored record, and the cleared anchor is disclosed."""
    monkeypatch.setenv(
        "FAKE_KIMI_ANSWER",
        json.dumps(
            {
                "summary": "see {PROMPT_PATH}",
                # The directory and an unlisted sibling: only the adapter's declared
                # staging_dir covers these, since `artifacts` names neither.
                "next_steps": ["ls {PROMPT_DIR}", "read {PROMPT_DIR}/notes.md"],
                "findings": [
                    {
                        "title": "TEXT D is false",
                        "severity": "high",
                        "file": "{PROMPT_PATH}",
                        "line": 28,
                        "evidence": "at {PROMPT_PATH}:28",
                    }
                ],
                "questions": [],
                "assumptions": [],
            }
        ),
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "why?", "workspace_root": str(repo), "detail": "full"},
        )
    body = res.structured_content
    assert body["ok"] is True
    [finding] = body["findings"]
    assert finding["title"] == "TEXT D is false" and finding["severity"] == "high"
    assert finding.get("file") is None and finding.get("line") is None
    assert body["findings_diagnostics"] == {
        "dropped": 0,
        "reasons": ["backend_artifact_reference_removed"],
    }
    # Control: the fake really did substitute a path, so its absence below means something.
    assert "[amicus temporary file]" in body["summary"]
    assert body["next_steps"] == ["ls [amicus temporary file]", "read [amicus temporary file]"]
    delivered = json.dumps(body)
    assert "amicus-kimi-handshake-" not in delivered and "prompt.md" not in delivered
    store = lifecycle.job_store(config.settings())
    _, payload = store.result_payload(str(repo.resolve()), body["meta"]["job_id"])
    assert "amicus-kimi-handshake-" not in json.dumps(payload), "scrubbed before it is stored"


async def test_a_review_citing_the_prompt_in_jsons_escaped_spelling_is_scrubbed(
    app, repo, monkeypatch
):
    """A review re-parses the raw answer, and JSON lets a path be written `\\/tmp\\/x`, which
    text replacement cannot see. Judged at detail=full, so raw_response.text is in scope."""
    (repo / "a.py").write_text("x = 2\n")
    answer = (
        '{"summary": "s", "verdict": "pass", "confidence": "high", "findings": '
        '[{"title": "t", "severity": "low", "file": "{PROMPT_PATH_ESCAPED}", "line": 4}], '
        '"questions": [], "assumptions": [], "next_steps": []}'
    )
    assert "\\/" not in answer, "control: only the fake's substitution supplies the escape"
    monkeypatch.setenv("FAKE_KIMI_ANSWER", answer)
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_review_changes",
            {"backend": "kimi", "workspace_root": str(repo), "detail": "full"},
        )
    body = res.structured_content
    assert body["ok"] is True and body["review_status"] == "completed", body.get("summary")
    [finding] = body["findings"]
    assert finding.get("file") is None and finding.get("line") is None
    assert body["findings_diagnostics"]["reasons"] == ["backend_artifact_reference_removed"]
    assert body["verdict"] == "pass" and body["confidence"] == "high", "never folds a verdict"
    assert body["raw_response"]["text"], "control: the raw answer was delivered"
    assert "amicus-kimi-handshake-" not in json.dumps(body)


async def test_a_failure_citing_the_handshake_prompt_is_scrubbed_too(app, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_EXIT", "1")
    monkeypatch.setenv("FAKE_KIMI_STDERR", "error: cannot parse {PROMPT_PATH}: line 3")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is False
    # Control: the stderr line did reach the message, so the path's absence means something.
    assert "cannot parse [amicus temporary file]: line 3" in body["error"]["message"]
    assert "amicus-kimi-handshake-" not in json.dumps(body)
    store = lifecycle.job_store(config.settings())
    _, payload = store.result_payload(str(repo.resolve()), body["meta"]["job_id"])
    assert "amicus-kimi-handshake-" not in json.dumps(payload)


async def test_consult_outside_a_repo_runs_in_an_empty_dir_with_a_warning(app, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(tmp_path)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["meta"]["security_warnings"] == [NO_REPO_WARNING]


async def test_review_and_delegate_end_to_end(app, tmp_path, repo, monkeypatch):
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        review = await c.call_tool(
            "amicus_review_changes", {"backend": "kimi", "workspace_root": str(repo)}
        )
    body = review.structured_content
    assert body["ok"] is True
    assert body["review_status"] == "completed" and body["verdict"] == "pass"
    assert body["meta"]["context_summary"]["files_changed"] == 1
    monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "Added b.py.")
    async with Client(app) as c:
        delegate = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = delegate.structured_content
    assert body["ok"] is True and body["summary"] == "Added b.py."
    assert "+written by fake kimi" in body["diff"]
    assert not (repo / "b.py").exists() and (repo / "a.py").read_text() == "x = 2\n"
    argv = _runs(tmp_path)[-1]["argv"]
    assert "--agent-file" not in argv and "write your final answer to" in argv[1]


async def test_empty_answer_is_an_empty_response_error(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert res.is_error is True
    err = res.structured_content["error"]
    assert err["code"] == "empty_response" and err["backend"] == "kimi"
    assert res.structured_content["meta"]["command_exit_code"] == 0


async def test_unsupported_effort_is_refused_before_spend(app, tmp_path, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "q",
                "workspace_root": str(repo),
                "model": "k3",
                "reasoning_effort": "xhigh",
            },
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_reasoning_effort" and err["temporary"] is False
    assert err["details"]["allowed_values"] == ["low", "medium", "high"]
    assert err["repair"]["tool"] == "amicus_models"
    assert _runs(tmp_path) == []
    async with Client(app) as c:
        ok = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "q",
                "workspace_root": str(repo),
                "model": "unlisted",
                "reasoning_effort": "xhigh",
            },
        )
    assert ok.structured_content["ok"] is True  # fail open on an unlisted alias
    assert _runs(tmp_path)[-1]["env"]["KIMI_MODEL_THINKING_EFFORT"] == "xhigh"


async def test_failures_are_classified_and_recorded(app, tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_EXIT", "1")
    monkeypatch.setenv("FAKE_KIMI_STDERR", "Error: 401 Unauthorized")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "backend_auth_required" and err["backend"] == "kimi"
    assert err["temporary"] is False
    assert res.structured_content["meta"]["command_exit_code"] == 1
    monkeypatch.setenv(
        "FAKE_KIMI_STDERR",
        'error: failed to run prompt: Model "zz" is not configured in config.toml.',
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo), "model": "zz"},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "invalid_model" and err["details"]["field"] == "model"
    assert err["repair"]["tool"] == "amicus_models"


async def test_discovery_tools_read_the_fake(app, tmp_path, repo):
    async with Client(app) as c:
        backends = await c.call_tool("amicus_backends", {"backend": "kimi", "detail": "full"})
        models = await c.call_tool("amicus_models", {"backend": "kimi"})
        dry = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "kimi", "workspace_root": str(repo)}
        )
    [entry] = backends.structured_content["backends"]
    assert entry["available"] is True and entry["status"] == {
        "installed": True,
        "version": "0.41.0",
        "authenticated": True,
        "warnings": [],
    }
    assert entry["features"] == ["delegate", "empty_response_detection", "model_validation"]
    assert {o["name"] for o in entry["options"]} == {"isolation"}
    assert entry["options"][0]["allowed_values"] == ["inherit", "ignore-skills"]
    assert "handshake" in entry["carriers"] and "Kimi provider" in entry["egress"]
    assert "session files" in entry["carriers"] and "session files" in entry["readonly_honesty"]
    body = models.structured_content
    assert body["source"] == "live" and [m["slug"] for m in body["models"]] == ["k3"]
    assert body["models"][0]["supported_reasoning_efforts"] == ["low", "medium", "high"]
    assert dry.structured_content["ok"] is True
    assert dry.structured_content["meta"]["backend"] == "kimi"
    assert _runs(tmp_path) == []


# --- #162: kimi's delegate answer FILE refused, with and without its stream -----------------


async def test_a_refused_answer_file_falls_back_to_the_stream_and_says_so(app, repo, monkeypatch):
    monkeypatch.setenv("FAKE_KIMI_ANSWER_MODE", "symlink")
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "Added b.py.")
    monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["summary"] == "Added b.py.", "the stream's whole answer"
    # `truncated` reports a bounded diff or input, never stream capture; it is false here
    # because this small diff fit, not because the stream was whole.
    assert body["meta"]["truncated"] is False
    assert any("answer file" in w for w in body["meta"]["security_warnings"])


async def test_a_refused_answer_file_with_no_stream_is_not_an_empty_response(
    app, repo, monkeypatch
):
    """Kimi's inspector calls a clean exit with no answer `empty_response`. Here the answer
    exists and amicus refused it, which is why it looked empty, so that is what is said."""
    monkeypatch.setenv("FAKE_KIMI_ANSWER_MODE", "symlink")
    monkeypatch.setenv(
        "FAKE_KIMI_EVENTS",
        '{"role":"meta","type":"session.resume_hint","session_id":"session-fake"}\n',
    )
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    err = res.structured_content["error"]
    assert err["code"] == "answer_unavailable" and err["backend"] == "kimi"
    assert err["details"]["reason"] == "artifact_not_regular"
    # Control: the same run with a READABLE EMPTY file and no stream is the ordinary empty
    # case. The fake writes the file itself; an unset answer would leave it absent instead.
    monkeypatch.setenv("FAKE_KIMI_ANSWER_MODE", "empty")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert res.structured_content["error"]["code"] == "empty_response"


# --- #198: an answer the stream capture cut is not delivered as a shorter one ------------
_CAP = 65_536  # the smallest AMICUS_MAX_OUTPUT_BYTES amicus accepts


def _set_stream(monkeypatch, tmp_path, events):
    """Through a file: a stream past the cap is over Linux's 128 KiB limit on one env string."""
    path = tmp_path / "events.jsonl"
    path.write_text(events, encoding="utf-8")
    monkeypatch.setenv("FAKE_KIMI_EVENTS_FILE", str(path))


def _capped_app(monkeypatch):
    """The `app` fixture reads settings before a test can set the cap, so build another."""
    monkeypatch.setenv("AMICUS_MAX_OUTPUT_BYTES", str(_CAP))
    settings = config.settings()
    assert settings.max_output_bytes == _CAP
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


def _stream(*contents, tool_lines=0):
    lines = ['{"role":"meta","type":"system.version","version":"0.41.0"}']
    lines += [json.dumps({"role": "assistant", "content": c}) for c in contents[:-1]]
    lines += [json.dumps({"role": "tool", "content": "x" * 1000})] * tool_lines
    lines.append(json.dumps({"role": "assistant", "content": contents[-1]}))
    lines.append('{"role":"meta","type":"session.resume_hint","session_id":"session-fake"}')
    return "\n".join(lines) + "\n"


async def _consult(app, cwd):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(cwd)},
            raise_on_error=False,
        )
    return res.structured_content


async def test_a_final_message_past_the_cap_is_answer_unavailable_not_the_one_before_it(
    app, repo, monkeypatch, tmp_path
):
    """The capture keeps a head and a tail, and a final message too large for the tail is
    evicted whole, so the interim message before it used to be delivered as the answer."""
    _set_stream(monkeypatch, tmp_path, _stream("EARLY interim", "FINAL " + "y" * 70_000))
    body = await _consult(_capped_app(monkeypatch), repo)
    assert body["ok"] is False, f"delivered {body.get('summary')!r}"
    err = body["error"]
    assert err["code"] == "answer_unavailable" and err["backend"] == "kimi"
    assert err["details"]["reason"] == "stream_truncated"
    assert err["temporary"] is False and err["repair"]["next_step"] == "reduce_input"
    assert "AMICUS_MAX_OUTPUT_BYTES" in err["repair"]["alternative"]
    assert "EARLY" not in json.dumps(body)
    # Control: the same stream with a final message that fits is delivered whole.
    _set_stream(monkeypatch, tmp_path, _stream("EARLY interim", "FINAL " + "y" * 200))
    ok = await _consult(_capped_app(monkeypatch), repo)
    assert ok["ok"] is True and ok["summary"].startswith("FINAL")


async def test_a_stream_cut_in_the_middle_still_delivers_its_final_message(
    app, repo, monkeypatch, tmp_path
):
    """What the tail keeps is the newest output, so a final message that survived is the
    true one; refusing it would fail a run that answers correctly."""
    _set_stream(monkeypatch, tmp_path, _stream("EARLY", "FINAL", tool_lines=200))
    body = await _consult(_capped_app(monkeypatch), repo)
    assert body["ok"] is True, body.get("error")
    assert body["summary"] == "FINAL"


async def test_a_stream_that_lost_its_only_message_is_answer_unavailable_not_empty(
    app, repo, monkeypatch, tmp_path
):
    """kimi's inspector sees no message and says empty_response, but the backend did answer:
    the capture dropped it."""
    _set_stream(monkeypatch, tmp_path, _stream("FINAL " + "y" * 70_000))
    body = await _consult(_capped_app(monkeypatch), repo)
    assert body["error"]["code"] == "answer_unavailable"
    assert body["error"]["details"]["reason"] == "stream_truncated"


async def test_a_delegate_answering_in_its_file_is_indifferent_to_the_stream(
    app, repo, monkeypatch, tmp_path
):
    """With the answer file read, the stream is accounting only, so its loss costs nothing."""
    monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "Added b.py.")
    _set_stream(monkeypatch, tmp_path, _stream("EARLY", "FINAL " + "y" * 70_000))
    async with Client(_capped_app(monkeypatch)) as c:
        res = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["summary"] == "Added b.py."


async def test_a_delegate_whose_stream_lost_its_summary_still_delivers_the_diff(
    app, repo, monkeypatch, tmp_path
):
    """No answer file and a cut stream: the summary is gone, the diff is from the worktree."""
    from amicus.orchestration.run import DELEGATE_SUMMARY_LOST

    monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
    monkeypatch.setenv("FAKE_KIMI_ANSWER", "")
    _set_stream(monkeypatch, tmp_path, _stream("EARLY", "FINAL " + "y" * 70_000))
    async with Client(_capped_app(monkeypatch)) as c:
        res = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    body = res.structured_content
    assert body["ok"] is True and body["summary"] == DELEGATE_SUMMARY_LOST
    assert "+written by fake kimi" in body["diff"]
    assert "EARLY" not in json.dumps(body)
    assert body["meta"]["security_warnings"] == [], "nothing was refused, so no ADR 0009 warning"
