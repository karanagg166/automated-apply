"""Phase 9B early-bird Telegram notifier: batching, caps, escaping, preference, circuit alerts (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.store import DiscoveryMeta, MemoryStore
from backend.app.events_v2.bus import InProcessBus
from backend.app.telegram_v2.notifications import (
    DAILY_CAP,
    TOPICS,
    EarlyBirdNotifier,
    register,
)

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail = fail

    async def send_message(self, chat_id: int, text: str, **_: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def job(n: int, **extra: Any) -> dict[str, Any]:
    return {"platform": "greenhouse", "external_job_id": str(n), "title": f"Backend Engineer {n}",
            "company": "Acme", "url": f"https://job-boards.greenhouse.io/acme/jobs/{n}", "priority": 0,
            "ats_supported": True} | extra


def notifier(client: FakeClient, clock: Clock, **kw: Any) -> EarlyBirdNotifier:
    return EarlyBirdNotifier(client, 42, clock, auto_flush=False, **kw)


async def test_p0_discoveries_are_batched_at_most_one_message_per_two_minutes_and_five_jobs():
    client, clock = FakeClient(), Clock()
    bot = notifier(client, clock)
    await bot.handle("job.priority_discovered", job(1))
    assert len(client.sent) == 1 and "Backend Engineer 1" in client.sent[0][1]
    for n in range(2, 9):
        await bot.handle("job.priority_discovered", job(n))
    await bot.handle("job.priority_discovered", job(2))  # duplicate while pending: ignored
    await bot.handle("job.priority_discovered", job(99, priority=1))  # only P0 is early-bird news
    assert len(client.sent) == 1 and len(bot.pending) == 7
    clock.now += timedelta(minutes=2)
    assert await bot.flush()
    text = client.sent[1][1]
    assert text.startswith("⚡ <b>5 early-bird jobs</b>") and text.count("• ") == 5
    assert not await bot.flush() and len(bot.pending) == 2  # next batch waits for the window
    clock.now += timedelta(minutes=2)
    assert await bot.flush() and bot.pending == [] and "Backend Engineer 99" not in "".join(t for _, t in client.sent)


async def test_html_is_escaped_and_unsupported_ats_jobs_carry_the_manual_link():
    client, clock = FakeClient(), Clock()
    await notifier(client, clock).handle("job.priority_discovered", job(
        1, title="<script>x</script> & Co", company="A<b>", platform="hiringcafe", ats_supported=False,
        apply_url="https://careers.example.com/apply?id=1&src=hc"))
    text = client.sent[0][1]
    assert "&lt;script&gt;x&lt;/script&gt; &amp; Co" in text and "A&lt;b&gt;" in text
    assert "Manual apply: https://careers.example.com/apply?id=1&amp;src=hc" in text


async def test_daily_cap_and_preference_off():
    client, clock = FakeClient(), Clock()
    bot = notifier(client, clock)
    for n in range(DAILY_CAP + 5):
        clock.now += timedelta(minutes=3)
        await bot.handle("job.priority_discovered", job(n))
    assert len(client.sent) == DAILY_CAP
    clock.now = NOW + timedelta(days=1)
    await bot.flush()
    assert len(client.sent) == DAILY_CAP + 1  # new day, new budget

    async def off() -> dict[str, Any]:
        return {"notify_early_bird": False}

    quiet_client = FakeClient()
    quiet = notifier(quiet_client, Clock(), prefs_provider=off)
    await quiet.handle("job.priority_discovered", job(1))
    await quiet.handle("job.applied", job(1))
    assert quiet_client.sent == []


async def test_applied_only_for_p0_p1_rows_with_store_lookup():
    store = MemoryStore()
    await store.upsert_discovered_meta(JobListing("greenhouse", "7", "https://x.example/7"), DiscoveryMeta(priority=1))
    await store.upsert_discovered_meta(JobListing("greenhouse", "8", "https://x.example/8"), DiscoveryMeta(priority=2))
    client, clock = FakeClient(), Clock()
    bot = notifier(client, clock, store=store)
    await bot.handle("job.applied", {"platform": "greenhouse", "external_job_id": "8", "title": "P2 job"})
    assert client.sent == []
    await bot.handle("job.applied", {"platform": "greenhouse", "external_job_id": "7", "title": "P1 job"})
    assert len(client.sent) == 1 and "Applied</b> (P1)" in client.sent[0][1]
    await bot.handle("job.applied", {"platform": "lever", "external_job_id": "x", "priority": 0, "title": "Fast"})
    assert len(client.sent) == 1  # per-type rate limit (1 / minute)


async def test_circuit_open_alert_is_sent_once_per_portal_per_half_hour_and_never_raises():
    client, clock = FakeClient(), Clock()
    bot = notifier(client, clock, prefs_provider=None)
    payload = {"platform": "naukri", "open_until": "2026-11-27T09:30:00+00:00", "reason": "3 failures <timeout>"}
    await bot.handle("portal.circuit_open", payload)
    await bot.handle("portal.circuit_open", payload)
    assert len(client.sent) == 1 and "naukri" in client.sent[0][1] and "&lt;timeout&gt;" in client.sent[0][1]
    clock.now += timedelta(minutes=31)
    await bot.handle("portal.circuit_open", payload)
    assert len(client.sent) == 2
    broken = notifier(FakeClient(fail=True), clock)
    await broken.handle("portal.circuit_open", payload)  # Telegram down: swallowed
    await broken.handle("job.priority_discovered", {"priority": object()})  # garbage payload: swallowed


async def test_register_subscribes_known_topics_and_skips_unknown_ones():
    bus = InProcessBus()
    client = FakeClient()
    bot = notifier(client, Clock())
    subscribed = register(bus, bot)
    assert set(subscribed) <= set(TOPICS) and "job.applied" in subscribed
    await bus.publish("job.applied", {"platform": "lever", "external_job_id": "1", "priority": 0, "title": "T"})
    await bus.drain()
    assert len(client.sent) == 1 and bus.errors == 0
