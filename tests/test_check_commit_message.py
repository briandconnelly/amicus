"""The commit-msg hook accepts this repo's scopes and rejects the rest."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_commit_message.py"
_spec = importlib.util.spec_from_file_location("check_commit_message", _SCRIPT)
assert _spec is not None and _spec.loader is not None
ccm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccm)


def test_valid_scoped_header_passes():
    assert ccm.validate("feat(schemas): add the parameter matrix") is None


def test_unknown_scope_fails():
    assert ccm.validate("feat(nope): x") == "scope 'nope' is not allowed"


def test_capitalized_subject_fails():
    assert ccm.validate("fix: Capitalized") == "subject must not start with a capital letter"


def test_git_generated_forms_are_skipped():
    assert ccm.validate('Revert "feat: x"') is None
    assert ccm.validate("Merge branch 'main'") is None


def test_main_reports_a_file(tmp_path, capsys):
    msg = tmp_path / "MSG"
    msg.write_text("chore(packaging): bump\n", encoding="utf-8")
    assert ccm.main([str(msg)]) == 0
    msg.write_text("bad message\n", encoding="utf-8")
    assert ccm.main([str(msg)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert ccm.main([]) == 1
