"""MemoryStore: the `Store` contract in memory, for tests and dry runs before migration 004."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from backend.app.browser_v2.rules import (
    ALL_EDITABLE_RULE_FIELDS,
    PortalRules,
)
from backend.app.browser_v2.state import (
    ApplicationState,
    InvalidTransition,
    check_transition,
)
from backend.app.browser_v2.store.memory_agent import MemoryAgentMixin
from backend.app.browser_v2.store.memory_base import MemoryBase
from backend.app.browser_v2.store.memory_drafts import MemoryDraftsMixin
from backend.app.browser_v2.store.memory_hitl import MemoryHitlMixin
from backend.app.browser_v2.store.memory_notify import MemoryNotifyMixin
from backend.app.browser_v2.store.memory_priority import (
    MemoryPriorityMixin,
    queue_sort_key,
)
from backend.app.browser_v2.store.memory_watcher import MemoryWatcherMixin
from backend.app.browser_v2.store.records import (
    ApplicationRecord,
    ProfileMissing,
    RevisionConflict,
    RulesNotFound,
    WorkerControl,
    WorkerState,
    _now,
    validate_preferences,
)


class MemoryStore(MemoryAgentMixin, MemoryPriorityMixin, MemoryWatcherMixin, MemoryHitlMixin, MemoryDraftsMixin,
                  MemoryNotifyMixin, MemoryBase):
    async def get_rules(self, platform: str) -> PortalRules:
        return self.rules.get(platform, PortalRules(platform=platform))

    async def list_rules(self) -> list[PortalRules]:
        return [self.rules[k] for k in sorted(self.rules)]

    async def update_rules(self, platform, changes, expected_revision):
        current = self.rules.get(platform)
        if current is None:
            raise RulesNotFound(platform)
        if current.revision != expected_revision:
            raise RevisionConflict(current.revision)
        allowed = {k: v for k, v in changes.items() if k in ALL_EDITABLE_RULE_FIELDS}
        self.rules[platform] = replace(current, **allowed, revision=current.revision + 1,
                                       updated_at=_now())
        return self.rules[platform]

    async def get(self, platform: str, external_job_id: str) -> ApplicationRecord | None:
        record = self.records.get((platform, external_job_id))
        return replace(record) if record else None

    async def get_application(self, application_id):
        for record in self.records.values():
            if record.id == application_id:
                return replace(record)
        return None

    async def transition(self, record, target, reason, *, receipt=None, payload=None,
                         count_attempt=False, retry_after=None):
        current = self.records[(record.platform, record.external_job_id)]
        if current.version != record.version:
            raise InvalidTransition("stale_version")
        check_transition(current.state, target)
        self.events.append({"application_id": current.id, "from": current.state, "to": target,
                            "reason": reason, "payload": payload or {}, "created_at": _now()})
        current.state, current.reason = ApplicationState(target), reason
        current.version += 1
        current.attempts += int(count_attempt)
        current.updated_at = _now()
        if receipt is not None:
            current.receipt = receipt
        if retry_after is not None:
            current.retry_after = retry_after
        if target == ApplicationState.APPLIED:
            current.applied_at = _now()
            self.applied_at.append((record.platform, current.applied_at))
        return replace(current)

    async def find_duplicates(self, key, *, platform, external_job_id):
        return [replace(r) for (p, e), r in self.records.items()
                if r.dedup_key == key and (p, e) != (platform, external_job_id)]

    async def list_by_state(self, platform, states, limit=50):
        # Same filter and order as Postgres (retry_after gate; tier, newest posting, oldest-touched).
        now = _now()
        rows = [replace(r) for (p, _), r in self.records.items() if p == platform and r.state in states
                and (r.retry_after is None or r.retry_after <= now)]
        rows.sort(key=queue_sort_key)
        return rows[:limit]

    async def record_auth(self, platform: str, status: str) -> None:
        self.auth[platform] = status
        if platform in self.rules:
            self.rules[platform] = replace(self.rules[platform], auth_status=status,
                                           auth_checked_at=_now())

    async def record_portal_limit(self, platform: str) -> None:
        if platform in self.rules:
            self.rules[platform] = replace(self.rules[platform], portal_limit_hit_at=_now())

    async def count_state(self, state, platform=None):
        return sum(1 for (p, _), r in self.records.items()
                   if r.state == state and (platform is None or p == platform))

    async def applied_since(self, platform: str, since: datetime) -> int:
        return sum(1 for p, at in self.applied_at if p == platform and at >= since)

    async def ambiguous_submits_since(self, platform: str, since: datetime) -> int:
        ids = {r.id for (p, _), r in self.records.items()
               if p == platform and r.state != ApplicationState.APPLIED}
        return len({e["application_id"] for e in self.events if e["application_id"] in ids
                    and e["to"] == ApplicationState.SUBMISSION_UNKNOWN and e["created_at"] >= since})

    async def stale_applying(self, older_than: datetime, limit: int = 20) -> list[ApplicationRecord]:
        rows = [replace(r) for r in self.records.values() if r.state == ApplicationState.APPLYING
                and (r.updated_at or _now()) < older_than]
        rows.sort(key=lambda r: r.updated_at or _now())
        return rows[:limit]

    async def list_applications(self, query):
        rows = [r for r in self.records.values()
                if (query.platform is None or r.platform == query.platform)
                and (query.state is None or r.state.value == query.state)
                and (query.since is None or (r.updated_at and r.updated_at >= query.since))
                and (query.until is None or (r.updated_at and r.updated_at < query.until))
                and (not query.q or any(query.q.casefold() in (text or "").casefold()
                                        for text in (r.company_name, r.role_title)))]
        rows.sort(key=lambda r: r.updated_at or _now(), reverse=True)
        return [replace(r) for r in rows[query.offset: query.offset + query.limit]], len(rows)

    async def application_events(self, application_id):
        if not any(r.id == application_id for r in self.records.values()):
            return None
        return [{"from_state": e["from"].value if e["from"] else None,
                 "to_state": ApplicationState(e["to"]).value, "event_type": e["reason"],
                 "payload": e["payload"], "created_at": e["created_at"]}
                for e in self.events if e["application_id"] == application_id]

    async def load_profile(self):
        return self.profile, []

    async def update_preferences(self, changes):
        if not self.profile:
            raise ProfileMissing("no_candidate_profile")
        merged = validate_preferences(dict(self.profile.get("preferences") or {}) | dict(changes))
        self.profile["preferences"] = merged
        return dict(merged)

    async def get_worker_control(self) -> WorkerControl:
        return replace(self.worker)

    async def set_worker_control(self, desired_state=None, *, dry_run=None, run_once=False):
        if desired_state is not None:
            self.worker.desired_state = WorkerState(desired_state)
        if dry_run is not None:
            self.worker.dry_run = dry_run
        if run_once:
            self.worker.run_once_requested_at = _now()
        self.worker.revision += 1
        self.worker.updated_at = _now()
        return replace(self.worker)

    async def worker_heartbeat(self, observed_state, *, current_platform=None, last_error=None,
                               cycle_completed=False, clear_run_once=False):
        self.heartbeats.append(observed_state)
        self.worker.observed_state = observed_state
        self.worker.heartbeat_at = _now()
        self.worker.current_platform = current_platform
        self.worker.last_error = last_error
        if cycle_completed:
            self.worker.last_cycle_at = _now()
        if clear_run_once:
            self.worker.run_once_requested_at = None

    # --- Phase 5 -------------------------------------------------------------------
    async def due_retries(self, platform, now, limit=20):
        rows = [replace(r) for (p, _), r in self.records.items()
                if p == platform and r.state == ApplicationState.DRAFTED_AND_QUEUED
                and r.retry_after is not None and r.retry_after <= now]
        rows.sort(key=lambda r: (r.retry_after, r.updated_at or now))
        return rows[:limit]

    async def parked_since(self, platform, since):
        ids = {r.id for (p, _), r in self.records.items() if p == platform}
        return sum(1 for e in self.events if e["application_id"] in ids
                   and ApplicationState(e["to"]) == ApplicationState.QUOTA_HIT_PENDING
                   and e["from"] != ApplicationState.QUOTA_HIT_PENDING and e["created_at"] >= since)

    async def close(self) -> None:
        return None
