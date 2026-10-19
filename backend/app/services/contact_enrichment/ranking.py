"""Explainable relevance categories; scores are ordering weights, not probabilities."""

from backend.app.services.contact_enrichment.verification import (
    email_kind,
    email_observed_at,
    fresh,
)


def rank_contact(contact, company, job=None, ttl_days=30):
    role = contact.role_title.casefold()
    metadata = contact.metadata_ or {}
    reasons, score = [], 0
    employee_count = (company.metadata_ or {}).get("employee_count")
    small = (type(employee_count) is int and employee_count <= 50) or (
        company.metadata_ or {}
    ).get("_verified_team_size_band") in {"1-10", "11-50"}
    large = type(employee_count) is int and employee_count >= 250
    recruiter = any(
        term in role for term in ("recruit", "talent", "human resources", "hr")
    )
    manager = any(
        term in role
        for term in (
            "engineering manager",
            "hiring manager",
            "head of engineering",
            "vp engineering",
            "vp of engineering",
        )
    )
    executive = any(
        term in role
        for term in ("founder", "cto", "chief technology", "ceo", "chief executive")
    )
    if recruiter or manager:
        score += 40
        reasons.append("Reported recruiting or engineering management role")
    elif executive:
        score += 45 if small else 10 if large else 20
        reasons.append(
            "Technical or executive leadership at a known small company"
            if small
            else "Leadership role; direct hiring responsibility is unconfirmed"
        )
    if job:
        reasons.append("Same employer as the target opening")
        if str(job.id) in metadata.get("job_ids", []):
            score += 40
            reasons.append("Explicitly associated with this opening")
        if "intern" in job.title.casefold() and any(
            t in role for t in ("campus", "university", "early career")
        ):
            score += 30
            reasons.append("Campus recruiting role fits internship hiring")
    if metadata.get("hiring_responsibility_confirmed"):
        score += 20
        reasons.append("Human-confirmed hiring responsibility")
    if metadata.get("evidence_strength") == "strong":
        score += 15
        reasons.append("Strong identity evidence")
    is_fresh = fresh(contact.last_checked_at, ttl_days)
    if is_fresh:
        score += 10
        reasons.append("Contact evidence checked within cache lifetime")
    else:
        reasons.append("Evidence requires a freshness review")
    review = bool(metadata.get("identity_review_required"))
    suppressed = bool(contact.do_not_contact)
    if review:
        reasons.append("Conflicting identity evidence requires review")
    if suppressed:
        reasons.append("Contact suppressed by human review")
    available = not suppressed and not review and is_fresh
    return {
        "priority": "suppressed"
        if suppressed
        else "review_required"
        if review
        else "high"
        if score >= 60
        else "medium"
        if score >= 35
        else "low",
        "ordering_score": 0 if suppressed or review else score,
        "reasons": reasons,
        "evidence_strength": metadata.get("evidence_strength", "unknown"),
        "confidence": "requires_review"
        if review
        else "supported"
        if metadata.get("evidence_strength") == "strong" and is_fresh
        else "limited",
        "manual_linkedin_available": bool(available and contact.linkedin_url),
        "email_send_ready": bool(
            available
            and contact.email
            and email_kind(contact.email) == "person_specific"
            and fresh(email_observed_at(contact), ttl_days)
            and contact.email_status == "verified"
            and fresh(contact.last_verified_at, ttl_days)
            and fresh(contact.last_reviewed_at, ttl_days)
        ),
        "manual_outreach_review_available": bool(
            not suppressed
            and not review
            and is_fresh
            and (
                contact.linkedin_url
                or contact.email_status in {"provider_reported", "verified"}
            )
        ),
        "outbound_messages_sent": 0,
    }
