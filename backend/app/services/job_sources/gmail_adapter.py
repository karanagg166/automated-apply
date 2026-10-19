"""Gmail Job Alert Adapter for extracting normalized job opportunities from job alert emails."""

import re
import hashlib
from datetime import datetime, timezone
from typing import Any
import httpx

from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.base import JobSourceAdapter


class GmailJobAlertAdapter(JobSourceAdapter):
    """Adapter for ingesting and parsing job alert emails received in Gmail."""

    source_name = "gmail_alert"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.client_id = client_id or settings.GMAIL_CLIENT_ID
        self.client_secret = client_secret or settings.GMAIL_CLIENT_SECRET
        self.refresh_token = refresh_token or settings.GMAIL_REFRESH_TOKEN
        self._client = http_client

    def parse_alert_html_or_text(
        self,
        message_id: str,
        subject: str,
        sender: str,
        body: str,
        received_at: datetime | None = None,
    ) -> list[NormalizedJob]:
        """Parse structured job opportunities out of typical job alert email bodies (Naukri, Indeed, LinkedIn alerts)."""
        now = received_at or datetime.now(timezone.utc)
        normalized: list[NormalizedJob] = []

        # 1. Identify alert origin
        sender_lower = sender.lower()
        sub_lower = subject.lower()

        alert_type = "generic"
        if "naukri" in sender_lower or "naukri" in sub_lower:
            alert_type = "naukri_alert"
        elif "indeed" in sender_lower or "indeed" in sub_lower:
            alert_type = "indeed_alert"
        elif "linkedin" in sender_lower or "linkedin" in sub_lower:
            alert_type = "linkedin_alert"
        elif "instahyre" in sender_lower or "instahyre" in sub_lower:
            alert_type = "instahyre_alert"

        # Regex patterns for common job block formats in email alerts
        # Look for links with anchor text or URL patterns
        # Example pattern: [Job Title] at [Company] - [Location]
        # Or HTML links: <a href="url">Job Title</a> ... Company: X

        # Strip heavy html tags
        clean_text = re.sub(r"<[^>]+>", " ", body)
        clean_text = re.sub(r"\s+", " ", clean_text)

        # Look for explicit job links in HTML
        link_matches = re.findall(
            r'href=[\'"](https?://[^\'">]+(?:job|viewjob|posting|careers)[^\'">]*)[\'"][^>]*>([^<]+)</a>',
            body,
            re.I,
        )

        if link_matches:
            for job_url, link_text in link_matches[:10]:
                title = link_text.strip()
                if (
                    len(title) < 3
                    or "unsubscribe" in title.lower()
                    or "view" in title.lower()
                    or "privacy" in title.lower()
                ):
                    continue

                # Search surrounding text for company and location
                company_match = re.search(
                    r"\b(?:at|with|by|company[:\s]+)\s+([A-Za-z0-9&.,]+(?:\s+[A-Za-z0-9&.,]+)?)",
                    clean_text,
                    re.I,
                )
                company_name = company_match.group(1).strip() if company_match else None

                loc_match = re.search(
                    r"\b(?:in|location[:\s]+)\s+([A-Za-z\s,]{2,30})", clean_text, re.I
                )
                location = loc_match.group(1).strip() if loc_match else None

                job = NormalizedJob(
                    source_name="gmail_alert",
                    source_job_id=f"gmail_{message_id}_{hashlib.sha256(job_url.encode()).hexdigest()[:24]}",
                    original_url=job_url,
                    company_name=company_name,
                    company_domain=None,
                    title=title,
                    description=f"Received via job alert email: '{subject}' from {sender}",
                    location=location,
                    is_remote="remote" in (str(location).lower() + title.lower()),
                    remote_type="remote"
                    if "remote" in (str(location).lower() + title.lower())
                    else "unspecified",
                    employment_type=None,
                    salary_raw=None,
                    skills_required=[],
                    application_url=job_url,
                    date_posted=None,
                    last_observed_date=now,
                    retrieved_at=now,
                    data_provenance={
                        "adapter": "GmailJobAlertAdapter",
                        "email_message_id": message_id,
                        "email_sender": sender,
                        "email_subject": subject,
                        "alert_type": alert_type,
                    },
                    is_confirmed_current=False,
                )
                normalized.append(job)

        return normalized

    async def fetch_jobs(
        self,
        query: str = "from:(alert OR jobalerts OR jobs-noreply)",
        max_messages: int = 10,
        **kwargs: Any,
    ) -> list[NormalizedJob]:
        """Fetch and parse job alert messages via Gmail REST API using OAuth refresh token."""
        if not (self.client_id and self.client_secret and self.refresh_token):
            logger.info(
                "Gmail OAuth credentials not configured. Ingestion ready in offline/parser mode."
            )
            return []

        client = self._client or httpx.AsyncClient(timeout=30.0)
        close_client = self._client is None

        try:
            # 1. Exchange refresh token for access token
            oauth_endpoint = "https://oauth2.googleapis.com/token"
            token_resp = await client.post(
                oauth_endpoint,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if token_resp.status_code != 200:
                logger.error("Gmail token refresh failed")
                return []
            access_token = token_resp.json()["access_token"]

            # 2. List matching messages
            list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
            headers = {"Authorization": f"Bearer {access_token}"}
            list_resp = await client.get(
                list_url,
                headers=headers,
                params={"q": query, "maxResults": max_messages},
            )
            if list_resp.status_code != 200:
                logger.error("Failed to list Gmail messages")
                return []

            messages = list_resp.json().get("messages", [])
            all_jobs: list[NormalizedJob] = []

            for msg_meta in messages:
                msg_id = msg_meta["id"]
                msg_url = (
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
                )
                detail_resp = await client.get(
                    msg_url, headers=headers, params={"format": "full"}
                )
                if detail_resp.status_code != 200:
                    continue

                detail = detail_resp.json()
                headers_list = detail.get("payload", {}).get("headers", [])
                subject = next(
                    (
                        h["value"]
                        for h in headers_list
                        if h["name"].lower() == "subject"
                    ),
                    "No Subject",
                )
                sender = next(
                    (h["value"] for h in headers_list if h["name"].lower() == "from"),
                    "Unknown Sender",
                )
                snippet = detail.get("snippet", "")

                parsed = self.parse_alert_html_or_text(
                    message_id=msg_id,
                    subject=subject,
                    sender=sender,
                    body=snippet,
                )
                all_jobs.extend(parsed)

            return all_jobs
        except Exception as e:
            logger.error(f"Error reading Gmail alerts: {e}")
            return []
        finally:
            if close_client:
                await client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        """Test connection status for Gmail integration."""
        if not (self.client_id and self.client_secret and self.refresh_token):
            return {
                "status": "not_attempted",
                "source": self.source_name,
                "sample_count": 0,
                "message": "Gmail OAuth credentials (client ID/secret/refresh token) not yet set in environment. Offline email alert parser is fully functional.",
                "details": {
                    "is_parser_ready": True,
                    "supported_email_sources": [
                        "naukri_alerts",
                        "indeed_alerts",
                        "linkedin_alerts",
                        "instahyre_alerts",
                    ],
                },
            }

        client = self._client or httpx.AsyncClient(timeout=15.0)
        close_client = self._client is None
        try:
            oauth_endpoint = "https://oauth2.googleapis.com/token"
            token_resp = await client.post(
                oauth_endpoint,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if token_resp.status_code == 200:
                return {
                    "status": "passed",
                    "source": self.source_name,
                    "sample_count": 0,
                    "message": "Gmail OAuth token successfully refreshed and verified with Google API",
                    "details": {},
                }
            else:
                return {
                    "status": "failed",
                    "source": self.source_name,
                    "sample_count": 0,
                    "message": f"Gmail token refresh failed with HTTP {token_resp.status_code}",
                    "details": {},
                }
        except Exception as e:
            return {
                "status": "failed",
                "source": self.source_name,
                "sample_count": 0,
                "message": f"Gmail connection test failed: {e}",
                "details": {},
            }
        finally:
            if close_client:
                await client.aclose()
