"""Naukri worker's local canonical-PDF preflight. No browser or network dispatch.

Byte verification is distinct from browser attachment and submission authority.
Only metadata is persisted; decrypted PDF bytes never enter an execution record.
The result is a version-pinned observation, not later upload authority; a future
dispatcher must revalidate current state at its durable admission boundary.
"""

import hashlib

from sqlalchemy import select

from backend.app.automation.store import instant
from backend.app.models.application_answer import CandidateResource
from backend.app.services.applications.resume_selector import select_resume

# The observed UI said 2 MB without an exact byte contract. Use the conservative
# decimal bound, never infer that a file near/above that limit will be accepted.
MAX_PDF_BYTES = 2_000_000


async def preflight(session, packet, settings, policy=None):
    selected = packet.snapshot.resume.selected
    metadata = {
        "state": "NEEDS_INPUT",
        "reason": "confirmed_primary_resume_required",
        "checked_at": (await instant(session)).isoformat(),
        "packet_id": str(packet.id),
        "packet_revision": packet.revision,
        "context_digest": packet.snapshot.context_digest,
        "job_id": str(packet.job_id),
        "candidate_profile_version": packet.candidate_profile_version,
        "resource_id": str(selected.resource_id) if selected else None,
        "resource_version": selected.resource_version if selected else None,
        "byte_count": None,
        "sha256": None,
        "browser_action_admitted": False,
        "maximum_bytes": MAX_PDF_BYTES,
        "required_media_type": "application/pdf",
    }

    def denied(reason):
        return {**metadata, "reason": reason}

    if packet.readiness.stale:
        return denied("packet_context_stale")
    if not selected or not selected.confirmed:
        return metadata
    if policy and (
        selected.resource_id != policy.resume_resource_id
        or selected.resource_version != policy.resume_version
    ):
        return denied("policy_resume_binding_changed")
    # Re-read current resources: a packet or a download URL is not a grant to
    # another profile's file, an old revision, or a non-primary resource.
    resources = (await session.scalars(
        select(CandidateResource).where(
            CandidateResource.candidate_profile_id == packet.candidate_profile_id
        ).execution_options(populate_existing=True)
    )).all()
    current = select_resume(resources).selected
    if not current or current.resource_id != selected.resource_id:
        return denied("confirmed_primary_resume_required")
    if current.resource_version != selected.resource_version:
        return denied("resume_revision_changed")
    resource = next(r for r in resources if r.id == selected.resource_id)
    if resource.source_type != "private_upload":
        return denied("canonical_private_pdf_required")
    if not settings.RESUME_ENCRYPTION_KEY:
        return denied("resume_decryption_key_unavailable")
    from backend.app.browser.service import pdf_bytes

    raw = await pdf_bytes(session, packet, settings)
    if raw is None:
        return denied("canonical_pdf_unavailable_or_invalid")
    if len(raw) > MAX_PDF_BYTES:
        return denied("pdf_exceeds_conservative_naukri_limit")
    return {
        **metadata,
        "state": "PDF_VERIFIED_LOCAL",
        "reason": "canonical_private_pdf_verified",
        "byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
