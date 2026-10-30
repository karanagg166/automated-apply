"""Offline approved sender/recipient fixtures shared with disposable PostgreSQL tests."""

from datetime import timedelta

from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.gmail.schemas import GmailAcceptance, SendRequest
from backend.app.integrations.google_oauth import SEND_SCOPES, GoogleOAuth
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.schemas.outreach import DraftInput
from backend.app.services.outreach_drafting import OutreachDraftingService
from backend.tests.phase4a_fakes import (
    CALLBACK,
    EMAIL,
    GoogleFixture,
    oauth_settings,
    state_from,
    target,
)


class SendFixture:
    def __init__(self):
        self.calls = []
        self.failure = None

    async def send(self, token, raw):
        self.calls.append((token, raw))
        if self.failure:
            raise self.failure
        return GmailAcceptance(id="mock-message-123", threadId="mock-thread-123")


async def approved_target(session, settings, *, suffix="one"):
    contact, company, job, evidence = await target(
        session, email_status="verified", suffix=suffix
    )
    mailbox = ContactEvidence(
        contact_id=contact.id,
        company_id=company.id,
        source="manual",
        evidence_type="mailbox_verification",
        user_confirmed=True,
        expires_at=now() + timedelta(days=30),
        provenance={
            "email": contact.email,
            "result": "deliverable",
            "method": "owner_confirmation",
        },
    )
    session.add(mailbox)
    await session.commit()
    drafts = OutreachDraftingService(session, settings)
    draft = await drafts.create(
        DraftInput(contact_id=contact.id, job_id=job.id, use_llm=False)
    )
    result = await drafts.decide(draft["id"], draft["draft_revision"], True)
    await session.commit()
    return result, contact, evidence, mailbox


def request_from(preview, key="owner-request-123"):
    return SendRequest(
        expected_revision=preview["draft_revision"],
        approval_hash=preview["approval_hash"],
        confirmation_token=preview["confirmation_token"],
        sender_account_id=preview["sender_account_id"],
        idempotency_key=key,
    )


async def connect_sender(session, settings, fake, http):
    connection = ConnectionService(session, settings, GoogleOAuth(settings, http))
    state = state_from(await connection.start(EMAIL, "browser"))
    await connection.callback(state, "browser", CALLBACK, "code")
    fake.token["scope"] = " ".join(sorted(SEND_SCOPES))
    state = state_from(await connection.start(EMAIL, "browser", send=True))
    await connection.callback(state, "browser", CALLBACK, "upgrade-code")
    return connection


async def bundle():
    # Caller owns fake HTTP context lifetime.
    settings, google = oauth_settings(GMAIL_SENDING_ENABLED=True, GMAIL_READ_DRAFT_ONLY=False), GoogleFixture()
    return settings, google
