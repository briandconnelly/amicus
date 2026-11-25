"""ADR 0055: the collaborating-with-amicus skill, served over the MCP skills extension.

The served files must be exactly the plugin's copy, so every expectation here is derived
from `skills/` independently of `amicus.skill`'s own selector."""

from __future__ import annotations

from pathlib import Path

import pytest

from amicus.skill import SKILL_NAME, SkillUnavailable, build_skill, served_files

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SKILL = REPO_ROOT / "skills" / SKILL_NAME
_BACKUP_SUFFIXES = ("~", ".swp", ".bak", ".orig")


def expected_files(root: Path) -> set[str]:
    """The served set, derived naively from the filesystem rather than from the selector."""
    out = {"SKILL.md"}
    for path in (root / "references").rglob("*"):
        rel = path.relative_to(root)
        if (
            path.is_file()
            and not any(part.startswith(".") for part in rel.parts)
            and not rel.name.endswith(_BACKUP_SUFFIXES)
        ):
            out.add(rel.as_posix())
    return out


def _fake_skill(root: Path) -> Path:
    (root / "references" / "sub").mkdir(parents=True)
    (root / "SKILL.md").write_bytes((REPO_SKILL / "SKILL.md").read_bytes())
    (root / "references" / "a.md").write_text("a")
    (root / "references" / "sub" / "b.md").write_text("b")
    return root


def test_served_set_is_exactly_skill_md_and_references():
    assert set(served_files(REPO_SKILL)) == expected_files(REPO_SKILL)


def test_served_bytes_match_the_plugin_copy():
    for path, data in served_files(REPO_SKILL).items():
        assert data == (REPO_SKILL / path).read_bytes(), path


def test_selection_skips_hidden_backups_and_tests_and_recurses(tmp_path):
    root = _fake_skill(tmp_path)
    (root / "references" / ".DS_Store").write_bytes(b"x")
    (root / "references" / "a.md.swp").write_bytes(b"x")
    (root / "references" / "a.md~").write_bytes(b"x")
    (root / "references" / ".hidden").mkdir()
    (root / "references" / ".hidden" / "c.md").write_text("c")
    (root / "tests").mkdir()
    (root / "tests" / "x.md").write_text("x")
    assert set(served_files(root)) == {"SKILL.md", "references/a.md", "references/sub/b.md"}


def test_a_symlink_is_rejected(tmp_path):
    root = _fake_skill(tmp_path)
    (root / "references" / "link.md").symlink_to(root / "references" / "a.md")
    with pytest.raises(SkillUnavailable, match=r"link\.md"):
        served_files(root)


def test_missing_references_is_rejected(tmp_path):
    (tmp_path / "SKILL.md").write_bytes((REPO_SKILL / "SKILL.md").read_bytes())
    with pytest.raises(SkillUnavailable, match="references"):
        served_files(tmp_path)


def test_missing_skill_md_is_rejected(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "a.md").write_text("a")
    with pytest.raises(SkillUnavailable, match=r"SKILL\.md"):
        served_files(tmp_path)


def test_served_skill_fits_claude_code_limits():
    files = served_files(REPO_SKILL)
    assert max(map(len, files.values())) <= 102_400
    assert sum(map(len, files.values())) <= 409_600


def test_checkout_fallback_works_from_a_foreign_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill = build_skill()
    assert skill.name == SKILL_NAME
    expected = {p: (REPO_SKILL / p).read_bytes() for p in expected_files(REPO_SKILL)}
    assert dict(skill.files) == expected


def test_build_skill_raises_when_no_root(monkeypatch):
    import amicus.skill

    monkeypatch.setattr(amicus.skill, "skill_root", lambda: None)
    with pytest.raises(SkillUnavailable):
        build_skill()


def test_invalid_frontmatter_is_unavailable(tmp_path, monkeypatch):
    import amicus.skill

    root = _fake_skill(tmp_path)
    (root / "SKILL.md").write_text("no frontmatter here\n")
    monkeypatch.setattr(amicus.skill, "skill_root", lambda: root)
    with pytest.raises(SkillUnavailable, match="not a valid Agent Skill"):
        build_skill()
