"""Behavior contract for scripts/check_github_actions_pinning.py.

The script lives under scripts/ (not the package), so coverage doesn't track it;
these tests pin its classification logic and 0/1/2 exit behavior directly. It is
loaded by path, mirroring tests/test_check_commit_message.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_github_actions_pinning.py"
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location("check_github_actions_pinning", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_script()


# --- iter_uses: extracting uses: values from YAML text -----------------------


def test_iter_uses_extracts_value_and_strips_inline_comment():
    text = "    steps:\n      - uses: actions/checkout@" + "a" * 40 + " # v6.0.3\n"
    found = check.iter_uses(text)
    assert found == [(2, "actions/checkout@" + "a" * 40, "v6.0.3")]


def test_iter_uses_skips_full_line_comments():
    text = "      # - uses: actions/checkout@v4\n      - run: echo hi\n"
    assert check.iter_uses(text) == []


def test_iter_uses_ignores_uses_substring_in_run_block():
    text = '      - run: echo "this uses: something"\n'
    assert check.iter_uses(text) == []


def test_iter_uses_ignores_uses_inside_multiline_literal_run_block():
    text = (
        "    steps:\n"
        "      - run: |\n"
        "          uses: not/a-real-action\n"
        "          echo done\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
    )
    assert check.iter_uses(text) == [(5, "actions/checkout@" + "a" * 40, None)]


def test_iter_uses_ignores_uses_inside_folded_run_block_with_chomp():
    text = "    steps:\n      - run: >-\n          uses: nope\n          still text\n"
    assert check.iter_uses(text) == []


def test_iter_uses_ignores_block_with_indent_then_chomp_indicator():
    # YAML allows the indentation indicator before the chomping indicator (|2-).
    text = (
        "    steps:\n"
        "      - run: |2-\n"
        "          uses: nope\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
    )
    assert check.iter_uses(text) == [(4, "actions/checkout@" + "a" * 40, None)]


def test_iter_uses_resumes_after_block_dedents():
    text = (
        "      - run: |\n          uses: ignored\n      - uses: actions/setup-uv@" + "b" * 40 + "\n"
    )
    assert check.iter_uses(text) == [(3, "actions/setup-uv@" + "b" * 40, None)]


def test_iter_uses_strips_surrounding_quotes():
    text = '      - uses: "actions/checkout@' + "a" * 40 + '"\n'
    assert check.iter_uses(text) == [(1, "actions/checkout@" + "a" * 40, None)]


# --- classify: None means OK, str means violation reason ---------------------


def test_classify_full_sha_is_ok():
    assert check.classify("actions/checkout@" + "a" * 40) is None


def test_classify_uppercase_hex_sha_is_ok():
    assert check.classify("actions/checkout@" + "A1B2C3D4" + "e" * 32) is None


def test_classify_local_action_is_ok():
    assert check.classify("./.github/actions/setup") is None


def test_classify_reusable_workflow_full_sha_is_ok():
    assert check.classify("owner/repo/.github/workflows/ci.yml@" + "b" * 40) is None


def test_classify_docker_digest_is_ok():
    assert check.classify("docker://alpine@sha256:" + "c" * 64) is None


def test_classify_tag_is_violation():
    assert check.classify("actions/checkout@v4") is not None


def test_classify_branch_is_violation():
    assert check.classify("actions/checkout@main") is not None


def test_classify_short_sha_is_violation():
    assert check.classify("actions/checkout@abc1234") is not None


def test_classify_missing_ref_is_violation():
    assert check.classify("actions/checkout") is not None


def test_classify_docker_tag_is_violation():
    assert check.classify("docker://alpine:3.18") is not None


def test_classify_docker_no_tag_is_violation():
    assert check.classify("docker://alpine") is not None


# --- main: exit codes --------------------------------------------------------


def _write_workflow(root: Path, body: str, *, on: str | None = "on: push\n") -> None:
    """Write ``ci.yml``, led by an ``on:`` line unless ``on`` is None: the check fails a
    workflow with no top-level ``on:``, so a fixture about something else needs one."""
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text((on or "") + body)


def test_main_returns_0_when_all_pinned(tmp_path, capsys):
    _write_workflow(
        tmp_path,
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + "a" * 40 + " # v6\n",
    )
    assert check.main([str(tmp_path)]) == 0


def test_main_returns_1_on_violation(tmp_path, capsys):
    _write_workflow(tmp_path, "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert check.main([str(tmp_path)]) == 1
    assert "actions/checkout@v4" in capsys.readouterr().out


def test_main_returns_2_when_no_workflows(tmp_path, capsys):
    assert check.main([str(tmp_path)]) == 2


def test_main_scans_yaml_extension_too(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yaml").write_text("jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert check.main([str(tmp_path)]) == 1


# --- rule 14's trailing version comment ----------------------------------------


_SHA = "a" * 40


def test_iter_uses_returns_the_flow_mapping_lines_trailing_comment():
    text = "      - { uses: actions/checkout@" + _SHA + " } # v6.0.3\n"
    assert check.iter_uses(text) == [(1, "actions/checkout@" + _SHA, "v6.0.3")]


def test_iter_uses_does_not_read_a_hash_inside_quotes_as_a_comment():
    text = "      - { uses: actions/checkout@" + _SHA + ', name: "x # v6" }\n'
    assert check.iter_uses(text) == [(1, "actions/checkout@" + _SHA, None)]


def test_iter_uses_reads_the_real_comment_after_a_quoted_hash():
    text = "      - { uses: actions/checkout@" + _SHA + ", name: 'a # b' } # v6.0.3\n"
    assert check.iter_uses(text) == [(1, "actions/checkout@" + _SHA, "v6.0.3")]


def test_iter_uses_does_not_read_a_hash_without_leading_space_as_a_comment():
    text = "      - uses: actions/checkout@" + _SHA + "#v6\n"
    assert check.iter_uses(text) == [(1, "actions/checkout@" + _SHA + "#v6", None)]


def test_version_comment_accepts_the_forms_this_repository_uses():
    for comment in ("v7.0.1", "v4", "1.14.3", "codeql-bundle-v2.25.6", "v4 (latest)"):
        assert check.version_comment_problem("actions/checkout@" + _SHA, comment) is None, comment


def test_version_comment_is_required_on_an_external_sha_pin():
    assert check.version_comment_problem("actions/checkout@" + _SHA, None) is not None


def test_version_comment_must_name_a_version():
    for comment in ("", "pinned", "TODO bump", "see #12"):
        assert check.version_comment_problem("actions/checkout@" + _SHA, comment) is not None, (
            comment
        )


def test_version_comment_is_required_on_a_reusable_workflow_pin():
    ref = "owner/repo/.github/workflows/ci.yml@" + _SHA
    assert check.version_comment_problem(ref, None) is not None


def test_version_comment_is_not_required_on_a_local_action_or_docker_digest():
    assert check.version_comment_problem("./.github/workflows/test.yml", None) is None
    assert check.version_comment_problem("docker://alpine@sha256:" + "c" * 64, None) is None


def test_main_returns_1_on_a_sha_pin_without_a_version_comment(tmp_path, capsys):
    _write_workflow(
        tmp_path, "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + _SHA + "\n"
    )
    assert check.main([str(tmp_path)]) == 1
    assert "ci.yml:5" in capsys.readouterr().out


def test_main_reports_a_mutable_ref_once_not_also_as_a_missing_comment(tmp_path, capsys):
    _write_workflow(tmp_path, "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert check.main([str(tmp_path)]) == 1
    assert capsys.readouterr().out.count("FAIL") == 1


# --- rule 15: no pull_request_target trigger ------------------------------------


_PRT_FORMS = {
    "scalar": "on: pull_request_target\n",
    "quoted scalar": "on: 'pull_request_target'\n",
    "double-quoted escape": 'on: "pull_request_\\u0074arget"\n',
    "tagged scalar": "on: !!str pull_request_target\n",
    "flow sequence": "on: [push, pull_request_target]\n",
    "flow mapping": "on: { pull_request_target: { types: [opened] } }\n",
    "flow mapping after a quoted hash": (
        'on: { workflow_dispatch: { inputs: { x: { description: "x # x" } } }, '
        "pull_request_target: {} }\n"
    ),
    "block sequence": "on:\n  - push\n  - pull_request_target\n",
    "block sequence at the key's indent": "on:\n- push\n- pull_request_target\n",
    "block mapping": "on:\n  push:\n  pull_request_target:\n    types: [opened]\n",
    "quoted key": '"on":\n  "pull_request_target":\n',
    "multi-line flow": "on: [\n  push,\n  pull_request_target,\n]\n",
}


def _forbidden(text: str) -> list[int]:
    return [n for n, reason in check.trigger_problems(text) if reason == check.PRT_FORBIDDEN]


def test_pull_request_target_is_found_in_every_form_of_on():
    for form, head in _PRT_FORMS.items():
        text = "name: x\n" + head + "jobs:\n  a:\n    runs-on: ubuntu-latest\n"
        assert _forbidden(text), form


def test_pull_request_target_is_found_under_an_indented_root():
    text = "  name: x\n  on: pull_request_target\n  jobs: {}\n"
    assert _forbidden(text) == [2]


def test_pull_request_target_reports_the_line_it_is_on():
    text = "name: x\non:\n  push:\n  pull_request_target:\njobs: {}\n"
    assert check.trigger_problems(text) == [(4, check.PRT_FORBIDDEN)]


def test_pull_request_target_outside_on_is_not_a_trigger():
    text = (
        "on: [push]\n"
        "# pull_request_target is forbidden here\n"
        "jobs:\n"
        "  a:\n"
        "    if: github.event_name != 'pull_request_target'\n"
        "    runs-on: ubuntu-latest\n"
    )
    assert check.trigger_problems(text) == []


def test_pull_request_target_inside_an_events_configuration_is_not_a_trigger():
    text = (
        "on:\n"
        "  push:\n"
        '    paths: ["docs/pull_request_target.md"]\n'
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      x: { description: pull_request_target }\n"
        "  pull_request: { branches: [pull_request_target] }\n"
        "jobs: {}\n"
    )
    assert check.trigger_problems(text) == []


def test_flow_quotes_close_after_an_escaped_backslash_and_open_only_at_a_token():
    text = 'on: { "a\\\\": {}, pull_request_target: {}, x: { d: don\'t } }\njobs: {}\n'
    assert check.trigger_problems(text) == [(1, check.PRT_FORBIDDEN)]


def test_a_comment_inside_on_is_not_a_trigger():
    text = "on:\n  # never add pull_request_target\n  push: # not pull_request_target\njobs: {}\n"
    assert check.trigger_problems(text) == []


def test_a_longer_event_name_is_not_pull_request_target():
    text = "on:\n  pull_request_target_x:\n  my_pull_request_target:\njobs: {}\n"
    assert check.trigger_problems(text) == []


def test_a_workflow_with_no_top_level_on_fails_closed():
    for text in ("jobs: {}\n", "{on: pull_request_target, jobs: {}}\n", "x:\n  on: push\n"):
        problems = check.trigger_problems(text)
        assert [reason for _, reason in problems] == [check.NO_ON], text


def test_an_event_name_the_check_cannot_read_fails_closed():
    for head in (
        'on: "pull_request_\\x74arget"\n',  # a YAML escape that JSON does not have
        "on: *events\n",
        "on:\n  ? pull_request_target\n",
        "on: [push, [pull_request_target]]\n",
    ):
        problems = check.trigger_problems(head + "jobs: {}\n")
        assert problems and all(r.startswith(check.UNREADABLE) for _, r in problems), head


def test_main_returns_1_on_a_pull_request_target_workflow(tmp_path, capsys):
    _write_workflow(
        tmp_path,
        "on:\n  pull_request_target:\njobs:\n  a:\n    steps:\n"
        "      - uses: actions/checkout@" + _SHA + " # v6\n",
        on=None,
    )
    assert check.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "ci.yml:2" in out and "pull_request_target" in out


# --- the real repository must pass the whole check ------------------------------


def test_this_repository_passes_the_check():
    """Enforcement that rides the already-required pytest gate, not just a CI step."""
    assert check.main([str(_REPO_ROOT)]) == 0


# --- alternate YAML forms: flow mappings are extracted, block scalars are rejected ---


def test_iter_uses_extracts_flow_mapping_entry():
    text = "    steps:\n      - { uses: actions/checkout@v4, with: { fetch-depth: 1 } }\n"
    assert check.iter_uses(text) == [(2, "actions/checkout@v4", None)]


def test_iter_uses_extracts_flow_mapping_inside_flow_sequence():
    text = "    steps: [{ uses: actions/checkout@" + "b" * 40 + " }]\n"
    assert check.iter_uses(text) == [(1, "actions/checkout@" + "b" * 40, None)]


def test_iter_uses_reports_block_scalar_uses_with_sentinel():
    text = "    steps:\n      - uses: >-\n          actions/checkout@v4\n      - run: echo hi\n"
    assert check.iter_uses(text) == [(2, check.BLOCK_SCALAR, None)]


def test_classify_block_scalar_sentinel_is_violation():
    assert check.classify(check.BLOCK_SCALAR) is not None


def test_main_returns_1_on_folded_scalar_uses(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "x.yml").write_text(
        "jobs:\n  a:\n    steps:\n      - uses: >-\n          actions/checkout@v4\n"
    )
    assert check.main([str(tmp_path)]) == 1


def test_main_returns_1_on_flow_mapping_uses(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "x.yml").write_text("jobs:\n  a:\n    steps:\n      - { uses: actions/checkout@v4 }\n")
    assert check.main([str(tmp_path)]) == 1


# --- this repository's checkouts never persist the job token ------------------


def test_this_repository_checkouts_do_not_persist_credentials():
    """Every actions/checkout step must set persist-credentials: false: the gate runs
    PR-controlled code (build hooks, tests) after checkout and needs no git auth."""
    workflows = sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    for path in workflows:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "uses: actions/checkout@" not in line:
                continue
            indent = len(line) - len(line.lstrip(" "))
            block = []
            for nxt in lines[i + 1 :]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                    break
                block.append(nxt.strip())
            assert "persist-credentials: false" in block, f"{path.name}:{i + 1}"


# --- the publish workflow's production job cannot be reached by a dispatch ----


_PUBLISH = _REPO_ROOT / ".github" / "workflows" / "publish.yml"

# The one safe condition for the production job. Asserted by equality, not by substring:
# substring checks pass on a NEGATED condition such as
# `!(github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v'))`, which permits
# exactly the tag-targeted dispatch this invariant exists to block.
_PYPI_CONDITION = "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"


def _job_lines(text: str, job: str) -> list[str]:
    """The lines of one top-level job, INDENTATION PRESERVED.

    Indentation is what distinguishes a job-level key from a step-level one, so it cannot be
    stripped here. Parsed by hand rather than with PyYAML: pyyaml is not a declared dependency
    of this project and is only transitively present, and the checks around this one read the
    workflow files as text for the same reason."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip() == f"  {job}:")
    block = []
    for nxt in lines[start + 1 :]:
        if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= 2:
            break
        block.append(nxt)
    return block


def _job_level_keys(lines: list[str], key: str) -> list[str]:
    """Only the job's own `key:` entries, at four spaces; a step's sit deeper."""
    return [
        line.strip()
        for line in lines
        if line.strip().startswith(f"{key}:") and (len(line) - len(line.lstrip(" "))) == 4
    ]


def test_the_publish_workflow_pypi_job_requires_a_push_event():
    """The `pypi` job must require the push event, not merely a `v*` ref.

    A workflow can be dispatched against any branch OR TAG, and `github.ref` is then the
    dispatched ref. Gating on the ref alone therefore let `gh workflow run publish.yml
    --ref v0.1.0` run the production job alongside the TestPyPI one and publish to real
    PyPI during a run the workflow calls a dry run. PyPI uploads are immutable, so there
    is no undo. Review caught it on PR #8 before any tag existed; this test is what stops
    it coming back, because nothing else does — the workflow never runs on a pull request,
    so CI cannot exercise the condition."""
    conditions = _job_level_keys(_job_lines(_PUBLISH.read_text(encoding="utf-8"), "pypi"), "if")
    assert conditions == [_PYPI_CONDITION], conditions


def test_the_publish_workflow_checks_the_tag_before_it_uploads():
    """The tag/version gate must run BEFORE the upload step, or it gates nothing.

    This assertion previously lived only in the publish-workflow plan, where it was prose
    that nobody executed and which went stale the moment the condition above changed. It
    belongs here, where it runs."""
    block = [line.strip() for line in _job_lines(_PUBLISH.read_text(encoding="utf-8"), "pypi")]
    gate = next(i for i, line in enumerate(block) if "GITHUB_REF_NAME" in line)
    upload = next(i for i, line in enumerate(block) if "gh-action-pypi-publish" in line)
    assert gate < upload, "the tag/version gate must precede the upload step"
