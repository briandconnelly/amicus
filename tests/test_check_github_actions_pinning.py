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
    assert found == [(2, "actions/checkout@" + "a" * 40)]


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
    assert check.iter_uses(text) == [(5, "actions/checkout@" + "a" * 40)]


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
    assert check.iter_uses(text) == [(4, "actions/checkout@" + "a" * 40)]


def test_iter_uses_resumes_after_block_dedents():
    text = (
        "      - run: |\n          uses: ignored\n      - uses: actions/setup-uv@" + "b" * 40 + "\n"
    )
    assert check.iter_uses(text) == [(3, "actions/setup-uv@" + "b" * 40)]


def test_iter_uses_strips_surrounding_quotes():
    text = '      - uses: "actions/checkout@' + "a" * 40 + '"\n'
    assert check.iter_uses(text) == [(1, "actions/checkout@" + "a" * 40)]


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


def _write_workflow(root: Path, body: str) -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text(body)


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


# --- the real repository must stay fully pinned ------------------------------


def test_this_repository_is_fully_pinned():
    """Enforcement that rides the already-required pytest gate, not just a CI step."""
    assert check.main([str(_REPO_ROOT)]) == 0


# --- alternate YAML forms: flow mappings are extracted, block scalars are rejected ---


def test_iter_uses_extracts_flow_mapping_entry():
    text = "    steps:\n      - { uses: actions/checkout@v4, with: { fetch-depth: 1 } }\n"
    assert check.iter_uses(text) == [(2, "actions/checkout@v4")]


def test_iter_uses_extracts_flow_mapping_inside_flow_sequence():
    text = "    steps: [{ uses: actions/checkout@" + "b" * 40 + " }]\n"
    assert check.iter_uses(text) == [(1, "actions/checkout@" + "b" * 40)]


def test_iter_uses_reports_block_scalar_uses_with_sentinel():
    text = "    steps:\n      - uses: >-\n          actions/checkout@v4\n      - run: echo hi\n"
    assert check.iter_uses(text) == [(2, check.BLOCK_SCALAR)]


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


def _job_block(text: str, job: str) -> list[str]:
    """The stripped lines of one top-level job, by indentation.

    Parsed by hand rather than with PyYAML: pyyaml is not a declared dependency of this
    project and is only transitively present, and the checks around this one read the
    workflow files as text for the same reason."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip() == f"  {job}:")
    block = []
    for nxt in lines[start + 1 :]:
        if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= 2:
            break
        block.append(nxt.strip())
    return block


def test_the_publish_workflow_pypi_job_requires_a_push_event():
    """The `pypi` job must require the push event, not merely a `v*` ref.

    A workflow can be dispatched against any branch OR TAG, and `github.ref` is then the
    dispatched ref. Gating on the ref alone therefore let `gh workflow run publish.yml
    --ref v0.1.0` run the production job alongside the TestPyPI one and publish to real
    PyPI during a run the workflow calls a dry run. PyPI uploads are immutable, so there
    is no undo. Review caught it on PR #8 before any tag existed; this test is what stops
    it coming back, because nothing else does — the workflow never runs on a pull request,
    so CI cannot exercise the condition."""
    text = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    conditions = [line for line in _job_block(text, "pypi") if line.startswith("if:")]
    assert len(conditions) == 1, f"expected one `if:` on the pypi job, found {conditions}"
    condition = conditions[0]
    assert "github.event_name == 'push'" in condition, condition
    assert "startsWith(github.ref, 'refs/tags/v')" in condition, condition
    assert "&&" in condition and "||" not in condition, condition


def test_the_publish_workflow_checks_the_tag_before_it_uploads():
    """The tag/version gate must run BEFORE the upload step, or it gates nothing.

    This assertion previously lived only in the publish-workflow plan, where it was prose
    that nobody executed and which went stale the moment the condition above changed. It
    belongs here, where it runs."""
    block = _job_block(
        text=(_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8"),
        job="pypi",
    )
    gate = next(i for i, line in enumerate(block) if "GITHUB_REF_NAME" in line)
    upload = next(i for i, line in enumerate(block) if "gh-action-pypi-publish" in line)
    assert gate < upload, "the tag/version gate must precede the upload step"
