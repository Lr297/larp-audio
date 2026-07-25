"""Smoke tests for the central standard-library logger."""

from __future__ import annotations

import logging

from larp_audio_mvp.core.logging import LOGGER_NAME, configure_logging, get_logger


def test_logging_configuration_is_idempotent() -> None:
    first = configure_logging(level=logging.WARNING)
    second = configure_logging(level=logging.INFO)

    assert first is second
    assert first.name == LOGGER_NAME
    assert first.level == logging.INFO
    assert len(first.handlers) == 1
    assert get_logger("smoke").name == f"{LOGGER_NAME}.smoke"
