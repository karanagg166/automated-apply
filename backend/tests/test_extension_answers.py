"""Explicit manual extension answers on fictional Zoho pages; no employer IO."""

import pytest
from sqlalchemy import func, select

from backend.app.browser.service import FormService, target
from backend.app.core.config import Settings
from backend.app.local_agent.contracts import Actor, Command
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.app.local_agent.service import dispatch
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job
from backend.app.services.applications.platforms.owner_page import manual_page_url
from backend.tests.chrome_profile_fixture import BINDING, SESSION, connected
from backend.tests.test_browser_forms import inspection

URL = "https://fictional-employer.zohorecruit.in/jobs/Careers/123456/Backend-Engineer?source=CareerSite&ref=fixture"
EXTENSION = "a" * 32


def config(**changes):
    return Settings(_env_file=None, **{
        "ENVIRONMENT": "testing", "BROWSER_FILL_ENABLED": True,
        "CHROME_EXTENSION_ID": EXTENSION, **changes,
    })


def command():
    return Command(**BINDING, browser_session_id=SESSION, tab_id=17, command="prepare_form_answers", title="Fictional Backend Engineer", inspection=inspection(URL))


async def prepare(session, **changes):
    await connected(session, config(**changes))
    return await dispatch(session, config(**changes), Actor(channel="chrome", identity=EXTENSION), command())


@pytest.mark.asyncio
async def test_answers_require_current_owner_review_before_saving_a_job(db_session, phase2_profile):
    result = await prepare(db_session)
    assert not result.ok and result.error_code == "profile_review_required"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.asyncio
async def test_answers_reuse_packets_and_leave_unknown_facts_unanswered(db_session, phase2_profile):
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    result = await prepare(db_session)
    assert result.ok and result.data["submitted"] is False
    plan = result.data["plan"]
    assert [action["value"] for action in plan["actions"]] == ["Alex Example", "alex@example.com", None, None]
    job = await db_session.scalar(select(Job))
    assert str(job.id) == plan["job_id"] and job.job_url == URL
    assert job.source_verification_status == "owner_selected"
    assert job.discovery_metadata["employer_identity_verified"] is False
    second = await prepare(db_session)
    assert second.ok and second.data["plan"]["application_id"] == plan["application_id"]
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ApplicationPacket)) == 1
    packet = await db_session.scalar(select(ApplicationPacket))
    assert packet.snapshot["destination"]["source_confidence"] == "unverified"
    service = FormService(db_session, config())
    await service.review(plan["id"], ["f0", "f1"])
    await service.consume(plan["id"], "manual_extension")
    with pytest.raises(ValueError):
        await service.consume(plan["id"], "manual_extension")


@pytest.mark.asyncio
async def test_existing_answer_authorizations_expire_after_profile_edit(db_session, phase2_profile):
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    result = await prepare(db_session)
    phase2_profile.version += 1
    await db_session.flush()
    with pytest.raises(ValueError):
        await FormService(db_session, config()).review(result.data["plan"]["id"], ["f0"])


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,enabled", [("owner", True), ("chrome", False)])
async def test_answer_requests_cannot_bypass_manual_extension_activation(db_session, actor, enabled):
    await connected(db_session, config(BROWSER_FILL_ENABLED=enabled))
    result = await dispatch(db_session, config(BROWSER_FILL_ENABLED=enabled), Actor(channel=actor, identity=EXTENSION), command())
    assert not result.ok
    assert result.error_code == ("profile_review_required" if actor == "chrome" else "manual_form_not_authorized")
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


def test_zoho_manual_destination_does_not_enable_autonomous_navigation():
    assert manual_page_url(URL) == URL
    with pytest.raises(ValueError):
        target(URL, config())
    for value in [URL + "&token=secret", URL.replace(".in/", ".in.evil.example/"), URL.replace("/jobs/Careers/", "/admin/"), URL + "#fragment", URL + "&ref=other", URL.replace("https:", "http:")]:
        assert manual_page_url(value) is None


@pytest.mark.asyncio
async def test_owner_selected_zoho_packet_cannot_enter_automation_mode(db_session, phase2_profile):
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    result = await prepare(db_session)
    with pytest.raises(ValueError):
        await FormService(db_session, config()).context(result.data["plan"]["application_id"])
