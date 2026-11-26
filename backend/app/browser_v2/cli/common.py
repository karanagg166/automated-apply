"""Shared CLI constants and the JSON `emit` printer."""

from __future__ import annotations

import json
from typing import Any

PHASE1_LIVE_LIMIT = 1
MAX_INSPECTIONS_PER_APPLY = 10
MAX_DEBUG_BUNDLES = 3


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))
