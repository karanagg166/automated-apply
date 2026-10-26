"""Owner-only cached discovery and preparation previews, using existing SQL state."""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import func, select

from backend.app.core.urls import PublicHTTPSURL
from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.contracts import page_kind
from backend.app.local_agent.intents import Intent
from backend.app.local_agent.memory import (
    context_key,
    load_memory,
    record_intent,
    reset_memory,
    save_memory,
)
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import evaluate, get_policy
from backend.app.local_agent.preferences import get_preferences
from backend.app.models.application_packet import (
    ApplicationPacket,
    ApplicationSubmissionEvidence,
)
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.job import Job

HELP = ('You can ask about application status, your resume, connections and approved profile facts; say “Find backend engineer jobs at Swiggy in India”, '
        '“Apply for Swiggy”, “Show jobs I haven’t applied to”, '
        '“Check whether Gmail is connected”, or “How many applications are pending?”. '
        'Search uses cached jobs; preparation stops at a preview. No submissions or email sends.')


def clean_label(value):
    value = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    value = re.sub(r"(?:sbp_|sk-)[A-Za-z0-9_-]+|\d{6,}:[A-Za-z0-9_-]{20,}", "[redacted]", value)
    return value[:120]


def safe_job_url(value):
    try:
        value = str(TypeAdapter(PublicHTTPSURL).validate_python(value))
    except (TypeError, ValueError):
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


async def save_context(session, actor, jobs, prepare, intent):
    previous = await load_memory(session, actor)
    value = {**previous, "job_ids": [str(job.id) for job in jobs[:10]], "prepare": prepare, "intent": intent.model_dump(mode="json"),
             "selected_job_id": None, "current_company": intent.company,
             "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    await save_memory(session, actor, value)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def matches(job, company, intent, prefs, profile):
    title, location = job.title.casefold(), (job.location or "").casefold()
    company_name = (company.name if company else "").casefold()
    if intent.company and company_name != intent.company.casefold():
        return False
    if intent.role and not all(word in title for word in intent.role.casefold().split()):
        return False
    if intent.location and intent.location.casefold() not in location:
        return False
    remote = intent.remote or prefs.get("remote_preference") == "remote"
    if remote and job.remote_type != "remote":
        return False
    if prefs.get("remote_preference") in {"onsite", "hybrid"} and job.remote_type != prefs["remote_preference"]:
        return False
    if not intent.location and prefs.get("preferred_locations") and not (remote or any(x.casefold() in location for x in prefs["preferred_locations"])):
        return False
    if not intent.role and prefs.get("target_titles") and not any(x.casefold() in title for x in prefs["target_titles"]):
        return False
    if prefs.get("employment_types") and job.employment_type not in prefs["employment_types"]:
        return False
    if prefs.get("source_platforms") and job.source_platform not in prefs["source_platforms"]:
        return False
    if intent.not_applied or prefs.get("application_status") == "not_applied":
        if job.status == "applied":
            return False
    if prefs.get("application_status") == "applied" and job.status != "applied":
        return False
    if job.status in {"archived", "rejected"}:
        return False
    days = intent.days or prefs.get("posting_recency_days")
    if days and (not job.date_posted or utc(job.date_posted) < datetime.now(timezone.utc) - timedelta(days=days)):
        return False
    skills = {x.casefold() for x in job.skills_required or []}
    if any(x.casefold() not in skills for x in intent.skills or prefs.get("technology_stacks", [])):
        return False
    if prefs.get("relevance_threshold") and (job.match_score is None or float(job.match_score) < prefs["relevance_threshold"]):
        return False
    for key, field, compare in [("minimum_salary", job.salary_min, lambda a, b: a >= b), ("maximum_salary", job.salary_max, lambda a, b: a <= b)]:
        if prefs.get(key) is not None:
            if field is None or not compare(float(field), prefs[key]) or job.salary_currency != prefs.get("salary_currency") or job.salary_period != prefs.get("salary_period"):
                return False
    metadata = company.metadata_ or {} if company else {}
    startup = metadata.get("startup_discovery", {})
    if intent.startup and not (job.source_platform == "work_at_a_startup" or startup.get("stage") in {"pre_seed", "seed", "early", "startup"}):
        return False
    if prefs.get("company_stages") and startup.get("stage") not in prefs["company_stages"]:
        return False
    for key, comparison in [("minimum_employees", lambda a, b: a >= b), ("maximum_employees", lambda a, b: a <= b)]:
        if prefs.get(key) is not None:
            employees = startup.get("employee_count")
            if type(employees) is not int or not comparison(employees, prefs[key]):
                return False
    # No numeric experience field exists on Job; never infer it from description text.
    if prefs.get("minimum_experience") is not None or prefs.get("maximum_experience") is not None:
        return False
    exclusions = prefs
    if any(company_name == x.casefold() for x in exclusions.get("excluded_companies", [])):
        return False
    if any(x.casefold() in title for x in exclusions.get("excluded_titles", [])):
        return False
    if any(x.casefold() in title + " " + (job.description or "").casefold() for x in exclusions.get("excluded_keywords", [])):
        return False
    return True


async def preview(session, job, policy):
    if not evaluate(policy, page_kind(job.application_url or job.job_url), "url_preview")["preview_allowed"]:
        return {"reply": "Preview denied: this platform is disabled.", "status": "denied"}
    from backend.app.schemas.applications import CreatePacket
    from backend.app.services.applications.service import ApplicationPacketService
    service = ApplicationPacketService(session)
    profile = await session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
    packet_id = None
    if profile:
        existing = await session.scalar(select(ApplicationPacket).where(ApplicationPacket.job_id == job.id,
            ApplicationPacket.candidate_profile_id == profile.id))
        value = await service.read(existing.id) if existing else await service.create(job.id,
            CreatePacket(idempotency_key="telegram-prepare-" + str(job.id)))
        packet_id = str(value.id)
    else:
        value = await service.preview(job.id)
    # Personal answers, profile details, resume contents and salary never enter replies.
    return {"reply": f"Application {'prepared for review' if packet_id else 'preview'}: {clean_label(job.title)}. Readiness: {value.readiness.state}. Review it in the dashboard. No application submitted.",
            "status": "prepared_for_review" if packet_id else "preparation_preview", "packet_id": packet_id,
            "job_id": str(job.id), "readiness": value.readiness.state, "submitted": False}


async def respond(session, settings, actor, intent, *, knowledge=None):
    count = await session.scalar(select(func.count()).select_from(AgentOperation).where(
        AgentOperation.actor == f"telegram:{actor.identity}",
        AgentOperation.created_at > datetime.now(timezone.utc) - timedelta(minutes=1)))
    if count >= 20:
        return {"reply": "Too many requests. Please wait one minute.", "status": "rate_limited"}
    memory = await record_intent(session, actor, intent)
    if intent.category == "RESET_CONTEXT":
        value = await reset_memory(session, actor)
        return {"reply": "Previous job and project selection cleared. Start a fresh search.", "status": "context_reset", "conversation_id": value["conversation_id"]}
    if intent.category in {"HELP", "UNKNOWN"}:
        return {"reply": HELP if intent.category == "HELP" else "AI chat unavailable. I could not safely interpret that. " + HELP, "status": intent.category.lower()}
    if intent.category == "GENERAL_CHAT":
        return {"reply": "You're welcome. " + HELP, "status": "general_chat"}
    if intent.category == "APPROVAL_REQUEST":
        return {"reply": "Review the exact item in the dashboard to approve it. Telegram cannot approve submissions, sending, purchases or profile facts.", "status": "owner_review_required"}
    if intent.category == "PROFILE_QUERY":
        from backend.app.local_agent.knowledge import profile_reply
        return await profile_reply(session)
    if intent.category in {"PROJECT_QUERY", "ANSWER_PREPARATION"}:
        from backend.app.local_agent.knowledge import project_reply
        memory["project_rank"] = intent.project_rank or memory.get("project_rank")
        if intent.follow_up == "answer" and memory.get("answer_question"):
            intent = intent.model_copy(update={"subject": memory["answer_question"]})
        else:
            memory["answer_question"] = intent.subject
        await save_memory(session, actor, memory)
        return await project_reply(intent.model_copy(update={"project_rank": memory["project_rank"]}), knowledge)
    if intent.category == "RESUME_STATUS":
        from backend.app.resume_sync.models import ResumeDriveSource
        source = await session.get(ResumeDriveSource, "primary")
        if not source:
            return {"reply": "Resume synchronization has no saved source. Configure and review your canonical PDF in Profile. An existing upload may still need confirmation.", "status": "resume_not_configured"}
        return {"reply": f"Resume sync: {clean_label(source.status)}. Approved version: {'available' if source.active_version_id else 'not selected'}. Periodic checking {'enabled' if source.sync_enabled else 'disabled'}; worker health is shown in Profile. Replacement PDFs require review.", "status": "resume_status"}
    if intent.category == "FOLLOW_UP":
        if intent.follow_up == "clarify":
            memory["clarification"] = "choose_one_request"
            await save_memory(session, actor, memory)
            return {"reply": "Those requests need different workflows. Choose one first: job search, status, profile, resume or connections.", "status": "clarification_required"}
        if not memory.get("intent") or not memory.get("job_ids"):
            return {"reply": "There is no current job selection. Search for jobs first, then choose a number or add a filter.", "status": "selection_required"}
        if intent.follow_up == "filter":
            prior = Intent.model_validate(memory["intent"])
            changes = {key: getattr(intent, key) for key in ("location", "days") if getattr(intent, key) is not None}
            if intent.remote:
                changes["remote"] = True
            if not changes:
                return {"reply": "Which filter should change? Specify remote, a location, or today's jobs.", "status": "clarification_required"}
            intent = prior.model_copy(update={**changes, "category": "FILTER_JOBS"})
        elif memory.get("selected_job_id"):
            if intent.follow_up == "prepare":
                memory["prepare"] = True
                await save_memory(session, actor, memory)
            intent = Intent(category="SHOW_JOB", job_id=memory["selected_job_id"])
        else:
            return {"reply": "Choose a listed job number first; 'that job' is ambiguous.", "status": "clarification_required"}
    if intent.category == "JOB_COMPARISON":
        ids = memory.get("job_ids", [])
        jobs = (await session.scalars(select(Job).where(Job.id.in_([UUID(i) for i in ids])))).all() if ids else []
        jobs = [job for job in jobs if job.status not in {"applied", "archived", "rejected"}]
        jobs.sort(key=lambda job: (-(float(job.match_score) if job.match_score is not None else -1), str(job.id)))
        if not jobs:
            return {"reply": "Search for jobs first so I can compare the current cached choices.", "status": "selection_required"}
        return {"reply": "Cached choices by saved match score (unknown scores last):\n" + "\n".join(f"{clean_label(job.title)}: {job.match_score if job.match_score is not None else 'not scored'}" for job in jobs[:5]) + ". Check eligibility and availability in the dashboard before prioritizing.", "status": "job_comparison"}
    if intent.category == "CONNECTION_STATUS":
        from backend.app.local_agent.registry import connection_report
        rows = await connection_report(session, settings)
        rows = [row for row in rows if not intent.connection or ("work at a startup" if intent.connection == "yc" else intent.connection) in row["name"].casefold()]
        return {"reply": "\n".join(f"{row['name']}: {row['state']}" for row in rows), "status": "connection_status"}
    if intent.category == "APPLICATION_STATUS":
        counts = (await session.execute(select(ApplicationPacket.tracking_state, func.count()).group_by(ApplicationPacket.tracking_state))).all()
        return {"reply": "Saved application packets: " + (", ".join(f"{clean_label(state)}: {count}" for state, count in counts) or "0") + ". These are saved tracking states; unverified submissions are not provider-confirmed.", "status": "application_status"}
    if intent.category in {"GMAIL_DRAFT_PREVIEW", "FOUNDER_RESEARCH_PREVIEW"}:
        return {"reply": "Use the dashboard to review " + ("a Gmail draft preview. No draft was created and no email was sent." if intent.category == "GMAIL_DRAFT_PREVIEW" else "cached recruiter/founder evidence. No paid enrichment or external research was run."), "status": "manual_review_required"}
    policy = await get_policy(session)
    profile = await session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
    saved = await session.get(OwnerPreference, "agent_search_preferences")
    prefs = {**(profile.preferences if profile else {}), **(saved.value if saved else {})}
    defaults = await get_preferences(session)
    prefs = {**defaults, **prefs}
    if intent.url:
        platform = page_kind(str(intent.url))
        if not evaluate(policy, platform, "url_preview")["preview_allowed"]:
            return {"reply": "Preview denied: this platform is disabled.", "status": "denied"}
        return {"reply": f"URL preview saved ({platform}). Page not inspected. Open the dashboard for review; no application submitted.", "status": "url_preview", "url": str(intent.url), "submitted": False}
    if intent.category == "SHOW_JOB":
        context = await session.get(OwnerPreference, context_key(actor))
        try:
            value = context.value
            if datetime.fromisoformat(value["expires_at"]) < datetime.now(timezone.utc):
                raise ValueError
            selected = str(intent.job_id) if intent.job_id else value["job_ids"][intent.selection - 1]
            if selected not in value["job_ids"]:
                raise ValueError
            job = await session.get(Job, UUID(selected))
            if not job or job.status in {"applied", "rejected", "archived"}:
                raise ValueError
            submitted = await session.scalar(select(ApplicationSubmissionEvidence.id).join(ApplicationPacket,
                ApplicationPacket.id == ApplicationSubmissionEvidence.packet_id).where(ApplicationPacket.job_id == job.id).limit(1))
            if submitted or not evaluate(policy, page_kind(job.job_url), "url_preview")["preview_allowed"]:
                raise ValueError
            company = await session.get(Company, job.company_id) if job.company_id else None
            if not matches(job, company, Intent.model_validate(value["intent"]), prefs, profile):
                raise ValueError
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            return {"reply": "That selection is unavailable or expired. Search again and choose a listed job number.", "status": "selection_required"}
        if value["prepare"]:
            await save_memory(session, actor, {**value, "selected_job_id": str(job.id)})
            return await preview(session, job, policy)
        await save_memory(session, actor, {**value, "selected_job_id": str(job.id)})
        return {"reply": f"{clean_label(job.title)} · {clean_label(job.source_platform)}\n{safe_job_url(job.job_url) or 'URL unavailable'}\nStatus: {clean_label(job.status)}. No application submitted.", "status": "job_details"}
    prepare = intent.category == "PREPARE_APPLICATION"
    # Resolve a company prefix only against actual saved company records. No name
    # is invented or fuzzy-corrected; ambiguous identities require clarification.
    if intent.role and not intent.company:
        names = (await session.scalars(select(Company.name).order_by(Company.name).limit(201))).all()
        candidates = [name for name in names if intent.role.casefold() == name.casefold()
            or intent.role.casefold().startswith(name.casefold() + " ")]
        if len(candidates) > 1:
            return {"reply": "Which company did you mean? " + ", ".join(clean_label(n) for n in candidates[:5]), "status": "clarification_required"}
        if candidates:
            company = candidates[0]
            intent = intent.model_copy(update={"company": company, "role": intent.role[len(company):].strip() or None})
    query = select(Job, Company).outerjoin(Company, Job.company_id == Company.id).order_by(Job.created_at.desc(), Job.id).limit(201)
    if intent.not_applied or prepare or prefs.get("application_status") == "not_applied":
        query = query.where(Job.id.not_in(select(ApplicationPacket.job_id).join(ApplicationSubmissionEvidence,
            ApplicationSubmissionEvidence.packet_id == ApplicationPacket.id)))
    if intent.company:
        query = query.where(func.lower(Company.name) == intent.company.casefold())
    rows = (await session.execute(query)).all()
    jobs = [job for job, company in rows[:200] if matches(job, company, intent, prefs, profile) and safe_job_url(job.job_url)
            and evaluate(policy, page_kind(job.job_url), "url_preview")["preview_allowed"]][:10]
    await save_context(session, actor, jobs, prepare, intent)
    if not jobs:
        return {"reply": "No matching cached jobs found under your saved filters. Live discovery was not run. Unknown required properties are excluded; no vacancies were invented.", "status": "no_matches", "search_limited": len(rows) > 200}
    if prepare and len(jobs) == 1:
        return await preview(session, jobs[0], policy)
    lines = [f"{i}. {clean_label(job.title)} · {clean_label(job.source_platform)}\n{safe_job_url(job.job_url)}" for i, job in enumerate(jobs, 1)]
    return {"reply": "Matching cached jobs (listing availability and eligibility still need review):\n" + "\n".join(lines) + "\nReply with a job number within 10 minutes." + (" Selection prepares a preview only." if prepare else " No application submitted.") + (" Search inspected the latest 200 records." if len(rows) > 200 else ""),
            "status": "selection_required", "job_ids": [str(job.id) for job in jobs], "search_limited": len(rows) > 200}
