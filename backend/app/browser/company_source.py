"""Reviewed public employer evidence through the existing opportunity workflow."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.browser.company_source_policy import source_url
from backend.app.browser.runner import browser, origin, validate_destination
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import RevisionInput
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService


class ReadCompanySource(RevisionInput):
    source_url: str = Field(min_length=1, max_length=2048)
    confirm_public_source_permission: StrictBool


def permitted_url(value):
    settings = get_settings()
    if (
        not settings.OPPORTUNITY_CONTEXT_ENABLED
        or not settings.COMPANY_SOURCE_FETCH_ENABLED
    ):
        raise HTTPException(503, "Public company source reading is disabled")
    try:
        url = source_url(value, testing=settings.ENVIRONMENT == "testing")
    except ValueError:
        raise HTTPException(422, "Unsupported public company source URL") from None
    if url not in settings.COMPANY_SOURCE_URLS:
        raise HTTPException(
            403, "This exact public page has no configured reading permission"
        )
    return url


async def reserve(session, job_id):
    instant = datetime.now(timezone.utc).timestamp()
    key = "cs-rate:" + str(job_id)
    insert = (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    await session.execute(
        insert(OwnerPreference).values(key=key, value={}).on_conflict_do_nothing()
    )
    row = await session.scalar(
        select(OwnerPreference).where(OwnerPreference.key == key).with_for_update()
    )
    value = row.value
    if value and instant - value["last"] < 60:
        raise HTTPException(
            429,
            "Wait before reading another source; use the existing preview or read manually",
        )
    if value and instant - value["window"] < 3600:
        if value["requests"] >= 4:
            raise HTTPException(429, "Public source reading limit reached for this job")
    else:
        value = {"window": instant, "requests": 0}
    row.value = {**value, "last": instant, "requests": value["requests"] + 1}
    # Preserve the request reservation and one-use owner proof before external I/O.
    await session.commit()


def enrich(packet_id, captured, token):
    runtime = browser.sessions.get(str(packet_id))
    saved = runtime.company_capture if runtime else None
    if (
        not saved
        or saved["token"] != token
        or saved["expires"] < datetime.now(timezone.utc).timestamp()
        or saved["base_capture_digest"] != captured["capture_digest"]
        or saved["revision"] != captured["expected_revision"]
        or saved["instance"] != runtime.instance_id
        or saved["document"] != runtime.document_epoch
        or permitted_url(saved["source_url"]) != saved["source_url"]
    ):
        raise HTTPException(
            409, "Company source preview expired or changed; capture and review again"
        )
    result = {
        **captured,
        "company_text": saved["company_text"],
        "company_source_url": saved["source_url"],
        "company_source_title": saved["source_title"],
        "company_source_fetched_at": saved["fetched_at"],
        "company_source_token": token,
    }
    result["capture_digest"] = digest(
        {k: v for k, v in result.items() if k != "capture_digest"}
    )
    return result


async def preview(session, packet_id, data):
    from backend.app.browser.opportunity import capture

    if not data.confirm_public_source_permission:
        raise HTTPException(
            422, "Confirm the official public source and its reading permission first"
        )
    url = permitted_url(data.source_url)
    captured = await capture(session, packet_id, data.expected_revision)
    runtime = browser.sessions[str(packet_id)]
    cached = runtime.company_capture
    if cached and cached["source_url"] == url:
        try:
            return enrich(packet_id, captured, cached["token"])
        except HTTPException:
            pass
    packet, _, _ = await ApplicationPacketService(session).locked(
        packet_id, data.expected_revision
    )
    job = await session.get(Job, packet.job_id)
    company = await session.get(Company, job.company_id)
    host = urlsplit(url).hostname
    if company.domain and host.removeprefix(
        "www."
    ) != company.domain.casefold().removeprefix("www."):
        raise HTTPException(
            409,
            "Company source differs from the saved employer domain; correct its identity first",
        )
    _, addresses = await validate_destination(
        url, get_settings(), return_addresses=True, allowed_origins=[origin(url)]
    )
    job_id, company_name = job.id, company.name
    instance, document = runtime.instance_id, runtime.document_epoch
    await reserve(session, job_id)
    browser.operations.checkpoint(packet_id)
    try:
        result = await runtime.resources.company_source.fetch(
            {
                "url": url,
                "address": addresses[0],
                "testing": get_settings().ENVIRONMENT == "testing",
                "company_name": company_name,
            }
        )
    except (ValueError, OSError, TimeoutError):
        raise HTTPException(
            409, "Public company source unavailable or unsupported; read it manually"
        ) from None
    browser.operations.checkpoint(packet_id)
    if (
        runtime is not browser.sessions.get(str(packet_id))
        or runtime.instance_id != instance
        or runtime.document_epoch != document
        or runtime.cancelled
    ):
        raise HTTPException(409, "Browser changed during source reading; review again")
    current = await capture(session, packet_id, data.expected_revision)
    if (
        current["capture_digest"] != captured["capture_digest"]
        or result["source_url"] != url
    ):
        raise HTTPException(
            409, "Application context changed during source reading; review again"
        )
    instant = datetime.now(timezone.utc)
    saved = {
        **result,
        "base_capture_digest": captured["capture_digest"],
        "revision": data.expected_revision,
        "instance": instance,
        "document": document,
        "fetched_at": instant.isoformat(),
        "expires": instant.timestamp() + 600,
    }
    saved["token"] = digest(saved)
    runtime.company_capture = saved
    return enrich(packet_id, current, saved["token"])
