"""A JSON document nested too deeply for the decoder raises RecursionError, which is not a
ValueError (#471). Every reader of backend output must treat it as unparseable instead of
letting it escape: one such line would otherwise turn a run into internal_error."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from amicus import _worker
from amicus.backends.claude import normalize as claude_normalize
from amicus.backends.codex import normalize as codex_normalize
from amicus.backends.kimi import cli as kimi_cli
from amicus.backends.kimi import models as kimi_models
from amicus.backends.kimi import normalize as kimi_normalize
from amicus.backends.pi import cli as pi_cli
from amicus.backends.pi import normalize as pi_normalize
from amicus.schemas import structured

_DEPTH = 200_000
DEEP = '{"a":' + "[" * _DEPTH + "]" * _DEPTH + "}"
SHALLOW = '{"a": [[1]]}'


def test_the_deep_document_really_overflows_the_decoder():
    """Control: if the decoder ever stops raising on DEEP, the tests below prove nothing."""
    with pytest.raises(RecursionError):
        json.loads(DEEP)
    assert json.loads(SHALLOW) == {"a": [[1]]}


def test_pi_event_readers_skip_a_deep_line():
    assert pi_normalize.final_assistant(DEEP + "\n") is None
    assert pi_normalize.failed_stop(DEEP) is None
    assert pi_normalize.parse_event_metadata(DEEP) == pi_normalize.parse_event_metadata("")


def test_codex_event_readers_skip_a_deep_line():
    assert codex_normalize.parse_event_metadata(DEEP) == (None, None)
    assert codex_normalize.extract_error_message(DEEP) is None
    assert codex_normalize._unwrap_json_message(DEEP) == DEEP


def test_kimi_event_readers_skip_a_deep_line():
    assert kimi_normalize.parse_event_metadata(DEEP) == (None, None)
    assert kimi_normalize.extract_error_message(DEEP) is None
    assert kimi_normalize._unwrap_json_message(DEEP) == DEEP


def test_claude_envelope_is_none_for_a_deep_document():
    assert claude_normalize.parse_envelope(DEEP) is None
    assert claude_normalize.parse_envelope(SHALLOW) == {"a": [[1]]}, "control"


@pytest.mark.parametrize("enclosed", [False, True])
def test_a_deep_structured_answer_is_invalid_json(enclosed):
    assert structured.classify_structured(DEEP, enclosed=enclosed) == ("invalid_json", None)
    assert structured.classify_structured(f"prose {DEEP} prose", enclosed=enclosed) == (
        "invalid_json",
        None,
    )
    assert structured.classify_structured(SHALLOW, enclosed=enclosed) == ("ok", {"a": [[1]]})


def _capture(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(
        stdout=stdout, stderr="", exit_code=0, binary_missing=False, timed_out=False
    )


def test_kimi_probes_read_a_deep_payload_as_unreadable(monkeypatch):
    assert kimi_cli._provider_count(DEEP) is None
    monkeypatch.setattr(kimi_models.runtime, "run_sync_capture", lambda *a, **k: _capture(DEEP))
    assert kimi_models.probe_catalog("kimi") is None
    monkeypatch.setattr(kimi_models.runtime, "run_sync_capture", lambda *a, **k: _capture(SHALLOW))
    assert kimi_models.probe_catalog("kimi") == {"a": [[1]]}, "control"


def test_pi_auth_probe_reads_a_deep_payload_as_unknown(monkeypatch):
    monkeypatch.setattr(pi_cli.runtime, "run_sync_capture", lambda *a, **k: _capture(DEEP))
    assert pi_cli.auth_status("pi", "openrouter/x/y") == "unknown"
    ready = _capture('{"status": "ready"}')
    monkeypatch.setattr(pi_cli.runtime, "run_sync_capture", lambda *a, **k: ready)
    assert pi_cli.auth_status("pi", "openrouter/x/y") == "ready", "control"


def test_the_worker_activity_observer_ignores_a_deep_line(tmp_path):
    observe, _recorder = _worker._activity_observer(tmp_path)
    observe(DEEP)
    observe(SHALLOW)
