"""Export the existing FastAPI contract without loading local account configuration."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
from backend.app.core.config import Settings, configure_operator

configure_operator(Settings(_env_file=None))
from backend.app.main import app

output = Path("reports/phase7-openapi.json")
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(app.openapi()))
