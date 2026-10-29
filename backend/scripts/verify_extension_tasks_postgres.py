"""Focused PostgreSQL owner/tab/authorization races on a fresh fictional DB only."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def verify(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
            or parsed.path != "/candidate_profile_test" or parsed.port in {None, 5432, 54322}
            or parsed.query or parsed.username != "postgres"):
        raise ValueError("disposable_loopback_postgresql_required")
    from backend.app.core.config import Settings, configure_operator
    settings = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="job_agent",
        DATABASE_URL=url.replace("postgresql://", "postgresql+asyncpg://", 1),
        CHROME_EXTENSION_ID="a" * 32, CHROME_NATIVE_MESSAGING_ENABLED=True,
        BROWSER_FILL_ENABLED=True, BROWSER_AUTOMATION_ENABLED=False,
        BROWSER_SUBMIT_ENABLED=False, GMAIL_SENDING_ENABLED=False,
        COHERE_ENABLED=False, GEMINI_ENABLED=False, AGY_ENABLED=False)
    configure_operator(settings)
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.browser import extension_tasks as tasks
    from backend.app.browser.contracts import FillReceipt, Inspection
    from backend.app.local_agent.contracts import Actor, Command
    from backend.app.local_agent.profile_confirmation import confirm_profile
    from backend.app.local_agent.service import dispatch
    from backend.app.main import app  # noqa: F401 - registers existing model metadata
    from backend.app.models.application_answer import CandidateResource
    from backend.app.models.base import Base
    from backend.app.models.job import Job
    from backend.app.repositories.candidate_profile import CandidateProfileRepository
    from backend.app.schemas.applications import CreatePacket
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    from backend.app.services.applications.service import ApplicationPacketService

    engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True,
        connect_args={"server_settings": {"search_path": "job_agent,public"}})
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    actor = Actor(channel="chrome", identity=settings.CHROME_EXTENSION_ID)
    try:
        async with engine.begin() as connection:
            assert not await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')")), "fresh_database_required"
            await connection.execute(text("CREATE SCHEMA job_agent"))
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(
                full_name="Alex Example", email="alex@example.com", verified_skills=["Python"],
                verified_experience_years=2))
            await confirm_profile(session, profile, profile.version)
            session.add(CandidateResource(candidate_profile_id=profile.id, resource_type="resume",
                label="Fictional confirmed resume", url="https://fictional.example/resume.pdf",
                is_primary=True, user_confirmed=True))
            packets = []
            for suffix in ["one", "two", "three"]:
                destination = f"https://jobs.lever.co/fictional/fictional-{suffix}/apply"
                job = Job(title=f"Fictional Engineer {suffix}", job_url=destination,
                    application_url=destination, source_platform="owner_extension", description="Fictional Python role")
                session.add(job)
                await session.flush()
                packet = await ApplicationPacketService(session).create(job.id,
                    CreatePacket(idempotency_key="pg-extension-fictional-" + suffix))
                packets.append(packet)
            await session.commit()

        async def send(command):
            async with factory() as session:
                result = await dispatch(session, settings, actor, command)
                await session.commit()
                return result

        browser_session = uuid4()
        opens = await asyncio.gather(*[send(Command(command="open_application_task",
            application_id=packets[0].id, browser_session_id=browser_session, tab_id=17)) for _ in range(2)])
        assert all(result.ok for result in opens)
        assert opens[0].data["task"]["id"] == opens[1].data["task"]["id"]
        task = opens[0].data["task"]
        async with factory() as session:
            assert len(await tasks.rows(session)) == 1
        races = await asyncio.gather(*[send(Command(command="update_application_task", task_id=task["id"],
            expected_task_version=task["version"], browser_session_id=browser_session,
            tab_id=17, task_event="pause")) for _ in range(2)])
        assert sum(result.ok for result in races) == 1
        assert next(result for result in races if not result.ok).error_code == "extension_task_revision_conflict"
        task = next(result for result in races if result.ok).data["task"]
        resumed = await send(Command(command="update_application_task", task_id=task["id"],
            expected_task_version=task["version"], browser_session_id=browser_session, tab_id=17, task_event="resume"))
        assert resumed.ok
        task = resumed.data["task"]
        inspected = await send(Command(command="inspect_form", application_id=packets[0].id,
            task_id=task["id"], expected_task_version=task["version"], browser_session_id=browser_session, tab_id=17,
            inspection=Inspection(document_id=str(uuid4()), url=task["target_url"], fields=[{
                "field_id": "f0", "kind": "email", "label": "Email", "required": True}])))
        assert inspected.ok, inspected.error_code
        task, plan = inspected.data["task"], inspected.data["plan"]
        authorizations = await asyncio.gather(*[send(Command(command="authorize_form", plan_id=plan["id"],
            field_ids=["f0"], task_id=task["id"], expected_task_version=task["version"],
            browser_session_id=browser_session, tab_id=17)) for _ in range(2)])
        assert sum(result.ok for result in authorizations) == 1
        task = next(result for result in authorizations if result.ok).data["task"]
        receipt = await send(Command(command="record_form_fill", task_id=task["id"], expected_task_version=task["version"],
            browser_session_id=browser_session, tab_id=17,
            receipt=FillReceipt(plan_id=plan["id"], state="form_filled", verification_method="retained_after_blur",
                results=[{"field_id": "f0", "status": "filled"}])))
        assert receipt.ok, receipt.error_code
        assert receipt.data["task"]["state"] == "READY_FOR_SUBMISSION"
        tab_session = uuid4()
        tab_race = await asyncio.gather(*[send(Command(command="open_application_task", application_id=packet.id,
            browser_session_id=tab_session, tab_id=19)) for packet in packets[1:]])
        assert sum(result.ok for result in tab_race) == 1
        assert next(result for result in tab_race if not result.ok).error_code == "extension_tab_already_owned"
        async with factory() as session:
            saved = await tasks.load(session, task["id"])
            assert len(saved.value["verified_receipts"]) == 1
            assert saved.value["verified_receipts"][0]["submitted"] is False
            assert await session.scalar(select(Job.id).limit(1)) is not None
        print(json.dumps({"cases": 4, "database": "isolated PostgreSQL17 ORM fixture",
            "duplicate_task_race": "one identity", "task_version_race": "one winner",
            "authorization_race": "one winner", "tab_ownership_race": "one winner",
            "durable_fill_receipts": 1, "submissions": 0}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    asyncio.run(verify(parser.parse_args().url))
