"""Logging goes to stderr (and optionally a file), never stdout."""

from __future__ import annotations

import logging
import sys

from amicus import config, obs


def test_configure_attaches_stderr_and_optional_file(tmp_path, clean_env):
    log_file = tmp_path / "amicus.log"
    settings = config.settings({"AMICUS_LOG_LEVEL": "DEBUG", "AMICUS_LOG_FILE": str(log_file)})
    logger = obs.configure(settings, force=True)
    assert logger.level == logging.DEBUG
    streams = [getattr(h, "stream", None) for h in logger.handlers]
    assert sys.stderr in streams and sys.stdout not in streams
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    assert logging.getLogger("pontonier").propagate is False
    obs.get_logger("amicus.x").debug("hello")
    for h in logger.handlers:
        h.flush()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_configure_is_idempotent_and_survives_a_bad_file(tmp_path, clean_env):
    settings = config.settings({"AMICUS_LOG_FILE": str(tmp_path / "missing" / "x.log")})
    logger = obs.configure(settings, force=True)
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    again = obs.configure(config.settings({"AMICUS_LOG_LEVEL": "ERROR"}))
    assert again is logger and logger.level != logging.ERROR
