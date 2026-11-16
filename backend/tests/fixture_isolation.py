"""Explicit final-runner plugin, loaded before conftest imports application settings."""

import os

if os.environ.get("AUTOMATED_APPLY_FIXTURE_ISOLATED") != "1":
    raise RuntimeError("explicit_fixture_isolation_required")

from backend.app.core.config import Settings

# No repository environment files are read by implicit Settings() in this process.
# Individual tests can still explicitly supply their own fictional _env_file.
Settings.model_config = {**Settings.model_config, "env_file": None}
