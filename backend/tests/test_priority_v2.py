"""Phase 9B: deterministic early-bird priority tiers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.browser_v2.priority import (
    PostedAt,
    Priority,
    PriorityInput,
    better,
    decayed,
    parse_posted_age_hours,
    posted_from,
    queue_key,
    score,
)

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def hours_ago(h: float, precision: str = "hour") -> PostedAt:
    return PostedAt(NOW - timedelta(hours=h), precision)


@pytest.mark.parametrize(("text", "expected"), [
    ("Just now", 0.0), ("3 hours ago", 3.0), ("45 minutes ago", 0.75), ("1 hr ago", 1.0),
    ("Posted 2h ago", 2.0), ("2 days ago", None), ("Yesterday", None), ("", None), (None, None),
    ("Few minutes ago", 0.0), ("30+ days ago", None),
])
def test_parse_posted_age_hours(text: str | None, expected: float | None) -> None:
    assert parse_posted_age_hours(text) == expected


def test_posted_from_precision_order() -> None:
    exact = datetime(2026, 11, 27, 10, 30, tzinfo=UTC)
    assert posted_from(now=NOW, posted_at=exact, age_days=3) == PostedAt(exact, "hour")
    midnight = datetime(2026, 11, 26, tzinfo=UTC)
    assert posted_from(now=NOW, posted_at=midnight).precision == "day"
    assert posted_from(now=NOW, age_hours=1.5).at == NOW - timedelta(hours=1.5)
    assert posted_from(now=NOW, age_hours=1, lower_bound=True).precision == "unknown"
    assert posted_from(now=NOW, age_days=2) == PostedAt(NOW - timedelta(days=2), "day")
    assert posted_from(now=NOW) == PostedAt(None, "unknown")
    future = NOW + timedelta(hours=3)
    assert posted_from(now=NOW, posted_at=future).at == NOW  # clock skew never creates the future


def test_p0_needs_strong_match_and_hour_precision() -> None:
    assert score(PriorityInput(hours_ago(1), strong_match=True), NOW).priority is Priority.P0
    assert score(PriorityInput(hours_ago(1), strong_match=False), NOW).priority is Priority.P1
    # day precision "today" is never P0 by age alone
    assert score(PriorityInput(hours_ago(1, "day"), strong_match=True), NOW).priority is Priority.P1
    assert score(PriorityInput(hours_ago(3), strong_match=True), NOW).priority is Priority.P1


def test_newly_seen_delta_is_p0_only_when_recent_or_unknown() -> None:
    fresh = PriorityInput(PostedAt(None), strong_match=True, newly_seen=True)
    assert score(fresh, NOW).priority is Priority.P0
    old = PriorityInput(hours_ago(72, "day"), strong_match=True, newly_seen=True)
    assert score(old, NOW).priority is Priority.P2
    weak = PriorityInput(PostedAt(None), strong_match=False, newly_seen=True)
    assert score(weak, NOW).priority is Priority.P2


def test_owner_requested_always_p0_and_other_tiers() -> None:
    assert score(PriorityInput(hours_ago(500, "day"), user_requested=True), NOW).reason == "owner_requested"
    assert score(PriorityInput(hitl_resume=True), NOW).priority is Priority.P1
    assert score(PriorityInput(via_alert_email=True), NOW).priority is Priority.P1
    assert score(PriorityInput(hours_ago(24 * 3, "day")), NOW).priority is Priority.P2
    assert score(PriorityInput(hours_ago(24 * 10, "day")), NOW).priority is Priority.P3
    assert score(PriorityInput(quota_retry=True), NOW).priority is Priority.P3
    assert score(PriorityInput(), NOW).priority is Priority.P2


def test_decay_never_promotes() -> None:
    assert decayed(0, NOW - timedelta(hours=1), NOW) == 0
    assert decayed(0, NOW - timedelta(hours=3), NOW) == 1
    assert decayed(0, NOW - timedelta(hours=30), NOW) == 2
    assert decayed(1, NOW - timedelta(hours=25), NOW) == 2
    assert decayed(3, NOW - timedelta(days=30), NOW) == 3


def test_queue_key_orders_tier_then_newest() -> None:
    created = NOW - timedelta(days=1)
    rows = [
        ("old_p1", 1, NOW - timedelta(hours=20)),
        ("new_p1", 1, NOW - timedelta(hours=1)),
        ("p0", 0, None),
        ("p2", 2, NOW),
    ]
    ordered = sorted(rows, key=lambda r: queue_key(r[1], r[2], created))
    assert [r[0] for r in ordered] == ["p0", "new_p1", "old_p1", "p2"]
    assert better(2, 0) == 0 and better(None, None) == 2 and better(None, 1) == 1
