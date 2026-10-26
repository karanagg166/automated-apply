"""Backend-controlled tool proposals. This registry exposes no general-purpose transport."""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import Field, ValidationError
from sqlalchemy import func, select

from backend.app.agent.contracts import Campaign, Filters, ToolCall
from backend.app.local_agent.contracts import StrictModel, page_kind
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import evaluate, get_policy
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job
from backend.app.services.applications.service import ApplicationPacketService


class SearchArgs(StrictModel):
    filters: Filters


class LimitArgs(StrictModel):
    limit: int = Field(ge=1, le=10)


class PurposeArgs(StrictModel):
    purpose: str = Field(min_length=1, max_length=100)


class ProjectArgs(PurposeArgs):
    project: str | None = Field(None, min_length=1, max_length=100)


class JobArgs(StrictModel):
    job_id: UUID


class AnswerArgs(JobArgs):
    question: str = Field(min_length=1, max_length=2000)


class CampaignArgs(StrictModel):
    campaign_id: UUID


class CompanyArgs(StrictModel):
    company_id: UUID


class OutreachArgs(JobArgs):
    contact_id: UUID


# Arguments and scope are immutable server definitions, never model-supplied metadata.
REGISTRY = {
    "search_jobs": (SearchArgs, "read"), "filter_jobs": (SearchArgs, "read"),
    "rank_jobs": (LimitArgs, "read"), "get_candidate_profile": (PurposeArgs, "read"),
    "get_approved_project_context": (ProjectArgs, "read"), "get_canonical_resume": (PurposeArgs, "read"),
    "get_application_history": (LimitArgs, "read"), "prepare_application": (JobArgs, "prepare"),
    "generate_grounded_answer": (AnswerArgs, "prepare"), "preview_application": (JobArgs, "read"),
    "fill_application": (JobArgs, "fill"), "submit_application": (JobArgs, "submit"),
    "get_campaign_status": (CampaignArgs, "read"), "cancel_campaign": (CampaignArgs, "control"),
    "find_founder_profiles": (CompanyArgs, "read"), "create_outreach_draft": (OutreachArgs, "draft"),
}


def definitions(names=None):
    return [{"type": "function", "function": {"name": name,
        "description": f"Propose {name}; backend permission checks apply.",
        "parameters": contract.model_json_schema()}}
        for name, (contract, _) in REGISTRY.items() if names is None or name in names]


def owner_allowed(actor, settings):
    return ((actor.channel == "owner" and actor.identity == "primary") or
            (actor.channel == "telegram" and settings.TELEGRAM_OWNER_USER_ID is not None
             and actor.identity == str(settings.TELEGRAM_OWNER_USER_ID)))


class ToolDenied(ValueError):
    pass


class ToolExecutor:
    def __init__(self, session, settings, actor, campaign: Campaign):
        self.session, self.settings, self.actor, self.campaign = session, settings, actor, campaign
        self.candidates = []

    async def execute(self, proposal, step):
        proposal = ToolCall.model_validate(proposal)
        key = f"agent_tool:{self.campaign.id}:{step}"
        digest = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
        previous = await self.session.get(AgentOperation, key)
        if previous:
            if previous.payload_hash != digest or not owner_allowed(self.actor, self.settings):
                raise ToolDenied("idempotency_or_identity_conflict")
            return previous.result
        try:
            if not owner_allowed(self.actor, self.settings) or self.campaign.owner != "primary":
                raise ToolDenied("authenticated_owner_required")
            if self.campaign.state == "cancelled":
                raise ToolDenied("campaign_cancelled")
            if step >= min(self.campaign.plan.max_steps, self.campaign.plan.max_tool_calls) or self.campaign.tool_calls >= self.campaign.plan.max_tool_calls:
                raise ToolDenied("tool_limit_exceeded")
            # Unknown token usage cannot authorize further model-driven work.
            if self.campaign.tokens_used >= self.campaign.plan.max_tokens:
                raise ToolDenied("campaign_token_limit")
            contract, scope = REGISTRY[proposal.name]
            arguments = contract.model_validate(proposal.arguments)
            allowed = {action.name for action in self.campaign.plan.actions}
            if proposal.name not in allowed:
                raise ToolDenied("action_outside_plan")
            count = await self.session.scalar(select(func.count()).select_from(AgentOperation).where(
                AgentOperation.command.like("agent_tool:%"),
                AgentOperation.created_at > datetime.now(timezone.utc) - timedelta(minutes=1)))
            if count >= 60:
                raise ToolDenied("tool_rate_limited")
            if scope in {"prepare", "fill", "submit", "draft"}:
                approval = self.campaign.approval
                if not approval or approval.scope != scope or self.campaign.state != "running":
                    raise ToolDenied("campaign_approval_required")
                if len(self.campaign.plan.selected_jobs) > approval.maximum_applications:
                    raise ToolDenied("campaign_application_limit")
            job = None
            if isinstance(arguments, JobArgs):
                if arguments.job_id not in self.campaign.plan.selected_jobs:
                    raise ToolDenied("job_outside_owner_selection")
                job = await self.session.get(Job, arguments.job_id)
                if job is None:
                    raise ToolDenied("job_not_found")
                platform = page_kind(job.application_url or job.job_url)
                if job.source_platform == "linkedin" or platform == "linkedin":
                    raise ToolDenied("linkedin_discovery_only")
                policy = evaluate(await get_policy(self.session), platform, proposal.name)
                if not policy["preview_allowed"]:
                    raise ToolDenied("platform_disabled")
                if scope in {"prepare", "fill", "submit"}:
                    if platform not in self.campaign.approval.platforms:
                        raise ToolDenied("platform_not_authorized")
                if job.status == "applied" and scope in {"prepare", "fill", "submit"}:
                    raise ToolDenied("already_applied")
            result = await self._run(proposal.name, arguments, job)
        except (ToolDenied, ValidationError) as exc:
            result = {"status": "denied", "error_code": str(exc) if isinstance(exc, ToolDenied) else "invalid_tool_arguments"}
        self.campaign.tool_calls += 1
        # Store only bounded outcome metadata, never provider transcripts or secrets.
        self.session.add(AgentOperation(key=key, actor=f"{self.actor.channel}:{self.actor.identity}",
            command="agent_tool:" + proposal.name, payload_hash=digest, result=result))
        await self.session.flush()
        return result

    async def _run(self, name, arguments, job):
        if name in {"search_jobs", "filter_jobs", "rank_jobs"}:
            from backend.app.agent.discovery import execute_search
            return await execute_search(self, name, arguments)
        if name == "get_candidate_profile":
            from backend.app.local_agent.knowledge import reviewed_profile
            profile = await reviewed_profile(self.session)
            return {"status": "available", "profile_id": str(profile.id), "version": profile.version,
                "verified_skills": profile.verified_skills} if profile else {"status": "needs_input", "missing_information": ["Review the current candidate profile."]}
        if name == "get_approved_project_context":
            from backend.app.candidate_context.persistence import SQLRecordStore
            from backend.app.candidate_context.service import CandidateContextService
            service = CandidateContextService(SQLRecordStore(self.session))
            projects = await service.projects()
            return {"status": "available", "projects": projects}
        if name == "get_canonical_resume":
            from backend.app.repositories.candidate_knowledge import (
                CandidateKnowledgeRepository,
            )
            from backend.app.services.applications.resume_selector import select_resume
            repo = CandidateKnowledgeRepository(self.session)
            profile = await repo.profile()
            selection = select_resume(await repo.resolution_resources(profile.id))
            return {"status": "available" if selection.selected else "needs_input",
                "selection": selection.model_dump(mode="json")}
        if name == "get_application_history":
            rows = (await self.session.scalars(select(ApplicationPacket).order_by(
                ApplicationPacket.created_at.desc()).limit(arguments.limit))).all()
            return {"status": "available", "applications": [{"job_id": str(row.job_id),
                "state": row.tracking_state, "packet_id": str(row.id)} for row in rows]}
        if name in {"prepare_application", "preview_application", "generate_grounded_answer"}:
            from backend.app.local_agent.knowledge import reviewed_profile
            profile = await reviewed_profile(self.session)
            if not profile:
                return {"status": "needs_input", "missing_information": ["Review the current profile in the dashboard."]}
            if name == "generate_grounded_answer":
                from backend.app.ai.schemas import GenerateRequest
                from backend.app.services.application_answer_service import (
                    ApplicationAnswerService,
                )
                result = await ApplicationAnswerService(self.session, self.settings).generate(
                    GenerateRequest(question=arguments.question, job_id=job.id, save_draft=True))
                return result.model_dump(mode="json")
            service = ApplicationPacketService(self.session)
            if name == "preview_application":
                preview = await service.preview(job.id)
                return {"status": "preview", "readiness": preview.readiness.model_dump(mode="json")}
            from backend.app.schemas.applications import CreatePacket
            existing = await self.session.scalar(select(ApplicationPacket).where(
                ApplicationPacket.job_id == job.id, ApplicationPacket.candidate_profile_id == profile.id))
            packet = await service.read(existing.id) if existing else await service.create(job.id,
                CreatePacket(idempotency_key=f"agent_{profile.id.hex}_{job.id.hex}"))
            return {"status": "prepared", "packet_id": str(packet.id),
                "job_id": str(job.id), "readiness": packet.readiness.model_dump(mode="json"),
                "requires_review": True, "submitted": False}
        if name in {"fill_application", "submit_application"}:
            # Production capability remains preview-only until independently accepted.
            return {"status": "manual_required", "reason": "browser_capability_not_accepted", "submitted": False}
        if name in {"get_campaign_status", "cancel_campaign"}:
            if arguments.campaign_id != self.campaign.id:
                raise ToolDenied("campaign_ownership_mismatch")
            if name == "cancel_campaign":
                self.campaign.state, self.campaign.fence = "cancelled", self.campaign.fence + 1
            return {"status": self.campaign.state, "campaign_id": str(self.campaign.id)}
        if name == "find_founder_profiles":
            from backend.app.models.discovery import DiscoveredPerson
            rows = (await self.session.scalars(select(DiscoveredPerson).where(
                DiscoveredPerson.company_id == arguments.company_id).limit(10))).all()
            return {"status": "cached_profiles", "people": [{"id": str(row.id),
                "profile_url": row.linkedin_url} for row in rows], "contacted": False}
        if name == "create_outreach_draft":
            from backend.app.schemas.outreach import DraftInput
            from backend.app.services.outreach_drafting import OutreachDraftingService
            return await OutreachDraftingService(self.session, self.settings).create(DraftInput(
                contact_id=arguments.contact_id, job_id=arguments.job_id, use_llm=False,
                idempotency_key=f"agent_{self.campaign.id.hex}_{arguments.contact_id.hex}"))
        raise ToolDenied("tool_not_implemented")
