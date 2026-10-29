"""Shared dispatcher for all local clients. URLs are validated and saved, never fetched."""
import asyncio
import hashlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.automation.models import AutomationSchedule
from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.contracts import Actor, Command, Result, page_kind
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import evaluate, get_policy

CAPABILITIES = {name: "preview_only" for name in (
    "preview_application_url", "preview_job_filters", "get_discovery_status", "conversation", "observe_platform_session",
)} | {name: "read_only" for name in (
    "health", "connection_status", "get_agent_capabilities", "get_application_policy",
)}


async def dispatch(session, settings, actor: Actor, command: Command):
    from backend.app.browser.chrome_profiles import NATIVE, native
    if command.command in NATIVE:
        return await native(session, settings, actor, command)
    if command.command in {"open_application_task", "get_application_task", "update_application_task", "ask_form_questions"}:
        from backend.app.browser.extension_tasks import dispatch_task
        return await dispatch_task(session, settings, actor, command)
    if command.command in {"inspect_form", "prepare_form_answers", "authorize_form", "record_form_fill"}:
        from backend.app.browser.manual import dispatch_form
        return await dispatch_form(session, settings, actor, command)
    key = f"{actor.channel}:{actor.identity}:{command.request_id}"
    digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    previous = await session.get(AgentOperation, key)
    if previous:
        if previous.payload_hash != digest:
            return Result(request_id=command.request_id, ok=False, capability="denied", error_code="request_id_conflict")
        return Result.model_validate(previous.result)
    async with asyncio.timeout(35):
        result = await execute(session, settings, actor, command)
        try:
            async with session.begin_nested():
                session.add(AgentOperation(key=key, actor=f"{actor.channel}:{actor.identity}",
                    command=command.command, payload_hash=digest, result=result.model_dump(mode="json")))
                await session.flush()
        except IntegrityError:
            previous = await session.get(AgentOperation, key)
            if previous and previous.payload_hash == digest:
                return Result.model_validate(previous.result)
            return Result(request_id=command.request_id, ok=False, capability="denied", error_code="request_id_conflict")
        return result


async def execute(session, settings, actor, command):
    data, error = {}, None
    if command.command == "observe_platform_session":
        from backend.app.local_agent.platforms import PLATFORMS, save_observation
        if actor.channel != "chrome" or actor.identity != settings.CHROME_EXTENSION_ID:
            error = "extension_identity_required"
        elif not command.url or page_kind(str(command.url)) not in PLATFORMS or command.observation is None:
            error = "unsupported_platform_observation"
        else:
            platform = page_kind(str(command.url))
            data = {**await save_observation(session, platform, command.observation),
                "platform": platform, "api_connected": False, "identity_verified": False, "submitted": False}
    elif command.command == "conversation":
        if actor.channel != "telegram" or actor.identity != str(settings.TELEGRAM_OWNER_USER_ID):
            error = "telegram_identity_required"
        elif command.intent is None:
            error = "intent_required"
        else:
            from backend.app.local_agent.conversation import respond
            knowledge = getattr(command, "knowledge", None)
            if knowledge is None:
                from backend.app.candidate_context.persistence import SQLRecordStore
                from backend.app.candidate_context.service import (
                    CandidateContextService,
                    TelegramKnowledgeAdapter,
                )
                svc = CandidateContextService(SQLRecordStore(session))
                cfg = await svc.configuration()
                if cfg.revision > 0 or any(p.name for p in cfg.configuration.projects):
                    knowledge = TelegramKnowledgeAdapter(svc)
            data = await respond(session, settings, actor, command.intent, knowledge=knowledge)
    elif command.command == "preview_application_url":
        if command.url is None:
            error = "url_required"
        else:
            platform = page_kind(str(command.url))
            policy = evaluate(await get_policy(session), platform, "url_preview")
            if not policy["preview_allowed"]:
                error = "connection_disabled"
            else:
                # Page titles are untrusted and deliberately not persisted or returned.
                data = {"url": str(command.url), "platform": platform, "policy": policy,
                        "status": "preview_saved", "page_inspected": False, "submitted": False}
    elif command.command == "get_application_policy":
        data = await get_policy(session)
    elif command.command == "get_agent_capabilities":
        data = {"operations": CAPABILITIES, "submissions": False, "email_sending": False, "paid_calls": False}
    elif command.command == "preview_job_filters":
        from backend.app.local_agent.preferences import get_preferences
        rows = (await session.scalars(select(OwnerPreference).where(OwnerPreference.key == "startup_presets"))).all()
        data = {"preferences": await get_preferences(session), "saved_presets": [{"key": row.key, "value": row.value} for row in rows], "executed": False}
    elif command.command == "get_discovery_status":
        row = await session.get(AutomationSchedule, "primary")
        data = {"deployment_enabled": settings.AUTOMATION_EXECUTION_ENABLED,
                "schedule_enabled": bool(row and row.enabled), "discovery_executed": False}
    elif command.command in {"health", "connection_status"}:
        from backend.app.local_agent.registry import connection_report
        rows = await connection_report(session, settings, api_request=actor.channel in {"owner", "chrome"})
        if command.command == "health":
            data = {"connections": [{"name": row["name"], "state": row["state"]} for row in rows
                                   if row["name"] in {"Supabase PostgreSQL", "Local FastAPI"}],
                    "endpoint": settings.LOCAL_AGENT_ENDPOINT}
        else:
            data = {"connections": [{key: row[key] for key in ("name", "state", "last_verification_time")} for row in rows]}
    return Result(request_id=command.request_id, ok=error is None,
                  capability=CAPABILITIES[command.command], error_code=error, data=data)
