"""One plain-text recipient, server-owned headers and deterministic serialization."""

import base64
import re
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from uuid import UUID

from pydantic import EmailStr, TypeAdapter


def mailbox(value):
    # EmailStr also accepts display names; this interface deliberately does not.
    if (
        not isinstance(value, str)
        or not value.isascii()
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("invalid_mailbox")
    validated = str(TypeAdapter(EmailStr).validate_python(value))
    if validated.casefold() != value.casefold() or any(c in value for c in '<>,;"()'):
        raise ValueError("invalid_mailbox")
    return validated


def message_id(attempt_id: UUID):
    return f"<outreach.{UUID(str(attempt_id)).hex}@automated-apply.invalid>"


def serialize(
    *, sender, recipient, subject, body, rfc_message_id, created_at: datetime
):
    sender, recipient = mailbox(sender), mailbox(recipient)
    if not subject or any(ord(c) < 32 or ord(c) == 127 for c in subject):
        raise ValueError("invalid_subject")
    if not re.fullmatch(
        r"<outreach\.[a-f0-9]{32}@automated-apply\.invalid>", rfc_message_id
    ):
        raise ValueError("invalid_message_id")
    if not isinstance(body, str) or not body or "\x00" in body:
        raise ValueError("invalid_body")
    msg = EmailMessage(policy=SMTP)
    msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
    msg["Message-ID"] = rfc_message_id
    msg["Date"] = format_datetime(created_at)
    msg.set_content(body.replace("\r\n", "\n").replace("\r", "\n"), charset="utf-8")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
