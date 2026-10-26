"""One grounding, freshness, review and audit boundary for both browser modes."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from backend.app.agent.tools import ToolDenied, approved_projects
from backend.app.browser.contracts import FillAction, FillPlan, Inspection
from backend.app.dashboard.models import OwnerPreference, PrivateResume
from backend.app.local_agent.contracts import page_kind
from backend.app.local_agent.knowledge import reviewed_profile
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import evaluate, get_policy
from backend.app.models.application_packet import ApplicationPacket
from backend.app.schemas.applications import QuestionInput
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.applications.answer_builder import AnswerBuilder
from backend.app.services.applications.platforms.base import safe_url
from backend.app.services.applications.platforms.owner_page import manual_page_url
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService


def target(url, settings):
    parsed = urlsplit(url)
    if (
        settings.ENVIRONMENT == "testing"
        and settings.BROWSER_FIXTURE_ORIGIN
        and parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and f"{parsed.scheme}://{parsed.netloc}" == settings.BROWSER_FIXTURE_ORIGIN
        and not parsed.username
        and not parsed.password
    ):
        return url
    if not safe_url(url) or parsed.query or parsed.fragment:
        raise ToolDenied("verified_public_application_url_required")
    if not (
        (
            parsed.hostname
            in {"boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co"}
        )
        or (parsed.hostname == "docs.google.com" and parsed.path.startswith("/forms/"))
    ):
        raise ToolDenied("unsupported_form_adapter")
    return url


async def project_stamp(session):
    _, projects = await approved_projects(session)
    return digest(projects)


async def pdf_bytes(session, packet, settings):
    """Only the confirmed canonical private PDF, never arbitrary URLs or file paths."""
    from cryptography.fernet import Fernet, InvalidToken

    from backend.app.models.application_answer import CandidateResource

    selected = packet.snapshot.resume.selected
    if not selected or not selected.confirmed:
        return None
    resource = await session.get(
        CandidateResource, selected.resource_id, populate_existing=True
    )
    if (
        not resource
        or not resource.user_confirmed
        or resource.source_type != "private_upload"
        or not resource.url.startswith("private-resume:")
    ):
        return None
    try:
        private = await session.get(
            PrivateResume,
            UUID(resource.url.removeprefix("private-resume:")),
            populate_existing=True,
        )
        if (
            not private
            or not private.confirmed
            or private.resource_id != resource.id
            or not settings.RESUME_ENCRYPTION_KEY
        ):
            return None
        raw = Fernet(
            settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode()
        ).decrypt(private.ciphertext)
        if (
            not raw.startswith(b"%PDF-")
            or len(raw) > 5 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != private.sha256
        ):
            return None
        return raw
    except (ValueError, InvalidToken):
        return None


class FormService:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings
        # Inspection never grants provider transmission consent, even if other AI is configured.
        local = settings.model_copy(
            update={
                "LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": None,
                "COHERE_ENABLED": False,
            }
        )
        self.answers = ApplicationAnswerService(session, local)
        self.packets = ApplicationPacketService(session, self.answers)

    async def context(self, application_id, mode="local_automation"):
        packet = await self.packets.read(application_id, lock_context=True)
        profile = await reviewed_profile(self.session)
        stored = await self.session.get(
            ApplicationPacket, application_id, populate_existing=True
        )
        if (
            not profile
            or profile.id != packet.candidate_profile_id
            or packet.readiness.stale
            or stored.lifecycle_state
            in {
                "abandoned",
                "withdrawn",
                "user_reported_submitted",
                "provider_confirmed_submitted",
            }
        ):
            raise ToolDenied("stale_or_unreviewed_candidate_context")
        from backend.app.models.job import Job

        saved_job = await self.session.get(Job, packet.job_id)
        if saved_job.status in {"applied", "archived"}:
            raise ToolDenied("application_not_eligible")
        fixture = (
            self.settings.ENVIRONMENT == "testing"
            and self.settings.BROWSER_FIXTURE_ORIGIN
        )
        if not fixture and not packet.snapshot.destination.valid:
            raise ToolDenied("unverified_application_destination")
        destination = packet.snapshot.destination.application_url or ""
        if (
            self.settings.ENVIRONMENT == "testing"
            and self.settings.BROWSER_FIXTURE_ORIGIN
        ):
            from backend.app.models.job import Job

            job = await self.session.get(Job, packet.job_id)
            destination = job.application_url
        url = (
            manual_page_url(destination)
            if mode == "manual_extension" and not fixture
            else target(destination, self.settings)
        )
        if not url:
            raise ToolDenied("unsupported_form_adapter")
        platform = page_kind(url)
        policy = await get_policy(self.session)
        if not evaluate(policy, platform, "fill_application")[
            "preview_allowed"
        ] or policy["platforms"].get(platform) in {
            "manual_only",
            "draft_only",
            "disabled",
        }:
            raise ToolDenied("platform_fill_policy_denied")
        return packet, profile, url

    async def prepare_current_form(self, inspection, title):
        """Reuse saved jobs, packets and the shared answer/freshness boundary."""
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        from backend.app.models.job import Job
        from backend.app.schemas.applications import CreatePacket

        profile = await reviewed_profile(self.session)
        if not profile:
            raise ToolDenied("profile_review_required")
        url = manual_page_url(inspection.url)
        if not url or inspection.state not in {"ready", "validation_errors"}:
            raise ToolDenied("unsupported_application_form")
        policy = await get_policy(self.session)
        if policy["platforms"].get(page_kind(url)) in {"manual_only", "draft_only", "disabled"}:
            raise ToolDenied("platform_fill_policy_denied")
        query = select(Job).where(Job.job_url == url).with_for_update()
        job = await self.session.scalar(query)
        if job is None:
            try:
                async with self.session.begin_nested():
                    job = Job(
                        title=title or urlsplit(url).path.rsplit("/", 1)[-1],
                        job_url=url, application_url=url, source_platform="owner_extension",
                        source_verification_status="owner_selected",
                        discovery_metadata={"capture": "explicit_extension_gesture", "employer_identity_verified": False},
                    )
                    self.session.add(job)
                    await self.session.flush()
            except IntegrityError:
                job = await self.session.scalar(query)
                if job is None:
                    raise ToolDenied("application_page_conflict") from None
        if job.status in {"applied", "archived"} or job.application_url != url:
            raise ToolDenied("application_not_eligible")
        packet_id = await self.session.scalar(select(ApplicationPacket.id).where(
            ApplicationPacket.job_id == job.id,
            ApplicationPacket.candidate_profile_id == profile.id,
        ))
        if packet_id is None:
            packet = await self.packets.create(job.id, CreatePacket(
                idempotency_key=f"extension_{profile.id.hex}_{job.id.hex}",
            ))
            packet_id = packet.id
        return await self.inspect(packet_id, inspection, "manual_extension")

    async def inspect(
        self, application_id, inspection: Inspection, mode, selected_project=None
    ):
        packet, profile, url = await self.context(application_id, mode)
        if inspection.url != url or inspection.state not in {
            "ready",
            "validation_errors",
        }:
            raise ToolDenied("manual_intervention_or_redirect")
        plan = FillPlan(
            application_id=application_id,
            job_id=packet.job_id,
            mode=mode,
            target_url=url,
            inspection=inspection,
            context_digest=packet.snapshot.context_digest,
            packet_revision=packet.revision,
            project_digest=await project_stamp(self.session),
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        )
        for field in inspection.fields:
            action = FillAction(
                job_id=packet.job_id,
                application_id=application_id,
                target_url=url,
                field_id=field.field_id,
                kind=field.kind,
                candidate_version=profile.version,
            )
            if field.kind == "file":
                raw = await pdf_bytes(self.session, packet, self.settings)
                if raw and "resume" in field.label.casefold():
                    action.safe_reference = (
                        "canonical_pdf:" + hashlib.sha256(raw).hexdigest()
                    )
                    action.evidence = [
                        "candidate_resource:"
                        + str(packet.snapshot.resume.selected.resource_id)
                    ]
                    action.needs_input = False
            elif field.label and not re.search(
                r"ignore.{0,40}instructions|system prompt|developer message|javascript:|execute.{0,20}command|send.{0,30}(?:email|resume)|click.{0,20}(?:submit|apply)",
                field.label,
                re.I,
            ):
                # Labels are untrusted; classifier/grounding services can abstain, never execute them.
                question_text = field.group_label or field.label
                if re.fullmatch(r"name[\s:*]*", question_text, re.I):
                    question_text = "Full name"
                question = QuestionInput(
                    question=question_text,
                    field_type="multiple_choice"
                    if field.kind == "select"
                    else "textarea"
                    if field.kind == "textarea"
                    else "text",
                    required=field.required,
                    max_characters=field.max_length,
                    options=field.options if field.kind == "select" else [],
                )
                built = await AnswerBuilder(self.answers).build(
                    question,
                    packet.job_id,
                    profile,
                    generate=True,
                    rewrite=False,
                    resume=packet.snapshot.resume,
                )
                if selected_project and built.category == "project_explanation":
                    contexts, projects = await approved_projects(self.session)
                    projects.sort(key=lambda p: p["priority"])
                    rank = next(
                        (
                            i + 1
                            for i, p in enumerate(projects)
                            if p["project_id"] == selected_project
                        ),
                        None,
                    )
                    if rank:
                        answer = await contexts.answer(field.label, project_rank=rank)
                        if answer.sources and len(answer.text) <= field.max_length:
                            action.value, action.evidence = (
                                answer.text,
                                [
                                    "approved_project:"
                                    + selected_project
                                    + ":"
                                    + digest(source)
                                    for source in answer.sources
                                ][:12],
                            )
                            action.project_version = next(
                                p["revision"]
                                for p in projects
                                if p["project_id"] == selected_project
                            )
                            action.requires_review = True
                elif (
                    built.effective_answer and built.validation_status == "draft_ready"
                ):
                    action.value = built.effective_answer
                    action.evidence = [
                        f"{e.source_type}:{e.source_id}"
                        for e in built.provenance.evidence_references
                    ]
                    if not action.evidence and built.provenance.source != "missing":
                        action.evidence = [
                            built.provenance.source + ":" + str(profile.id)
                        ]
                    action.requires_review = built.requires_review
                if field.kind in {"checkbox", "radio"}:
                    # Only a grounded exact choice, with a separate group question, is executable.
                    if (
                        field.group_label
                        and action.value
                        and action.evidence
                        and field.options
                    ):
                        action.value = (
                            "true"
                            if action.value.casefold() == field.options[0].casefold()
                            else "false"
                        )
                    else:
                        action.value, action.evidence = None, []
                if action.value and field.kind == "number":
                    numeric = re.fullmatch(
                        r"([0-9]+(?:\.[0-9]+)?)(?: years)?", action.value
                    )
                    action.value = numeric[1] if numeric else None
                if (
                    action.value
                    and field.kind == "email"
                    and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", action.value)
                ):
                    action.value = None
                if action.value and field.kind == "url" and not safe_url(action.value):
                    action.value = None
                if action.value and action.evidence:
                    action.needs_input = False
            plan.actions.append(action)
        self.session.add(
            OwnerPreference(
                key=f"fill_plan:{plan.id}", value=plan.model_dump(mode="json")
            )
        )
        self.audit(plan, "form_inspected", [])
        await self.session.flush()
        return plan

    async def load(self, plan_id, lock=True):
        await self.session.flush()
        row = await self.session.get(
            OwnerPreference,
            f"fill_plan:{plan_id}",
            with_for_update=lock,
            populate_existing=True,
        )
        if not row:
            raise ToolDenied("fill_plan_not_found")
        # JSON persisted UUIDs are intentionally decoded through JSON validation.
        import json

        return row, FillPlan.model_validate_json(json.dumps(row.value))

    async def fresh(self, plan):
        packet, _, url = await self.context(plan.application_id, plan.mode)
        if (
            datetime.now(timezone.utc) >= datetime.fromisoformat(plan.expires_at)
            or packet.snapshot.context_digest != plan.context_digest
            or packet.revision != plan.packet_revision
            or url != plan.target_url
            or await project_stamp(self.session) != plan.project_digest
        ):
            raise ToolDenied("fill_plan_stale")
        references = [a.safe_reference for a in plan.actions if a.safe_reference]
        if references:
            raw = await pdf_bytes(self.session, packet, self.settings)
            if not raw or any(
                ref != "canonical_pdf:" + hashlib.sha256(raw).hexdigest()
                for ref in references
            ):
                raise ToolDenied("canonical_pdf_changed")
        return packet

    async def review(self, plan_id, field_ids):
        row, plan = await self.load(plan_id)
        await self.fresh(plan)
        allowed = {a.field_id for a in plan.actions if not a.needs_input and a.evidence}
        if (
            plan.state != "preview"
            or len(set(field_ids)) != len(field_ids)
            or not set(field_ids) <= allowed
        ):
            raise ToolDenied("invalid_field_approval")
        plan.approved_fields = field_ids
        plan.state = "authorized"
        row.value = plan.model_dump(mode="json")
        return plan

    async def consume(self, plan_id, mode):
        if not self.settings.BROWSER_FILL_ENABLED:
            raise ToolDenied("browser_fill_disabled")
        row, plan = await self.load(plan_id)
        packet = await self.fresh(plan)
        if plan.mode != mode or plan.state != "authorized":
            raise ToolDenied("single_use_fill_authorization_required")
        plan.state = "consumed"
        row.value = plan.model_dump(mode="json")
        self.audit(plan, "fill_authorized", [])
        return plan, packet

    def audit(self, plan, event, results):
        self.session.add(
            AgentOperation(
                key=f"browser:{plan.id}:{event}",
                actor="owner:primary",
                command="browser:" + event,
                payload_hash=digest([str(plan.id), event]),
                result={
                    "plan_id": str(plan.id),
                    "application_id": str(plan.application_id),
                    "status": event,
                    "fields": results,
                    "submitted": False,
                },
            )
        )

    async def receipt(self, receipt):
        row, plan = await self.load(receipt.plan_id)
        if plan.state == "finished":
            return {"status": "already_recorded", "submitted": False}
        if plan.state != "consumed" or any(
            r.field_id not in plan.approved_fields for r in receipt.results
        ):
            raise ToolDenied("invalid_fill_receipt")
        plan.state = "finished"
        row.value = plan.model_dump(mode="json")
        self.audit(plan, receipt.state, [r.model_dump() for r in receipt.results])
        return {"status": receipt.state, "submitted": False}
