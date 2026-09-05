"""settings(): profile, clamps, tasks gate, and the env report it carries."""

from __future__ import annotations

from pathlib import Path

from amicus import config


def test_defaults(clean_env):
    s = config.settings({})
    assert s.enabled_backends == ("codex", "kimi", "claude")
    assert s.timeout_seconds == 300
    assert s.max_input_bytes == 200_000
    assert (s.job_ttl_seconds, s.job_max_seconds, s.job_max_count) == (86_400, 1_800, 50)
    assert s.state_dir == Path.home() / ".cache" / "amicus" / "jobs"
    assert s.log_level == "WARNING" and s.log_file is None
    assert s.tasks_enabled is False and s.tasks_backend_url == "memory://"
    assert s.host_name is None and s.allow_cwd_workspace is False
    assert s.env_warnings == () and s.config_errors == () and s.placeholders == ()


def test_profile_parsing_keeps_order_and_drops_unknown_with_an_error(clean_env):
    s = config.settings({"AMICUS_BACKENDS": "claude, codex"})
    assert s.enabled_backends == ("claude", "codex")
    s = config.settings({"AMICUS_BACKENDS": "codex,gemini"})
    assert s.enabled_backends == ("codex",)
    assert any("gemini" in e for e in s.config_errors)
    s = config.settings({"AMICUS_BACKENDS": ""})
    assert s.enabled_backends == ("codex", "kimi", "claude")


def test_clamps_and_bad_ints_warn(clean_env):
    s = config.settings({"AMICUS_TIMEOUT_SECONDS": "5", "AMICUS_JOB_MAX_SECONDS": "99999"})
    assert s.timeout_seconds == 10 and s.job_max_seconds == 7_200
    s = config.settings({"AMICUS_TIMEOUT_SECONDS": "lots"})
    assert s.timeout_seconds == 300
    assert any("AMICUS_TIMEOUT_SECONDS" in w for w in s.env_warnings)


def test_legacy_shim_and_conflict_surface_in_settings(clean_env):
    s = config.settings({"CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "120"})
    assert s.timeout_seconds == 120
    assert any("CODEX_IN_CLAUDE_TIMEOUT_SECONDS" in w for w in s.env_warnings)
    s = config.settings({"AMICUS_TIMEOUT_SECONDS": "120", "MOONBRIDGE_TIMEOUT_SECONDS": "60"})
    assert s.timeout_seconds == 120  # the amicus value is used; the conflict is reported
    assert any("MOONBRIDGE_TIMEOUT_SECONDS" in e for e in s.config_errors)


def test_placeholder_is_reported_and_treated_as_unset(clean_env):
    s = config.settings({"AMICUS_LOG_FILE": "${LOG}", "AMICUS_HOST_NAME": "Codex"})
    assert s.log_file is None and s.placeholders == ("AMICUS_LOG_FILE",)
    assert s.host_name == "Codex"


def test_conflict_fallback_never_leaks_a_placeholder(clean_env):
    s = config.settings(
        {
            "AMICUS_LOG_FILE": "${LOG_FILE}",
            "CODEX_IN_CLAUDE_LOG_FILE": "/a.log",
            "MOONBRIDGE_LOG_FILE": "/b.log",
        }
    )
    assert s.log_file is None
    assert s.placeholders == ("AMICUS_LOG_FILE",)
    assert any("LOG_FILE" in e for e in s.config_errors)


def test_state_dir_override(clean_env):
    s = config.settings({"AMICUS_STATE_DIR": "~/x"})
    assert s.state_dir == Path("~/x").expanduser()


def test_flags(clean_env):
    s = config.settings(
        {
            "AMICUS_TASKS": "1",
            "AMICUS_ALLOW_CWD_WORKSPACE": "true",
            "AMICUS_TASKS_BACKEND_URL": "redis://x/0",
            "AMICUS_LOG_LEVEL": "debug",
        }
    )
    assert s.tasks_enabled and s.allow_cwd_workspace
    assert s.tasks_backend_url == "redis://x/0" and s.log_level == "DEBUG"
    s = config.settings({"AMICUS_TASKS": "no", "AMICUS_LOG_LEVEL": "loud"})
    assert not s.tasks_enabled and s.log_level == "WARNING"


def test_settings_reads_the_process_environment_by_default(clean_env):
    clean_env.setenv("AMICUS_TIMEOUT_SECONDS", "42")
    assert config.settings().timeout_seconds == 42


def test_every_declared_var_has_a_description_and_is_documented():
    for var in config.GLOBAL_ENV.vars:
        assert var.description
        assert var.name.startswith("AMICUS_")
