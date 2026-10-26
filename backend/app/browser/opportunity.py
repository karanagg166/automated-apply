"""Fixed DOM capture and exact owner-reviewed opportunity context; no arbitrary fetch."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from pydantic import Field, StrictBool

from backend.app.browser.runner import browser
from backend.app.core.config import get_settings
from backend.app.knowledge.opportunity import (
    KEY,
    binding,
    evidence_key,
    unsafe_instruction,
)
from backend.app.models.company import Company
from backend.app.schemas.applications import PacketEdit, RevisionInput
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.profile_link_resolver import normalize

EXTRACT = Path(__file__).with_suffix(".js").read_text()


class ReviewOpportunity(RevisionInput):
    capture_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    job_text: str = Field(min_length=1, max_length=4000)
    company_text: str = Field(default="", max_length=4000)
    confirm_company_job_and_source: StrictBool
    company_source_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


async def capture(session, packet_id, revision):
    if not get_settings().OPPORTUNITY_CONTEXT_ENABLED:
        raise HTTPException(503, "Reviewed opportunity context is disabled")
    service = ApplicationPacketService(session)
    packet, _, _ = await service.locked(packet_id, revision)
    from backend.app.models.job import Job

    job = await session.get(Job, packet.job_id)
    company = await session.get(Company, job.company_id) if job.company_id else None
    runtime = browser.sessions.get(str(packet_id))
    if not runtime or runtime.manual:
        raise HTTPException(
            409, "Open the dedicated browser and analyze this page first"
        )
    await runtime.scan()  # exact destination, connected state and access challenges
    heading = normalize(
        runtime.context_evidence.get("heading", "")
        + " "
        + runtime.context_evidence.get("title", "")
    )
    if (
        not company
        or normalize(company.name) not in heading
        or normalize(job.title) not in heading
    ):
        raise HTTPException(
            409,
            "Page title and heading do not establish the saved company and role; use manual context review",
        )
    text = await runtime.page.evaluate(EXTRACT)
    if not text["job_text"]:
        raise HTTPException(
            409,
            "No unambiguous public job description found; prepare the answer manually",
        )
    snapshot = {
        **text,
        "source_url": runtime.url,
        "company_name": company.name if company else None,
        "job_title": job.title,
        "binding": binding(job, company),
    }
    return {
        **snapshot,
        "capture_digest": digest(snapshot),
        "expected_revision": packet.revision,
    }


async def approve(session, packet_id, data):
    if not data.confirm_company_job_and_source:
        raise HTTPException(
            422, "Review the actual company, job and source before saving"
        )
    current = await capture(session, packet_id, data.expected_revision)
    if data.company_source_token:
        from backend.app.browser.company_source import enrich

        current = enrich(packet_id, current, data.company_source_token)
    if data.capture_digest != current["capture_digest"]:
        raise HTTPException(
            409, "Page or job context changed; capture and review again"
        )
    if unsafe_instruction(data.job_text + " " + data.company_text):
        raise HTTPException(
            422,
            "Excerpt contains instruction-like website text; remove it and review again",
        )
    # Owner can shorten the excerpt, never add content attributed to the website.
    if data.job_text not in current["job_text"] or (
        data.company_text and data.company_text not in current["company_text"]
    ):
        raise HTTPException(
            422, "Reviewed excerpts must occur verbatim in the captured page"
        )
    service = ApplicationPacketService(session)
    packet, _, _ = await service.locked(packet_id, data.expected_revision)
    from backend.app.models.job import Job

    job = await session.get(Job, packet.job_id)
    reviewed = {
        "binding": current["binding"],
        "source_url": current["source_url"],
        "job_text": data.job_text,
        "company_text": data.company_text,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if data.company_source_token and data.company_text:
        reviewed.update(
            {
                key: current[key]
                for key in (
                    "company_source_url",
                    "company_source_title",
                    "company_source_fetched_at",
                )
            }
        )
    reviewed["digest"] = digest(reviewed)
    from backend.app.dashboard.models import OwnerPreference

    # Keep evidence referenced by saved drafts after the canonical current context changes.
    key = evidence_key(reviewed["digest"])
    previous = await session.get(OwnerPreference, key)
    if previous and previous.value.get("digest") != reviewed["digest"]:
        raise HTTPException(409, "Evidence key collision; no context was changed")
    if not previous:
        session.add(OwnerPreference(key=key, value={**reviewed, "job_id": str(job.id)}))
    job.discovery_metadata = {**(job.discovery_metadata or {}), KEY: reviewed}
    await session.flush()
    # The canonical packet refresh invalidates old review/answers and increments
    # the existing revision. The evidence is included in its context digest.
    await service.edit(
        packet_id,
        PacketEdit(expected_revision=data.expected_revision, refresh_saved_data=True),
    )
    return {
        "saved": True,
        "source_url": reviewed["source_url"],
        "digest": reviewed["digest"],
    }
