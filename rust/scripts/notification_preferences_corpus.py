"""Actual notification preference DTO with the current system IANA database; no runtime imports."""
import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = dict(__name__=__name__, Literal=Literal, ZoneInfo=ZoneInfo, ZoneInfoNotFoundError=ZoneInfoNotFoundError, BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, field_validator=field_validator)
    path = "backend/app/dashboard/schemas.py"
    cls = next(n for n in ast.parse((ROOT / path).read_text()).body if isinstance(n, ast.ClassDef) and n.name == "NotificationPreferences")
    exec(compile(ast.Module(body=[cls], type_ignores=[]), path, "exec"), scope)
    inputs = [{}, dict(paused=True, in_app=False), dict(unexpected="rejected")]
    for key in ["in_app", "paused", "daily_digest", "automation_failures", "browser_push", "telegram", "whatsapp"]:
        inputs.extend({key: value} for value in [None, False, True, 0, 1, 0.0, "false", "yes", " false ", 2])
    for key in ["minimum_job_score", "minimum_startup_score", "quiet_start", "quiet_end"]:
        inputs.extend({key: value} for value in [None, False, True, -1, 0, "1.0", "1_0", 1.5, 23, 24, 100, 101])
    zones = sorted(available_timezones())
    inputs.extend(dict(timezone=key) for key in [None, True, 1, "", " UTC ", "/etc/passwd", "../UTC", "Asia//Kolkata", "Asia/../UTC", "./UTC", "Etc/UTC/", "Not/AZone", "localtime", "posixrules", "posix/UTC", "right/UTC", "Factory", "tzdata.zi", "x" * 101, *zones])
    cases = []
    for raw in inputs:
        try: result = dict(accepted=True, output=scope["NotificationPreferences"].model_validate(raw).model_dump(mode="json"))
        except (ValueError, OSError): result = dict(accepted=False)
        cases.append(dict(input=raw, **result))
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("notification_preferences_oracle_loaded_runtime")
    data = dict(system_zone_count=len(zones), cases=cases)
    target = ROOT / "rust/agent-runtime/tests/fixtures/notification-preferences-corpus.json"
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded: raise SystemExit("notification_preferences_corpus_drift")
    else: target.write_text(encoded)
    print(f"fictional_notification_preferences:{len(cases)} system_zones:{len(zones)}")


if __name__ == "__main__":
    main()
