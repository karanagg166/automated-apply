"""Confirmed resource selection only. Links are never interpreted as uploaded bytes."""

import hashlib
import json
from uuid import UUID

from backend.app.schemas.applications import ResumeOption, ResumeSelection
from backend.app.services.applications.platforms.base import safe_url


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def private_resume_id(resource):
    if getattr(resource, "source_type", None) != "private_upload":
        return None
    prefix = "private-resume:"
    if not resource.url.startswith(prefix):
        return None
    value = resource.url.removeprefix(prefix)
    try:
        return value if str(UUID(value)) == value else None
    except ValueError:
        return None


def select_resume(resources, selected_id=None):
    options = [
        ResumeOption(
            resource_id=r.id,
            label=r.label,
            # The pinned PostgreSQL approval guard binds the snapshot to the exact
            # saved reference. Private references are served only by the owner BFF.
            url=r.url if private_resume_id(r) else safe_url(r.url),
            confirmed=r.user_confirmed,
            primary=r.is_primary,
            download_path=("/api/backend/dashboard/resumes/" + private_resume_id(r))
            if private_resume_id(r) else None,
            resource_version=digest(
                [
                    str(r.id),
                    r.label,
                    r.url,
                    r.user_confirmed,
                    r.is_primary,
                    str(r.updated_at),
                ]
            ),
        )
        for r in resources
        if r.resource_type == "resume"
    ]
    selected, reason = (
        None,
        "Choose a confirmed resume resource and mark a unique primary or select it explicitly",
    )
    if selected_id:
        matches = [
            r for r in options if r.resource_id == selected_id and r.confirmed and (r.url or r.download_path)
        ]
        if matches:
            selected, reason = (
                matches[0],
                "Explicit owner selection of a confirmed saved resume",
            )
        else:
            reason = "Selected resume is missing, unconfirmed, invalid, or belongs to another profile"
    else:
        primary = [r for r in options if r.primary]
        if len(primary) == 1 and primary[0].confirmed and (primary[0].url or primary[0].download_path):
            selected, reason = primary[0], "Unique confirmed primary resume"
        elif len(primary) > 1:
            reason = "Conflicting primary resumes; choose one explicitly"
    return ResumeSelection(selected=selected, alternatives=options, reason=reason)
