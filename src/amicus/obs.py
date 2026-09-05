"""Diagnostic logging: stderr (plus an optional file), never stdout."""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings

ROOT_LOGGER_NAME = "amicus"
LIBRARY_LOGGER_NAME = "pontonier"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def configure(settings: Settings, *, force: bool = False) -> logging.Logger:
    """Configure the amicus and pontonier loggers once (idempotent unless ``force``)."""
    global _configured  # noqa: PLW0603
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if _configured and not force:
        return logger
    formatter = logging.Formatter(_LOG_FORMAT)
    for name in (ROOT_LOGGER_NAME, LIBRARY_LOGGER_NAME):
        target = logging.getLogger(name)
        target.setLevel(settings.log_level)
        target.propagate = False
        for handler in target.handlers[:]:
            target.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        target.addHandler(stderr_handler)
        if settings.log_file:
            try:
                file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
                file_handler.setFormatter(formatter)
                target.addHandler(file_handler)
            except OSError:
                target.warning(
                    "could not open AMICUS_LOG_FILE %r; logging to stderr only", settings.log_file
                )
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
