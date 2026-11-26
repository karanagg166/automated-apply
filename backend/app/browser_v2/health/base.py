"""Health-check status constants, probe types and the Check record."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from backend.app.operations.v2_schema import TABLES

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
API_HEALTH_URL = "http://127.0.0.1:8000/health"
DASHBOARD_URL = "http://127.0.0.1:3000/"
V2_LABELS = ("com.automated-apply.api-v2", "com.automated-apply.worker-v2", "com.automated-apply.frontend-v2")
LEGACY_RUST_LABEL = "com.automated-apply.rust"
CONNECTION_WARN_AT = 4
CONNECTION_CAP = 5
HEARTBEAT_STALE_AFTER = timedelta(minutes=5)
FAILURE_SCREENSHOT_CAP = 20
V2_TABLES = tuple(sorted(TABLES))

Runner = Callable[[list[str]], str]
Fetcher = Callable[[str], int]


@dataclass
class Check:
    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)
