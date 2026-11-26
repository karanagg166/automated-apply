"""The read-only 3-tier MailReadService: OTP / magic links, recruiter-reply watcher, job-alert ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.event_store import MailEventStore
from backend.app.mail_v2.gmail_api_reader import GmailApiReadClient
from backend.app.mail_v2.imap_reader import ImapReadClient
from backend.app.mail_v2.mail_app_reader import MailAppReadClient
from backend.app.mail_v2.read_models import (
    ALERT_SENDERS,
    ALERT_SUBJECT,
    INTERVIEW,
    JOB_LINKS,
    MAGIC_LINK,
    MAX_MESSAGES,
    NO_REPLY,
    OTP_CONTEXT,
    OTP_WINDOW,
    PORTAL_MAIL,
    RECRUITER,
    MailEvent,
    MailMessage,
    MailReadError,
)
from backend.app.mail_v2.read_parsing import (
    ALERT_PLATFORMS,
    EXTRA_ALERT_SENDERS,
    _clean_text,
    alert_job_links,
    extract_otp,
)


@dataclass
class ScanReport:
    scanned: int = 0
    new_events: int = 0
    alerts: list[str] = field(default_factory=list)
    discovered: int = 0
    tier: str | None = None
    errors: list[str] = field(default_factory=list)


Clock = Callable[[], datetime]


class MailReadService:
    PERMISSION = "READ_ONLY"

    def __init__(self, config: MailConfig, *, imap: ImapReadClient | None = None,
                 gmail_api: GmailApiReadClient | None = None, mail_app: MailAppReadClient | None = None,
                 events: MailEventStore | None = None, clock: Clock | None = None) -> None:
        self.config = config
        self.imap = imap or ImapReadClient(config)
        self.gmail_api = gmail_api or GmailApiReadClient()
        self.mail_app = mail_app or MailAppReadClient(config)
        self.events = events or MailEventStore()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.last_tier: str | None = None
        self.last_errors: list[str] = []

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any) -> MailReadService:
        return cls(MailConfig.from_env(env), **kwargs)

    @property
    def tiers(self) -> list[tuple[str, Any]]:
        return [("imap", self.imap), ("gmail_api", self.gmail_api), ("mail_app", self.mail_app)]

    @property
    def any_configured(self) -> bool:
        return not self.config.disabled and any(client.configured for _, client in self.tiers)

    def status(self) -> dict[str, Any]:
        return {"permission": self.PERMISSION, "tiers": {name: bool(client.configured) for name, client in self.tiers},
                "last_tier": self.last_tier, "last_errors": self.last_errors[-3:]}

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        """First configured tier that answers wins; failures fall through to the next tier."""
        errors = []
        for name, client in self.tiers:
            if not client.configured:
                continue
            try:
                messages = await client.recent(since, sender_domain=sender_domain, limit=limit)
            except MailReadError as exc:
                errors.append(f"{name}:{exc.code}")
                continue
            except Exception as exc:  # noqa: BLE001 - never let a reader crash the worker
                errors.append(f"{name}:{type(exc).__name__}")
                continue
            self.last_tier, self.last_errors = name, errors
            return messages
        self.last_tier, self.last_errors = None, errors
        if errors:
            raise MailReadError("all_mail_read_tiers_failed:" + ",".join(errors))
        raise MailReadError("mail_read_unconfigured")

    # --- 1. auto OTP / magic link ----------------------------------------------------------
    async def fetch_recent_otp(self, portal: str, since: datetime | None = None, *,
                               want_link: bool = False) -> str | None:
        fingerprint = PORTAL_MAIL.get(portal)
        if fingerprint is None:
            return None
        sender_re, subject_re = fingerprint
        floor = since or (self.clock() - OTP_WINDOW)
        try:
            messages = await self.recent(floor - timedelta(days=1), limit=15)  # IMAP SINCE is day-granular
        except MailReadError:
            return None
        for message in sorted(messages, key=lambda m: m.received_at or floor, reverse=True):
            if message.received_at is not None and message.received_at < floor:
                continue
            if not sender_re.search(message.sender_domain):
                continue
            if not subject_re.search(message.subject) and not OTP_CONTEXT.search(message.body):
                continue
            if want_link:
                link = MAGIC_LINK.search(message.body)
                if link and (urlsplit(link.group(0)).hostname or "").endswith(
                        tuple(d for d in (message.sender_domain,) if d)):
                    return link.group(0)
                continue
            code = extract_otp(f"{message.subject} {message.body}")
            if code:
                return code
        return None

    async def poll_otp(self, portal: str, since: datetime, *, timeout_s: float = 45.0,
                       interval_s: float = 5.0) -> str | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            code = await self.fetch_recent_otp(portal, since)
            if code or loop.time() >= deadline:
                return code
            await asyncio.sleep(interval_s)

    # --- 2. recruiter replies / interview watcher --------------------------------------------
    async def scan_recruiter_replies(self, store: Any, *, since: datetime | None = None,
                                     notify: Callable[[str], Awaitable[None]] | None = None) -> ScanReport:
        report = ScanReport()
        floor = since or (self.clock() - timedelta(days=2))
        try:
            messages = await self.recent(floor)
        except MailReadError as exc:
            report.errors.append(exc.code)
            return report
        report.tier = self.last_tier
        drafted = await _drafted_recipients(store)
        own = (self.config.imap_email or "").lower()
        for message in messages:
            report.scanned += 1
            address = message.sender_address
            if not address or address == own or NO_REPLY.match(address):
                continue
            text = f"{message.subject} {message.body[:2000]}"
            linked = drafted.get(address) or next((v for k, v in drafted.items()
                                                    if k.endswith("@" + message.sender_domain)), None)
            interview = INTERVIEW.search(text)
            if linked is None and not (interview and RECRUITER.search(text)):
                continue
            kind = "INTERVIEW" if interview else "RECRUITER_REPLY"
            event = MailEvent(message.key, kind, message.source, message.sender[:200], message.subject[:300],
                              _clean_text(message.body, 400) or None, message.received_at,
                              platform=(linked or {}).get("platform"), company_name=(linked or {}).get("company"),
                              application_id=(linked or {}).get("application_id"))
            if not await self.events.add(event):
                continue
            report.new_events += 1
            label = "Interview alert" if kind == "INTERVIEW" else "Recruiter reply"
            company = event.company_name or message.sender_domain or "unknown company"
            alert = f"📬 {label} from {company}: {message.subject[:140]}"
            report.alerts.append(alert)
            if notify is not None:
                try:
                    await notify(alert)
                    await self.events.mark_alerted(message.key)
                except Exception as exc:  # noqa: BLE001 - alert delivery is best effort
                    report.errors.append("notify:" + type(exc).__name__)
        return report

    # --- 3. ban-safe job-alert ingestion -------------------------------------------------------
    async def scan_job_alert_emails(self, store: Any, *, since: datetime | None = None,
                                    max_jobs: int = 50) -> ScanReport:
        report = ScanReport()
        floor = since or (self.clock() - timedelta(days=1))
        try:
            messages = await self.recent(floor)
        except MailReadError as exc:
            report.errors.append(exc.code)
            return report
        report.tier = self.last_tier
        senders = {**ALERT_SENDERS, **EXTRA_ALERT_SENDERS}
        for message in messages:
            report.scanned += 1
            if not ALERT_SUBJECT.search(message.subject):
                continue
            source = next((name for name, pattern in senders.items() if pattern.search(message.sender_domain)),
                          None)
            links = alert_job_links(source, message.body, JOB_LINKS)
            if not links:
                continue
            event = MailEvent(message.key, "JOB_ALERT", message.source, message.sender[:200], message.subject[:300],
                              f"{len(links)} job link(s)", message.received_at, platform=source or "ats")
            if not await self.events.add(event):
                continue
            report.new_events += 1
            for (platform, job_id), url in list(links.items())[:max_jobs - report.discovered]:
                if await _ingest_alert_link(store, platform, job_id, url, self.clock()):
                    report.discovered += 1
            if report.discovered >= max_jobs:
                break
        return report


async def _ingest_alert_link(store: Any, platform: str, job_id: str, url: str, now: datetime) -> bool:
    """Upsert one alert link; True when a new row was created.

    LinkedIn stays manual-import only (AGENTS.md Tier 4): recorded as `linkedin_alert` with no
    priority, never queued for an adapter. Every other link is a P1 `job_alert_email` row.
    """
    from backend.app.browser_v2.adapters.base import JobListing
    from backend.app.browser_v2.priority import PriorityInput, score
    from backend.app.browser_v2.store.phase9_records import DiscoveryMeta

    if platform == "linkedin":
        listing = JobListing(platform="linkedin_alert", external_job_id=job_id, url=url)
        if await store.get(listing.platform, job_id) is not None:
            return False
        await store.upsert_discovered(listing)
        return True
    if platform not in ALERT_PLATFORMS:
        return False
    listing = JobListing(platform=platform, external_job_id=job_id, url=url)
    decision = score(PriorityInput(via_alert_email=True), now)
    meta = DiscoveryMeta(priority=int(decision.priority), priority_reason=decision.reason,
                         discovered_via=f"mail_alert:{platform}")
    result = await store.upsert_discovered_meta(listing, meta)
    return bool(result.inserted)


async def _drafted_recipients(store: Any) -> dict[str, dict[str, Any]]:
    """recipient address -> {application_id, platform, company} for drafts we created."""
    try:
        drafts, _ = await store.list_email_drafts(limit=200)
    except Exception:  # noqa: BLE001
        return {}
    output: dict[str, dict[str, Any]] = {}
    for draft in drafts:
        address = (getattr(draft, "recipient_email", None) or "").lower()
        if address and getattr(draft, "status", "") == "CREATED":
            output[address] = {"application_id": draft.application_id, "platform": draft.platform,
                               "company": getattr(draft, "company_name", None)}
    return output
