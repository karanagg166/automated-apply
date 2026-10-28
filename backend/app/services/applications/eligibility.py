"""Readiness is computed independently of lifecycle and external submission claims."""
from datetime import datetime, timezone

from backend.app.schemas.applications import Readiness


def readiness(snapshot, fields, *, stale=False, approved=False, submitted=False):
    warnings = [*snapshot.warnings, *snapshot.destination.warnings]
    manual = [
        "Open the official application website yourself",
        "Complete the form and submit it on that website",
    ]
    if snapshot.resume.selected:
        manual.insert(
            1,
            "manual_resume_upload_required: open the selected resource and upload the actual file if requested",
        )
    if submitted:
        return Readiness(
            state="completed_by_user",
            warnings=warnings
            + ["Submission is self-reported; no provider confirmation exists"],
            stale=stale,
        )
    blockers = []
    if snapshot.candidate is None:
        return Readiness(
            state="needs_profile",
            blockers=["Save a candidate profile"],
            warnings=warnings,
            stale=stale,
        )
    if not snapshot.preparation_supported:
        return Readiness(
            state="unsupported",
            blockers=["No preparation adapter is implemented for this saved source"],
            warnings=warnings,
        )
    if not snapshot.destination.valid:
        blockers.append(
            "Correct the saved application URL or expired listing before refreshing this packet"
        )
    if snapshot.destination.source_confidence != "source_consistent":
        blockers.append(
            "Correct the saved posting source so its platform label and host agree"
        )
    if stale:
        return Readiness(
            state="needs_review",
            blockers=[
                "Saved profile, resume, evidence or job changed; refresh the packet and review its new revision"
            ],
            manual_steps=manual,
            warnings=warnings,
            stale=True,
        )
    if not snapshot.resume.selected:
        return Readiness(
            state="needs_resume",
            blockers=[snapshot.resume.reason, *blockers],
            warnings=warnings,
        )
    for field in fields:
        if field.provenance.answer_expires_at and field.provenance.answer_expires_at <= datetime.now(timezone.utc):
            blockers.append(f"Reconfirm expired answer: {field.question}")
        if (
            field.required
            and field.validation_status != "file_upload_required"
            and (not field.effective_answer or field.validation_status != "draft_ready")
        ):
            blockers.append(f"Answer required: {field.question}")
    if blockers:
        return Readiness(
            state="needs_input",
            blockers=blockers,
            manual_steps=manual,
            warnings=warnings,
        )
    pending = [
        f.question
        for f in fields
        if f.effective_answer and f.requires_review and f.review_status != "reviewed"
    ]
    if pending or not approved:
        return Readiness(
            state="needs_review",
            blockers=[
                *(f"Review answer: {q}" for q in pending),
                "Review the exact packet revision, selected resume and application destination",
            ],
            manual_steps=manual,
            warnings=warnings,
        )
    return Readiness(
        state="ready_for_manual_handoff", manual_steps=manual, warnings=warnings
    )
