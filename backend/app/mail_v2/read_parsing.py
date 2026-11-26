"""Read-only mail reader: RFC 822 / HTML text extraction, message keys, link cleaning and OTP parsing."""

from __future__ import annotations

import email
import hashlib
import html
import re
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

from backend.app.mail_v2.read_models import (
    MAX_BODY_CHARS,
    OTP_CODE,
    OTP_CONTEXT,
    MailMessage,
)


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


# --- job-alert links (Phase 9B) ----------------------------------------------------------------
# Portals whose alert mails are trusted only from their own sender domain (in addition to read_models).
EXTRA_ALERT_SENDERS: dict[str, re.Pattern[str]] = {
    "instahyre": re.compile(r"(?:^|\.)instahyre\.com$", re.IGNORECASE),
    "internshala": re.compile(r"(?:^|\.)internshala\.com$", re.IGNORECASE),
}
EXTRA_JOB_LINKS: dict[str, re.Pattern[str]] = {
    "instahyre": re.compile(r"https://(?:www\.)?instahyre\.com/job-(\d{3,12})-[A-Za-z0-9-]*/?"),
    "internshala": re.compile(r"https://(?:www\.)?internshala\.com/(?:job|internship)/detail/[a-z0-9-]*?(\d{6,})"
                              r"(?=[/?#\s\"'<>]|$)/?"),
}
# Hosted-ATS postings are employer pages (no portal account involved): recognised in any alert mail.
ATS_LINK = re.compile(r"https://(?:(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io|jobs(?:\.eu)?\.lever\.co)"
                      r"/[^\s<>\"']+")
ASHBY_LINK = re.compile(r"https://jobs\.ashbyhq\.com/[A-Za-z0-9._%-]{1,100}/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                        r"[0-9a-f]{4}-[0-9a-f]{12})")
ALERT_PLATFORMS = frozenset({"naukri", "wellfound", "instahyre", "internshala", "greenhouse", "lever", "ashby"})


def alert_job_links(source: str | None, body: str,
                    portal_links: dict[str, re.Pattern[str]]) -> dict[tuple[str, str], str]:
    """{(platform, external_job_id): clean URL} for one alert mail.

    Portal links only count from that portal's own sender (`source`); Greenhouse / Lever /
    Ashby posting links count in any alert mail. Tracking query strings are never kept.
    """
    from backend.app.browser_v2.adapters.common import ats_handoff_target

    found: dict[tuple[str, str], str] = {}
    pattern = portal_links.get(source or "") or EXTRA_JOB_LINKS.get(source or "")
    if pattern is not None:
        for match in pattern.finditer(body):
            found.setdefault((source or "", match.group(1)), clean_link(match.group(0)))
    for match in ATS_LINK.finditer(body):
        handoff = ats_handoff_target(html.unescape(match.group(0)).rstrip(".,;)"))
        if handoff is not None:
            found.setdefault((handoff.platform, handoff.external_job_id), clean_link(handoff.url))
    for match in ASHBY_LINK.finditer(body):
        found.setdefault(("ashby", match.group(1)), clean_link(match.group(0)))
    return found
