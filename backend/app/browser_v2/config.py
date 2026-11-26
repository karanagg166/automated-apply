"""Shared v2 configuration: the project env file and dedicated Brave paths.

Owner rule (2026-11-26): every env value lives in the project directory - the single
`<repo>/.env` (gitignored). Override with an explicit path or $AUTOMATED_APPLY_ENV_FILE.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
FRONTEND_ENV_FILE = REPO_ROOT / "frontend" / ".env.local"
ENV_FILE_VARIABLE = "AUTOMATED_APPLY_ENV_FILE"
REPO_FILES_SWITCH = "AUTOMATED_APPLY_ENV_REPO_FILES"  # "0" in tests: never read the owner's real .env


def _repo_env_allowed() -> bool:
    return (os.environ.get(REPO_FILES_SWITCH) or "").strip().lower() not in {"0", "false", "no", "off"}


def env_file(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """Explicit path, then $AUTOMATED_APPLY_ENV_FILE, then <repo>/.env."""
    candidates = [explicit, os.environ.get(ENV_FILE_VARIABLE)]
    if _repo_env_allowed():
        candidates.append(DEFAULT_ENV_FILE)
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return Path(candidate).expanduser()
    return None


def load_settings(explicit: str | os.PathLike[str] | None = None):
    """Settings from the project env file (process env still wins)."""
    from backend.app.core.config import Settings, get_settings

    path = env_file(explicit)
    # pydantic-settings accepts _env_file at runtime; its stub does not declare it.
    return Settings(_env_file=str(path)) if path else get_settings()  # type: ignore[call-arg]
