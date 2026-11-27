"""MemoryStore parity for the Milestone 2 ops queries (see store/ops_repo.py)."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from typing import Any

from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store.memory_base import MemoryBase

S = ApplicationState


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _event_id(index: int, event: dict[str, Any]) -> str:
    return event.get("id") or hashlib.sha256(f"{index}:{event.get('application_id')}".encode()).hexdigest()[:32]


def _verified(receipt: dict[str, Any] | None) -> bool:
    return bool((receipt or {}).get("email_verified"))


class MemoryOpsMixin(MemoryBase):
    async def ops_active_job(self) -> dict[str, Any] | None:
        rows = sorted((r for r in self.records.values() if r.state == S.APPLYING),
                      key=lambda r: r.updated_at or datetime.min, reverse=True)
        if not rows:
            return None
        record = rows[0]
        step = next((str(e.get("reason")) for e in reversed(self.events)
                     if e.get("application_id") == record.id and e.get("reason")), "apply_started")
        return {"application_id": record.id, "platform": record.platform, "company": record.company_name,
                "title": record.role_title, "step": step, "started_at": record.updated_at}

    async def ops_first_mover_lags(self, since: datetime) -> list[float]:
        lags: list[float] = []
        for record in self.records.values():
            if record.state != S.APPLIED or record.applied_at is None or record.applied_at < since:
                continue
            lag = ((record.receipt or {}).get("timing") or {}).get("first_mover_lag_seconds")
            if isinstance(lag, (int, float)) and not isinstance(lag, bool):
                lags.append(float(lag))
        return lags

    async def ops_receipt_counts(self, since: datetime, stale_before: datetime) -> dict[str, int]:
        verified = sum(1 for r in self.records.values() if r.state == S.APPLIED and r.applied_at is not None
                       and r.applied_at >= since and _verified(r.receipt))
        stale = sum(1 for r in self.records.values() if r.state == S.SUBMISSION_UNKNOWN
                    and r.updated_at is not None and r.updated_at < stale_before and not _verified(r.receipt))
        return {"verified_today": verified, "needs_reconciliation": stale}

    async def ops_answer_sources(self, since: datetime) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for event in self.events:
            if event.get("created_at") is None or event["created_at"] < since:
                continue
            answers = (event.get("payload") or {}).get("answers")
            for answer in answers if isinstance(answers, list) else []:
                if isinstance(answer, dict) and answer.get("source"):
                    counts[str(answer["source"])] += 1
        return dict(counts)

    async def ops_active_watchers(self, since: datetime, now: datetime) -> int:
        return sum(1 for w in self.watchers.values() if w.last_poll_at is not None and w.last_poll_at >= since
                   and (w.open_until is None or w.open_until <= now))

    async def ops_pushes_since(self, since: datetime) -> int:
        ledger = getattr(self, "_ledger", {}) or {}
        return sum(1 for e in ledger.values() if e.last_sent_at is not None and e.last_sent_at >= since)

    async def ops_event_feed(self, since: datetime, limit: int = 200) -> dict[str, Any]:
        by_id = {r.id: r for r in self.records.values()}
        events: list[dict[str, Any]] = []
        for index, event in enumerate(self.events):
            created = event.get("created_at")
            if created is None or created <= since:
                continue
            record = by_id.get(str(event.get("application_id")))
            source, target = event.get("from"), event.get("to")
            events.append({"id": _event_id(index, event), "application_id": event.get("application_id"),
                           "from_state": getattr(source, "value", source), "to_state": getattr(target, "value", target),
                           "event_type": event.get("reason"), "created_at": _iso(created),
                           "platform": getattr(record, "platform", None),
                           "company_name": getattr(record, "company_name", None),
                           "role_title": getattr(record, "role_title", None),
                           "priority": getattr(record, "priority", None)})
        hitl = [{"id": h["id"], "application_id": h.get("application_id"), "platform": h["platform"],
                 "kind": h["kind"], "status": h["status"], "prompt_text": h.get("prompt"),
                 "created_at": _iso(h.get("created_at")), "resolved_at": _iso(h.get("resolved_at")),
                 "resolved_via": h.get("resolved_via")}
                for h in self.hitl if (h.get("created_at") and h["created_at"] > since)
                or (h.get("resolved_at") and h["resolved_at"] > since)]
        worker = self.worker
        return {"events": events[:limit], "hitl": hitl[:limit],
                "worker": {"desired_state": getattr(worker.desired_state, "value", worker.desired_state),
                           "dry_run": worker.dry_run, "observed_state": worker.observed_state,
                           "current_platform": worker.current_platform,
                           "heartbeat_at": _iso(worker.heartbeat_at), "last_error": worker.last_error,
                           "revision": worker.revision},
                "breakers": [{"platform": r.platform, "enabled": r.enabled, "auth_status": r.auth_status,
                              "circuit_level": r.circuit_level, "circuit_open_until": _iso(r.circuit_open_until),
                              "circuit_reason": r.circuit_reason} for r in sorted(self.rules.values(),
                                                                                 key=lambda r: r.platform)]}
