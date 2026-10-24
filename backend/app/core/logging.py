"""Structured logging configuration for Job Pulse Agent."""

import logging
import sys

from backend.app.core.config import get_settings


def setup_logging() -> logging.Logger:
    """Configure standard application logging."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logger = logging.getLogger("job_pulse_agent")
    logger.setLevel(log_level)

    # Avoid adding duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logging()


class SecretRedactionFilter(logging.Filter):
    """Defense in depth for application logs, including unexpected exception messages."""

    def filter(self, record):
        settings = get_settings()
        sensitive = [settings.DATABASE_URL, settings.SECRET_KEY]
        from sqlalchemy.engine import make_url
        try:
            sensitive.append(make_url(settings.DATABASE_URL).password)
        except Exception:
            sensitive.append(None)
        for name in type(settings).model_fields:
            if any(part in name for part in ("API_KEY", "API_TOKEN", "CLIENT_SECRET", "REFRESH_TOKEN", "BOT_TOKEN")):
                value = getattr(settings, name)
                sensitive.append(value.get_secret_value() if hasattr(value, "get_secret_value") else value)
        sensitive.extend(key.get_secret_value() for key in settings.OAUTH_ENCRYPTION_KEYS.values())
        message = record.getMessage()
        for value in sorted((v for v in sensitive if isinstance(v, str) and len(v) >= 4), key=len, reverse=True):
            message = message.replace(value, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


if not any(isinstance(item, SecretRedactionFilter) for item in logger.filters):
    logger.addFilter(SecretRedactionFilter())
