"""ADR 0055: the collaborating-with-amicus skill, served over the MCP skills extension.

The served files must be exactly the plugin's copy, so every expectation here is derived
from `skills/` independently of `amicus.skill`'s own selector."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.skills.client import SkillsClientExtension
from tests.support.fingerprint_pins import load_pins

from amicus import config, server, surface
from amicus.registry import BackendRegistry
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


# --- Task 3: AMICUS_SERVE_SKILL, cli() and --no-serve-skill ---------------------------------


def test_serve_skill_defaults_off(clean_env):
    assert config.settings().serve_skill is False


def test_serve_skill_reads_the_env(clean_env):
    clean_env.setenv("AMICUS_SERVE_SKILL", "1")
    assert config.settings().serve_skill is True


def _capture_settings(monkeypatch) -> list:
    seen: list = []

    def fake_create_app(settings):
        seen.append(settings)
        return SimpleNamespace(run=lambda: None)

    monkeypatch.setattr(server, "create_app", fake_create_app)
    return seen


def test_the_flag_outranks_the_env(clean_env, restored_signal_handlers):
    clean_env.setenv("AMICUS_SERVE_SKILL", "1")
    seen = _capture_settings(clean_env)
    server.main(["--no-serve-skill"])
    assert seen[0].serve_skill is False


def test_without_the_flag_the_env_stands(clean_env, restored_signal_handlers):
    clean_env.setenv("AMICUS_SERVE_SKILL", "1")
    seen = _capture_settings(clean_env)
    server.main([])
    assert seen[0].serve_skill is True


def test_unknown_argv_is_ignored_with_a_warning(clean_env, restored_signal_handlers, capsys):
    seen = _capture_settings(clean_env)
    server.main(["--bogus", "--api-key=SENTINEL-SECRET"])
    assert len(seen) == 1
    err = capsys.readouterr().err
    assert "ignoring 2 unrecognized arguments" in err
    assert "SENTINEL" not in err
    assert "--bogus" not in err


def test_cli_passes_sys_argv(clean_env, restored_signal_handlers):
    clean_env.setenv("AMICUS_SERVE_SKILL", "1")
    clean_env.setattr(sys, "argv", ["amicus-mcp", "--no-serve-skill"])
    seen = _capture_settings(clean_env)
    server.cli()
    assert seen[0].serve_skill is False


# --- Task 4: serving from create_app --------------------------------------------------------

SKILLS_EXTENSION = "io.modelcontextprotocol/skills"


def _app(serve: bool):
    env = {"AMICUS_SERVE_SKILL": "1"} if serve else {}
    return server.create_app(config.settings(env), BackendRegistry({}, {}))


def _skills_client(app) -> Client:
    return Client(app, extensions=[SkillsClientExtension()])


def _extensions(client: Client) -> dict:
    caps = client.server_capabilities
    return dict(caps.extensions or {}) if caps else {}


async def test_enabled_server_advertises_and_serves_the_whole_skill():
    async with _skills_client(_app(serve=True)) as c:
        assert c.protocol_version == "2026-07-28"
        assert SKILLS_EXTENSION in _extensions(c)
        (entry,) = await c.list_skills()
        assert entry.frontmatter.name == SKILL_NAME
        served = await c.read_skill(str(entry.uri))
    assert dict(served.files) == {
        p: (REPO_SKILL / p).read_bytes() for p in expected_files(REPO_SKILL)
    }


async def test_enabled_skill_resource_set_is_pinned():
    async with _skills_client(_app(serve=True)) as c:
        uris = {str(r.uri) for r in await c.list_resources() if str(r.uri).startswith("skill://")}
    base = f"skill://{SKILL_NAME}/"
    assert uris == {base + p for p in expected_files(REPO_SKILL)} | {base + "_manifest"}


async def test_default_surface_has_no_skill_trace():
    app = _app(serve=False)
    async with _skills_client(app) as c:
        assert SKILLS_EXTENSION not in _extensions(c)
        resources = await c.list_resources()
    assert not any(str(r.uri).startswith("skill://") for r in resources)
    assert await surface.surface_digest(app) == load_pins()["surface_digest"]["all"]


async def test_enabled_surface_digest_differs_from_the_default():
    assert await surface.surface_digest(_app(serve=True)) != await surface.surface_digest(
        _app(serve=False)
    )


def test_unavailable_skill_is_one_config_error(monkeypatch):
    import amicus.skill

    def unavailable():
        raise SkillUnavailable("the skill's files are not installed")

    monkeypatch.setattr(amicus.skill, "build_skill", unavailable)
    app = _app(serve=True)
    errors = [e for e in server.state_of(app).config_errors if "AMICUS_SERVE_SKILL" in e]
    assert errors == [
        "AMICUS_SERVE_SKILL=1 but the skill could not be served: "
        "the skill's files are not installed"
    ]


async def test_unavailable_skill_advertises_no_extension(monkeypatch):
    import amicus.skill

    def unavailable():
        raise SkillUnavailable("x")

    monkeypatch.setattr(amicus.skill, "build_skill", unavailable)
    async with _skills_client(_app(serve=True)) as c:
        assert SKILLS_EXTENSION not in _extensions(c)


def test_a_symlinked_references_dir_is_rejected(tmp_path):
    real = _fake_skill(tmp_path / "real")
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_bytes((real / "SKILL.md").read_bytes())
    (root / "references").symlink_to(real / "references")
    with pytest.raises(SkillUnavailable, match=r"references is a symlink"):
        served_files(root)


def test_a_symlinked_skill_md_is_rejected(tmp_path):
    real = _fake_skill(tmp_path / "real")
    root = tmp_path / "skill"
    (root / "references").mkdir(parents=True)
    (root / "references" / "a.md").write_text("a")
    (root / "SKILL.md").symlink_to(real / "SKILL.md")
    with pytest.raises(SkillUnavailable, match=r"SKILL\.md is a symlink"):
        served_files(root)


def test_a_symlinked_skill_root_is_rejected(tmp_path):
    real = _fake_skill(tmp_path / "real")
    root = tmp_path / "skill"
    root.symlink_to(real)
    with pytest.raises(SkillUnavailable, match=r"skill root is a symlink"):
        served_files(root)


@pytest.mark.parametrize("token", ["--no-serve", "--no-serve-skill=false", "--no-serve-skil"])
def test_only_the_exact_flag_disables_serving(clean_env, restored_signal_handlers, capsys, token):
    clean_env.setenv("AMICUS_SERVE_SKILL", "1")
    seen = _capture_settings(clean_env)
    server.main([token])
    assert seen[0].serve_skill is True
    err = capsys.readouterr().err
    assert "ignoring 1 unrecognized argument" in err
    assert token not in err
