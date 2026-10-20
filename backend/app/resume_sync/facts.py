"""Deterministic evidence sections, not inferred career facts or AI extraction."""

import re

from backend.app.dashboard.resumes import suggestions

HEADINGS = {
    "skills": r"(?:technical |professional )?skills|technologies|tech stack",
    "work_experience": r"(?:professional |work |relevant )?experience|employment(?: history)?|internships?",
    "education": r"education|academic(?: background| qualifications)?",
    "projects": r"(?:personal |selected |academic |technical )?projects",
    "achievements": r"achievements(?: and awards)?|awards(?: and achievements)?|honou?rs|certifications",
    "other_claims": r"summary|profile|objective|publications|volunteering|leadership|activities|interests",
}
CATEGORIES = ("skills", "work_experience", "employment_dates", "education", "projects", "professional_links", "achievements", "other_claims")


def extract_facts(text: str) -> dict:
    sections = {key: [] for key in CATEGORIES}
    category = "other_claims"
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip(" •·")[:2000]
        if not line:
            continue
        heading = line.rstrip(":").strip()
        match = next((key for key, pattern in HEADINGS.items() if re.fullmatch(pattern, heading, re.I)), None)
        if match:
            category = match
        else:
            sections[category].append(line)
    for key in sections:
        sections[key] = sections[key][:100]
    sections["professional_links"] = sorted(set(re.findall(r"https://[^\s<>\[\]()]+", text)))[:100]
    # Verbatim dates stay evidence; no month, employment duration or current role is inferred.
    sections["employment_dates"] = [line for line in sections["work_experience"] if re.search(r"\b(?:19|20)\d{2}\b|\bpresent\b", line, re.I)]
    suggested = suggestions(text)
    return {"sections": sections, "suggestions": suggested, "text": text[:32000]}


def verified_context(profile: dict | None, skills: list[str]) -> dict[str, list[str]]:
    profile = profile or {}
    roles, education, projects = (profile.get(key, []) for key in ("verified_roles", "education", "projects"))
    def describe(item, fields):
        return " · ".join(str(item[key]) for key in fields if item.get(key))[:2000]
    return {
        "skills": skills,
        "work_experience": [describe(item, ("company", "role", "highlight")) for item in roles],
        "employment_dates": [describe(item, ("company", "role", "start_date", "end_date")) for item in roles],
        "education": [describe(item, ("institution", "qualification", "field_of_study", "graduation_year")) for item in education],
        "projects": [describe(item, ("name", "description", "contribution", "measurable_results")) for item in projects],
        "professional_links": [str(profile[key]) for key in ("github_url", "linkedin_url", "portfolio_url", "personal_website") if profile.get(key)],
        "achievements": [achievement for item in projects for achievement in item.get("achievements", [])] + [describe(item, ("name", "issuer", "issued_on")) for item in profile.get("certifications", [])],
        "other_claims": [str(profile[key]) for key in ("full_name", "email", "phone", "summary", "verified_experience_years") if profile.get(key) is not None],
    }


def differences(previous: dict | None, current: dict, verified_skills: list[str], verified_profile: dict | None = None) -> list[dict]:
    changes = []
    verified = verified_context(verified_profile, verified_skills)
    for category in CATEGORIES:
        before = (previous or {}).get("sections", {}).get(category, [])
        after = current["sections"][category]
        if category == "skills":
            before = (previous or {}).get("suggestions", {}).get("verified_skills", verified_skills)
            after = current["suggestions"]["verified_skills"]
        changes.append({
            "category": category, "before": before, "after": after,
            "current_verified": verified[category],
            "added": [item for item in after if item.casefold() not in {s.casefold() for s in before}],
            "removed": [item for item in before if item.casefold() not in {s.casefold() for s in after}],
        })
    return changes
