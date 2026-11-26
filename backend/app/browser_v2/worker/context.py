"""Phase 9B scheduler value objects: per-cycle context, resumable portal turns, circuit state."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.rules import CandidatePreferences, PortalRules
from backend.app.browser_v2.worker.reports import CycleReport, PortalReport

# Outcome of a worker wait.
ELAPSED, WOKEN, STOPPED = "elapsed", "woken", "stopped"


@dataclass
class WorkItem:
    """One job a portal turn will hand to `handle_listing`."""

    listing: JobListing
    consume_id: str | None = None  # requeued HITL row: mark its answers consumed after the attempt
    recycle: bool = False  # check the 3-hour Brave recycle after this job
    via: str | None = None


@dataclass
class Turn:
    """A portal turn that can yield to an apply cooldown and resume later in the same cycle."""

    rules: PortalRules
    prefs: CandidatePreferences
    profile: tuple[dict[str, Any], list[tuple[str, str]]]
    portal: PortalReport
    items: AsyncGenerator[WorkItem, None]
    dry_run: bool
    run_once: bool
    pushback: WorkItem | None = None  # the job that hit the cooldown runs first on resume


@dataclass
class CycleContext:
    rules: dict[str, PortalRules]
    prefs: CandidatePreferences
    profile: tuple[dict[str, Any], list[tuple[str, str]]]
    dry_run: bool
    run_once: bool
    report: CycleReport
    deadline: datetime  # cooldown waits never run past the next cycle
    portals: dict[str, PortalReport] = field(default_factory=dict)

    def portal(self, platform: str) -> PortalReport:
        """The cycle's report for `platform` (created on first use, kept in report order)."""
        if platform not in self.portals:
            self.portals[platform] = PortalReport(platform=platform)
            self.report.portals.append(self.portals[platform])
        return self.portals[platform]


@dataclass
class Circuit:
    """Persisted per-portal circuit breaker (mirrors portal_rules.circuit_*)."""

    failures: int = 0
    level: int = 0
    open_until: datetime | None = None
    reason: str | None = None

    @property
    def clean(self) -> bool:
        return self.failures == 0 and self.level == 0 and self.open_until is None
