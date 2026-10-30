"""A GET-only Gmail client. No arbitrary paths, mailbox writes or raw bodies at rest."""

import asyncio
import base64
import json
import re
from html.parser import HTMLParser

import httpx
from pydantic import TypeAdapter

from backend.app.core.urls import PublicHTTPSURL
from backend.app.integrations.token_store import ConnectionError

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.hidden = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag == "a" and not self.hidden:
            self.links.extend(v for k, v in attrs if k == "href" and v)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def content_evidence(payload):
    """Bound depth/parts/decoded bytes; ignore attachments, hidden HTML and unsafe links."""
    texts, links, remaining, parts_seen = [], [], 262144, 0

    def walk(part, depth=0):
        nonlocal remaining, parts_seen
        parts_seen += 1
        if depth > 12 or parts_seen > 100 or not isinstance(part, dict):
            raise ConnectionError("gmail_mime_limits")
        if part.get("filename") or (part.get("body") or {}).get("attachmentId"):
            return
        mime = part.get("mimeType")
        if mime in {"text/plain", "text/html"}:
            encoded = (part.get("body") or {}).get("data", "")
            if not isinstance(encoded, str) or len(encoded) > 350000:
                raise ConnectionError("gmail_mime_limits")
            try:
                raw = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                )
            except (ValueError, TypeError):
                raise ConnectionError("gmail_mime_invalid") from None
            remaining -= len(raw)
            if remaining < 0:
                raise ConnectionError("gmail_mime_limits")
            text = raw.decode("utf-8", errors="replace")
            if mime == "text/html":
                parser = TextHTML()
                parser.feed(text)
                links.extend(parser.links)
                text = " ".join(parser.text)
            texts.append(text)
            links.extend(re.findall(r"https://[^\s<>\"']+", text))
        for child in part.get("parts", []):
            walk(child, depth + 1)

    walk(payload)
    safe = []
    for link in links[:200]:
        try:
            from urllib.parse import urlsplit, urlunsplit

            parsed = urlsplit(str(TypeAdapter(PublicHTTPSURL).validate_python(link)))
            # Query strings often include personal/tracking tokens. Never retain them.
            clean = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            if clean not in safe:
                safe.append(clean)
        except ValueError:
            continue
    text = " ".join(texts).casefold()
    signals = [
        name
        for name, pattern in {
            "possible_interview": r"\binterview\b",
            "possible_rejection": r"\b(?:unfortunately|not moving forward)\b",
            "possible_acknowledgment": r"\b(?:application received|received your application)\b",
            "possible_job_lead": r"\b(?:job alert|vacanc|hiring|open position|job opening)\b",
            "possible_recruiter_response": r"\b(?:recruit(?:er|ing|ment)|talent acquisition)\b.{0,100}\b(?:response|reply|opportunity|reach(?:ing)? out|discuss)\b",
            "possible_follow_up_request": r"\b(?:please|kindly)\b.{0,100}\b(?:provide|share|reply|respond|confirm|complete|send)\b|\bfollow[ -]?up\b",
            "possible_status_update": r"\b(?:application status|status of your application|application update|under review|next stage|next steps)\b",
        }.items()
        if re.search(pattern, text)
    ]
    return {
        "links": safe[:25],
        "signals": signals,
        "verification_status": "requires_review",
        "submission_confirmed": False,
        "signal_basis": "selected_message_body_keywords",
        "status_confirmed": False,
    }


class GmailReadClient:
    def __init__(self, token, client=None):
        self.token, self.client = token, client
        from backend.app.integrations.logging import install_provider_log_filter

        install_provider_log_filter()

    async def get(self, path, params):
        if path.rsplit("/", 1)[-1] in {
            "send",
            "modify",
            "trash",
            "untrash",
            "delete",
            "import",
            "insert",
            "batchDelete",
            "batchModify",
        } or (
            path != "messages"
            and not re.fullmatch(r"messages/[A-Za-z0-9_-]{1,200}", path)
        ):
            raise ConnectionError("gmail_read_operation_denied")

        async def request(client):
            async with asyncio.timeout(20):
                async with client.stream(
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/" + path,
                    params=params,
                    headers={"Authorization": "Bearer " + self.token},
                    timeout=15,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {401, 403}:
                        raise ConnectionError("gmail_read_permission_required")
                    if response.status_code == 429:
                        raise ConnectionError("gmail_read_rate_limited")
                    if response.status_code != 200:
                        raise ConnectionError("gmail_read_upstream_error")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1048576:
                            raise ConnectionError("gmail_read_response_limit")
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise ConnectionError("gmail_read_invalid_response")
                    return data

        try:
            if self.client:
                return await request(self.client)
            async with httpx.AsyncClient(trust_env=False) as client:
                return await request(client)
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            if isinstance(exc, ConnectionError):
                raise
            raise ConnectionError("gmail_read_transport_or_response_error") from None

    async def messages(self, *, labels, query=None, page_token=None, limit=25):
        params = [("maxResults", str(min(25, max(1, limit))))]
        params.extend(("labelIds", label) for label in labels)
        if query:
            params.append(("q", query))
        if page_token:
            params.append(("pageToken", page_token))
        return await self.get("messages", params)

    async def message(self, message_id, *, body=False):
        if not isinstance(message_id, str) or not IDENTIFIER.fullmatch(message_id):
            raise ConnectionError("gmail_message_id_invalid")
        return await self.get(
            "messages/" + message_id,
            [
                ("format", "full" if body else "metadata"),
                ("metadataHeaders", "From"),
                ("metadataHeaders", "Subject"),
                ("metadataHeaders", "Date"),
                ("metadataHeaders", "To"),
                ("metadataHeaders", "Message-ID"),
                ("metadataHeaders", "Authentication-Results"),
            ],
        )
