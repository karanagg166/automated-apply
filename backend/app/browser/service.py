"""Browser orchestration reuses packet revisions, answers, audit, resumes and tracking."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import select

from backend.app.browser.contracts import PrepareBrowser
from backend.app.browser.runner import browser, validate_destination
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference, PrivateResume
from backend.app.dashboard.resumes import MAX_PDF, cipher
from backend.app.models.application_answer import CandidateResource
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket, QuestionInput
from backend.app.services.applications.answer_builder import value_error
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService


def metadata_key(packet_id):
    return "browser:" + str(packet_id)


async def metadata(session, packet_id):
    return await session.get(OwnerPreference, metadata_key(packet_id))


async def prepare(session, data: PrepareBrowser):
    await validate_destination(data.application_url, get_settings())
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


async def status(session, packet_id):
    packet = await ApplicationPacketService(session).read(packet_id)
    saved = await metadata(session, packet_id)
    current = browser.sessions.get(str(packet_id))
    from backend.app.browser.adapters import execution_adapter

    adapter = execution_adapter(
        packet.snapshot.destination.application_url, get_settings()
    )
    execution = None
    if adapter.submission_enabled:
        from backend.app.browser.submissions import attempt_for, attempt_output

        attempt = await attempt_for(session, packet_id)
        execution = attempt_output(attempt) if attempt else None
    recovery = None
    if packet.lifecycle_state in {"submitting", "submission_unknown"}:
        recovery = "Check the saved submission receipt; do not resubmit or reopen this application."
    elif (current and current.blocked_step_requests and not current.manual) or (
        saved and saved.value.get("diagnostic") == "network_activity_requires_takeover"
    ):
        recovery = "This form tried to send data during assistance. Requests were blocked; never replay interrupted actions. Take Over to continue manually, then analyze again."
    elif saved and saved.value.get("diagnostic") in {
        "step_started",
        "step_handoff_required",
    }:
        recovery = "A step was interrupted or needs manual work. Inspect the website with Take Over and analyze again; never replay the previous step action."
    elif (
        packet.lifecycle_state
        not in {"provider_confirmed_submitted", "user_reported_submitted"}
        and not current
    ):
        recovery = "Open a dedicated session and reanalyze; no action is replayed"
    return {
        "packet": packet.model_dump(mode="json"),
        "connected": bool(current and not current.page.is_closed()),
        "manual": bool(current and current.manual),
        "in_page_network_isolation": bool(
            current and current.in_page_mode and not current.manual
        ),
        "analysis": saved.value if saved else None,
        "submission_mode": "mock_only"
        if adapter.submission_enabled
        else "manual_handoff",
        "automated_submission_enabled": adapter.submission_enabled,
        "real_employer_submission_enabled": False,
        "owner_consent_available": bool(get_settings().BROWSER_OWNER_APPROVAL_KEY),
        "opportunity_context_available": get_settings().OPPORTUNITY_CONTEXT_ENABLED,
        "execution": execution,
        "recovery": recovery,
    }


async def analyze(session, packet, service, runtime):
    fields, warnings = await runtime.scan()
    if not fields:
        raise HTTPException(
            409, "No supported application form detected; use manual handoff"
        )
    old = await metadata(session, packet.id)
    previous_map = {
        f["identity"]: f["field_id"] for f in (old.value["fields"] if old else [])
    }
    existing = {str(f.id): f for f in await service.repo.fields(packet.id)}
    previous = packet.lifecycle_state
    await service.repo.advance(packet, packet.revision)
    _, profile, snapshot = await service.builder.context(
        packet.job_id, packet.resume_resource_id
    )
    mapped = []
    for field in fields:
        identity = digest(
            {k: v for k, v in field.items() if k not in {"key", "field_id"}}
        )
        field_id = previous_map.get(identity)
        if field_id not in existing:
            if len(existing) >= 100:
                raise HTTPException(
                    409, "Too many changing questions; complete manually"
                )
            kind = field["kind"]
            question = QuestionInput(
                question=field["question"],
                required=field["required"],
                field_type="yes_no"
                if kind == "checkbox"
                else "multiple_choice"
                if kind in {"select", "radio_group", "combobox"} and field["options"]
                else "file"
                if kind == "file"
                else "textarea"
                if kind == "textarea"
                else "text",
                options=["Yes", "No"]
                if kind == "checkbox"
                else field["options"]
                if kind in {"select", "radio_group", "combobox"}
                else [],
                max_characters=field["max_characters"],
            )
            answer = await service.builder.answers.build(
                question, packet.job_id, profile, resume=snapshot.resume
            )
            item = service.repo.add_field(packet.id, answer, len(existing))
            field_id = str(item.id)
            existing[field_id] = item
        # Opaque browser handles live in memory only; persist sanitized structure and field links.
        mapped.append(
            {
                **{k: v for k, v in field.items() if k != "key"},
                "identity": identity,
                "field_id": field_id,
            }
        )
    if not old:
        old = OwnerPreference(key=metadata_key(packet.id), value={})
        session.add(old)
    old.value = {
        "signature": runtime.signature,
        "page_context": runtime.context_evidence,
        "fields": mapped,
        "warnings": warnings,
        "diagnostic": "analyzed",
        "filled_field_ids": [],
        "validation": [],
        "steps": [
            {k: v for k, v in step.items() if k != "key"} for step in runtime.steps
        ],
        "step_history": old.value.get("step_history", []),
    }
    # finish() runs the existing readiness evaluator and emits an existing audited event type.
    await service.finish(
        packet,
        previous,
        "questions_added",
        note="Dedicated browser form analyzed without submission",
    )
    return await status(session, packet.id)


async def fill(session, packet, service, runtime, confirm, confirm_context=False):
    if not confirm_context:
        raise HTTPException(
            422,
            "Confirm that the actual page belongs to the saved company and job before filling",
        )
    if not confirm:
        raise HTTPException(
            422, "Review the proposed values and explicitly confirm before filling"
        )
    saved = await metadata(session, packet.id)
    if not saved:
        raise HTTPException(409, "Analyze the form before filling")
    fields, _ = await runtime.unchanged(saved.value["signature"])
    items = {
        str(f.id): service.repo.field_read(f)
        for f in await service.repo.fields(packet.id)
    }
    plan, validation = [], []
    for actual, mapped in zip(fields, saved.value["fields"], strict=True):
        item = items[mapped["field_id"]]
        if not actual["supported"]:
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": False,
                    "reason": actual["manual_reason"],
                }
            )
            continue
        if actual["kind"] == "file":
            # Only exact selected, confirmed, encrypted database bytes. Never read a client path or URL.
            resource = (
                await session.get(CandidateResource, packet.resume_resource_id)
                if packet.resume_resource_id
                else None
            )
            candidates = (
                list(
                    (
                        await session.scalars(
                            select(PrivateResume).where(
                                PrivateResume.resource_id == packet.resume_resource_id,
                                PrivateResume.confirmed.is_(True),
                            )
                        )
                    ).all()
                )
                if packet.resume_resource_id
                else []
            )
            resume = candidates[0] if len(candidates) == 1 else None
            if resume and not (
                resource
                and resource.user_confirmed
                and resource.source_type == "private_upload"
                and resource.candidate_profile_id == packet.candidate_profile_id
                and resource.url == "private-resume:" + str(resume.id)
            ):
                raise HTTPException(
                    409, "Selected resume reference does not match the approved PDF"
                )
            if not resume:
                validation.append(
                    {
                        "field_id": str(item.id),
                        "complete": False,
                        "reason": "Select an approved private PDF resume",
                    }
                )
                continue
            raw = cipher().decrypt(resume.ciphertext)
            if (
                len(raw) > MAX_PDF
                or not raw.startswith(b"%PDF-")
                or hashlib.sha256(raw).hexdigest() != resume.sha256
            ):
                raise HTTPException(409, "Resume integrity validation failed")
            plan.append(
                (
                    actual,
                    item,
                    None,
                    {
                        "name": "resume.pdf",
                        "mimeType": "application/pdf",
                        "buffer": raw,
                    },
                )
            )
            continue
        value = item.effective_answer
        if (
            not value
            or item.validation_status != "draft_ready"
            or value_error(item, value)
        ):
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": False,
                    "reason": "Answer missing or invalid",
                }
            )
            continue
        if item.requires_review and item.review_status != "reviewed":
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": False,
                    "reason": "Review this answer before filling",
                }
            )
            continue
        plan.append((actual, item, value, None))
    # Persist intent before side effects. A lost response never replays automatically.
    saved.value = {
        **saved.value,
        "diagnostic": "fill_started",
        "filled_field_ids": [],
        "validation": validation,
    }
    await session.commit()
    await service.locked(packet.id, packet.revision)
    filled = []
    try:
        if runtime.blocked_step_requests:
            raise HTTPException(409, "Network-dependent form requires manual takeover")
        for actual, item, value, upload in plan:
            # Dynamic questions may appear after any change. Stop before addressing a changed form.
            fresh, _ = await runtime.unchanged(saved.value["signature"])
            index = next(
                i
                for i, f in enumerate(saved.value["fields"])
                if f["field_id"] == str(item.id)
            )
            valid = await runtime.fill(fresh[index], value=value, upload=upload)
            filled.append(str(item.id))
            if runtime.blocked_step_requests:
                raise HTTPException(409, "Network-dependent form requires manual takeover")
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": valid,
                    "reason": None if valid else "Browser validation failed",
                }
            )
        await runtime.unchanged(saved.value["signature"])
        if runtime.blocked_step_requests:
            raise HTTPException(409, "Network-dependent form requires manual takeover")
        diagnostic = "filled_review_on_website"
    except Exception:
        diagnostic = (
            "network_activity_requires_takeover"
            if runtime.blocked_step_requests
            else "interrupted_reanalyze_before_retry"
        )
    saved.value = {
        **saved.value,
        "diagnostic": diagnostic,
        "filled_field_ids": filled,
        "validation": validation,
    }
    await session.commit()
    return await status(session, packet.id)
