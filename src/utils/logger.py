"""Logging utilities for Repeater Griffin."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure root logging for Repeater Griffin.

    Args:
        level: Logging level (e.g., logging.INFO).
        log_file: Optional path to a log file. Parent directories are created
            automatically. If file creation fails, logging continues to console.

    Returns:
        The configured 'repeater_griffin' logger.
    """
    logger = logging.getLogger("repeater_griffin")
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Could not initialize log file %s: %s", log_file, exc)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'repeater_griffin' hierarchy."""
    if name.startswith("repeater_griffin"):
        return logging.getLogger(name)
    return logging.getLogger(f"repeater_griffin.{name}")

