"""Parse generated RFC MIME independently, including UTF-8 and hostile headers."""

import base64
import uuid
from email import policy
from email.parser import BytesParser

import pytest

from backend.app.integrations.gmail.mime import message_id, serialize
from backend.app.models.discovery import now


def values():
    return dict(
        sender="secondary@example.com",
        recipient="person@example.org",
        subject="Backend — café 日本語",
        body="Hello café 日本語\n\nPlain text.\r\nThanks.",
        rfc_message_id=message_id(uuid.uuid4()),
        created_at=now(),
    )


def test_utf8_headers_plain_text_and_base64url():
    data = values()
    raw = serialize(**data)
    assert "+" not in raw and "/" not in raw
    decoded = base64.urlsafe_b64decode(raw)
    assert b"\n" not in decoded.replace(b"\r\n", b"")
    msg = BytesParser(policy=policy.default).parsebytes(decoded)
    assert str(msg["Subject"]) == data["subject"]
    assert str(msg["From"]) == data["sender"] and str(msg["To"]) == data["recipient"]
    assert str(msg["Message-ID"]).strip() == data["rfc_message_id"]
    assert (
        msg.get_content_type() == "text/plain" and msg.get_content_charset() == "utf-8"
    )
    assert (
        msg.get_content().replace("\r\n", "\n")
        == data["body"].replace("\r\n", "\n") + "\n"
    )
    assert not msg["Bcc"] and not msg["Cc"] and not msg.is_multipart()
    assert raw == serialize(**data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sender", "sender@example.com\r\nBcc: other@example.com"),
        ("recipient", "person@example.org,other@example.org"),
        ("recipient", "Display <person@example.org>"),
        ("recipient", "invalid"),
        ("recipient", "person@example.org\n"),
        ("subject", "Hello\r\nBcc: other@example.org"),
        ("subject", "bad\x00subject"),
        ("rfc_message_id", "<arbitrary@example.org>"),
        ("body", "null\x00body"),
    ],
)
def test_header_injection_and_invalid_inputs_rejected(field, value):
    data = values() | {field: value}
    with pytest.raises(ValueError):
        serialize(**data)


def test_message_id_is_deterministic_and_unique():
    first, second = uuid.uuid4(), uuid.uuid4()
    assert message_id(first) == message_id(first) != message_id(second)
