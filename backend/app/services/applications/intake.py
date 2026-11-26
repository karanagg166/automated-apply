"""Owner-pasted URL intake: save the job draft and create its packet. No navigation."""

from fastapi import HTTPException
from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket, PrepareBrowser
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService


async def prepare_packet(session, data: PrepareBrowser):
    # Draft intake performs no navigation; browser grants are checked on open/fill.
    # URL and company/title uniqueness are enforced by the existing jobs table.
    canonical = digest(
        {"company": data.company_name.casefold(), "title": data.job_title.casefold()}
    )
    job = await session.scalar(select(Job).where(Job.job_url == data.application_url))
    if not job:
        other = await session.scalar(
            select(Job).where(Job.content_identity == canonical)
        )
        if other:
            raise HTTPException(
                409,
                "A job with this company and title already exists; use its saved packet",
            )
        company = await session.scalar(
            select(Company).where(Company.name == data.company_name)
        )
        if not company:
            company = Company(name=data.company_name)
            session.add(company)
            await session.flush()
        job = Job(
            title=data.job_title,
            company_id=company.id,
            job_url=data.application_url,
            application_url=data.application_url,
            source_platform="manual_browser",
            content_identity=canonical,
            source_verification_status="owner_provided",
        )
        session.add(job)
        await session.flush()
    elif job.company_id:
        company = await session.get(Company, job.company_id)
        if job.title != data.job_title or company.name != data.company_name:
            raise HTTPException(
                409, "Saved job context differs; review its company and title"
            )
    return await ApplicationPacketService(session).create(
        job.id,
        CreatePacket(
            idempotency_key=data.idempotency_key,
            resume_resource_id=data.resume_resource_id,
        ),
    )
