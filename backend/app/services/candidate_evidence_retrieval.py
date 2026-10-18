"""Deterministic, bounded retrieval of personally attributable professional facts."""
import json
import re

from backend.app.ai.schemas import EvidenceReference

STOPWORDS = set("tell us about your a an the my i and or what most how have with you to of it in is thing describe built project work experience technical".split())


def tokens(value):
    return set(re.findall(r"[a-z0-9+#.]+", value.casefold())) - STOPWORDS


def retrieve(profile, evidence, question, category):
    facts = []

    def add(source_type, source_id, data, rank=0):
        text = json.dumps(data, ensure_ascii=False)
        score = len(tokens(question) & tokens(text)) + rank
        facts.append({"reference": EvidenceReference(source_type=source_type, source_id=source_id).model_dump(),
                      "facts": data, "score": score})

    if category in {"project_explanation", "technical_experience"}:
        challenging = bool(re.search(r"challeng|problem|solv", question, re.I))
        for i, project in enumerate(profile.projects):
            if not project.get("contribution") or not (project.get("purpose") or project.get("description")):
                continue
            if challenging and not (project.get("engineering_challenges") and project.get("solutions")):
                continue
            add("verified_project", f"{profile.id}:project:{i}", project, 2)
        for item in evidence:
            if not item.user_confirmed:
                continue
            if item.project:
                project = item.project
                if not project.get("contribution") or not (project.get("purpose") or project.get("description")):
                    continue
                if challenging and not (project.get("engineering_challenges") and project.get("solutions")):
                    continue
                add("candidate_evidence", str(item.id), {"project": project}, 2)
            elif category == "technical_experience" and re.search(r"\bI (?:built|implemented|worked|developed|designed)\b", item.content, re.I):
                add("candidate_evidence", str(item.id), {"title": item.title, "content": item.content})
        if category == "technical_experience":
            for i, role in enumerate(profile.verified_roles):
                if role.get("highlight"):
                    add("verified_role", f"{profile.id}:role:{i}", role)
        # A skill-specific question requires that skill in the actual work, not just the skills list.
        requested = re.search(r"(?:experience (?:with|using|in)|worked with)\s+(.+)", question, re.I)
        if requested:
            requested_tokens = tokens(requested[1])
            if requested_tokens:
                facts = [f for f in facts if requested_tokens & tokens(json.dumps(f["facts"]))]
        mentioned_skills = {s for s in profile.verified_skills if s.casefold() in question.casefold()}
        if mentioned_skills:
            facts = [f for f in facts if all(s.casefold() in json.dumps(f["facts"]).casefold() for s in mentioned_skills)]
    elif category in {"motivation", "startup_interest"}:
        prefs = {k: v for k, v in profile.preferences.items() if k in {
            "target_titles", "technology_stacks", "target_industries", "company_stages", "prioritize_startups"
        } and v not in (None, [], False)}
        if prefs:
            add("candidate_preferences", str(profile.id), prefs)
    elif category == "short_text":
        data = {k: getattr(profile, k) for k in ("summary", "verified_roles", "education", "certifications") if getattr(profile, k)}
        if data:
            add("candidate_profile", str(profile.id), data)
    return sorted(facts, key=lambda f: (-f["score"], f["reference"]["source_id"]))[:6]
