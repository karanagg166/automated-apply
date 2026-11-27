"""Pure read-model builders for the dashboard's "Applied" views (no I/O).

`build_summary` folds the store's raw per-state / per-day counts into per-portal KPIs.
`build_detail` projects one application row: the `receipt` JSONB and the event payloads are
reduced to a whitelist (screening Q&A, verification source, sanitized URLs, a screenshot FLAG);
filesystem paths, raw payloads and URL query strings never leave the API.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from backend.app.browser_v2.schemas import (
    ApplicationDetail,
    ApplicationRead,
    ApplicationSummary,
    DailyApplied,
    PortalSummary,
    ReceiptSummary,
    ScreeningAnswer,
    TimelineEvent,
)
from backend.app.browser_v2.store import ApplicationRecord

SUMMARY_TZ = "Asia/Kolkata"
WEEK_DAYS = 7
MAX_ANSWERS = 100
TEXT_CHARS = 600
QUEUED = ("DISCOVERED", "SCORED")
QUOTA_PARKED = ("QUOTA_HIT_PENDING", "DRAFTED_AND_QUEUED")
SOURCE_TOKEN = re.compile(r"[A-Za-z0-9_:.\-]{1,60}")
LOCAL_PATH = re.compile(r"(?:~|/(?:Users|home|private|tmp|var|Volumes|opt|root))/[^\s\"'<>]+"
                        r"|[A-Za-z]:\\[^\s\"'<>]+")


# --- summary --------------------------------------------------------------------------
def summary_window(days: int, now: datetime, tz: str = SUMMARY_TZ) -> tuple[date, datetime]:
    """(local today, UTC-aware start of the oldest local day needed for the chart AND the 7-day KPI)."""
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    first = today - timedelta(days=max(days, WEEK_DAYS) - 1)
    return today, datetime.combine(first, time.min, tzinfo=zone)


def _portal(platform: str, states: Mapping[str, int], applied_by_day: Mapping[date, int],
            today: date) -> PortalSummary:
    week_start = today - timedelta(days=WEEK_DAYS - 1)
    return PortalSummary(
        platform=platform, applied_total=states.get("APPLIED", 0),
        applied_today=applied_by_day.get(today, 0),
        applied_7d=sum(n for day, n in applied_by_day.items() if week_start <= day <= today),
        submission_unknown=states.get("SUBMISSION_UNKNOWN", 0), failed=states.get("FAILED", 0),
        waiting_for_user=states.get("WAITING_FOR_USER", 0), applying=states.get("APPLYING", 0),
        queued=sum(states.get(s, 0) for s in QUEUED), quota_parked=sum(states.get(s, 0) for s in QUOTA_PARKED),
        filtered_out=states.get("FILTERED_OUT", 0), total=sum(states.values()), states=dict(states))


def build_summary(states: Mapping[str, Mapping[str, int]], daily: Iterable[tuple[str, date, int]],
                  platforms: Iterable[str], *, days: int, now: datetime,
                  tz: str = SUMMARY_TZ) -> ApplicationSummary:
    today, _ = summary_window(days, now, tz)
    per_portal: dict[str, dict[date, int]] = {}
    for platform, day, count in daily:
        bucket = per_portal.setdefault(platform, {})
        bucket[day] = bucket.get(day, 0) + count
    names = sorted(set(platforms) | set(states) | set(per_portal))
    portals = [_portal(name, states.get(name, {}), per_portal.get(name, {}), today) for name in names]
    portals.sort(key=lambda p: (-p.applied_total, -p.total, p.platform))
    all_states: dict[str, int] = {}
    all_days: dict[date, int] = {}
    for counts in states.values():
        for state, n in counts.items():
            all_states[state] = all_states.get(state, 0) + n
    for by_day in per_portal.values():
        for day, n in by_day.items():
            all_days[day] = all_days.get(day, 0) + n
    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        by_platform = {name: by_day[day] for name, by_day in sorted(per_portal.items()) if by_day.get(day)}
        series.append(DailyApplied(date=day, applied=all_days.get(day, 0), by_platform=by_platform))
    return ApplicationSummary(generated_at=now, timezone=tz, days=days,
                              totals=_portal("all", all_states, all_days, today), portals=portals, daily=series)


# --- detail ---------------------------------------------------------------------------
def safe_text(value: Any, limit: int = TEXT_CHARS) -> str | None:
    """Plain text with local filesystem paths reduced to their file name (resume.pdf, not /Users/...)."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = LOCAL_PATH.sub(lambda m: PurePosixPath(m.group().replace("\\", "/")).name or "[file]", str(value))
    text = text.strip()
    return text[:limit] if text else None


def safe_url(value: Any) -> str | None:
    """http(s) URL without credentials, query string or fragment (those can carry tokens)."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, host, parts.path, "", ""))[:500]


def safe_token(value: Any) -> str | None:
    return value if isinstance(value, str) and SOURCE_TOKEN.fullmatch(value) else None


def safe_answers(raw: Any) -> list[ScreeningAnswer]:
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw[:MAX_ANSWERS]:
        if not isinstance(item, Mapping):
            continue
        question, answer = safe_text(item.get("question")), safe_text(item.get("answer"))
        if question is None and answer is None:
            continue
        out.append(ScreeningAnswer(question=question or "Unlabelled field", answer=answer or "",
                                   source=safe_token(item.get("source"))))
    return out


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def receipt_summary(record: ApplicationRecord, events: list[dict[str, Any]]) -> ReceiptSummary:
    receipt = record.receipt if isinstance(record.receipt, Mapping) else {}
    apply_event = next((e.get("payload") for e in reversed(events)
                        if isinstance(e.get("payload"), Mapping)
                        and ("answers" in e["payload"] or "clicked_apply" in e["payload"])), None) or {}
    answers = safe_answers(receipt.get("answers"))
    answers_source = "receipt" if answers else None
    if not answers:
        answers = safe_answers(apply_event.get("answers"))
        answers_source = "event" if answers else None
    clicked = apply_event.get("clicked_apply")
    source = safe_token(receipt.get("source"))
    return ReceiptSummary(
        verified=record.state.value == "APPLIED" and source is not None, source=source,
        ats=safe_token(receipt.get("ats")), portal_status=safe_text(receipt.get("status"), 80),
        verified_at=_timestamp(receipt.get("verified_at")), confirmation_url=safe_url(receipt.get("url")),
        external_url=safe_url(receipt.get("external_url")), resume=safe_text(receipt.get("resume"), 120),
        clicked_apply=clicked if isinstance(clicked, bool) else None,
        has_screenshot=bool(receipt.get("screenshot") or apply_event.get("screenshot")),
        answers=answers, answers_source=answers_source)


def build_detail(record: ApplicationRecord, events: list[dict[str, Any]]) -> ApplicationDetail:
    timeline = [TimelineEvent(from_state=e.get("from_state"), to_state=e["to_state"],
                              event_type=safe_text(e.get("event_type"), 80) or "",
                              created_at=e.get("created_at")) for e in events]
    return ApplicationDetail(**ApplicationRead(**record.public()).model_dump(),
                             receipt=receipt_summary(record, events), timeline=timeline)
