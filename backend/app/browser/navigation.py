"""Resume a page the owner reached manually; never navigate, save or submit a step."""

from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import Field, StrictBool

from backend.app.browser.contracts import DetectedField
from backend.app.browser.runner import DETECT, browser, origin, validate_destination
from backend.app.browser.service import analyze, metadata, status
from backend.app.core.config import get_settings
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import RevisionInput
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.profile_link_resolver import normalize


class ResumePage(RevisionInput):
    capture_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_same_application: StrictBool


async def capture(session, packet_id, revision):
    service = ApplicationPacketService(session)
    packet, _, _ = await service.locked(packet_id, revision)
    runtime = browser.sessions.get(str(packet_id))
    if not runtime or runtime.cancelled or runtime.page.is_closed():
        raise HTTPException(
            409, "Open the dedicated browser before reviewing this page"
        )
    if not (runtime.manual or runtime.paused_for_resume):
        raise HTTPException(
            409, "Use Take Over before reviewing a manually reached page"
        )
    url, epoch = runtime.page.url, runtime.document_epoch
    if origin(url) != runtime.target:
        raise HTTPException(403, "Resuming a different origin is not supported")
    await validate_destination(url, get_settings())
    # Stop owner-mode networking before reading the form. This is a pause, not
    # permission to fill or an indication that a server accepted the prior step.
    runtime.paused_for_resume = True
    await runtime.set_manual(False)
    result = await runtime.page.evaluate(DETECT)
    if result["blocked"]:
        raise HTTPException(
            409, "Resolve access or authentication manually before resuming"
        )
    if result["has_frames"]:
        raise HTTPException(409, "Embedded application pages require manual handoff")
    fields = [DetectedField.model_validate(field) for field in result["fields"]]
    if not fields or not any(field.supported for field in fields):
        raise HTTPException(409, "No supported application fields; continue manually")
    job = await session.get(Job, packet.job_id)
    company = await session.get(Company, job.company_id) if job.company_id else None
    heading = normalize(result["title"] + " " + result["heading"])
    if (
        not company
        or normalize(company.name) not in heading
        or normalize(job.title) not in heading
    ):
        raise HTTPException(
            409, "Page does not establish the saved company and role; continue manually"
        )
    if runtime.page.url != url or runtime.document_epoch != epoch:
        raise HTTPException(409, "Page changed during review; capture it again")
    bound = {
        "packet_id": str(packet.id),
        "job_id": str(packet.job_id),
        "revision": packet.revision,
        "url": url,
        "document_epoch": epoch,
        "browser_instance": runtime.instance_id,
        "form": result["signature"],
        "title": result["title"],
        "heading": result["heading"],
    }
    parsed = urlsplit(url)
    view = {
        "expected_revision": packet.revision,
        "capture_digest": digest(bound),
        "display_url": parsed._replace(query="", fragment="").geturl(),
        "title": result["title"],
        "heading": result["heading"],
        "questions": [
            {
                "question": field.question,
                "required": field.required,
                "supported": field.supported,
            }
            for field in fields
        ],
        "warning": "Page networking is paused. Confirm this is the same application, then review fresh answers before filling. No navigation, server save, submission or earlier action will be replayed.",
    }
    return service, packet, runtime, url, view


async def preview(session, packet_id, revision):
    *_, view = await capture(session, packet_id, revision)
    return view


async def resume(session, packet_id, data):
    if not data.confirm_same_application:
        raise HTTPException(
            422, "Confirm that this page belongs to the same application"
        )
    service, packet, runtime, url, view = await capture(
        session, packet_id, data.expected_revision
    )
    if view["capture_digest"] != data.capture_digest:
        raise HTTPException(409, "Page or form changed; review a fresh page preview")
    saved = await metadata(session, packet_id)
    history = list(saved.value.get("navigation_history", [])) if saved else []
    if len(history) >= 20:
        raise HTTPException(409, "Too many page resumptions; continue manually")
    old_url = runtime.url
    try:
        runtime.url, runtime.paused_for_resume = url, False
        runtime.blocked_step_requests = 0
        await analyze(session, packet, service, runtime)
        saved = await metadata(session, packet_id)
        saved.value = {
            **saved.value,
            "diagnostic": "owner_page_resumed",
            "navigation_history": [
                *history,
                {
                    "capture_digest": data.capture_digest,
                    "url_digest": digest(url),
                    "revision": packet.revision,
                    "outcome": "owner_page_resumed",
                },
            ],
        }
        await session.commit()
    except BaseException:
        runtime.url, runtime.paused_for_resume = old_url, True
        raise
    return await status(session, packet_id)
