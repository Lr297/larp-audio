"""Central standard-library logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "larp_audio_mvp"
DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(
    *,
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> logging.Logger:
    """Configure and return the project logger without third-party handlers."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(DEFAULT_FORMAT)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.handlers.extend(handlers)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger inside the project namespace."""

    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")

