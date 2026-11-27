"""In-process cache decision counters + one structured log line per decision.

`cache_decision_stats()` is what Telegram `/cache` and `GET /semantic-cache/stats` read. Counters
are per process (worker and API each keep their own) and reset on restart; durable per-entry
counts (hits, overrides, form validation errors, status) live on the rows themselves.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("backend.app.ai_v2.semantic_cache")

DECISIONS = (
    "exact_hit", "semantic_hit",
    "rejected_entity_mismatch", "rejected_polarity_flip", "rejected_option_mismatch",
    "rejected_cross_company", "rejected_stale_profile", "rejected_below_threshold",
    "rejected_field_type", "rejected_intent", "rejected_scope", "rejected_inactive",
    "miss_to_llm", "miss_to_hitl", "skipped_geo_unknown", "skipped_never_cache",
    "promoted_human", "promoted_llm_verified", "promoted_profile", "refused_unverified_llm", "refused_write",
    "quarantined",
)
HITS = ("exact_hit", "semantic_hit")
MISSES = ("miss_to_llm", "miss_to_hitl", "skipped_geo_unknown", "skipped_never_cache")


class CacheTelemetry:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = threading.Lock()
        self.since = datetime.now(UTC)

    def record(self, decision: str, **fields: Any) -> None:
        with self._lock:
            self._counts[decision] += 1
        detail = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
        logger.info("semantic_cache decision=%s %s", decision, detail)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = {name: int(self._counts.get(name, 0)) for name in DECISIONS}
        hits = sum(counts[name] for name in HITS)
        lookups = hits + sum(counts[name] for name in MISSES)
        rejected = {name: value for name, value in counts.items() if name.startswith("rejected_") and value}
        return {"since": self.since.isoformat(), "lookups": lookups, "hits": hits,
                "hit_rate": round(hits / lookups, 4) if lookups else None, "counters": counts,
                "rejections": rejected}

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
        self.since = datetime.now(UTC)


TELEMETRY = CacheTelemetry()


def cache_decision_stats() -> dict[str, Any]:
    """Process-wide decision counters: {since, lookups, hits, hit_rate, counters{...}, rejections{...}}."""
    return TELEMETRY.snapshot()
