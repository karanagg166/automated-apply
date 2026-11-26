"""Profile-sync value objects (pure; shared by the diff, the adapters, the service and the API).

Raw profile values only live in memory for the duration of one sync. Everything that is
persisted (``public.profile_sync_runs.fields`` / ``receipt``) or logged goes through
``value_ref`` / ``public()``: a SHA-256 reference plus a length, never the value itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

# Canonical field names (the union over every portal; each adapter supports a subset).
FIELDS = ("resume_headline", "profile_summary", "key_skills", "notice_period", "current_ctc", "expected_ctc",
          "preferred_locations", "current_location", "resume_pdf")
# Same CHECK constraints as followup 005 (public.profile_sync_runs).
TRIGGERS = frozenset({"schedule", "telegram", "dashboard", "cli", "profile_change", "mcp"})
RUN_STATUSES = ("running", "ok", "partial", "failed", "skipped", "auth_required")
PLATFORM_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
ERROR_CHARS = 500
PROFILE_UPDATED_EVENT = "profile.updated"


class FieldStatus(StrEnum):
    UNCHANGED = "unchanged"
    WOULD_UPDATE = "would_update"
    UPDATED = "updated"
    SKIPPED_UNSUPPORTED = "skipped_unsupported"
    SKIPPED_EMPTY_SOURCE = "skipped_empty_source"
    SKIPPED_NOT_CALIBRATED = "skipped_not_calibrated"
    VERIFY_FAILED = "verify_failed"
    ERROR = "error"


SKIPPED = frozenset({FieldStatus.SKIPPED_UNSUPPORTED, FieldStatus.SKIPPED_EMPTY_SOURCE,
                     FieldStatus.SKIPPED_NOT_CALIBRATED})
FAILED = frozenset({FieldStatus.VERIFY_FAILED, FieldStatus.ERROR})


def value_ref(value: Any) -> dict[str, Any] | None:
    """SHA-256 reference + length of a value (None stays None). Never returns the value."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str,
                                                           ensure_ascii=False)
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "length": len(text)}


def clip_error(error: str | None) -> str | None:
    return error[:ERROR_CHARS] if error else None


def profile_sync_live(preferences: Mapping[str, Any] | None, platform: str) -> bool:
    """`preferences.profile_sync.<platform>.live == true` (strict bool); anything else is False."""
    config = preferences.get("profile_sync") if isinstance(preferences, Mapping) else None
    entry = config.get(platform) if isinstance(config, Mapping) else None
    return isinstance(entry, Mapping) and entry.get("live") is True


@dataclass(frozen=True)
class FieldValue:
    """One value read from a portal. `status` is set when the adapter could not read it."""

    value: Any = None
    status: FieldStatus | None = None
    reason: str | None = None

    def public(self) -> dict[str, Any]:
        return {"status": self.status.value if self.status else None, "reason": self.reason,
                "ref": value_ref(self.value)}


@dataclass(frozen=True)
class FieldDiff:
    field: str
    status: FieldStatus
    portal: Any = None
    proposed: Any = None
    reason: str | None = None
    additions: tuple[str, ...] = ()  # key_skills only: canonical skills missing on the portal
    removals: tuple[str, ...] = ()  # key_skills only: portal skills not in the profile (never removed)

    def with_status(self, status: FieldStatus, reason: str | None = None) -> FieldDiff:
        return replace(self, status=status, reason=reason if reason is not None else self.reason)

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status.value, "portal": value_ref(self.portal),
                               "proposed": value_ref(self.proposed)}
        if self.reason:
            out["reason"] = self.reason
        if self.additions or self.removals:
            out["additions"] = len(self.additions)
            out["removals"] = len(self.removals)
        return out


@dataclass(frozen=True)
class ProfileSnapshot:
    """Canonical values (FIELDS keys) built from candidate_profiles + the active resume."""

    values: Mapping[str, Any]
    resume_path: str | None = None
    resume_sha256: str | None = None
    preferences: Mapping[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        return self.values.get(name)

    def public(self) -> dict[str, Any]:
        return {name: value_ref(self.values.get(name)) for name in FIELDS}


@dataclass
class SyncReport:
    platform: str
    dry_run: bool
    trigger: str
    statuses: dict[str, FieldDiff] = field(default_factory=dict)
    receipt: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    run_id: str | None = None
    error: str | None = None

    def fields_public(self) -> dict[str, dict[str, Any]]:
        return {name: diff.public() for name, diff in self.statuses.items()}

    def counts(self) -> dict[str, int]:
        return dict(Counter(diff.status.value for diff in self.statuses.values()))

    def public(self) -> dict[str, Any]:
        return {"platform": self.platform, "dry_run": self.dry_run, "trigger": self.trigger,
                "status": self.status, "run_id": self.run_id, "error": self.error,
                "counts": self.counts(), "fields": self.fields_public(), "receipt": dict(self.receipt)}

    def summary(self) -> str:
        mode = "dry-run" if self.dry_run else "live"
        counts = ", ".join(f"{n} {s}" for s, n in sorted(self.counts().items())) or "no fields"
        tail = f" ({self.error})" if self.error else ""
        return f"{self.platform} {mode}: {self.status} - {counts}{tail}"


def run_status(report: SyncReport) -> str:
    """Aggregate run status from the per-field statuses (session/exception paths set it earlier)."""
    statuses = {diff.status for diff in report.statuses.values()}
    if statuses & FAILED:
        return "partial" if FieldStatus.UPDATED in statuses else "failed"
    if FieldStatus.UPDATED in statuses or report.receipt.get("freshness_touched"):
        return "ok"
    if not statuses or statuses <= SKIPPED:
        return "skipped"
    return "ok"
