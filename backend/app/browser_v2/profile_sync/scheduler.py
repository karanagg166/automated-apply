"""ProfileSyncScheduler: decides WHEN a portal profile sync runs (the worker runs it between jobs).

- interval: every calibrated portal is synced once per ``interval`` (default 24 h);
- on demand: ``request(portals, dry_run, trigger)`` (Telegram agent / dashboard / MCP) queues
  one run per portal (a newer request replaces a queued one for the same portal);
- ``profile.updated``: a 10-minute debounce (every new update restarts it), then one live
  (flag-gated) run per portal;
- never while P0/P1 work is pending (injected ``high_priority_pending`` predicate, checked
  before every run) and only when the worker calls ``run_due()`` between jobs.

NOT wired into the worker here (the orchestrator does that). The Telegram agent talks to the
``ProfileSyncRequester`` protocol (``request_sync``), which only enqueues.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from backend.app.browser_v2.profile_sync.models import (
    PROFILE_UPDATED_EVENT,
    TRIGGERS,
    SyncReport,
)
from backend.app.browser_v2.profile_sync.service import ProfileSyncService

DEFAULT_INTERVAL = timedelta(hours=24)
PROFILE_CHANGE_DEBOUNCE = timedelta(minutes=10)


@runtime_checkable
class ProfileSyncRequester(Protocol):
    async def request_sync(self, portals: Sequence[str], *, dry_run: bool, trigger: str) -> str: ...


@dataclass(frozen=True)
class SyncRequest:
    platform: str
    dry_run: bool
    trigger: str
    requested_at: datetime


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ProfileSyncScheduler:
    def __init__(self, service: ProfileSyncService, *, portals: Sequence[str] | None = None,
                 clock: Callable[[], datetime] | None = None, interval: timedelta = DEFAULT_INTERVAL,
                 debounce: timedelta = PROFILE_CHANGE_DEBOUNCE,
                 high_priority_pending: Callable[[], Awaitable[bool]] | None = None) -> None:
        self.service = service
        # Interval runs only for calibrated adapters (an uncalibrated run would be a no-op row a day).
        self.portals = tuple(portals if portals is not None else
                             [name for name, adapter in service.adapters.items() if adapter.calibrated])
        self.clock = clock or service.clock
        self.interval = interval
        self.debounce = debounce
        self.high_priority_pending = high_priority_pending
        self._queue: dict[str, SyncRequest] = {}
        self._changed_at: datetime | None = None
        self._change_pending: set[str] = set()

    # --- inputs ----------------------------------------------------------------------------
    def request(self, portals: Sequence[str], dry_run: bool = True, trigger: str = "telegram") -> list[str]:
        """Queue on-demand runs; returns the accepted portals (unknown portals are ignored)."""
        if trigger not in TRIGGERS:
            raise ValueError(f"invalid_trigger:{trigger}")
        now = self.clock()
        accepted = []
        for platform in dict.fromkeys(portals):
            if platform in self.service.adapters:
                self._queue[platform] = SyncRequest(platform, bool(dry_run), trigger, now)
                accepted.append(platform)
        return accepted

    def note_profile_updated(self, at: datetime | None = None) -> None:
        self._changed_at = at or self.clock()
        self._change_pending = set(self.portals)

    async def on_event(self, event_type: str, payload: Mapping[str, Any] | None = None) -> None:
        if event_type == PROFILE_UPDATED_EVENT:
            self.note_profile_updated()

    @property
    def queued(self) -> list[SyncRequest]:
        return list(self._queue.values())

    # --- decisions -------------------------------------------------------------------------
    async def due(self) -> list[SyncRequest]:
        now = self.clock()
        out = list(self._queue.values())
        taken = set(self._queue)
        if self._changed_at is not None and now - self._changed_at >= self.debounce:
            for platform in sorted(self._change_pending - taken):
                out.append(SyncRequest(platform, False, "profile_change", now))
                taken.add(platform)
        for platform in self.portals:
            if platform in taken:
                continue
            last = await self.service.runs.last(platform)
            started = _aware(last.get("started_at")) if last else None
            if started is None or now - started >= self.interval:
                out.append(SyncRequest(platform, False, "schedule", now))
        return out

    async def blocked(self) -> bool:
        return bool(self.high_priority_pending is not None and await self.high_priority_pending())

    async def run_due(self) -> list[SyncReport]:
        """Run everything due, one portal at a time; stops as soon as P0/P1 work is pending."""
        reports: list[SyncReport] = []
        for job in await self.due():
            if await self.blocked():
                break
            self._queue.pop(job.platform, None)
            if not job.dry_run:  # a dry run does not apply the profile change
                self._change_pending.discard(job.platform)
            if not self._change_pending:
                self._changed_at = None
            reports.append(await self.service.sync(job.platform, dry_run=job.dry_run, trigger=job.trigger))
        return reports

    # --- ProfileSyncRequester ----------------------------------------------------------------
    async def request_sync(self, portals: Sequence[str], *, dry_run: bool = True, trigger: str = "telegram") -> str:
        accepted = self.request(portals, dry_run=dry_run, trigger=trigger)
        unknown = [p for p in portals if p not in accepted]
        mode = "dry-run" if dry_run else "live (only where profile_sync.<portal>.live is on)"
        if not accepted:
            return f"No profile sync queued: unknown portal(s) {', '.join(unknown) or '-'}."
        text = f"Queued profile sync ({mode}) for {', '.join(accepted)}; it runs between jobs."
        return text + (f" Ignored unknown: {', '.join(unknown)}." if unknown else "")


def build_profile_sync(store: Any, manager: Any, *, adapters: Mapping[str, Any] | None = None,
                       runs: Any = None, session_adapters: Mapping[str, Any] | None = None,
                       fallback_resume_path: str | None = None, clock: Callable[[], datetime] | None = None,
                       receipts: Any = None, high_priority_pending: Callable[[], Awaitable[bool]] | None = None,
                       portals: Sequence[str] | None = None) -> ProfileSyncScheduler:
    """Scheduler + service over the worker's store and Brave manager.

    Pass ``session_adapters=browser_service.adapters`` (their ``check_session``) and
    ``fallback_resume_path=browser_service.env_profile.get("resume_path")``.
    """
    from backend.app.browser_v2.profile_sync.adapters import default_profile_adapters
    from backend.app.browser_v2.profile_sync.runs import runs_for

    service = ProfileSyncService(store, manager, adapters or default_profile_adapters(),
                                 runs or runs_for(store, clock=clock), clock, receipts,
                                 session_adapters=session_adapters, fallback_resume_path=fallback_resume_path)
    return ProfileSyncScheduler(service, portals=portals, clock=clock, high_priority_pending=high_priority_pending)
