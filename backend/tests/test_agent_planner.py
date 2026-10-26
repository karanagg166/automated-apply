"""Typed commands and follow-ups contain no model-controlled permission bits."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.agent.contracts import Filters, Understanding
from backend.app.agent.planner import CommandPlanner, deterministic
from backend.app.core.config import Settings


@pytest.mark.parametrize("text,intent", [
    ("Find backend jobs in India.", "search"), ("Only show startups.", "filter"),
    ("Skip internships.", "filter"), ("Apply to the first three.", "apply"),
    ("Use Quick-Clinic as my main project.", "select_project"),
    ("What happened to yesterday's applications?", "status"),
    ("Cancel the pending campaign.", "cancel"), ("Stop", "cancel"), ("yes", "approve"),
])
def test_natural_commands(text, intent):
    result = deterministic(text)
    assert result is not None and result.intent == intent


def test_followups_preserve_filters_and_resolve_only_previous_jobs():
    planner = CommandPlanner(Settings(_env_file=None))
    jobs = [str(uuid4()) for _ in range(3)]
    memory = {"agent_filters": {"role": "backend", "location": "India"}, "job_ids": jobs}
    plan = planner.plan(deterministic("Only show startups"), memory)
    assert plan.filters.role == "backend" and plan.filters.location == "India" and plan.filters.startup
    plan = planner.plan(deterministic("Apply to the first three"), memory)
    assert [str(job) for job in plan.selected_jobs] == jobs
    assert plan.confirmation_required
    assert all(action.name == "prepare_application" for action in plan.actions)
    missing = planner.plan(deterministic("Apply to the first three"), {})
    assert missing.missing_information and not missing.actions


@pytest.mark.parametrize("payload", [
    {"intent": "apply", "positions": [1], "authorized": True},
    {"intent": "apply", "positions": []}, {"intent": "apply", "positions": [1, 1]},
    {"intent": "apply", "positions": [11]}, {"intent": "submit_application"},
    {"intent": "search", "filters": {"maximum_employees": 1, "minimum_employees": 10}},
])
def test_model_cannot_smuggle_authorization_or_bad_selections(payload):
    with pytest.raises(ValidationError):
        Understanding.model_validate(payload)


@pytest.mark.asyncio
async def test_unknown_without_cloud_requests_clarification():
    understanding, tokens = await CommandPlanner(Settings(_env_file=None)).understand(
        "Handle everything on that other thing", {})
    assert understanding.intent == "clarify" and understanding.missing_information and tokens == 0


def test_caps_and_unverified_salary_remain_explicit():
    with pytest.raises(ValidationError):
        Filters(limit=100)
    plan = CommandPlanner(Settings(_env_file=None)).plan(Understanding(intent="search",
        filters=Filters(minimum_salary=100000, minimum_employees=2, maximum_employees=10)), {})
    assert plan.filters.salary_currency is None and plan.filters.salary_period is None
