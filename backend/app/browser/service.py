"""Integrated owner-reviewed browser workflows with separate route and approval boundaries."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from backend.app.agent.tools import ToolDenied, approved_projects
from backend.app.browser.contracts import (
    FillAction,
    FillPlan,
    Inspection,
    PrepareBrowser,
)
from backend.app.browser.field_policy import manual_only
from backend.app.browser.runner import browser, validate_destination
from backend.app.core.config import get_settings
from backend.app.core.timing import timed
from backend.app.dashboard.models import OwnerPreference, PrivateResume
from backend.app.dashboard.resumes import MAX_PDF, cipher
from backend.app.local_agent.contracts import page_kind
from backend.app.local_agent.knowledge import reviewed_profile
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import evaluate, get_policy
from backend.app.models.application_answer import CandidateResource
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket, QuestionInput
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.applications.answer_builder import AnswerBuilder, value_error
from backend.app.services.applications.platforms.base import safe_url
from backend.app.services.applications.platforms.owner_page import manual_page_url
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import TERMINAL, ApplicationPacketService


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
    if not safe_url(url) or parsed.fragment:
        raise ToolDenied("verified_public_application_url_required")
    from backend.app.browser.site_policy import application_page_url

    if not application_page_url(url, settings.BROWSER_ALLOWED_ORIGINS):
        raise ToolDenied("unsupported_form_adapter")
    return url


async def project_stamp(session):
    _, projects = await approved_projects(session)
    return digest(projects)


@timed("resume_read")
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

    @timed("packet_context_resume")
    async def context(self, application_id, mode="local_automation", *, lock_context=True):
        packet = await self.packets.read(application_id, lock_context=lock_context)
        from backend.app.local_agent.profile_confirmation import confirmation_matches
        from backend.app.models.candidate_profile import CandidateProfile

        row = (await self.session.execute(
            select(ApplicationPacket, CandidateProfile, Job, OwnerPreference)
            .join(Job, Job.id == ApplicationPacket.job_id)
            .outerjoin(CandidateProfile, CandidateProfile.singleton_key == "primary")
            .outerjoin(OwnerPreference, OwnerPreference.key == "phase1_profile_confirmation")
            .where(ApplicationPacket.id == application_id)
            .execution_options(populate_existing=True)
        )).one()
        stored, profile, saved_job, confirmation = row
        if not confirmation_matches(profile, confirmation.value if confirmation else {}):
            profile = None
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
        if saved_job.status in {"applied", "archived"}:
            raise ToolDenied("application_not_eligible")
        if saved_job.source_platform == "naukri":
            from backend.app.execution.recurring import require_enabled
            await require_enabled(self.session)
            from backend.app.execution.store import previously_applied
            from backend.app.services.applications.platforms.naukri import (
                posting_unavailable,
            )

            if posting_unavailable(saved_job) or await previously_applied(self.session, saved_job):
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
            job = await self.session.get(Job, packet.job_id)
            destination = job.application_url
        url = (
            manual_page_url(destination, self.settings)
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
        url = manual_page_url(inspection.url, self.settings)
        if not url or inspection.state not in {"ready", "validation_errors", "manual_required"}:
            raise ToolDenied("unsupported_application_form")
        policy = await get_policy(self.session)
        if policy["platforms"].get(page_kind(url)) in {
            "manual_only",
            "draft_only",
            "disabled",
        }:
            raise ToolDenied("platform_fill_policy_denied")
        query = select(Job).where(Job.job_url == url).with_for_update()
        job = await self.session.scalar(query)
        if job is None:
            try:
                async with self.session.begin_nested():
                    job = Job(
                        title=title or urlsplit(url).path.rsplit("/", 1)[-1],
                        job_url=url,
                        application_url=url,
                        source_platform="owner_extension",
                        source_verification_status="owner_selected",
                        discovery_metadata={
                            "capture": "explicit_extension_gesture",
                            "employer_identity_verified": False,
                        },
                    )
                    self.session.add(job)
                    await self.session.flush()
            except IntegrityError:
                job = await self.session.scalar(query)
                if job is None:
                    raise ToolDenied("application_page_conflict") from None
        if job.status in {"applied", "archived"} or job.application_url != url:
            raise ToolDenied("application_not_eligible")
        packet_id = await self.session.scalar(
            select(ApplicationPacket.id).where(
                ApplicationPacket.job_id == job.id,
                ApplicationPacket.candidate_profile_id == profile.id,
            )
        )
        if packet_id is None:
            packet = await self.packets.create(
                job.id,
                CreatePacket(
                    idempotency_key=f"extension_{profile.id.hex}_{job.id.hex}",
                ),
            )
            packet_id = packet.id
        return await self.inspect(packet_id, inspection, "manual_extension")

    @timed("form_inspection_answers")
    async def inspect(
        self, application_id, inspection: Inspection, mode, selected_project=None
    ):
        if urlsplit(inspection.url).hostname in {"naukri.com", "www.naukri.com"}:
            from backend.app.execution.store import memory_row
            await memory_row(self.session, lock=True)
        packet, profile, url = await self.context(application_id, mode)
        preview_only = mode == "manual_extension" and (
            inspection.state == "manual_required"
            or inspection.challenge_state not in {"NONE", "MANUALLY_RESOLVED_AND_SITE_VERIFIED"}
        )
        if inspection.url != url or (inspection.state not in {
            "ready", "validation_errors",
        } and not preview_only):
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
            state="read_only" if preview_only else "preview",
        )
        for field in inspection.fields:
            action = FillAction(
                job_id=packet.job_id,
                application_id=application_id,
                target_url=url,
                field_id=field.field_id,
                kind=field.kind,
                candidate_version=profile.version,
                preview_only=field.preview_only,
            )
            repeated = sum(
                (other.section, other.group_label, other.label) == (field.section, field.group_label, field.label)
                for other in inspection.fields
            ) > 1
            if repeated or len(field.label) >= 160 or len(field.group_label or "") >= 160 or manual_only(field.label, field.group_label or "", field.section or "", *field.options):
                plan.actions.append(action)
                continue
            if field.kind == "file":
                raw = await pdf_bytes(self.session, packet, self.settings)
                if raw and re.search(r"\b(?:resume|cv)\b", f"{field.section or ''} {field.label}", re.I) and not re.search(r"cover letter", field.label, re.I):
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
                from backend.app.browser.extension_tasks import field_question
                question_text = field_question(field)
                if re.fullmatch(r"name[\s:*]*", question_text, re.I):
                    question_text = "Full name"
                question = QuestionInput(
                    question=question_text,
                    field_type="multiple_choice"
                    if field.kind == "select" and len(field.options) <= 50
                    else "textarea"
                    if field.kind == "textarea"
                    else "text",
                    required=field.required,
                    max_characters=field.max_length,
                    options=field.options if field.kind == "select" and len(field.options) <= 50 else [],
                )
                saved_answers = [
                    f for f in packet.fields
                    if f.question.strip().casefold() == question_text.strip().casefold()
                    and (not field.semantic_key or f.provenance.form_semantic_key in {None, field.semantic_key})
                    and (not f.provenance.form_semantic_key or f.provenance.form_semantic_key == field.semantic_key)
                    and f.human_answer and f.validation_status == "draft_ready"
                    and (not f.provenance.answer_expires_at or f.provenance.answer_expires_at > datetime.now(timezone.utc))
                    and not value_error(question, f.human_answer)
                ]
                # Show an existing owner answer without creating another missing-input
                # request. Pending answers remain visible but cannot be authorized.
                if len(saved_answers) > 1:
                    plan.actions.append(action)
                    continue
                saved = saved_answers[0] if saved_answers else None
                if saved and saved.review_status != "reviewed":
                    action.value = saved.human_answer
                    action.evidence = [f"reviewed_packet_answer:{saved.id}:{saved.answer_revision}"]
                    action.preview_only = True
                    action.requires_review = True
                    action.needs_input = False
                    plan.actions.append(action)
                    continue
                # A history section is not evidence that an aggregate profile fact
                # answers an individual employer/institution/date control.
                contextual_history = bool(re.search(
                    r"employment|work experience|education|previous employer|experience [0-9]",
                    field.section or "", re.I,
                ))
                if contextual_history and not saved:
                    plan.actions.append(action)
                    continue
                built = None if saved else await AnswerBuilder(self.answers).build(
                    question,
                    packet.job_id,
                    profile,
                    generate=True,
                    rewrite=False,
                    resume=packet.snapshot.resume,
                )
                action.missing_input_id = built.provenance.missing_input_id if built else None
                if action.missing_input_id:
                    from backend.app.knowledge.missing_input import PREFIX
                    saved_question = await self.session.get(OwnerPreference, PREFIX + action.missing_input_id, with_for_update=True)
                    if saved_question:
                        action.missing_input_version = saved_question.value["version"]
                    if saved_question and not saved_question.value.get("packet_id"):
                        saved_question.value = {**saved_question.value, "packet_id": str(application_id)}
                reviewed_answer = saved
                if reviewed_answer:
                    action.value = reviewed_answer.human_answer
                    action.evidence = ["reviewed_packet_answer:" + str(reviewed_answer.id) + ":" + str(reviewed_answer.answer_revision)]
                    action.requires_review = True
                    action.missing_input_id = None
                    action.missing_input_version = None
                elif selected_project and built.category == "project_explanation":
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
                        action.value = "true" if action.value.casefold() == field.options[0].casefold() else None
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
                if action.value and field.kind in {"date", "month"}:
                    pattern = r"\d{4}-\d{2}-\d{2}" if field.kind == "date" else r"\d{4}-\d{2}"
                    try:
                        if not re.fullmatch(pattern, action.value):
                            raise ValueError
                        datetime.strptime(action.value, "%Y-%m-%d" if field.kind == "date" else "%Y-%m")
                    except ValueError:
                        action.value = None
                if action.value and field.kind == "select" and action.value not in field.options:
                    action.value = None
                if action.value and action.evidence:
                    action.needs_input = False
                    if not any(source.startswith("owner_answer:") for source in action.evidence):
                        # An approved project/profile fallback can resolve a question
                        # independently of the unanswered request created earlier.
                        action.missing_input_id = None
                        action.missing_input_version = None
            plan.actions.append(action)
        if urlsplit(inspection.url).hostname in {"naukri.com", "www.naukri.com"}:
            from backend.app.execution.questions import bridge_form
            packet = await bridge_form(self.session, packet, plan)
        self.session.add(
            OwnerPreference(
                key=f"fill_plan:{plan.id}", value=plan.model_dump(mode="json")
            )
        )
        self.audit(plan, "form_inspected", [])
        await self.session.flush()
        return plan

    @timed("plan_load")
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

    @timed("plan_revalidation")
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
        from backend.app.knowledge.missing_input import MissingInputService
        for action in plan.actions:
            if action.missing_input_id and not action.needs_input:
                saved = await MissingInputService(self.session).read(action.missing_input_id)
                if saved["version"] != action.missing_input_version or saved["stale"] or saved["status"] != "approved":
                    raise ToolDenied("fill_plan_stale")
        for action in plan.actions:
            for reference in action.evidence:
                if reference.startswith("reviewed_packet_answer:"):
                    _, field_id, revision = reference.split(":")
                    field = next((f for f in packet.fields if str(f.id) == field_id), None)
                    if (not field or field.answer_revision != int(revision)
                        or (not action.preview_only and field.review_status != "reviewed")
                        or (field.provenance.answer_expires_at and field.provenance.answer_expires_at <= datetime.now(timezone.utc))):
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
        allowed = {a.field_id for a in plan.actions if not a.needs_input and a.evidence and not a.preview_only}
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
        from backend.app.execution.store import fill_event, lock_plan_execution
        execution = await lock_plan_execution(self.session, plan_id)
        if not self.settings.BROWSER_FILL_ENABLED:
            raise ToolDenied("browser_fill_disabled")
        row, plan = await self.load(plan_id)
        packet = await self.fresh(plan)
        if plan.mode != mode or plan.state != "authorized":
            raise ToolDenied("single_use_fill_authorization_required")
        plan.state = "consumed"
        row.value = plan.model_dump(mode="json")
        await fill_event(self.session, execution, plan, "fill_authorized")
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
        from backend.app.execution.store import fill_event, lock_plan_execution
        execution = await lock_plan_execution(self.session, receipt.plan_id)
        row, plan = await self.load(receipt.plan_id)
        if plan.state == "finished":
            return {"status": "already_recorded", "submitted": False}
        if plan.state != "consumed" or len({r.field_id for r in receipt.results}) != len(receipt.results) or any(
            r.field_id not in plan.approved_fields for r in receipt.results
        ):
            raise ToolDenied("invalid_fill_receipt")
        plan.state = "finished"
        row.value = plan.model_dump(mode="json")
        state = receipt.state
        completed = {r.field_id for r in receipt.results if r.status == "filled"}
        if state == "form_filled" and (
            set(plan.approved_fields) - completed
            or any(f.required and f.field_id not in completed for f in plan.inspection.fields)
            or any(r.status != "filled" for r in receipt.results)
        ):
            state = "needs_input"
        await fill_event(self.session, execution, plan, state)
        self.audit(plan, state, [r.model_dump() for r in receipt.results])
        return {"status": state, "submitted": False}


def metadata_key(packet_id):
    return "browser:" + str(packet_id)


async def metadata(session, packet_id):
    return await session.get(OwnerPreference, metadata_key(packet_id))


async def prepare(session, data: PrepareBrowser):
    await validate_destination(data.application_url, get_settings())
    return await prepare_packet(session, data)


async def prepare_packet(session, data: PrepareBrowser):
    # Draft intake performs no navigation; browser grants are checked on open/fill.
    # URL and company/title uniqueness are enforced by the existing jobs table.
    canonical = digest(
        {"company": data.company_name.casefold(), "title": data.job_title.casefold()}
    )
    job = await session.scalar(select(Job).where(Job.job_url == data.application_url))
    if not job:
        other = await session.scalar(
            select(Job).where(Job.content_identity == canonical)
        )
        if other:
            raise HTTPException(
                409,
                "A job with this company and title already exists; use its saved packet",
            )
        company = await session.scalar(
            select(Company).where(Company.name == data.company_name)
        )
        if not company:
            company = Company(name=data.company_name)
            session.add(company)
            await session.flush()
        job = Job(
            title=data.job_title,
            company_id=company.id,
            job_url=data.application_url,
            application_url=data.application_url,
            source_platform="manual_browser",
            content_identity=canonical,
            source_verification_status="owner_provided",
        )
        session.add(job)
        await session.flush()
    elif job.company_id:
        company = await session.get(Company, job.company_id)
        if job.title != data.job_title or company.name != data.company_name:
            raise HTTPException(
                409, "Saved job context differs; review its company and title"
            )
    return await ApplicationPacketService(session).create(
        job.id,
        CreatePacket(
            idempotency_key=data.idempotency_key,
            resume_resource_id=data.resume_resource_id,
        ),
    )


async def status(session, packet_id):
    packet = await ApplicationPacketService(session).read(packet_id)
    saved = await metadata(session, packet_id)
    current = browser.sessions.get(str(packet_id))
    from backend.app.browser.adapters import execution_adapter

    adapter = execution_adapter(
        packet.snapshot.destination.application_url, get_settings()
    )
    execution = None
    if adapter.submission_enabled:
        from backend.app.browser.submissions import attempt_for, attempt_output

        attempt = await attempt_for(session, packet_id)
        execution = attempt_output(attempt) if attempt else None
    recovery = None
    if packet.lifecycle_state in {"submitting", "submission_unknown"}:
        recovery = "Check the saved submission receipt; do not resubmit or reopen this application."
    elif (current and current.blocked_step_requests and not current.manual) or (
        saved and saved.value.get("diagnostic") == "network_activity_requires_takeover"
    ):
        recovery = "This form tried to send data during assistance. Requests were blocked; never replay interrupted actions. Take Over to continue manually, then analyze again."
    elif saved and saved.value.get("diagnostic") in {
        "step_started",
        "step_handoff_required",
    }:
        recovery = "A step was interrupted or needs manual work. Inspect the website with Take Over and analyze again; never replay the previous step action."
    elif (
        packet.lifecycle_state
        not in {"provider_confirmed_submitted", "user_reported_submitted"}
        and not current
    ):
        recovery = "Open a dedicated session and reanalyze; no action is replayed"
    return {
        "packet": packet.model_dump(mode="json"),
        "connected": bool(current and not current.page.is_closed()),
        "manual": bool(current and current.manual),
        "active_operation": browser.operations.public(packet_id),
        "cancellation_pending": str(packet_id) in browser.operations.stopping,
        "in_page_network_isolation": bool(
            current and current.in_page_mode and not current.manual
        ),
        "page_review_required": bool(
            current
            and packet.lifecycle_state not in TERMINAL
            and (
                current.paused_for_resume
                or current.page.url != current.url
                or current.document_epoch != current.assisted_document_epoch
            )
        ),
        "assets": current.assets.state() if current else None,
        "analysis": saved.value if saved else None,
        "submission_mode": "mock_only"
        if adapter.submission_enabled
        else "manual_handoff",
        "automated_submission_enabled": adapter.submission_enabled,
        "real_employer_submission_enabled": False,
        "owner_consent_available": bool(get_settings().BROWSER_OWNER_APPROVAL_KEY),
        "opportunity_context_available": get_settings().OPPORTUNITY_CONTEXT_ENABLED,
        "company_source_urls": get_settings().COMPANY_SOURCE_URLS
        if get_settings().COMPANY_SOURCE_FETCH_ENABLED
        and get_settings().OPPORTUNITY_CONTEXT_ENABLED
        else [],
        "execution": execution,
        "recovery": recovery,
    }


async def analyze(session, packet, service, runtime):
    from backend.app.services.applications.multi_select import available

    runtime.multi_enabled = multi_enabled = await available(session)
    fields, warnings = await runtime.scan()
    if not fields:
        raise HTTPException(
            409, "No supported application form detected; use manual handoff"
        )
    old = await metadata(session, packet.id)
    previous_map = {
        f["identity"]: f["field_id"] for f in (old.value["fields"] if old else [])
    }
    existing = {str(f.id): f for f in await service.repo.fields(packet.id)}
    previous = packet.lifecycle_state
    await service.repo.advance(packet, packet.revision)
    _, profile, snapshot = await service.builder.context(
        packet.job_id, packet.resume_resource_id
    )
    mapped = []
    for field in fields:
        identity = digest(
            {k: v for k, v in field.items() if k not in {"key", "field_id"}}
        )
        field_id = previous_map.get(identity)
        if field_id is None and not field.get("choices_on_open"):
            # Older saved analyses predate this capability flag. Preserve exact
            # unchanged fields and their human answers/reviews across upgrades.
            legacy = digest(
                {
                    k: v
                    for k, v in field.items()
                    if k not in {"key", "field_id", "choices_on_open"}
                }
            )
            field_id = previous_map.get(legacy)
        if field_id not in existing:
            if len(existing) >= 100:
                raise HTTPException(
                    409, "Too many changing questions; complete manually"
                )
            kind = field["kind"]
            question = QuestionInput(
                question=field["question"],
                required=field["required"],
                field_type="yes_no"
                if kind == "checkbox"
                else "multi_select"
                if kind in {"multi_select", "checkbox_group"}
                and multi_enabled
                and field["options"]
                else "multiple_choice"
                if kind in {"select", "radio_group", "combobox"} and field["options"]
                else "file"
                if kind == "file"
                else "textarea"
                if kind == "textarea"
                else "text",
                options=["Yes", "No"]
                if kind == "checkbox"
                else field["options"]
                if kind in {"select", "radio_group", "combobox"}
                or (
                    kind in {"multi_select", "checkbox_group"}
                    and multi_enabled
                    and field["options"]
                )
                else [],
                max_characters=field["max_characters"],
            )
            answer = await service.builder.answers.build(
                question, packet.job_id, profile, resume=snapshot.resume
            )
            item = service.repo.add_field(packet.id, answer, len(existing))
            field_id = str(item.id)
            existing[field_id] = item
        # Opaque browser handles live in memory only; persist sanitized structure and field links.
        mapped.append(
            {
                **{k: v for k, v in field.items() if k != "key"},
                "identity": identity,
                "field_id": field_id,
            }
        )
    if not old:
        old = OwnerPreference(key=metadata_key(packet.id), value={})
        session.add(old)
    old.value = {
        "signature": runtime.signature,
        "page_context": runtime.context_evidence,
        "fields": mapped,
        "warnings": warnings,
        "diagnostic": "analyzed",
        "filled_field_ids": [],
        "validation": [],
        "steps": [
            {k: v for k, v in step.items() if k != "key"} for step in runtime.steps
        ],
        "step_history": old.value.get("step_history", []),
        "navigation_history": old.value.get("navigation_history", []),
    }
    # finish() runs the existing readiness evaluator and emits an existing audited event type.
    await service.finish(
        packet,
        previous,
        "questions_added",
        note="Dedicated browser form analyzed without submission",
    )
    runtime.assisted_document_epoch = runtime.document_epoch
    return await status(session, packet.id)


async def fill(session, packet, service, runtime, confirm, confirm_context=False):
    if not confirm_context:
        raise HTTPException(
            422,
            "Confirm that the actual page belongs to the saved company and job before filling",
        )
    if not confirm:
        raise HTTPException(
            422, "Review the proposed values and explicitly confirm before filling"
        )
    saved = await metadata(session, packet.id)
    if not saved:
        raise HTTPException(409, "Analyze the form before filling")
    from backend.app.services.applications.multi_select import available

    runtime.multi_enabled = multi_enabled = await available(session)
    fields, _ = await runtime.unchanged(saved.value["signature"])
    items = {
        str(f.id): service.repo.field_read(f)
        for f in await service.repo.fields(packet.id)
    }
    plan, validation = [], []
    for actual, mapped in zip(fields, saved.value["fields"], strict=True):
        item = items[mapped["field_id"]]
        if (
            not actual["supported"]
            or not mapped["supported"]
            or (
                actual["kind"] in {"multi_select", "checkbox_group"}
                and not multi_enabled
            )
        ):
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": False,
                    "reason": actual["manual_reason"],
                }
            )
            continue
        if actual["kind"] == "file":
            # Only exact selected, confirmed, encrypted database bytes. Never read a client path or URL.
            resource = (
                await session.get(CandidateResource, packet.resume_resource_id)
                if packet.resume_resource_id
                else None
            )
            candidates = (
                list(
                    (
                        await session.scalars(
                            select(PrivateResume).where(
                                PrivateResume.resource_id == packet.resume_resource_id,
                                PrivateResume.confirmed.is_(True),
                            )
                        )
                    ).all()
                )
                if packet.resume_resource_id
                else []
            )
            resume = candidates[0] if len(candidates) == 1 else None
            if resume and not (
                resource
                and resource.user_confirmed
                and resource.source_type == "private_upload"
                and resource.candidate_profile_id == packet.candidate_profile_id
                and resource.url == "private-resume:" + str(resume.id)
            ):
                raise HTTPException(
                    409, "Selected resume reference does not match the approved PDF"
                )
            if not resume:
                validation.append(
                    {
                        "field_id": str(item.id),
                        "complete": False,
                        "reason": "Select an approved private PDF resume",
                    }
                )
                continue
            raw = cipher().decrypt(resume.ciphertext)
            if (
                len(raw) > MAX_PDF
                or not raw.startswith(b"%PDF-")
                or hashlib.sha256(raw).hexdigest() != resume.sha256
            ):
                raise HTTPException(409, "Resume integrity validation failed")
            plan.append(
                (
                    actual,
                    item,
                    None,
                    {
                        "name": "resume.pdf",
                        "mimeType": "application/pdf",
                        "buffer": raw,
                    },
                )
            )
            continue
        value = item.effective_answer
        if (
            not value
            or item.validation_status != "draft_ready"
            or value_error(item, value)
        ):
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": False,
                    "reason": "Answer missing or invalid",
                }
            )
            continue
        if item.requires_review and item.review_status != "reviewed":
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": False,
                    "reason": "Review this answer before filling",
                }
            )
            continue
        plan.append((actual, item, value, None))
    # Persist intent before side effects. A lost response never replays automatically.
    saved.value = {
        **saved.value,
        "diagnostic": "fill_started",
        "filled_field_ids": [],
        "validation": validation,
    }
    await session.commit()
    await service.locked(packet.id, packet.revision)
    filled = []
    try:
        if runtime.blocked_step_requests:
            raise HTTPException(409, "Network-dependent form requires manual takeover")
        for actual, item, value, upload in plan:
            # Dynamic questions may appear after any change. Stop before addressing a changed form.
            fresh, _ = await runtime.unchanged(saved.value["signature"])
            index = next(
                i
                for i, f in enumerate(saved.value["fields"])
                if f["field_id"] == str(item.id)
            )
            valid = await runtime.fill(fresh[index], value=value, upload=upload)
            if valid is None:
                validation.append(
                    {
                        "field_id": str(item.id),
                        "complete": False,
                        "reason": "Existing answer preserved; review it on the website",
                    }
                )
                continue
            filled.append(str(item.id))
            if runtime.blocked_step_requests:
                raise HTTPException(
                    409, "Network-dependent form requires manual takeover"
                )
            validation.append(
                {
                    "field_id": str(item.id),
                    "complete": valid,
                    "reason": None if valid else "Browser validation failed",
                }
            )
        await runtime.unchanged(saved.value["signature"])
        if runtime.blocked_step_requests:
            raise HTTPException(409, "Network-dependent form requires manual takeover")
        diagnostic = "filled_review_on_website"
    except Exception:
        diagnostic = (
            "network_activity_requires_takeover"
            if runtime.blocked_step_requests
            else "interrupted_reanalyze_before_retry"
        )
    saved.value = {
        **saved.value,
        "diagnostic": diagnostic,
        "filled_field_ids": filled,
        "validation": validation,
    }
    await session.commit()
    return await status(session, packet.id)
