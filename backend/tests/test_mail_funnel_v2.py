"""Milestone 2: post-apply mail funnel reconciliation, owner release, outreach draft handoff (offline)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import (
    EMAIL_RECONCILE_REASON,
    OWNER_RELEASE_REASON,
    InvalidTransition,
    check_transition,
)
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.browser_v2.worker.funnel_reconcile import FunnelReconciler
from backend.app.browser_v2.worker.outreach import OutreachHandoff, fit_score
from backend.app.mail_v2.event_store import MailEventStore
from backend.app.mail_v2.funnel import (
    CONFIRMATION,
    INTERVIEW_INVITE,
    OA_INVITE,
    RECRUITER_REPLY,
    REJECTED,
    classify,
    match_application,
    normalize_company,
)
from backend.app.mail_v2.read_models import MailMessage
from backend.app.telegram_v2.notify_policy import NotifyConfig, Priority
from backend.app.telegram_v2.notify_policy import classify as notify_classify

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)


def mail(key, subject, body="", sender="Hiring Team <no-reply@greenhouse-mail.io>", at=NOW):
    return MailMessage(key, sender, subject, at, body, "imap")


class FakeReader:
    def __init__(self, messages):
        self.messages = messages
        self.events = MailEventStore()

    async def recent(self, since, **_):
        return [m for m in self.messages if m.received_at is None or m.received_at >= since]


class Bus:
    def __init__(self):
        self.events = []

    async def __call__(self, topic, payload):
        self.events.append((topic, payload))


async def applied(store, i, company="Acme", title="Backend Engineer", state=S.APPLIED, at=None):
    record = await store.upsert_discovered(JobListing(platform="greenhouse", external_job_id=str(i),
                                                      url=f"https://example.com/{i}", title=title, company=company))
    record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    record = await store.transition(record, state, "confirmed" if state == S.APPLIED else "confirmation_ambiguous",
                                    receipt={"source": "dom"} if state == S.APPLIED else None)
    row = store.records[("greenhouse", str(i))]
    row.updated_at = at or NOW - timedelta(hours=1)
    if state == S.APPLIED:
        row.applied_at = at or NOW - timedelta(hours=1)
    return row


# --- classifier / matcher --------------------------------------------------------------------
@pytest.mark.parametrize(("subject", "body", "kind"), [
    ("Thank you for applying to Acme", "We have received your application.", CONFIRMATION),
    ("Your application to Acme", "Unfortunately we will not be moving forward. Thank you for applying.", REJECTED),
    ("Acme: next steps", "Please complete the HackerRank coding assessment within 3 days.", OA_INVITE),
    ("Interview with Acme", "We'd like to schedule a call with you.", INTERVIEW_INVITE),
    ("Re: Backend Engineer", "Hi, I'm the recruiter at Acme.", RECRUITER_REPLY),
    ("Newsletter", "Our product updates", None),
    ("Security code for your application to Acme", "Copy this security code: AB12CD34", None),
])
def test_classify(subject, body, kind):
    assert classify(mail("k", subject, body)) == kind


def test_normalize_company_drops_suffixes():
    assert normalize_company("The Acme Technologies Pvt. Ltd.") == "acme"
    assert normalize_company("Stripe, Inc.") == "stripe"


async def test_match_requires_company_and_refuses_ambiguity():
    store = MemoryStore()
    a = await applied(store, 1, title="Backend Engineer")
    b = await applied(store, 2, title="Frontend Engineer")
    other = await applied(store, 3, company="Globex")
    message = mail("k", "Thank you for applying to Acme", "Backend Engineer role")
    assert match_application(message, CONFIRMATION, [a, b, other]).record.id == a.id
    assert match_application(mail("k", "Thank you for applying to Acme", "an opening"),
                             CONFIRMATION, [a, b]) is None  # two Acme rows, nothing tells them apart
    assert match_application(mail("k", "Thank you for applying to Initech"), CONFIRMATION, [a, b]) is None


# --- reconciler -------------------------------------------------------------------------------
async def test_confirmation_upgrades_submission_unknown_and_is_idempotent():
    store, bus = MemoryStore(), Bus()
    row = await applied(store, 1, state=S.SUBMISSION_UNKNOWN)
    reader = FakeReader([mail("<m1@x>", "Thank you for applying to Acme", "Backend Engineer")])
    reconciler = FunnelReconciler(store, reader, publish=bus, clock=lambda: NOW)
    report = await reconciler.run()
    fresh = store.records[("greenhouse", "1")]
    assert (report.upgraded, report.verified, fresh.state, fresh.reason) == (1, 1, S.APPLIED, EMAIL_RECONCILE_REASON)
    assert fresh.receipt["email_verified"] is True and fresh.receipt["confirmation_email_id"] == "<m1@x>"
    assert [t for t, _ in bus.events] == ["mail.reconciled"] and bus.events[0][1]["upgraded"] is True
    assert reader.events.memory["<m1@x>"].application_id == row.id
    again = await reconciler.run()  # same mail on the next tick: no second event, no second publish
    assert again.matched == 0 and len(bus.events) == 1


async def test_confirmation_on_applied_annotates_without_touching_quota():
    store, bus = MemoryStore(), Bus()
    await applied(store, 1)
    applied_before = list(store.applied_at)
    await FunnelReconciler(store, FakeReader([mail("m", "Application received - Acme")]), publish=bus,
                           clock=lambda: NOW).run()
    fresh = store.records[("greenhouse", "1")]
    assert fresh.state == S.APPLIED and fresh.receipt["email_verified"] is True and fresh.receipt["source"] == "dom"
    assert store.applied_at == applied_before  # annotation never re-counts the daily cap
    events = await store.application_events(fresh.id)
    assert events[-1]["event_type"] == "email_verified" and events[-1]["from_state"] == events[-1]["to_state"]


async def test_oa_and_interview_emit_p1_rejection_digest_only():
    store, bus = MemoryStore(), Bus()
    await applied(store, 1)
    await applied(store, 2, company="Globex", title="Data Engineer")
    await applied(store, 3, company="Initech", title="SRE")
    reader = FakeReader([
        mail("oa", "Acme coding assessment", "Please complete the Codility test for Backend Engineer."),
        mail("iv", "Interview invitation - Globex", "We'd like to schedule a call. Data Engineer"),
        mail("rj", "Your Initech application", "Unfortunately we decided to move forward with other candidates."),
    ])
    report = await FunnelReconciler(store, reader, publish=bus, clock=lambda: NOW).run()
    assert report.signals == {OA_INVITE: 1, INTERVIEW_INVITE: 1, REJECTED: 1}
    config = NotifyConfig()
    tiers = {p["kind"]: notify_classify(t, p, config, NOW).priority for t, p in bus.events if t == "mail.funnel_signal"}
    assert tiers == {OA_INVITE: Priority.P1, INTERVIEW_INVITE: Priority.P1, REJECTED: Priority.P2}
    rejected = notify_classify("mail.funnel_signal", next(p for t, p in bus.events if p.get("kind") == REJECTED),
                               config, NOW)
    assert rejected.text == ""  # never pushed: digest line only
    events = await store.application_events(store.records[("greenhouse", "1")].id)
    assert events[-1]["event_type"] == "mail_oa_invite"
    # The furthest funnel stage is exposed on the application row (pipeline board columns).
    assert store.records[("greenhouse", "1")].public()["funnel_stage"] == OA_INVITE
    assert store.records[("greenhouse", "2")].public()["funnel_stage"] == INTERVIEW_INVITE
    assert store.records[("greenhouse", "3")].public()["funnel_stage"] == REJECTED


async def test_wrong_company_and_pre_apply_mail_are_ignored():
    store, bus = MemoryStore(), Bus()
    await applied(store, 1, state=S.SUBMISSION_UNKNOWN)
    reader = FakeReader([mail("x", "Thank you for applying to Globex"),
                         mail("old", "Thank you for applying to Acme", at=NOW - timedelta(days=1))])
    report = await FunnelReconciler(store, reader, publish=bus, clock=lambda: NOW).run()
    assert report.matched == 0 and store.records[("greenhouse", "1")].state == S.SUBMISSION_UNKNOWN
    assert bus.events == []


async def test_stale_submission_unknown_needs_reconciliation():
    store = MemoryStore()
    await applied(store, 1, state=S.SUBMISSION_UNKNOWN, at=NOW - timedelta(hours=30))
    await applied(store, 2, state=S.SUBMISSION_UNKNOWN, at=NOW - timedelta(hours=2))
    report = await FunnelReconciler(store, FakeReader([]), clock=lambda: NOW).run()
    assert report.needs_reconciliation == 1


# --- owner release ----------------------------------------------------------------------------
async def test_submission_unknown_to_failed_only_with_owner_reason_and_frees_quota():
    with pytest.raises(InvalidTransition):
        check_transition(S.SUBMISSION_UNKNOWN, S.FAILED)
    with pytest.raises(InvalidTransition):
        check_transition(S.SUBMISSION_UNKNOWN, S.FAILED, "stale_applying_recovered")
    check_transition(S.SUBMISSION_UNKNOWN, S.FAILED, OWNER_RELEASE_REASON)
    with pytest.raises(InvalidTransition):
        check_transition(S.APPLIED, S.FAILED, OWNER_RELEASE_REASON)  # never for a confirmed application
    store = MemoryStore()
    row = await applied(store, 1, state=S.SUBMISSION_UNKNOWN)
    since = NOW - timedelta(days=2)
    assert await store.ambiguous_submits_since("greenhouse", since) == 1
    await store.transition(row, S.FAILED, OWNER_RELEASE_REASON)
    assert await store.ambiguous_submits_since("greenhouse", since) == 0


# --- outreach draft handoff ---------------------------------------------------------------------
class FakeQuota:
    def __init__(self):
        self.calls = []

    async def draft_once(self, record, profile):
        self.calls.append(record.external_job_id)
        return "quota_hit_drafted_and_queued", {"draft_reason": "drafted", "channel": "imap"}


async def test_outreach_disabled_by_default_and_threshold():
    assert OutreachHandoff.from_env(MemoryStore(), FakeQuota(), {}).enabled is False
    store, quota, bus = MemoryStore(profile={"preferences": {"target_titles": ["Backend Engineer"]}}), FakeQuota(), Bus()
    high = await applied(store, 1)
    store.records[("greenhouse", "1")].priority = 0
    await applied(store, 2, title="Sales Manager")
    handoff = OutreachHandoff.from_env(store, quota, {"AUTO_OUTREACH_DRAFT_ENABLED": "true"}, publish=bus)
    assert handoff.enabled and handoff.threshold == 85
    for i in ("1", "2"):
        await handoff.on_applied("job.applied", {"platform": "greenhouse", "external_job_id": i})
    results = await handoff.drain()
    assert [r["outcome"] for r in results] == ["drafted", "below_threshold"]
    assert quota.calls == ["1"] and [t for t, _ in bus.events] == ["job.outreach_draft"]
    events = await store.application_events(high.id)
    assert events[-1]["event_type"] == "outreach_drafted" and events[-1]["payload"]["sent"] is False


def test_fit_score_explicit_wins():
    assert fit_score(object(), {}, {"score": 91}) == 91
