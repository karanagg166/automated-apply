"""Differential matching on fictional data only. Never loads settings or a database."""
import copy
import json
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from backend.app.integrations.gmail.history import canonical_url
from backend.app.schemas.candidate_profile import CandidateProfileRead
from backend.app.services.application_assistant import (
    ApplicationAssistant,
    CandidateProfile,
)
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher

ROOT = Path(__file__).resolve().parents[2]


def cases():
    rng = random.Random(20261114)
    for _ in range(1200):
        skills = rng.choice([[], ["Rust"], ["React.js", "Postgres"], ["C", "C++", "C#", "Node.js"], ["Fast API", "Python", "Python"], ["Straße", "STRASSE"], ["ΟΣ", "ος", "οσ"], ["İ", "I"], ["Ⴀ", "Ა", "ა"]])
        yield {
            "job": {"title": rng.choice(["Backend Web Developer", "Front—End Engineer", "fullstack developer", "Senior Java Developer", "Junior C++ Developer", "Rust Backend Intern", "Other", "İΣ", "ος", "Rust"]), "description": rng.choice([None, "<b>Rust</b> React.js Node.js C++", "Use C&#43;&#43; &amp; Python", "&#82;ust &notit; &#x80;", "Csharp TypeScript Ruster", "ος", "ΟΣ Rust", " Rust\u0307 "]), "skills_required": skills, "location": rng.choice([None, "", "Fictional City", "Remote", "Bengaluru"]), "is_remote": rng.choice([True, False]), "remote_type": rng.choice(["remote", "onsite", "hybrid", "unknown"]), "experience_level": rng.choice([None, "", "junior", "senior", "mid"]), "employment_type": rng.choice([None, "full_time", "internship", "contract"]), "salary_min": rng.choice([None, 100.0, 200.0]), "salary_max": rng.choice([None, 200.0, 300.0]), "salary_currency": rng.choice([None, "INR", "USD"]), "salary_period": rng.choice([None, "month", "year"]), "date_posted": rng.choice([None, "2026-11-13T00:00:00Z"])},
            "profile": {"verified_skills": rng.choice([[], ["Rust", "React", "PostgreSQL"], ["C", "C++", "C#", "Nodejs"], ["Python", "FastAPI", "React.js", "React"], ["Straße"], ["ος", "οσ"], ["İ"], ["ა"]]), "verified_experience_years": rng.choice([None, 0, 1, 4, 8]), "preferences": {"target_titles": rng.choice([[], ["Backend Developer"], ["Full Stack Developer"], ["Frontend Engineer"], ["Rust"]]), "preferred_locations": rng.choice([[], ["Bengaluru"], ["Fictional City"]]), "remote_preference": rng.choice([None, "any", "remote", "onsite", "hybrid"]), "employment_types": rng.choice([[], ["internship"], ["full_time", "contract"]]), "prioritize_startups": rng.choice([None, False, True]), "company_stages": rng.choice([[], ["seed"], ["established"]]), "minimum_salary": rng.choice([None, 150.0, 350.0]), "salary_currency": rng.choice([None, "INR", "USD"]), "salary_period": rng.choice([None, "month", "year"]), "excluded_companies": rng.choice([[], ["Fictional Company"], ["fictional.example"]]), "excluded_titles": rng.choice([[], ["Senior"]]), "excluded_keywords": rng.choice([[], ["Rust"], ["React"]])}},
            "company": rng.choice([None, {"name": "Fictional Company", "domain": "fictional.example", "startup_stage": rng.choice([None, "seed", "established"]), "startup_source": rng.choice([None, "work_at_a_startup"])}]),
            "history_match": rng.choice([False, False, True]),
        }
    template = {"job": {"title": "", "remote_type": "unknown", "skills_required": []}, "profile": {"verified_skills": [], "preferences": {}}, "company": None}
    for count in range(1, 101):
        value = copy.deepcopy(template)
        value["job"]["skills_required"] = [f"Skill{i}" for i in range(count)]
        value["profile"]["verified_skills"] = [f"Skill{i}" for i in range(count // 3)]
        yield value


def prepare(value):
    job = {"description": None, "location": None, "is_remote": False, "experience_level": None, "employment_type": None, "salary_min": None, "salary_max": None, "salary_currency": None, "salary_period": None, "date_posted": None, **value["job"], "id": UUID(int=1), "job_url": "https://boards.greenhouse.io/fictional/jobs/123456", "application_url": None}
    job = SimpleNamespace(**job)
    data = value["profile"]
    profile = CandidateProfileRead(id=UUID(int=2), singleton_key="primary", version=1, full_name="Fictional Candidate", email="fixture@example.com", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), **data)
    prefs = profile.preferences
    base_profile = CandidateProfile(full_name=profile.full_name, email=str(profile.email), verified_skills=profile.verified_skills, verified_experience_years=profile.verified_experience_years, target_titles=prefs.target_titles, preferred_locations=prefs.preferred_locations, remote_preference="remote_only" if prefs.remote_preference == "remote" else prefs.remote_preference)
    company = value.get("company")
    company = SimpleNamespace(name=company["name"], domain=company.get("domain"), metadata_={"startup_discovery": {"stage": company.get("startup_stage"), "source": company.get("startup_source")}}) if company else None
    history = [{"confirmed_application": True, "job_url": canonical_url(job.job_url)}] if value.get("history_match") else []
    assert not history or history[0]["job_url"], "fictional_history_url_invalid"
    return job, base_profile, profile, company, history


def evaluate(prepared):
    job, base_profile, profile, company, history = prepared
    base = ApplicationAssistant(None).calculate_match(job, base_profile).model_dump()
    base.pop("job_id")
    result = JobDiscoveryMatcher(None, history).match(job, profile, company).model_dump()
    return {"base": base, "discovery": result}


def expected(value):
    return evaluate(prepare(value))


def main():
    values = list(cases())
    start = time.perf_counter()
    original = [expected(value) for value in values]
    python_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    response = subprocess.run([str(ROOT / "target/release/examples/match_contract")], input=json.dumps(values).encode(), capture_output=True, check=True, timeout=30, cwd=ROOT)
    rust_ms = (time.perf_counter() - start) * 1000
    actual = json.loads(response.stdout)
    assert len(actual) == len(original), "matching_parity_result_count"
    failures = []
    for index, (a, b) in enumerate(zip(original, actual, strict=True)):
        if a != b:
            failures.append(index)
            if len(failures) <= 3:
                print(json.dumps({"case": index, "expected": a, "actual": b}, ensure_ascii=False))
    if failures:
        raise SystemExit(f"matching_parity_failed:{len(failures)}")
    print(json.dumps({"cases": len(values), "passed": len(values), "python_ms_includes_validation": round(python_ms, 3), "rust_ms_includes_process_and_json": round(rust_ms, 3), "scope": "fictional deterministic scores/skills/factors/unknowns/explanations; not production acceptance or equivalent-boundary performance"}))


if __name__ == "__main__":
    main()
