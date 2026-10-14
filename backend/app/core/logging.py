"""Structured logging configuration for Job Pulse Agent."""

import logging
import sys
from typing import Any
from backend.app.core.config import get_settings


def setup_logging() -> logging.Logger:
    """Configure standard application logging."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logger = logging.getLogger("job_pulse_agent")
    logger.setLevel(log_level)

    # Avoid adding duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logging()
