"""Freeze preference schema and cached matching with AST-only fictional objects/fixed time."""
import argparse
import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import Field, model_validator
from backend.app.schemas.candidate_profile import JobSearchPreferences

ROOT = Path(__file__).resolve().parents[2]


def load():
    tree = ast.parse((ROOT / "backend/app/local_agent/preferences.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SearchPreferences")
    scope = dict(JobSearchPreferences=JobSearchPreferences, Field=Field, model_validator=model_validator, Literal=Literal, __name__=__name__)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "fictional-preference-schema", "exec"), scope)
    preferences = scope["SearchPreferences"]
    tree = ast.parse((ROOT / "backend/app/local_agent/conversation.py").read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"utc", "matches"}]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
            return value if tz else value.replace(tzinfo=None)
    scope = dict(datetime=Clock, timedelta=timedelta, timezone=timezone)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "fictional-cached-match", "exec"), scope)
    return preferences, scope["matches"]


def build():
    preferences, matches = load()
    job = dict(title="Rust Developer", location="India", remote_type="remote", employment_type="full_time", source_platform="naukri", status="discovered", date_posted="2026-11-16T12:00:00+00:00", skills_required=["Rust", "SQL"], match_score=70, salary_min=1000, salary_max=2000, salary_currency="INR", salary_period="year", description="Fictional Rust role")
    company = dict(name="Fictional Labs", metadata_={"startup_discovery": {"stage": "seed", "employee_count": 20}})
    patch_list = [{}, {"preferred_locations": ["India"]}, {"preferred_locations": ["Europe"]}, {"remote_preference": "remote"}, {"remote_preference": "hybrid"}, {"target_titles": ["Rust"]}, {"technology_stacks": ["Rust", "SQL"]}, {"technology_stacks": ["Java"]}, {"company_stages": ["seed"]}, {"company_stages": ["growth"]}, {"minimum_employees": 10, "maximum_employees": 30}, {"minimum_salary": 900, "maximum_salary": 2200, "salary_currency": "INR", "salary_period": "year"}, {"minimum_experience": 0}, {"relevance_threshold": 80}, {"application_status": "applied"}, {"source_platforms": ["instahyre"]}, {"posting_recency_days": 1}, {"saved_jobs_only": True}]
    intents = [{}, {"company": "Fictional Labs"}, {"role": "Rust developer"}, {"location": "Europe"}, {"remote": True}, {"not_applied": True}, {"startup": True}, {"skills": ["Rust", "SQL"]}, {"days": 1}]
    mutations = [{}, {"date_posted": None}, {"date_posted": "2026-10-01T12:00:00+00:00"}, {"status": "applied"}, {"status": "archived"}, {"remote_type": None}, {"match_score": None}, {"salary_min": None}, {"skills_required": []}, {"source_platform": "work_at_a_startup"}]
    jobs = [job | mutation for mutation in mutations]
    preference_values = [preferences.model_validate(patch).model_dump(mode="json") for patch in patch_list]
    intent_values = [dict(company=None, role=None, location=None, remote=False, startup=False, not_applied=False, days=None, skills=[]) | change for change in intents]
    cases = []
    for row_index, row in enumerate(jobs):
        converted = row | {"date_posted": datetime.fromisoformat(row["date_posted"]) if row["date_posted"] else None}
        for pref_index, prefs in enumerate(preference_values):
            for intent_index, intent in enumerate(intent_values):
                output = matches(SimpleNamespace(**converted), SimpleNamespace(**company), SimpleNamespace(**intent), prefs, None)
                cases.append(dict(job=row_index, preferences=pref_index, intent=intent_index, output=output))
    preference_cases = []
    for raw in [{}, {"minimum_employees": 30, "maximum_employees": 10}, {"minimum_experience": 0}, {"require_known_properties": False}, {"duplicate_prevention": False}, {"source_platforms": ["naukri", "naukri"]}, {"preferred_locations": [" India ", "India"]}, {"posting_recency_days": "14"}, {"unknown": True}]:
        try:
            result = preferences.model_validate(raw).model_dump(mode="json")
            preference_cases.append(dict(input=raw, accepted=True, output=result))
        except (ValueError, TypeError):
            preference_cases.append(dict(input=raw, accepted=False))
    return preferences.model_json_schema(), dict(cases=cases, preference_cases=preference_cases, jobs=jobs, preferences=preference_values, intents=intent_values, company=company, now="2026-11-17T12:00:00+00:00")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    schema, value = build()
    files = {ROOT / "rust/agent-runtime/schemas/conversation-preferences.json": schema, ROOT / "rust/agent-runtime/tests/fixtures/conversation-filters.json": value}
    for target, item in files.items():
        data = json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.write:
            target.write_text(data)
        elif target.read_text() != data:
            raise SystemExit("conversation_filter_contract_changed")
    print(json.dumps(dict(mode="written" if args.write else "matched", cases=len(value["cases"]), preference_cases=len(value["preference_cases"]))))


if __name__ == "__main__":
    main()
