"""Explicit skill-gap consent never changes facts or the remaining job filters."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import queue_reconsideration as rechecks
from backend.app.execution.queue_contracts import (
    QueueControl,
    QueuePolicy,
    QueuePolicyUpdate,
)
from backend.app.execution.queue_preparation import prepare_one
from backend.app.models.candidate_profile import CandidateProfile
from backend.tests.test_application_queue import URL
from backend.tests.test_naukri_background_queue import call, job_report, observe, setup
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


@pytest.mark.parametrize("allow, change, expected", [
    (False, None, "current_profile_preferences_or_required_skills_exclude_job"),
    (True, None, None),
    (True, "zero_skills", "current_profile_preferences_or_required_skills_exclude_job"),
    (True, "score", "minimum_match_score_required"),
    (True, "applicants", "applicant_limit_reached"),
    (True, "unknown_count", "applicant_count_requires_review"),
    (True, "age", "posting_outside_age_limit"),
    (True, "experience", "required_experience_outside_verified_band"),
    (True, "role", "current_profile_preferences_or_required_skills_exclude_job"),
])
async def test_skill_policy_does_not_authorize_fabrication_or_filter_bypass(db_session, upload_case, allow, change, expected):
    from sqlalchemy import select

    context = await setup(db_session)
    profile = await db_session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
    skills_before = list(profile.verified_skills)
    config = await queue.configuration(db_session)
    policy = QueuePolicy.model_validate(config["policy"])
    policy.global_limits.minimum_match_score = 100 if change == "score" else 50
    policy.global_limits.applicant_limit = 1000
    policy.platforms["naukri"].skill_match_mode = "any" if allow else "all"
    configured = await queue.configure(db_session, QueuePolicyUpdate(expected_revision=config["revision"], policy=policy))
    await queue.control(db_session, QueueControl(expected_revision=configured["revision"], action="start"))
    assert (await db_session.get(OwnerPreference, rechecks.KEY)).value["status"] == "pending"
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    facts = {"skills": ["Python", "AWS"], "employment_type": "full_time"}
    if change == "zero_skills":
        facts["skills"] = ["UnverifiedFramework", "AWS"]
    elif change == "applicants":
        facts.update(applicants_min=1000, applicants_max=1000)
    elif change == "unknown_count":
        facts.update(applicants_min=100, applicants_max=None)
    elif change == "age":
        facts["posted_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    elif change == "experience":
        facts.update(experience_min=50, experience_max=60)
    elif change == "role":
        facts["title"] = "Unrelated Sales Representative"
    result = await call(db_session, context, "finish_naukri_work", work, work_report=job_report(**facts))
    assert result.ok, result.error_code
    value = (await queue.load(db_session, item["id"])).value
    if expected:
        assert value["reason"] == expected
        assert value["stage"] in {"SKIPPED", "NEEDS_INPUT"}
        assert not value["packet_id"]
    else:
        assert value["stage"] == "ELIGIBLE" and value["match_score"] >= 50
        await db_session.commit()
        assert await prepare_one(db_session, upload_case.settings)
        value = (await queue.load(db_session, item["id"])).value
        assert value["stage"] == "READY_TO_APPLY", value
        assert value["packet_id"] and not value["admitted_actions"]
    assert (await db_session.get(CandidateProfile, profile.id)).verified_skills == skills_before
    assert "AWS" not in skills_before and not value["admitted_actions"]

async def test_skill_mode_alone_requests_fresh_reconsideration(db_session, upload_case):
    await setup(db_session)
    current = await queue.configuration(db_session)
    before = (await db_session.get(OwnerPreference, rechecks.KEY)).value["id"]
    policy = QueuePolicy.model_validate(current["policy"])
    assert policy.platforms["naukri"].skill_match_mode == "all"
    policy.platforms["naukri"].skill_match_mode = "any"
    await queue.configure(db_session, QueuePolicyUpdate(expected_revision=current["revision"], policy=policy))
    state = (await db_session.get(OwnerPreference, rechecks.KEY)).value
    assert state["id"] != before and state["status"] == "pending"
    assert (await queue.configuration(db_session))["state"] == "PAUSED"
