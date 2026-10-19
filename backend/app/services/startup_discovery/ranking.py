"""Explainable relevance weights, never truth probabilities."""

from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher


def rank_startup(
    session, company, jobs, attributes, size, hiring, contacts, profile, filters
):
    reasons, missing, score = [], [], 0.0
    matches = (
        [JobDiscoveryMatcher(session).match(job, profile, company) for job in jobs]
        if profile
        else []
    )
    eligible = [m for m in matches if not m.exclusion_reasons]
    if eligible:
        score += max(m.match_score for m in eligible) * 0.55
        reasons.append("Best saved-profile job relevance contributes up to 55 points")
    elif not profile:
        missing.append("saved_candidate_profile")
    skills = filters.skills or (profile.verified_skills if profile else [])
    tech = {s.casefold() for s in attributes.get("technology_stack", [])}
    if skills and tech:
        overlap = sorted(s for s in skills if s.casefold() in tech)
        score += 10 * len(overlap) / len(skills)
        if overlap:
            reasons.append("Reported technology matches: " + ", ".join(overlap))
    else:
        missing.append("technology_compatibility")
    if size["team_size_band"] in {"1-10", "11-50"}:
        score += 10
        reasons.append(
            "Evidence reports a company of 1–50 employees; engineering team size is unknown"
        )
    elif size["team_size_band"] == "unknown":
        missing.append(size["team_size_evidence_status"])
    if hiring["hiring_status"] == "hiring_confirmed":
        score += 15
        reasons.append("Fresh attributable current opening")
    elif hiring["hiring_status"] == "hiring_possible":
        score += 5
        reasons.append("Recent hiring evidence needs confirmation")
    prefs = profile.preferences if profile else None
    locations = filters.locations or (prefs.preferred_locations if prefs else [])
    policy = filters.remote_preference or (prefs.remote_preference if prefs else None)
    location = attributes.get("location") or " ".join(j.location or "" for j in jobs)
    remote = attributes.get("remote_policy", "unknown")
    if remote == "unknown" and jobs and all(j.remote_type == "remote" for j in jobs):
        remote = "remote"
    if (locations and any(v.casefold() in location.casefold() for v in locations)) or (
        policy == "remote" and remote == "remote"
    ):
        score += 5
        reasons.append(
            "Location or remote evidence matches saved/requested preferences; work eligibility requires review"
        )
    if (
        prefs
        and prefs.company_stages
        and attributes.get("stage") in prefs.company_stages
    ):
        score += 3
        reasons.append("Reported stage matches saved preferences")
    if any(
        c["confidence"] == "supported"
        and c["priority"] not in {"suppressed", "review_required"}
        for c in contacts
    ):
        score += 2
        reasons.append("Fresh strong professional evidence is available")
    else:
        missing.append("independently_confirmed_professional_contact")
    excluded = list(dict.fromkeys(r for m in matches for r in m.exclusion_reasons))
    if prefs and any(
        v.casefold() in {company.name.casefold(), (company.domain or "").casefold()}
        for v in prefs.excluded_companies
    ):
        excluded.append("Company excluded by saved preferences")
    return dict(
        startup_match_score=round(min(100, max(0, score)), 2),
        ranking_reasons=reasons,
        missing_information=missing,
        matching_roles=len(eligible) if profile else len(jobs),
        profile_version=profile.version if profile else None,
        exclusion_reasons=excluded,
        score_kind="relevance_not_probability",
    )
