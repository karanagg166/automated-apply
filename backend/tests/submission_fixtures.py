"""Entirely fictional owner, employer and canonical PDF for submission acceptance."""

import hashlib
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr

from backend.app.agent import store
from backend.app.agent.contracts import Message
from backend.app.agent.executor import CommandExecutor
from backend.app.browser.contracts import FillReceipt, Inspection
from backend.app.browser.service import FormService
from backend.app.browser.submission import SubmissionService
from backend.app.browser.submission_contracts import SubmissionApproval
from backend.app.dashboard.models import PrivateResume
from backend.app.local_agent.contracts import Actor
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.app.schemas.applications import CreatePacket
from backend.app.services.applications.service import ApplicationPacketService
from backend.tests.phase5a_fakes import target
from backend.tests.test_browser_forms import config

OWNER = Actor(channel="owner", identity="primary")


async def candidate(session, profile, origin, adapter="greenhouse", slug="success"):
    settings = config(
        BROWSER_SUBMIT_ENABLED=True,
        BROWSER_FIXTURE_ORIGIN=origin,
        TELEGRAM_OWNER_USER_ID=111,
        TELEGRAM_OWNER_CHAT_ID=111,
    )
    job, resource = await target(session, profile)
    job.source_platform = "greenhouse" if adapter == "google" else adapter
    job.job_url = "https://boards.greenhouse.io/fictional/jobs/1"
    job.application_url = (
        f"{origin}/fixtures/{adapter}/example-circuit/jobs/{slug}/apply"
    )
    job.location, job.employment_type = "India", "full_time"
    raw = b"%PDF-1.4\nFictional canonical resume only\n%%EOF"
    encryption = Fernet.generate_key()
    private = PrivateResume(
        label="Fictional canonical",
        ciphertext=Fernet(encryption).encrypt(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        confirmed=True,
        resource_id=resource.id,
    )
    session.add(private)
    await session.flush()
    resource.source_type, resource.url = (
        "private_upload",
        "private-resume:" + str(private.id),
    )
    await confirm_profile(session, profile, profile.version)
    await session.commit()
    return (
        settings.model_copy(
            update={"RESUME_ENCRYPTION_KEY": SecretStr(encryption.decode())}
        ),
        job,
        private,
    )


async def reviewed(
    session, profile, origin="http://127.0.0.1:18765", adapter="greenhouse"
):
    settings, job, private = await candidate(session, profile, origin, adapter)
    packet = await ApplicationPacketService(session).create(
        job.id, CreatePacket(idempotency_key="fictional-submission-packet")
    )
    campaign = await store.intake(
        session, settings, OWNER, Message(text="Fill the first application")
    )
    row, _ = await store.load(session, campaign.id)
    campaign.plan.selected_jobs, campaign.state = [job.id], "completed"
    store.save(row, campaign)
    form = FormService(session, settings)
    from uuid import uuid4

    plan = await form.inspect(
        packet.id,
        Inspection(
            document_id=str(uuid4()),
            url=job.application_url,
            fields=[
                {
                    "field_id": "f0",
                    "kind": "text",
                    "label": "Full name",
                    "required": True,
                }
            ],
            has_submit=True,
        ),
        "local_automation",
    )
    await form.review(plan.id, ["f0"])
    await form.consume(plan.id, "local_automation")
    await form.receipt(
        FillReceipt(
            plan_id=plan.id,
            state="form_filled",
            results=[{"field_id": "f0", "status": "filled"}],
        )
    )
    service = SubmissionService(session, settings)
    s = await service.create_review(
        plan.id,
        campaign.id,
        {
            "state": "reviewable",
            "document_id": plan.inspection.document_id,
            "document_digest": "a" * 64,
        },
    )
    await session.commit()
    return settings, s, private


def approval(s, **changes):
    return SubmissionApproval(
        nonce=s.nonce,
        review_digest=s.review_digest,
        campaign_revision=s.campaign_revision,
        application_ids=[s.application_id],
    ).model_copy(update=changes)


async def authorized(session, settings, s):
    service = SubmissionService(session, settings)
    await service.approve(s.application_id, OWNER, approval(s))
    await service.release(s.application_id, OWNER)
    await session.commit()


def acknowledgment(s, *, url=None, status="received"):
    import json

    return {
        "url": url or s.request_url,
        "status": 200,
        "content_type": "application/json",
        "body": json.dumps(
            {
                "status": status,
                "correlation_id": str(s.idempotency_key),
                "application": {"id": "fixture-accepted-1"},
            }
        ),
    }


async def command(session, factory, settings, text):
    accepted = await store.intake(session, settings, OWNER, Message(text=text))
    await session.commit()
    result = await CommandExecutor(factory, settings).run_once()
    assert result and result.id == accepted.id
    return result


async def submission_for(session, settings, application_id):
    return (await SubmissionService(session, settings).load(UUID(str(application_id))))[
        1
    ]
