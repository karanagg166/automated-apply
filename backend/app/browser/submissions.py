"""Exact owner grants, one durable dispatch per packet, and receipt-only confirmation.

Only the local fictional adapter is executable. Real employer submission stays disabled.
All non-idempotent intent is committed before browser I/O. Unknown outcomes never replay.
"""

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from backend.app.browser.adapters import FORM_STATE, execution_adapter
from backend.app.browser.runner import browser
from backend.app.browser.service import metadata
from backend.app.browser.submission_models import (
    BrowserSubmissionAttempt,
    BrowserSubmissionGrant,
)
from backend.app.core.config import get_settings
from backend.app.dashboard.models import PrivateResume
from backend.app.models.application_packet import ApplicationSubmissionEvidence
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def policy(packet):
    adapter = execution_adapter(packet.application_url, get_settings())
    if not adapter.submission_enabled:
        raise HTTPException(
            403,
            "No submission adapter is authorized for this destination; use manual handoff",
        )
    return adapter


def runtime_for(packet_id):
    runtime = browser.sessions.get(str(packet_id))
    if not runtime or runtime.page.is_closed() or runtime.manual:
        raise HTTPException(
            409, "Analyze the connected dedicated browser before authorizing submission"
        )
    return runtime


async def attempt_for(session, packet_id):
    return await session.scalar(
        select(BrowserSubmissionAttempt)
        .where(BrowserSubmissionAttempt.packet_id == packet_id)
        .execution_options(populate_existing=True)
    )


def attempt_output(attempt):
    return {
        "attempt_id": str(attempt.id),
        "packet_id": str(attempt.packet_id),
        "state": attempt.state,
        "adapter": attempt.adapter,
        "receipt": attempt.receipt,
        "diagnostic": attempt.diagnostic,
        "dispatched_at": aware(attempt.dispatched_at).isoformat(),
        "recovery_required": attempt.state in {"dispatched", "unknown"},
        "resubmission_allowed": False,
    }


async def preview(session, packet_id, expected_revision, *, confirm_context):
    service = ApplicationPacketService(session)
    packet, _, current = await service.locked(packet_id, expected_revision)
    adapter = policy(packet)
    if not confirm_context:
        raise HTTPException(
            422, "Confirm the actual company and job before submission preview"
        )
    if await attempt_for(session, packet_id):
        raise HTTPException(
            409,
            "An application dispatch already exists; check its receipt, never resubmit",
        )
    runtime = runtime_for(packet_id)
    saved = await metadata(session, packet_id)
    if not saved:
        raise HTTPException(409, "Analyze the current form first")
    fields, warnings = await runtime.unchanged(saved.value["signature"])
    if warnings:
        raise HTTPException(409, "Embedded application forms require manual submission")
    state = await runtime.page.evaluate(FORM_STATE)
    adapter.validate_form(state)
    if not state["valid"]:
        raise HTTPException(
            409,
            "Complete all required fields and fix browser validation before submission",
        )
    if len(state["controls"]) != len(fields):
        raise HTTPException(409, "Form ownership or structure is unsupported")
    items = {
        str(f.id): service.repo.field_read(f)
        for f in await service.repo.fields(packet_id)
    }
    visible, consents = [], []
    selected_resume_sha = None
    for actual, mapped, control in zip(
        fields, saved.value["fields"], state["controls"], strict=True
    ):
        item = items[mapped["field_id"]]
        if control["key"] != actual["key"] or control["disabled"]:
            raise HTTPException(409, "Ambiguous or disabled application control")
        if actual["kind"] in {"checkbox", "radio"}:
            # The assistant never checks consent. Every checked consent is separately reviewed.
            consent_id = digest(
                {
                    "field_id": str(item.id),
                    "kind": actual["kind"],
                    "name": control["name"],
                }
            )
            consents.append(
                {
                    "consent_id": consent_id,
                    "question": item.question,
                    "checked": control["checked"],
                    "required": control["required"],
                }
            )
            continue
        if not actual["supported"]:
            raise HTTPException(409, "Unsupported controls require manual submission")
        if actual["kind"] == "file":
            resumes = list(
                (
                    await session.scalars(
                        select(PrivateResume).where(
                            PrivateResume.resource_id == packet.resume_resource_id,
                            PrivateResume.confirmed.is_(True),
                        )
                    )
                ).all()
            )
            uploads = [
                value
                for name, value in state["entries"]
                if name == control["name"] and isinstance(value, dict)
            ]
            if (
                len(resumes) != 1
                or control["file_count"] != 1
                or len(uploads) != 1
                or uploads[0]["sha256"] != resumes[0].sha256
            ):
                raise HTTPException(
                    409,
                    "Uploaded file does not match the exact selected approved resume",
                )
            selected = current.resume.selected
            if (
                not selected
                or selected.download_path
                != "/api/backend/dashboard/resumes/" + str(resumes[0].id)
                or selected.resource_id != packet.resume_resource_id
            ):
                raise HTTPException(409, "Select and confirm the exact private resume")
            selected_resume_sha = resumes[0].sha256
            visible.append(
                {
                    "field_id": str(item.id),
                    "question": item.question,
                    "value": uploads[0]["name"],
                    "source": "approved_private_resume",
                    "sha256": selected_resume_sha,
                }
            )
        else:
            effective = item.effective_answer or ""
            if control["value"] != effective or (
                effective
                and (
                    item.validation_status != "draft_ready"
                    or (item.requires_review and item.review_status != "reviewed")
                )
            ):
                raise HTTPException(
                    409,
                    "Actual form values differ from reviewed packet answers; save and review changes first",
                )
            visible.append(
                {
                    "field_id": str(item.id),
                    "question": item.question,
                    "value": control["value"],
                    "source": item.provenance.source,
                }
            )
    payload_digest = digest(state["entries"])
    data = {
        "adapter": adapter.key,
        "destination": packet.application_url,
        "packet_id": str(packet_id),
        "packet_revision": packet.revision,
        "context_digest": current.context_digest,
        "form_signature": runtime.signature,
        "payload_digest": payload_digest,
        "company": current.company_name,
        "job_title": current.job_title,
        "resume_sha256": selected_resume_sha,
        "fields": visible,
        "consents": consents,
        "mode": "mock_only",
        "real_employer_submission_enabled": False,
    }
    data["preview_digest"] = digest(data)
    return data


async def authorize(session, packet_id, data):
    if not data.confirm_exact_application:
        raise HTTPException(422, "Explicit exact-application authorization is required")
    current = await preview(
        session, packet_id, data.expected_revision, confirm_context=True
    )
    checked = {c["consent_id"] for c in current["consents"] if c["checked"]}
    if (
        len(set(data.reviewed_consent_ids)) != len(data.reviewed_consent_ids)
        or set(data.reviewed_consent_ids) != checked
    ):
        raise HTTPException(
            422, "Explicitly review each checked consent or radio answer"
        )
    if not secrets.compare_digest(current["preview_digest"], data.preview_digest):
        raise HTTPException(
            409, "The exact application preview changed; review it again"
        )
    # New authorization revokes unused predecessors. Neither an expired nor revoked grant dispatches.
    await session.execute(
        update(BrowserSubmissionGrant)
        .where(
            BrowserSubmissionGrant.packet_id == packet_id,
            BrowserSubmissionGrant.consumed_at.is_(None),
            BrowserSubmissionGrant.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    token = secrets.token_urlsafe(32)
    grant = BrowserSubmissionGrant(
        id=uuid4(),
        packet_id=packet_id,
        packet_revision=data.expected_revision,
        preview_digest=data.preview_digest,
        authorization=current,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now() + timedelta(seconds=120),
    )
    session.add(grant)
    await session.flush()
    return {
        "grant_id": str(grant.id),
        "grant_token": token,
        "packet_revision": grant.packet_revision,
        "expires_at": aware(grant.expires_at).isoformat(),
        "preview_digest": grant.preview_digest,
        "mode": "mock_only",
    }


async def finish(session, attempt_id, receipt=None, *, diagnostic=None):
    # Always lock packet before execution rows, matching authorize/dispatch/cancel lock order.
    attempt = await session.get(BrowserSubmissionAttempt, attempt_id)
    service = ApplicationPacketService(session)
    packet = await service.repo.get(attempt.packet_id, lock=True)
    attempt = await session.scalar(
        select(BrowserSubmissionAttempt)
        .where(BrowserSubmissionAttempt.id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if attempt.state == "verified":
        return attempt_output(attempt)
    if receipt is None and attempt.state == "unknown":
        return attempt_output(attempt)
    previous = packet.lifecycle_state
    await service.repo.advance(packet, packet.revision)
    if receipt is None:
        attempt.state, attempt.finished_at, attempt.diagnostic = (
            "unknown",
            now(),
            diagnostic or "receipt_unconfirmed",
        )
        await session.flush()
        packet.lifecycle_state, packet.readiness_state = (
            "submission_unknown",
            "manual_action_required",
        )
        note = "Submission receipt unconfirmed; automatic resubmission is forbidden"
        evidence_id = None
    else:
        evidence = ApplicationSubmissionEvidence(
            id=uuid4(),
            packet_id=packet.id,
            packet_revision=packet.revision,
            confirmation_source="mock_employer",
            evidence_confidence="mock_receipt_verified",
            human_confirmed=False,
            receipt_reference=receipt["receipt_reference"],
            idempotency_key="browser_" + attempt.id.hex,
            request_hash=digest(receipt),
        )
        session.add(evidence)
        await session.flush()
        attempt.state, attempt.receipt, attempt.evidence_id = (
            "verified",
            receipt,
            evidence.id,
        )
        attempt.finished_at, attempt.diagnostic = (
            now(),
            "independent_mock_receipt_verified",
        )
        await session.flush()
        packet.lifecycle_state, packet.tracking_state = (
            "provider_confirmed_submitted",
            "applied_verified",
        )
        packet.readiness_state = "completed_verified"
        note, evidence_id = (
            "Independent fictional employer receipt verified; no real employer submission",
            evidence.id,
        )
    await session.flush()
    service.repo.event(
        packet, "tracking_updated", previous, note=note, evidence_id=evidence_id
    )
    await session.commit()
    return attempt_output(attempt)


async def submit(session, packet_id, data):
    service = ApplicationPacketService(session)
    packet = await service.repo.get(packet_id, lock=True)
    adapter = policy(packet)
    request_hash = digest(
        {
            "packet_id": str(packet_id),
            "grant_id": str(data.grant_id),
            "expected_revision": data.expected_revision,
            "key": data.idempotency_key,
        }
    )
    existing = await attempt_for(session, packet_id)
    if existing:
        if (
            existing.idempotency_key == data.idempotency_key
            and existing.request_hash == request_hash
        ):
            return attempt_output(existing)
        raise HTTPException(
            409,
            "Application already dispatched; do not resubmit even if its outcome is unknown",
        )
    grant = await session.scalar(
        select(BrowserSubmissionGrant)
        .where(BrowserSubmissionGrant.id == data.grant_id)
        .with_for_update()
    )
    if (
        not grant
        or grant.packet_id != packet_id
        or grant.packet_revision != data.expected_revision
        or grant.revoked_at
        or grant.consumed_at
        or aware(grant.expires_at) <= now()
        or not secrets.compare_digest(
            grant.token_hash,
            hashlib.sha256(data.grant_token.get_secret_value().encode()).hexdigest(),
        )
    ):
        raise HTTPException(
            403,
            "Submission authorization is missing, expired, revoked or already consumed",
        )
    current = await preview(
        session, packet_id, data.expected_revision, confirm_context=True
    )
    if not secrets.compare_digest(current["preview_digest"], grant.preview_digest):
        raise HTTPException(
            409, "The form, facts, answers or resume changed after authorization"
        )
    runtime = runtime_for(packet_id)
    previous = packet.lifecycle_state
    grant.consumed_at = now()
    await session.flush()
    await service.repo.advance(packet, data.expected_revision)
    attempt = BrowserSubmissionAttempt(
        id=uuid4(),
        packet_id=packet_id,
        grant_id=grant.id,
        packet_revision=packet.revision,
        idempotency_key=data.idempotency_key,
        request_hash=request_hash,
        adapter=adapter.key,
        destination=packet.application_url,
        payload_digest=current["payload_digest"],
        state="dispatched",
        dispatched_at=now(),
        lease_until=now() + timedelta(seconds=30),
    )
    session.add(attempt)
    await session.flush()
    packet.lifecycle_state, packet.readiness_state = (
        "submitting",
        "manual_action_required",
    )
    await session.flush()
    service.repo.event(
        packet,
        "tracking_updated",
        previous,
        note="Owner-authorized mock submission dispatch reserved",
    )
    # Crash after this commit is an unknown outcome, never permission to replay.
    await session.commit()
    receipt, diagnostic = None, None
    try:
        async with asyncio.timeout(25):
            await runtime.submit_mock(adapter, attempt.id, attempt.payload_digest)
            receipt = await adapter.receipt(attempt.id, attempt.payload_digest)
    except Exception:
        diagnostic = "browser_or_receipt_interrupted"
    return await finish(session, attempt.id, receipt, diagnostic=diagnostic)


async def recover(session, packet_id):
    service = ApplicationPacketService(session)
    packet = await service.repo.get(packet_id, lock=True)
    adapter = policy(packet)
    attempt = await attempt_for(session, packet_id)
    if not attempt:
        raise HTTPException(409, "No dispatched application exists")
    if attempt.state == "verified":
        return attempt_output(attempt)
    # A new worker never clicks. It can only inspect the exact independent receipt.
    await session.commit()
    receipt = None
    try:
        receipt = await adapter.receipt(attempt.id, attempt.payload_digest)
    except Exception:
        return await finish(
            session, attempt.id, None, diagnostic="recovery_receipt_unavailable"
        )
    return await finish(
        session, attempt.id, receipt, diagnostic="recovery_receipt_unconfirmed"
    )


async def revoke(session, packet_id):
    await session.execute(
        update(BrowserSubmissionGrant)
        .where(
            BrowserSubmissionGrant.packet_id == packet_id,
            BrowserSubmissionGrant.consumed_at.is_(None),
            BrowserSubmissionGrant.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )


async def reconcile_expired(session, *, as_of=None):
    """Safety-only restart recovery: expire uncertain leases, never execute a browser action."""
    ids = list(
        (
            await session.scalars(
                select(BrowserSubmissionAttempt.id).where(
                    BrowserSubmissionAttempt.state == "dispatched",
                    BrowserSubmissionAttempt.lease_until <= (as_of or now()),
                )
            )
        ).all()
    )
    for attempt_id in ids:
        await finish(
            session, attempt_id, None, diagnostic="dispatch_lease_expired_no_replay"
        )
    return len(ids)


async def set_consent(session, packet_id, data):
    """Only a direct owner action selects consent; models and fill plans never infer it."""
    if not data.confirm_page_context:
        raise HTTPException(
            422, "Confirm the current company and job before selecting consent"
        )
    service = ApplicationPacketService(session)
    packet, _, _ = await service.locked(packet_id, data.expected_revision)
    runtime = runtime_for(packet_id)
    saved = await metadata(session, packet_id)
    if not saved:
        raise HTTPException(409, "Analyze the form before reviewing consent")
    fields, _ = await runtime.unchanged(saved.value["signature"])
    matches = [
        (actual, mapped)
        for actual, mapped in zip(fields, saved.value["fields"], strict=True)
        if mapped["field_id"] == str(data.field_id)
    ]
    if len(matches) != 1 or matches[0][0]["kind"] != "checkbox":
        raise HTTPException(
            409,
            "Only an unambiguous detected native checkbox supports this owner action",
        )
    field = matches[0][0]
    # Selecting a consent value authorizes that value only, never a background
    # submission through an input/change handler or a delayed callback.
    runtime.in_page_mode = True
    await runtime.page.locator(f'[data-aa-field="{field["key"]}"]').set_checked(
        data.checked
    )
    previous = packet.lifecycle_state
    await service.repo.advance(packet, packet.revision)
    item = await service.repo.field(packet_id, data.field_id)
    item.human_answer = "Yes" if data.checked else "No"
    item.provenance = {**item.provenance, "source": "human", "resolver": "human"}
    item.validation_status, item.requires_review = "draft_ready", False
    item.missing_information = []
    saved.value = {
        **saved.value,
        "diagnostic": "owner_consent_updated",
        "validation": [
            {
                **v,
                "complete": data.checked or not field["required"],
                "reason": None
                if data.checked or not field["required"]
                else "Required consent is unselected",
            }
            if v["field_id"] == str(data.field_id)
            else v
            for v in saved.value.get("validation", [])
        ],
    }
    await service.finish(
        packet,
        previous,
        "tracking_updated",
        note="Owner explicitly "
        + ("selected" if data.checked else "cleared")
        + " detected consent checkbox",
    )
    await session.commit()
    from backend.app.browser.service import status

    return await status(session, packet_id)
