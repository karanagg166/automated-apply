"""STRICTLY READ-ONLY inbox reading (Phase 6A). Nothing here can send, draft, flag,
move or delete mail.

3-tier fallback chain (`MailReadService.recent`):
  1. Gmail IMAP: `select(readonly=True)` (= EXAMINE) + SEARCH + FETCH BODY.PEEK[] so
     messages are never marked \\Seen (GMAIL_IMAP_EMAIL + GMAIL_IMAP_APP_PASSWORD).
  2. Gmail API `gmail.readonly` via the existing GET-only `GmailReadClient` when an OAuth
     access-token provider is wired (API process; the worker has no SQLAlchemy session).
  3. macOS Mail.app JXA reader (`mail_app_reader.js`, stays in the background, read-only).

Automations on top:
  - `fetch_recent_otp(portal, since)`: 4-8 digit code / magic link from the portal's
    sender in the last 3 minutes (auto-login + Naukri OTP entry). Codes are never stored.
  - `scan_recruiter_replies()`: replies from addresses we drafted to, or interview /
    shortlist / assessment keywords -> deduplicated `public.mail_events` + Telegram alert.
  - `scan_job_alert_emails()`: Naukri / LinkedIn / Wellfound job-alert emails -> job links
    -> `applications` rows in DISCOVERED (no LinkedIn login is ever automated).
"""

from __future__ import annotations

import asyncio
import base64
import email
import hashlib
import html
import imaplib
import json
import logging
import os
import re
import ssl
import tempfile
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.app.mail_v2.config import OSASCRIPT, MailConfig

logger = logging.getLogger(__name__)
READ_SCRIPT = Path(__file__).with_name("mail_app_reader.js")
TIMEOUT_SEC = 20
MAX_BODY_CHARS = 6000
MAX_MESSAGES = 40
OTP_WINDOW = timedelta(minutes=3)

# Portal sender/subject fingerprints for OTP + magic-link mails.
PORTAL_MAIL: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "naukri": (re.compile(r"naukri\.com$", re.IGNORECASE), re.compile(r"otp|verification|one time|login", re.IGNORECASE)),
    "instahyre": (re.compile(r"instahyre\.com$", re.IGNORECASE), re.compile(r"otp|verif|login|sign ?in|code", re.IGNORECASE)),
    "internshala": (re.compile(r"internshala\.com$", re.IGNORECASE), re.compile(r"otp|verif|login|code", re.IGNORECASE)),
    "wellfound": (re.compile(r"(?:wellfound|angel)\.(?:com|co)$", re.IGNORECASE), re.compile(r"sign ?in|login|verif|code|magic", re.IGNORECASE)),
    "work_at_a_startup": (re.compile(r"(?:ycombinator|workatastartup)\.com$", re.IGNORECASE),
                          re.compile(r"sign ?in|login|verif|code", re.IGNORECASE)),
    "himalayas": (re.compile(r"himalayas\.app$", re.IGNORECASE), re.compile(r"sign ?in|login|verif|code|magic", re.IGNORECASE)),
}
OTP_CODE = re.compile(r"(?<![\d-])(\d{4,8})(?![\d-])")
OTP_CONTEXT = re.compile(r"\b(?:otp|one[- ]time|verification code|security code|login code|passcode|code is|"
                         r"your code|enter (?:the )?code)\b", re.IGNORECASE)
MAGIC_LINK = re.compile(r"https://[^\s<>\"']+(?:login|signin|sign_in|verify|magic|auth|token)[^\s<>\"']*", re.IGNORECASE)
INTERVIEW = re.compile(r"\b(?:interview|shortlist(?:ed)?|assessment|coding (?:round|test|challenge)|hr (?:call|round)|"
                       r"technical round|next (?:round|steps?)|schedule (?:a )?(?:call|chat)|take[- ]home)\b", re.IGNORECASE)
RECRUITER = re.compile(r"\b(?:recruit(?:er|ing|ment)|talent acquisition|hiring (?:manager|team)|your application)\b",
                       re.IGNORECASE)
ALERT_SENDERS: dict[str, re.Pattern[str]] = {
    "naukri": re.compile(r"(?:^|\.)naukri\.com$", re.IGNORECASE),
    "linkedin": re.compile(r"(?:^|\.)linkedin\.com$", re.IGNORECASE),
    "wellfound": re.compile(r"(?:^|\.)(?:wellfound|angel)\.(?:com|co)$", re.IGNORECASE),
}
ALERT_SUBJECT = re.compile(r"job alert|jobs? (?:for|matching|you might|recommended)|new jobs|recommended jobs|"
                           r"jobs? based on|hiring for", re.IGNORECASE)
JOB_LINKS: dict[str, re.Pattern[str]] = {
    "naukri": re.compile(r"https://www\.naukri\.com/job-listings-[A-Za-z0-9%_-]+-(\d{10,20})"),
    "linkedin": re.compile(r"https://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d{6,20})"),
    "wellfound": re.compile(r"https://wellfound\.com/jobs/(\d{3,12})-[A-Za-z0-9-]*"),
}
NO_REPLY = re.compile(r"^(?:no-?reply|do-?not-?reply|notifications?|alerts?|mailer-daemon)@", re.IGNORECASE)


class MailReadError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MailMessage:
    key: str
    sender: str
    subject: str
    received_at: datetime | None
    body: str
    source: str  # imap | gmail_api | mail_app

    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1].lower()

    @property
    def sender_domain(self) -> str:
        return self.sender_address.rsplit("@", 1)[-1] if "@" in self.sender_address else ""


@dataclass
class MailEvent:
    message_key: str
    kind: str  # RECRUITER_REPLY | INTERVIEW | JOB_ALERT
    source: str
    sender: str | None
    subject: str | None
    snippet: str | None
    received_at: datetime | None
    platform: str | None = None
    company_name: str | None = None
    application_id: str | None = None
    alerted_at: datetime | None = None
    created_at: datetime | None = None
    id: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# --- message helpers --------------------------------------------------------------------------
def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, LookupError):
        return value


def _clean_text(value: str, limit: int = MAX_BODY_CHARS) -> str:
    # Keep link targets (job-alert ingestion needs them) before dropping the markup.
    linked = re.sub(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>", r" \1 ", value or "", flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<(script|style)\b[^>]*>.*?</\1>|<[^>]+>", " ", linked,
                                flags=re.DOTALL | re.IGNORECASE))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def body_text(message: Message, limit: int = MAX_BODY_CHARS) -> str:
    """Plain text from text/plain (preferred) or text/html parts; attachments ignored."""
    plain: list[str] = []
    rich: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        text = payload[:200_000].decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if part.get_content_type() == "text/plain" else rich if part.get_content_type() == "text/html"
         else []).append(text)
    return _clean_text(" ".join(plain) if plain else " ".join(rich), limit)


def message_key(message_id: str | None, sender: str, subject: str, received: datetime | None) -> str:
    if message_id and message_id.strip():
        return message_id.strip()[:300]
    digest = hashlib.sha256(f"{sender}|{subject}|{received}".encode()).hexdigest()
    return "sha256:" + digest


def parse_rfc822(raw: bytes, source: str) -> MailMessage:
    message = email.message_from_bytes(raw[:2_000_000])
    sender, subject = _decode(message.get("From")), _decode(message.get("Subject"))
    try:
        received = parsedate_to_datetime(message.get("Date") or "")
        received = received if received.tzinfo else received.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        received = None
    return MailMessage(message_key(message.get("Message-ID"), sender, subject, received), sender[:300], subject[:300],
                       received, body_text(message), source)


def clean_link(link: str) -> str:
    """Drop query strings / fragments (personal tracking tokens are never retained)."""
    parts = urlsplit(link)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _plausible_code(text: str, match: re.Match[str]) -> bool:
    code = match.group(1)
    before = text[max(0, match.start() - 2): match.start()]
    if re.fullmatch(r"(?:19|20)\d{2}", code) or re.search(r"[+\d]\s?$", before):
        return False  # a year, or part of a phone number like "+91 98450 12345"
    return not re.match(r"\s?\d", text[match.end(): match.end() + 2])


def extract_otp(text: str) -> str | None:
    """The code right after an OTP phrase (else just before it); never a date, phone number or price."""
    text = text or ""
    for phrase in OTP_CONTEXT.finditer(text):
        for match in OTP_CODE.finditer(text[: min(len(text), phrase.end() + 60)], phrase.end()):
            if _plausible_code(text, match):
                return match.group(1)
        start = max(0, phrase.start() - 40)
        before = [m for m in OTP_CODE.finditer(text[: phrase.start()], start) if _plausible_code(text, m)]
        if before:
            return before[-1].group(1)
    return None


# --- tier clients -------------------------------------------------------------------------------
ImapFactory = Callable[[str, int], Any]


def default_imap_factory(host: str, port: int) -> Any:
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_SEC)


class ImapReadClient:
    """EXAMINE-only Gmail IMAP reader. Allowed calls: login, select(readonly), search, fetch, logout."""

    def __init__(self, config: MailConfig, *, factory: ImapFactory = default_imap_factory,
                 mailbox: str = "INBOX") -> None:
        self.config = config
        self.factory = factory
        self.mailbox = mailbox

    @property
    def configured(self) -> bool:
        return self.config.imap_configured and not self.config.disabled

    def _read(self, since: datetime, sender_domain: str | None, limit: int) -> list[MailMessage]:
        try:
            imap = self.factory(self.config.imap_host, self.config.imap_port)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailReadError("imap_" + type(exc).__name__.lower()) from None
        try:
            imap.login(self.config.imap_email, self.config.imap_password)
            status, _ = imap.select('"' + self.mailbox + '"', readonly=True)  # EXAMINE
            if status != "OK":
                raise MailReadError("imap_examine_failed")
            criteria = ["SINCE", since.astimezone(UTC).strftime("%d-%b-%Y")]
            if sender_domain:
                criteria += ["FROM", '"' + re.sub(r'[^A-Za-z0-9.@-]', "", sender_domain) + '"']
            status, data = imap.search(None, *criteria)
            if status != "OK":
                raise MailReadError("imap_search_failed")
            ids = (data[0] or b"").split()[-limit:]
            messages = []
            for number in reversed(ids):
                status, parts = imap.fetch(number, "(BODY.PEEK[])")  # PEEK: never sets \\Seen
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and isinstance(p[1], bytes)), None)
                if status == "OK" and raw:
                    messages.append(parse_rfc822(raw, "imap"))
            return messages
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailReadError("imap_" + type(exc).__name__.lower()) from None
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001, S110
                pass

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        return await asyncio.to_thread(self._read, since, sender_domain, limit)


TokenProvider = Callable[[], Awaitable[str | None]]


def _gmail_text(payload: Mapping[str, Any], limit: int = MAX_BODY_CHARS) -> str:
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: Any, depth: int = 0) -> None:
        if depth > 10 or not isinstance(part, Mapping) or part.get("filename"):
            return
        data = (part.get("body") or {}).get("data")
        if isinstance(data, str) and len(data) < 400_000 and part.get("mimeType") in ("text/plain", "text/html"):
            try:
                text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                text = ""
            (plain if part.get("mimeType") == "text/plain" else rich).append(text)
        for child in part.get("parts") or []:
            walk(child, depth + 1)

    walk(payload)
    return _clean_text(" ".join(plain) if plain else " ".join(rich), limit)


class GmailApiReadClient:
    """Tier 2: `gmail.readonly` through the existing GET-only GmailReadClient."""

    def __init__(self, token_provider: TokenProvider | None = None, *, client: Any = None) -> None:
        self.token_provider = token_provider
        self.client = client

    @property
    def configured(self) -> bool:
        return self.token_provider is not None

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        from backend.app.integrations.gmail.read_client import GmailReadClient

        if self.token_provider is None:
            raise MailReadError("gmail_api_unconfigured")
        token = await self.token_provider()
        if not token:
            raise MailReadError("gmail_api_token_unavailable")
        reader = GmailReadClient(token, self.client)
        query = f"after:{int(since.timestamp())}" + (f" from:{sender_domain}" if sender_domain else "")
        try:
            listing = await reader.messages(labels=["INBOX"], query=query, limit=min(limit, 25))
            messages = []
            for item in (listing.get("messages") or [])[:limit]:
                full = await reader.message(item.get("id"), body=True)
                headers = {h.get("name", "").lower(): h.get("value", "")
                           for h in (full.get("payload") or {}).get("headers", []) if isinstance(h, dict)}
                received = None
                if str(full.get("internalDate", "")).isdigit():
                    received = datetime.fromtimestamp(int(full["internalDate"]) / 1000, tz=UTC)
                sender, subject = headers.get("from", "")[:300], headers.get("subject", "")[:300]
                messages.append(MailMessage(message_key(headers.get("message-id"), sender, subject, received),
                                            sender, subject, received, _gmail_text(full.get("payload") or {}),
                                            "gmail_api"))
            return messages
        except Exception as exc:  # noqa: BLE001 - provider errors are fixed internal codes only
            code = exc.args[0] if exc.args and isinstance(exc.args[0], str) else type(exc).__name__
            raise MailReadError("gmail_api:" + re.sub(r"[^a-z0-9_]", "", code.lower())[:40]) from None


ReadRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def osascript_read_runner(request: dict[str, Any]) -> dict[str, Any]:
    descriptor, path = tempfile.mkstemp(prefix="aa-mailread-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(request, handle)
        os.chmod(path, 0o600)
        child = await asyncio.create_subprocess_exec(
            str(OSASCRIPT), "-l", "JavaScript", str(READ_SCRIPT), path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, _ = await asyncio.wait_for(child.communicate(), 45)
        except TimeoutError:
            child.kill()
            await child.communicate()
            raise MailReadError("mail_app_timeout") from None
        if child.returncode or len(output) > 2_000_000:
            raise MailReadError("mail_app_scripting_unavailable")
        result = json.loads(output)
        if not isinstance(result, dict):
            raise MailReadError("mail_app_invalid_response")
        return result
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class MailAppReadClient:
    def __init__(self, config: MailConfig, *, runner: ReadRunner = osascript_read_runner,
                 available: bool | None = None) -> None:
        self.config = config
        self.runner = runner
        self.available = available  # None = detect (macOS + Mail.app present)

    @property
    def configured(self) -> bool:
        detected = self.config.mail_app_available if self.available is None else self.available
        return detected and not self.config.disabled

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        result = await self.runner({"action": "read_recent", "since_ms": int(since.timestamp() * 1000),
                                    "limit": limit, "max_chars": MAX_BODY_CHARS})
        if result.get("error") or not isinstance(result.get("messages"), list):
            raise MailReadError("mail_app_read_failed")
        messages = []
        for item in result["messages"]:
            if not isinstance(item, dict):
                continue
            received = datetime.fromtimestamp(item["received_ms"] / 1000, tz=UTC) \
                if isinstance(item.get("received_ms"), (int, float)) else None
            sender, subject = str(item.get("sender") or "")[:300], str(item.get("subject") or "")[:300]
            msg = MailMessage(message_key(item.get("message_id"), sender, subject, received), sender, subject,
                              received, _clean_text(str(item.get("body") or "")), "mail_app")
            if sender_domain and not msg.sender_domain.endswith(sender_domain.lower()):
                continue
            messages.append(msg)
        return messages


# --- service ------------------------------------------------------------------------------------
class MailEventStore:
    """public.mail_events (Postgres) or memory; dedup on message_key."""

    def __init__(self, connection: Any = None) -> None:
        self.connection = connection
        self.memory: dict[str, MailEvent] = {}

    async def add(self, event: MailEvent) -> bool:
        """True when new (first time this message is seen)."""
        if self.connection is None:
            if event.message_key in self.memory:
                return False
            event.created_at = datetime.now(UTC)
            event.id = hashlib.sha256(event.message_key.encode()).hexdigest()[:32]
            self.memory[event.message_key] = event
            return True
        row = await self.connection.fetchrow(
            """INSERT INTO public.mail_events (message_key, kind, source, platform, company_name, sender, subject,
                   snippet, application_id, received_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::uuid, $10)
               ON CONFLICT (message_key) DO NOTHING RETURNING id""",
            event.message_key, event.kind, event.source, event.platform, (event.company_name or None) and
            event.company_name[:200], (event.sender or None) and event.sender[:200],
            (event.subject or None) and event.subject[:300], (event.snippet or None) and event.snippet[:500],
            event.application_id, event.received_at)
        if row is not None:
            event.id = str(row["id"])
        return row is not None

    async def mark_alerted(self, message_key: str) -> None:
        if self.connection is None:
            if message_key in self.memory:
                self.memory[message_key].alerted_at = datetime.now(UTC)
            return
        await self.connection.execute("UPDATE public.mail_events SET alerted_at=now() WHERE message_key=$1",
                                      message_key)

    async def recent(self, kinds: Iterable[str] | None = None, limit: int = 50) -> list[MailEvent]:
        wanted = list(kinds) if kinds else ["RECRUITER_REPLY", "INTERVIEW", "JOB_ALERT"]
        if self.connection is None:
            rows = [e for e in self.memory.values() if e.kind in wanted]
            rows.sort(key=lambda e: e.created_at or datetime.now(UTC), reverse=True)
            return rows[:limit]
        rows = await self.connection.fetch(
            """SELECT id, message_key, kind, source, platform, company_name, sender, subject, snippet,
                      application_id, received_at, alerted_at, created_at
               FROM public.mail_events WHERE kind = ANY($1::text[]) ORDER BY created_at DESC LIMIT $2""",
            wanted, limit)
        return [MailEvent(**{**dict(r), "id": str(r["id"]),
                             "application_id": str(r["application_id"]) if r["application_id"] else None})
                for r in rows]

    @staticmethod
    async def ready(connection: Any) -> bool:
        try:
            return bool(await connection.fetchval("SELECT to_regclass('public.mail_events') IS NOT NULL"))
        except Exception:  # noqa: BLE001
            return False


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
        from backend.app.browser_v2.adapters.base import JobListing

        report = ScanReport()
        floor = since or (self.clock() - timedelta(days=1))
        try:
            messages = await self.recent(floor)
        except MailReadError as exc:
            report.errors.append(exc.code)
            return report
        report.tier = self.last_tier
        for message in messages:
            report.scanned += 1
            source = next((name for name, pattern in ALERT_SENDERS.items() if pattern.search(message.sender_domain)),
                          None)
            if source is None or not ALERT_SUBJECT.search(message.subject):
                continue
            pattern = JOB_LINKS[source]
            links = {m.group(1): clean_link(m.group(0)) for m in pattern.finditer(message.body)}
            if not links:
                continue
            event = MailEvent(message.key, "JOB_ALERT", message.source, message.sender[:200], message.subject[:300],
                              f"{len(links)} job link(s)", message.received_at, platform=source)
            if not await self.events.add(event):
                continue
            report.new_events += 1
            # LinkedIn stays manual-import only (AGENTS.md Tier 4): recorded, never automated.
            platform = "linkedin_alert" if source == "linkedin" else source
            for job_id, url in list(links.items())[:max_jobs - report.discovered]:
                existing = await store.get(platform, job_id)
                if existing is None:
                    await store.upsert_discovered(JobListing(platform=platform, external_job_id=job_id, url=url))
                    report.discovered += 1
            if report.discovered >= max_jobs:
                break
        return report


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
