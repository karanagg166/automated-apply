"""Shared v2 configuration: private env file and dedicated Brave paths."""

from __future__ import annotations

import os
from pathlib import Path

OWNER_SUPPORT_DIR = Path.home() / "Library/Application Support/Automated Apply"
DEFAULT_ENV_FILE = OWNER_SUPPORT_DIR / "phase1.private.env"
ENV_FILE_VARIABLE = "AUTOMATED_APPLY_ENV_FILE"


def env_file(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """Explicit path, then $AUTOMATED_APPLY_ENV_FILE, then the private phase1 env."""
    for candidate in (explicit, os.environ.get(ENV_FILE_VARIABLE), DEFAULT_ENV_FILE):
        if candidate and Path(candidate).expanduser().is_file():
            return Path(candidate).expanduser()
    return None


def load_settings(explicit: str | os.PathLike[str] | None = None):
    """Load settings from the private env file; never the repository .env."""
    from backend.app.core.config import Settings, get_settings

    path = env_file(explicit)
    # pydantic-settings accepts _env_file at runtime; its stub does not declare it.
    return Settings(_env_file=str(path)) if path else get_settings()  # type: ignore[call-arg]
