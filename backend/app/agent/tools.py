"""Fixed typed tool registry. Model proposals never grant authority or execute transports."""
import hashlib
from uuid import UUID

from pydantic import Field, ValidationError
from sqlalchemy import select

from backend.app.agent.contracts import Campaign, Filters, ToolCall
from backend.app.local_agent.contracts import StrictModel, page_kind
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import evaluate, get_policy
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job


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


REGISTRY = {
    "search_jobs": SearchArgs, "filter_jobs": SearchArgs, "rank_jobs": LimitArgs,
    "get_candidate_profile": PurposeArgs, "get_approved_project_context": ProjectArgs,
    "get_canonical_resume": PurposeArgs, "get_application_history": LimitArgs,
    "prepare_application": JobArgs, "generate_grounded_answer": AnswerArgs,
    "get_campaign_status": CampaignArgs, "cancel_campaign": CampaignArgs,
    "fill_application": JobArgs, "inspect_application": JobArgs,
}
DISABLED = {"submit_application"}


def definitions():
    return [{"type": "function", "function": {"name": name,
             "description": f"Propose {name}; backend authorization is mandatory.",
             "parameters": contract.model_json_schema()}} for name, contract in REGISTRY.items()]


def owner_allowed(actor, settings):
    # The application has one owner. No client/model may choose a different tenant.
    return ((actor.channel == "owner" and actor.identity == "primary") or
            (actor.channel == "telegram" and settings.TELEGRAM_OWNER_USER_ID is not None
             and actor.identity == str(settings.TELEGRAM_OWNER_USER_ID)))


class ToolDenied(ValueError):
    pass


async def approved_projects(session):
    from backend.app.candidate_context.persistence import SQLRecordStore
    from backend.app.candidate_context.service import CandidateContextService
    service = CandidateContextService(SQLRecordStore(session))
    config = (await service.configuration()).configuration
    names = {p.id: p.name for p in config.projects}
    return service, [{"project_id": p.project_id, "name": names[p.project_id], "revision": p.revision,
                      "priority": priority, "commit_sha": p.commit_sha,
                      "fact_ids": list(p.fact_ids)} for p, priority in await service.approved_projects()]


class ToolExecutor:
    def __init__(self, session, settings, actor, campaign: Campaign, memory):
        self.session, self.settings, self.actor, self.campaign, self.memory = session, settings, actor, campaign, memory

    async def execute(self, proposal, step):
        try:
            proposal = ToolCall.model_validate(proposal)
            if not owner_allowed(self.actor, self.settings) or self.campaign.owner != "primary":
                raise ToolDenied("authenticated_owner_required")
            if self.campaign.state != "running":
                raise ToolDenied("campaign_not_running")
            if proposal.name in DISABLED or (proposal.name == "fill_application" and not self.settings.BROWSER_FILL_ENABLED):
                return {"status": "capability_not_enabled", "submitted": False}
            if proposal.name not in REGISTRY:
                raise ToolDenied("tool_not_allowed")
            arguments = REGISTRY[proposal.name].model_validate(proposal.arguments)
            if (step != self.campaign.next_step or step >= len(self.campaign.plan.actions) or
                    proposal != self.campaign.plan.actions[step]):
                raise ToolDenied("action_outside_plan")
            if step >= self.campaign.plan.max_steps or self.campaign.tool_calls >= self.campaign.plan.max_tool_calls:
                raise ToolDenied("tool_limit_exceeded")
            if self.campaign.tokens_used >= self.campaign.plan.max_tokens:
                raise ToolDenied("campaign_token_limit")
            digest = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
            key = f"agent_tool:{self.campaign.id}:{step}"
            previous = await self.session.get(AgentOperation, key)
            if previous:
                if previous.payload_hash != digest or previous.actor != self.actor_key:
                    raise ToolDenied("tool_replay_conflict")
                return previous.result
            job = None
            if isinstance(arguments, JobArgs):
                if arguments.job_id not in self.campaign.plan.selected_jobs:
                    raise ToolDenied("job_outside_owner_selection")
                job = await self.session.get(Job, arguments.job_id)
                if job is None:
                    raise ToolDenied("job_not_found")
                if proposal.name == "prepare_application":
                    await self.validate_preparation(job)
            if isinstance(arguments, CampaignArgs) and arguments.campaign_id != self.campaign.id:
                raise ToolDenied("campaign_ownership_mismatch")
            result = await self.run(proposal.name, arguments, job)
            self.campaign.tool_calls += 1
            self.session.add(AgentOperation(key=key, actor=self.actor_key,
                command="agent_tool:" + proposal.name, payload_hash=digest, result=result))
            await self.session.flush()
            return result
        except (ToolDenied, ValidationError):
            # No validation input, provider payloads, or arbitrary exception strings in output.
            return {"status": "denied", "error_code": "tool_permission_or_arguments_rejected", "submitted": False}

    @property
    def actor_key(self):
        return f"{self.actor.channel}:{self.actor.identity}"

    async def validate_preparation(self, job):
        approval = self.campaign.approval
        if (not approval or approval.scope != "prepare" or
                approval.expected_revision != self.campaign.revision or
                approval.nonce != self.campaign.approval_nonce or
                len(self.campaign.plan.selected_jobs) > approval.maximum_applications):
            raise ToolDenied("preparation_approval_required")
        platform = page_kind(job.application_url or job.job_url)
        if job.source_platform == "linkedin" or platform == "linkedin":
            raise ToolDenied("linkedin_discovery_only")
        if platform not in approval.platforms or not evaluate(await get_policy(self.session), platform, "prepare_application")["preview_allowed"]:
            raise ToolDenied("platform_disabled")
        from backend.app.dashboard.states import SUBMITTED
        submitted = await self.session.scalar(select(ApplicationPacket.id).where(
            ApplicationPacket.job_id == job.id, ApplicationPacket.lifecycle_state.in_(SUBMITTED)))
        if job.status in {"applied", "archived"} or submitted:
            raise ToolDenied("job_not_eligible")

    async def run(self, name, args, job):
        from backend.app.local_agent.knowledge import reviewed_profile
        if name in {"fill_application", "inspect_application"}:
            from backend.app.browser.queue import enqueue
            return await enqueue(self.session, self.settings, self.campaign, job, inspect_only=name == "inspect_application")
        if name in {"search_jobs", "filter_jobs"}:
            from backend.app.agent.discovery import saved_results
            return await saved_results(self.session, self.campaign, self.memory, search=name == "search_jobs")
        if name == "rank_jobs":
            from backend.app.agent.discovery import rank
            return await rank(self.session, self.campaign, args.limit)
        if name == "get_candidate_profile":
            profile = await reviewed_profile(self.session)
            return {"status": "available", "profile_id": str(profile.id), "version": profile.version,
                    "verified_skills": profile.verified_skills} if profile else {
                        "status": "needs_input", "missing_information": ["Review the current candidate profile in the dashboard."]}
        if name == "get_approved_project_context":
            _, projects = await approved_projects(self.session)
            if args.project:
                projects = [p for p in projects if args.project.casefold() in {p["name"].casefold(), p["project_id"].casefold()}]
            return {"status": "available" if projects else "needs_input", "projects": projects,
                    "missing_information": [] if projects else ["Approve the named project context in Profile first."]}
        if name == "get_canonical_resume":
            from backend.app.repositories.candidate_knowledge import (
                CandidateKnowledgeRepository,
            )
            from backend.app.services.applications.resume_selector import select_resume
            profile = await reviewed_profile(self.session)
            selection = select_resume(await CandidateKnowledgeRepository(self.session).resolution_resources(profile.id)) if profile else None
            return {"status": "available" if selection and selection.selected else "needs_input",
                    "selection": selection.model_dump(mode="json") if selection else None}
        if name == "get_application_history":
            from backend.app.models.candidate_profile import CandidateProfile
            profile = await self.session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
            rows = (await self.session.scalars(select(ApplicationPacket).where(
                ApplicationPacket.candidate_profile_id == profile.id).order_by(
                    ApplicationPacket.created_at.desc()).limit(args.limit))).all() if profile else []
            return {"status": "available", "applications": [{"job_id": str(r.job_id), "state": r.lifecycle_state,
                    "readiness": r.readiness_state, "packet_id": str(r.id)} for r in rows]}
        if name in {"prepare_application", "generate_grounded_answer"}:
            profile = await reviewed_profile(self.session)
            if not profile:
                return {"status": "needs_input", "missing_information": ["Review the current candidate profile in the dashboard."]}
            from backend.app.ai.schemas import GenerateRequest
            from backend.app.services.application_answer_service import (
                ApplicationAnswerService,
            )
            answers = ApplicationAnswerService(self.session, self.settings)
            if name == "generate_grounded_answer":
                if self.campaign.selected_project:
                    service, projects = await approved_projects(self.session)
                    projects.sort(key=lambda p: p["priority"])
                    selected = next((i + 1 for i, p in enumerate(projects) if p["project_id"] == self.campaign.selected_project), None)
                    if not selected:
                        return {"status": "needs_input", "missing_information": ["Reapprove the selected project."]}
                    answer = await service.answer(args.question, project_rank=selected)
                    return {"status": "draft_ready" if answer.sources else "needs_input", "answer": answer.text,
                            "sources": list(answer.sources), "requires_review": True, "used_llm": False}
                return (await answers.generate(GenerateRequest(question=args.question, job_id=job.id,
                                                               save_draft=True, rewrite=False))).model_dump(mode="json")
            from backend.app.schemas.applications import CreatePacket
            from backend.app.services.applications.service import (
                ApplicationPacketService,
            )
            service = ApplicationPacketService(self.session, answers)
            existing = await self.session.scalar(select(ApplicationPacket).where(
                ApplicationPacket.job_id == job.id, ApplicationPacket.candidate_profile_id == profile.id))
            packet = await service.read(existing.id) if existing else await service.create(job.id, CreatePacket(
                idempotency_key=f"agent_{profile.id.hex}_{job.id.hex}"))
            missing = list(dict.fromkeys([
                *(packet.readiness.blockers if packet.readiness.stale or packet.readiness.state in {"needs_input", "needs_resume", "needs_profile", "unsupported"} else []),
                *[m for f in packet.fields if f.required and f.validation_status != "file_upload_required" for m in f.missing_information]]))
            project_context = None
            if self.campaign.selected_project:
                contexts, projects = await approved_projects(self.session)
                projects.sort(key=lambda p: p["priority"])
                selected = next((i + 1 for i, p in enumerate(projects) if p["project_id"] == self.campaign.selected_project), None)
                if selected:
                    project_context = (await contexts.answer("Describe my main project and my contribution", project_rank=selected)).model_dump(mode="json")
                else:
                    missing.append("Reapprove the selected project context.")
            return {"status": "needs_input" if missing else "prepared", "packet_id": str(packet.id),
                    "job_id": str(job.id), "readiness": packet.readiness.model_dump(mode="json"),
                    "missing_information": missing, "selected_project": self.campaign.selected_project,
                    "requires_review": True, "submitted": False, "project_context": project_context,
                    "provenance": {"profile_id": str(profile.id), "profile_version": profile.version,
                                   "resume_resource_id": str(packet.snapshot.resume.selected.resource_id) if packet.snapshot.resume.selected else None}}
        if name in {"get_campaign_status", "cancel_campaign"}:
            if name == "cancel_campaign":
                from backend.app.agent.store import transition
                from backend.app.automation.store import instant
                transition(self.campaign, "cancelled", await instant(self.session), "validated_owner_control")
                self.campaign.fence += 1
                self.campaign.lease_until = None
                self.campaign.reply = "Campaign cancelled. Zero submissions were made."
            return {"status": self.campaign.state, "campaign_id": str(self.campaign.id),
                    "next_step": self.campaign.next_step, "tool_calls": self.campaign.tool_calls}
        raise ToolDenied("tool_not_implemented")
