"""RFC 5322 draft construction (UTF-8 plain text + optional verified PDF resume)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
APP_ID_HEADER = "X-Automated-Apply-App-Id"
TEST_SUBJECT_PREFIX = "[TEST DRAFT] "
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DraftValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DraftContent:
    subject: str
    body: str
    composer: str = "template"  # llm | template
    provider: str | None = None


def valid_recipient(value: str | None) -> str:
    """Exactly one syntactically valid address; no display names, lists or header injection."""
    email = (value or "").strip()
    if not _EMAIL.match(email) or len(email) > 254:
        raise DraftValidationError("invalid_recipient")
    return email.lower()


def clean_subject(subject: str) -> str:
    text = " ".join(_CONTROL.sub(" ", subject or "").replace("\r", " ").replace("\n", " ").split())
    if not text:
        raise DraftValidationError("empty_subject")
    return text[:180]


def resume_attachment(path: str | None) -> tuple[Path | None, str | None]:
    """(path, None) for a readable PDF <= 5 MB; (None, reason) otherwise. Never raises."""
    if not path:
        return None, None
    candidate = Path(path).expanduser()
    try:
        if not candidate.is_file():
            return None, "resume_not_found"
        size = candidate.stat().st_size
        if size == 0 or size > MAX_ATTACHMENT_BYTES:
            return None, "resume_size_invalid"
        if candidate.suffix.lower() != ".pdf":
            return None, "resume_not_pdf"
        with candidate.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return None, "resume_not_pdf"
    except OSError:
        return None, "resume_unreadable"
    return candidate, None


def build_draft_message(content: DraftContent, *, recipient: str, sender_email: str | None,
                        sender_name: str | None = None, application_id: str | None = None,
                        attachment: Path | None = None) -> EmailMessage:
    message = EmailMessage()
    to = valid_recipient(recipient)
    if sender_email:
        sender = valid_recipient(sender_email)
        name = _CONTROL.sub("", sender_name or "").strip()[:80]
        message["From"] = formataddr((name, sender)) if name else sender
        domain = Address(addr_spec=sender).domain
    else:
        domain = "automated-apply.local"
    message["To"] = to
    message["Subject"] = clean_subject(content.subject)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(idstring="automated-apply", domain=domain)
    if application_id:
        message[APP_ID_HEADER] = re.sub(r"[^A-Za-z0-9-]", "", application_id)[:64]
    body = _CONTROL.sub("", content.body or "").strip()
    if not body:
        raise DraftValidationError("empty_body")
    message.set_content(body + "\n", subtype="plain", charset="utf-8")
    if attachment is not None:
        if attachment.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise DraftValidationError("attachment_too_large")
        message.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf",
                               filename=attachment.name)
    return message
