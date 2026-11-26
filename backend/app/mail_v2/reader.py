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

Facade: the code lives in ``read_models`` (limits, fingerprints, models), ``read_parsing``
(text / OTP helpers), ``imap_reader``, ``gmail_api_reader``, ``mail_app_reader`` (the three
tiers), ``event_store`` (MailEventStore) and ``read_service`` (MailReadService). Every name
stays importable from here.
"""

from __future__ import annotations

import logging

from backend.app.mail_v2.config import OSASCRIPT, MailConfig
from backend.app.mail_v2.event_store import MailEventStore
from backend.app.mail_v2.gmail_api_reader import (
    GmailApiReadClient,
    TokenProvider,
    _gmail_text,
)
from backend.app.mail_v2.imap_reader import (
    ImapFactory,
    ImapReadClient,
    default_imap_factory,
)
from backend.app.mail_v2.mail_app_reader import (
    READ_SCRIPT,
    MailAppReadClient,
    ReadRunner,
    osascript_read_runner,
)
from backend.app.mail_v2.read_models import (
    ALERT_SENDERS,
    ALERT_SUBJECT,
    INTERVIEW,
    JOB_LINKS,
    MAGIC_LINK,
    MAX_BODY_CHARS,
    MAX_MESSAGES,
    NO_REPLY,
    OTP_CODE,
    OTP_CONTEXT,
    OTP_WINDOW,
    PORTAL_MAIL,
    RECRUITER,
    TIMEOUT_SEC,
    MailEvent,
    MailMessage,
    MailReadError,
)
from backend.app.mail_v2.read_parsing import (
    _clean_text,
    _decode,
    _plausible_code,
    body_text,
    clean_link,
    extract_otp,
    message_key,
    parse_rfc822,
)
from backend.app.mail_v2.read_service import (
    Clock,
    MailReadService,
    ScanReport,
    _drafted_recipients,
)

__all__ = [
    "ALERT_SENDERS",
    "ALERT_SUBJECT",
    "INTERVIEW",
    "JOB_LINKS",
    "MAGIC_LINK",
    "MAX_BODY_CHARS",
    "MAX_MESSAGES",
    "NO_REPLY",
    "OSASCRIPT",
    "OTP_CODE",
    "OTP_CONTEXT",
    "OTP_WINDOW",
    "PORTAL_MAIL",
    "READ_SCRIPT",
    "RECRUITER",
    "TIMEOUT_SEC",
    "Clock",
    "GmailApiReadClient",
    "ImapFactory",
    "ImapReadClient",
    "MailAppReadClient",
    "MailConfig",
    "MailEvent",
    "MailEventStore",
    "MailMessage",
    "MailReadError",
    "MailReadService",
    "ReadRunner",
    "ScanReport",
    "TokenProvider",
    "_clean_text",
    "_decode",
    "_drafted_recipients",
    "_gmail_text",
    "_plausible_code",
    "body_text",
    "clean_link",
    "default_imap_factory",
    "extract_otp",
    "logger",
    "message_key",
    "osascript_read_runner",
    "parse_rfc822",
]

logger = logging.getLogger(__name__)
