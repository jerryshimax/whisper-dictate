"""Logging configuration with RotatingFileHandler."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys

from whisper_dictate.config import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT, _ensure_private_dir, _set_private


def setup_logging() -> logging.Logger:
    """Configure root 'whisper_dictate' logger with rotating file + stderr handlers."""
    _ensure_private_dir(LOG_FILE)

    root_logger = logging.getLogger("whisper_dictate")
    root_logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated calls
    if root_logger.handlers:
        return root_logger

    fmt = logging.Formatter(
        "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (rotating)
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

    # Stderr handler
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    root_logger.addHandler(sh)

    _set_private(LOG_FILE)

    return root_logger
