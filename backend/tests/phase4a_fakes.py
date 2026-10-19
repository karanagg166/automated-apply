"""Fictional Google and candidate fixtures. All HTTP goes through MockTransport."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.fernet import Fernet

from backend.app.core.config import Settings
from backend.app.integrations.google_oauth import SCOPES
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.models.job import Job

EMAIL = "secondary@example.com"
CALLBACK = "https://localhost/api/v1/integrations/gmail/oauth/callback"


def oauth_settings(**kwargs):
    return Settings(
        _env_file=None,
        GMAIL_CLIENT_ID="fictional-client.apps.googleusercontent.com",
        GMAIL_CLIENT_SECRET="fictional-client-secret",
        GMAIL_REDIRECT_URI=CALLBACK,
        OAUTH_ENCRYPTION_KEYS={"test-v1": Fernet.generate_key().decode()},
        OAUTH_ACTIVE_KEY_ID="test-v1",
        **kwargs,
    )


def state_from(result):
    return parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]


class GoogleFixture:
    def __init__(self):
        self.requests = []
        self.token = {
            "access_token": "fictional-access",
            "refresh_token": "fictional-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": " ".join(sorted(SCOPES)),
        }
        self.identity = {
            "sub": "fictional-stable-subject",
            "email": EMAIL,
            "email_verified": True,
        }
        self.gmail_email = EMAIL
        self.fail = None

    def respond(self, request):
        self.requests.append(request)
        if self.fail and self.fail in request.url.path:
            return httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "secret must not escape",
                },
            )
        if request.url.path == "/token":
            return httpx.Response(200, json=self.token)
        if request.url.path == "/v1/userinfo":
            return httpx.Response(200, json=self.identity)
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": self.gmail_email})
        if request.url.path == "/revoke":
            return httpx.Response(200)
        raise AssertionError("Unexpected Google endpoint: " + request.url.path)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.respond))


async def target(session, email_status="provider_reported", suffix="one"):
    company = Company(
        name="Example Startup " + suffix,
        domain=f"{suffix}.example.com",
        metadata_={
            "employee_count": 12,
            "startup_intelligence": {"technologies": ["Python"], "source": "wellfound"},
        },
    )
    session.add(company)
    await session.flush()
    contact = Contact(
        company_id=company.id,
        full_name="Taylor Example",
        role_title="CTO",
        email=f"taylor@{suffix}.example.com",
        email_status=email_status,
        linkedin_url="https://www.linkedin.com/in/taylor-example",
        last_checked_at=now(),
        last_reviewed_at=now(),
        last_verified_at=now(),
        metadata_={"evidence_strength": "strong"},
    )
    session.add(contact)
    await session.flush()
    evidence = ContactEvidence(
        contact_id=contact.id,
        company_id=company.id,
        source="public_search",
        evidence_type="identity",
        observed_company=company.name,
        observed_role="CTO",
        evidence_url=f"https://{suffix}.example.com/team",
        strength="strong",
        expires_at=now() + timedelta(days=30),
    )
    job = Job(
        company_id=company.id,
        title="Backend Engineer",
        job_url=f"https://{suffix}.example.com/jobs/1",
        source_platform="manual",
        skills_required=["Python"],
        description="Backend work using Python and FastAPI",
    )
    session.add_all([evidence, job])
    await session.commit()
    return contact, company, job, evidence
