"""Pure factual-answer AST and public request DTO oracles; fictional values only."""
import argparse
import itertools
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from backend.app.ai.schemas import GenerateRequest
from backend.app.core.text import normalize
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = dict(__name__=__name__, re=re, dataclass=dataclass, Decimal=Decimal, normalize=normalize)
    extract("backend/app/knowledge/facts.py", ["FactAnswer", "number", "resolve_fact"], scope)
    compensation = {"amount": "1250000.00", "currency": "INR", "period": "year", "kind": "ctc"}
    india = {"country_code": "IN", "country_name": "India", "authorized_to_work": True, "requires_sponsorship_now_or_future": None}
    us = {"country_code": "US", "country_name": "United States", "authorized_to_work": False, "requires_sponsorship_now_or_future": True}
    preferences = [{}, {"current_compensation": compensation}, {"expected_compensation": {**compensation, "amount": "2.25E+6"}}, {"current_compensation": {**compensation, "amount": "1234.50", "currency": "USD", "period": "month", "kind": "base_salary"}}, {"availability_date": "2026-12-01", "current_location": "Fictional City", "open_to_relocation": False, "relocation_locations": ["New Delhi", "Bengaluru", "Zürich"], "work_authorizations": [india, us]}, {"open_to_relocation": True, "relocation_locations": ["Delhi"], "work_authorizations": [india]}, {"work_authorizations": [us]}, {"minimum_salary": 999999, "salary_currency": "INR", "work_authorization": "A generic saved string is not country-specific evidence"}]
    for amount in ["-0.0000", "0E-999999999999", "0.01", "1000000000000.00", "100000000000000000000E-20"]:
        preferences.append({"current_compensation": {**compensation, "amount": amount}})
    questions = []
    for when, period, kind, unit in itertools.product(["current", "present", "expected", "desired"], ["", "annual ", "monthly ", "hourly "], ["ctc", "salary", "compensation"], ["", " in INR", " USD", " LPA"]):
        questions.append((f"{when} {period}{kind}{unit}", "compensation"))
    questions.extend((q, "personal_details") for q in ["What is your current CTC?", "Please provide your current salary", "Please specify your expected annual compensation in INR", "Please enter current compensation", "Provide your current CTC", "Enter your current CTC", "When can you start?", "What is your availability date?", "When are you available to start?", "Current location", "Current city", "City of residence", "Are you willing to relocate?", "Would you be open to relocation?", "Open to relocation to Bengaluru", "Are you willing to relocate to Delhi?", "Are you willing to relocate to New Delhi?", "Would you be open to relocation to Zürich?", "Can you relocate?", "Minimum salary", "Current CTC and expected CTC", "Guess my salary", "Email"])
    for country in ["India", "IN", "the US", "United States", "Canada"]:
        for question in [f"Are you authorized to work in {country}?", f"Are you legally eligible to work in {country}?", f"Will you require visa sponsorship to work in {country}?", f"Will you now or in the future require sponsorship in {country}?", f"Do you require sponsorship in {country}?", f"Are you authorized to work in {country} without sponsorship?"]:
            questions.append((question, "work_authorization"))
    questions.extend([(q, "work_authorization") for q in ["What is your work authorization?", "Are you authorized to work in India and United States?", "I have a visa", "Please guess my visa status"]])
    cases = []
    for pindex, prefs in enumerate(preferences):
        for question, category in questions:
            result = scope["resolve_fact"](SimpleNamespace(preferences=prefs), question, category)
            cases.append({"preferences": pindex, "question": question, "category": category, "output": asdict(result)})
    request_cases = []
    base = {"question": " Describe   work "}
    inputs = [base, {}, {**base, "approve": True}]
    for key in GenerateRequest.model_fields:
        for value in [None, True, False, 0, 1, 1.0, 1.5, "", " ", "true", " true ", "no", "1_0", "1.0", [], {}, " a   b "]:
            inputs.append({**base, key: value})
    for key, values in {"question": ["x" * 2000, "x" * 2001, " \u001cGithub?\u001f "], "company_name": [" Fictional   Company ", "x" * 201], "job_description": [" One\n two ", "x" * 10001], "writing_style": ["professional", "technical", "concise", "conversational", "founder_focused", " concise "], "job_id": ["30000000-0000-0000-0000-000000000001", "{30000000-0000-0000-0000-000000000001}", "urn:uuid:30000000-0000-0000-0000-000000000001"], "max_characters": [19, 20, 10000, 10001, "1_500", "1500.0"], "max_words": [1, 1500, 1501, "1_0", "1e2"]}.items():
        inputs.extend({**base, key: value} for value in values)
    for body in inputs:
        try:
            result = {"accepted": True, "output": GenerateRequest.model_validate(body).model_dump(mode="json")}
        except ValueError:
            result = {"accepted": False}
        request_cases.append({"input": body, **result})
    value = {"preferences": preferences, "facts": cases, "requests": request_cases}
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/factual-answer-corpus.json"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("factual_answer_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_factual_cases:{len(cases)} request_cases:{len(request_cases)}")


if __name__ == "__main__":
    main()
