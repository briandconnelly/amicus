"""RunSpec: the public half persists; the input half never does."""

from __future__ import annotations

import json

from amicus.request import INPUT_FIELDS, RunSpec, meta_for


def _spec(**kw) -> RunSpec:
    base = dict(
        backend="codex",
        kind="consult",
        tool="amicus_consult",
        cwd="/repo",
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=60,
        model=None,
        reasoning_effort=None,
        options={"isolation": "inherit"},
        scope=None,
        base=None,
        commit=None,
        paths=None,
        untracked="explicit_only",
        git_timeout=60,
        max_input_bytes=200_000,
        max_diff_bytes=200_000,
        max_output_bytes=10 * 1024 * 1024,
        question="why?",
        task=None,
        extra_context="ctx",
        instructions_append="focus",
        focus=None,
    )
    base.update(kw)
    return RunSpec(**base)


def test_public_half_never_carries_inputs_and_round_trips():
    spec = _spec()
    public = spec.public()
    assert not set(public) & set(INPUT_FIELDS)
    assert public["kind"] == "consult" and public["options"] == {"isolation": "inherit"}
    inputs = json.loads(spec.inputs_json())
    assert inputs == {
        "question": "why?",
        "task": None,
        "extra_context": "ctx",
        "instructions_append": "focus",
        "focus": None,
        "target": None,
        "evidence": None,
    }
    assert RunSpec.from_parts(json.loads(json.dumps(public)), inputs) == spec


def test_from_parts_tolerates_a_legacy_public_half_missing_optional_keys():
    public = _spec().public()
    for key in ("focus", "untracked", "max_output_bytes"):
        public.pop(key, None)
    spec = RunSpec.from_parts(public, {"question": "q"})
    assert spec.untracked == "explicit_only" and spec.max_output_bytes > 0 and spec.focus is None


def test_meta_for_fingerprints_instructions_and_carries_provenance():
    meta = meta_for(_spec(workspace_source="cwd"))
    assert meta.backend == "codex" and meta.cwd == "/repo" and meta.roots_source == "client"
    assert meta.workspace_warning is not None and "workspace_root" in meta.workspace_warning
    assert meta.instructions_append is not None and meta.instructions_append.bytes == 5
    assert meta.backend_details == {"isolation": "inherit"}
    assert meta.timeout_seconds == 60 and meta.model is None
    assert meta_for(_spec(instructions_append=None, options={})).instructions_append is None
    assert meta_for(_spec(options={})).backend_details is None


def test_identity_drops_connection_and_provenance_fields_and_digests_the_inputs():
    spec = _spec()
    ident = spec.identity()
    for name in ("cwd", "workspace_source", "roots_source", "host_name", "kind", "tool"):
        assert name not in ident, name
    for name in INPUT_FIELDS:
        assert name not in ident, name
    assert ident["backend"] == "codex" and ident["timeout_seconds"] == 60
    assert len(ident["inputs_digest"]) == 64 and int(ident["inputs_digest"], 16) >= 0
    assert "why?" not in json.dumps(ident) and "focus" not in json.dumps(ident)


def test_arg_hash_is_stable_across_connections_but_not_across_prompts_or_knobs():
    a = _spec().arg_hash()
    assert len(a) == 64
    assert _spec(cwd="/elsewhere", host_name="Codex", roots_source="none").arg_hash() == a
    assert _spec(question="why not?").arg_hash() != a
    assert _spec(extra_context=None).arg_hash() != a
    assert _spec(model="o3").arg_hash() != a
    assert _spec(scope="branch").arg_hash() != a
    assert _spec(options={"isolation": "worktree"}).arg_hash() != a
