"""Reviewed employer evidence, distinct from facts about the applicant.

Reuse canonical Job JSON storage. No network research, browser sessions, applicant
history or account authority is inferred from a company name or a page URL.
"""

from datetime import datetime, timedelta, timezone

from backend.app.services.applications.resume_selector import digest

KEY = "application_opportunity"


def evidence_key(content_digest):
    # Existing owner_preferences.key is VARCHAR(50) in PostgreSQL. Retain the
    # full hash in the record and verify it on read/collision rather than migrate.
    return "opp:" + content_digest[:40]


def unsafe_instruction(text):
    import re

    return bool(
        re.search(
            r"ignore\s+(?:all\s+)?(?:previous|prior|system)|(?:system|developer)\s*(?:prompt|message|instruction)|reveal\s+(?:secrets|credentials)|send\s+(?:secrets|cookies)|execute\s+(?:command|script)|disregard\s+instructions",
            text,
            re.I,
        )
    )


def binding(job, company):
    return digest(
        {
            "job_id": str(job.id),
            "title": job.title,
            "url": job.application_url or job.job_url,
            "description": job.description,
            "company_id": str(job.company_id),
            "company": company.name if company else None,
            "company_domain": company.domain if company else None,
        }
    )


def reviewed_context(job, company):
    saved = (job.discovery_metadata or {}).get(KEY)
    if not isinstance(saved, dict) or saved.get("binding") != binding(job, company):
        return []
    if saved.get("digest") != digest({k: v for k, v in saved.items() if k != "digest"}):
        return []
    try:
        observed = datetime.fromisoformat(saved["reviewed_at"])
        instant = datetime.now(timezone.utc)
        if (
            observed.tzinfo is None
            or not instant - timedelta(days=14) <= observed <= instant
        ):
            return []
    except (KeyError, ValueError, TypeError):
        return []
    facts = []
    for kind in ("job", "company"):
        quote = saved.get(kind + "_text")
        if isinstance(quote, str) and quote.strip() and not unsafe_instruction(quote):
            facts.append(
                {
                    "reference": {
                        "source_type": "opportunity_" + kind,
                        "source_id": saved["digest"] + ":" + kind,
                    },
                    "facts": quote,
                    "source_url": saved.get("company_source_url", saved["source_url"])
                    if kind == "company"
                    else saved["source_url"],
                    "reviewed_at": saved["reviewed_at"],
                    "verification": "owner_reviewed_page_excerpt",
                }
            )
    return facts
