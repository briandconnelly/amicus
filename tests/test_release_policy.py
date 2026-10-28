"""`scripts/release.py policy`: read back rule 21's ruleset and the `pypi` environment (#389).

`gh api` is stubbed with records shaped like the live responses: the ruleset as the maintainer's
token sees it (with `bypass_actors`) and as the agent App token sees it (without the key). The
positive control runs first, so a broken stub cannot make a refusal pass vacuously.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")

BASE = "repos/briandconnelly/amicus"
RULESET_ID = 22594956

SUMMARIES = [
    {"id": 23704977, "name": "Copilot review for default branch", "target": "branch"},
    {"id": RULESET_ID, "name": "release tags", "target": "tag"},
]

# As the maintainer's token reads `rulesets/<id>`.
RULESET = {
    "id": RULESET_ID,
    "name": "release tags",
    "target": "tag",
    "enforcement": "active",
    "conditions": {"ref_name": {"exclude": [], "include": ["refs/tags/v*"]}},
    "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
    "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
    "current_user_can_bypass": "always",
}

ENVIRONMENT = {
    "name": "pypi",
    "protection_rules": [
        {"type": "branch_policy"},
        {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"id": 1}}]},
    ],
    "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
}

POLICIES = {"total_count": 1, "branch_policies": [{"id": 1, "name": "v*", "type": "tag"}]}


class FakeGh:
    """Answers `gh api PATH` from a table; any other command fails the test."""

    def __init__(self, ruleset=RULESET, environment=ENVIRONMENT, policies=POLICIES):
        self.responses = {
            f"{BASE}/rulesets?per_page=100": [SUMMARIES],
            f"{BASE}/rulesets/{RULESET_ID}": ruleset,
            f"{BASE}/environments/pypi": environment,
            f"{BASE}/environments/pypi/deployment-branch-policies?per_page=100": policies,
        }
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        assert cmd[:2] == ["gh", "api"], cmd
        path = cmd[-1]
        if path not in self.responses:
            raise AssertionError(f"unexpected gh api call: {cmd}")
        if path.startswith(f"{BASE}/rulesets?"):
            assert cmd[2:4] == ["--paginate", "--slurp"], cmd
        answer = self.responses[path]
        if isinstance(answer, subprocess.CompletedProcess):
            return answer
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(answer), stderr="")


def _run(capsys, gh) -> tuple[int, str, str]:
    ctx = release.Context(run=gh)
    code = release.main(["policy"], context=ctx)
    out = capsys.readouterr()
    return code, out.out, out.err


def _ruleset(**changes):
    ruleset = copy.deepcopy(RULESET)
    ruleset.update(changes)
    return ruleset


def test_maintainer_view_of_the_live_configuration_holds(capsys):
    code, out, err = _run(capsys, FakeGh())
    assert code == 0, err
    assert "read-back holds" in out
    assert "RepositoryRole 5" in out
    assert "current_user_can_bypass is 'always'" in out
    assert "describes whoever's token" in out


def test_absent_bypass_actors_is_unknown_not_empty(capsys):
    """The agent App token's view: no `bypass_actors` key at all, and `never` for itself."""
    agent_view = _ruleset(current_user_can_bypass="never")
    del agent_view["bypass_actors"]
    code, out, err = _run(capsys, FakeGh(ruleset=agent_view))
    assert code == 1
    assert "UNKNOWN" in err and "no `bypass_actors` key" in err
    assert "read-back holds" not in out
    assert "empty bypass list" not in err
    assert "current_user_can_bypass is 'never'" in out


def test_integration_bypass_actor_fails(capsys):
    actors = [*RULESET["bypass_actors"], {"actor_id": 99, "actor_type": "Integration"}]
    code, _, err = _run(capsys, FakeGh(ruleset=_ruleset(bypass_actors=actors)))
    assert code == 1
    assert "lets an Integration bypass it (actor_id 99)" in err


def test_integration_bypass_on_a_second_covering_ruleset_fails(capsys):
    gh = FakeGh()
    extra = _ruleset(
        id=7, name="extra", bypass_actors=[{"actor_id": 3, "actor_type": "Integration"}]
    )
    gh.responses[f"{BASE}/rulesets?per_page=100"] = [SUMMARIES, [{"id": 7, "target": "tag"}]]
    gh.responses[f"{BASE}/rulesets/7"] = extra
    code, _, err = _run(capsys, gh)
    assert code == 1
    assert "ruleset 'extra' (7) lets an Integration bypass it" in err


def test_empty_bypass_list_blocks_the_release(capsys):
    code, _, err = _run(capsys, FakeGh(ruleset=_ruleset(bypass_actors=[])))
    assert code == 1
    assert "empty bypass list" in err


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"enforcement": "evaluate"}, "enforcement is 'evaluate'"),
        ({"rules": [{"type": "update"}, {"type": "deletion"}]}, "does not restrict creation"),
        (
            {
                "conditions": {
                    "ref_name": {"include": ["refs/tags/v*"], "exclude": ["refs/tags/v9*"]}
                }
            },
            "excludes",
        ),
    ],
)
def test_a_weakened_ruleset_does_not_qualify(capsys, changes, expected):
    code, out, err = _run(capsys, FakeGh(ruleset=_ruleset(**changes)))
    assert code == 1
    assert expected in out
    assert "no active ruleset covering refs/tags/v*" in err


def test_no_ruleset_targets_v_tags(capsys):
    ruleset = _ruleset(conditions={"ref_name": {"include": ["refs/tags/release-*"], "exclude": []}})
    code, _, err = _run(capsys, FakeGh(ruleset=ruleset))
    assert code == 1
    assert "no ruleset targets refs/tags/v*" in err


def test_branch_typed_v_policy_fails(capsys):
    policies = {"total_count": 1, "branch_policies": [{"name": "v*", "type": "branch"}]}
    code, _, err = _run(capsys, FakeGh(policies=policies))
    assert code == 1
    assert "no deployment policy typed 'tag' named 'v*'" in err
    assert "also allows branch 'v*'" in err


def test_an_extra_deployment_policy_fails(capsys):
    policies = {
        "total_count": 2,
        "branch_policies": [{"name": "v*", "type": "tag"}, {"name": "main", "type": "branch"}],
    }
    code, _, err = _run(capsys, FakeGh(policies=policies))
    assert code == 1
    assert "also allows branch 'main'" in err


def test_missing_reviewers_fails(capsys):
    environment = copy.deepcopy(ENVIRONMENT)
    environment["protection_rules"] = [{"type": "branch_policy"}]
    code, _, err = _run(capsys, FakeGh(environment=environment))
    assert code == 1
    assert "no required_reviewers rule" in err


@pytest.mark.parametrize(
    "scope", [None, {"protected_branches": True, "custom_branch_policies": False}]
)
def test_environment_not_using_custom_policies_fails(capsys, scope):
    environment = copy.deepcopy(ENVIRONMENT)
    environment["deployment_branch_policy"] = scope
    code, _, err = _run(capsys, FakeGh(environment=environment))
    assert code == 1
    assert "must use custom policies" in err


def test_truncated_policy_list_is_unknown(capsys):
    policies = {"total_count": 2, "branch_policies": [{"name": "v*", "type": "tag"}]}
    code, _, err = _run(capsys, FakeGh(policies=policies))
    assert code == 1
    assert "UNKNOWN: the deployment-branch-policies response lists 1 of 2" in err


def test_a_failed_gh_call_is_unknown_not_a_pass(capsys):
    gh = FakeGh()
    path = f"{BASE}/environments/pypi"
    gh.responses[path] = subprocess.CompletedProcess(
        ["gh"], 1, stdout="", stderr="gh: Not Found (HTTP 404)"
    )
    code, _, err = _run(capsys, gh)
    assert code == 1
    assert "UNKNOWN: could not read the 'pypi' environment" in err
    assert "HTTP 404" in err


def test_gh_missing_is_unknown(capsys):
    def no_gh(cmd, *args, **kwargs):
        raise FileNotFoundError("gh")

    code, _, err = _run(capsys, no_gh)
    assert code == 1
    assert "UNKNOWN: could not read the rulesets" in err
    assert "UNKNOWN: could not read the 'pypi' environment" in err
