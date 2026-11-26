"""Read-only packet assembly from saved jobs, confirmed profiles and resources."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.core.timing import timed
from backend.app.models.application_answer import CandidateEvidence, CandidateResource
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.discovery import JobSourceObservation
from backend.app.models.job import Job
from backend.app.schemas.applications import (
    Destination,
    PacketPreview,
    PacketSnapshot,
    QuestionInput,
)
from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileRead,
)
from backend.app.services.applications.answer_builder import AnswerBuilder
from backend.app.services.applications.base import ApplicationNotFound
from backend.app.services.applications.eligibility import readiness
from backend.app.services.applications.platforms.base import safe_url
from backend.app.services.applications.platforms.registry import application_platforms
from backend.app.services.applications.resume_selector import digest, select_resume
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher


def core_questions():
    # Local checklist fields, not asserted to be Naukri form structure or IDs.
    return [
        QuestionInput(question=q, category=c, field_type=t, required=r)
        for q, c, t, r in [
            ("Full name", "personal_information", "text", True),
            ("Email", "contact_information", "text", True),
            ("Phone number", "contact_information", "text", False),
            ("GitHub profile URL", "professional_profile_url", "url", False),
            ("LinkedIn profile URL", "professional_profile_url", "url", False),
            ("Portfolio URL", "professional_profile_url", "url", False),
            ("Upload resume", "resume_upload", "file", True),
        ]
    ]


class PacketBuilder:
    def __init__(self, session, answer_service):
        self.session, self.answers = session, AnswerBuilder(answer_service)
        self.platforms = application_platforms()

    @timed("packet_context_build")
    async def context(self, job_id, selected_resume=None, *, lock=False):
        async def one(model, condition):
            query = (
                select(model).where(condition).execution_options(populate_existing=True)
            )
            return await self.session.scalar(query.with_for_update() if lock else query)

        job = await one(Job, Job.id == job_id)
        if job is None:
            raise ApplicationNotFound("Saved job not found")
        profile = await one(
            CandidateProfile, CandidateProfile.singleton_key == "primary"
        )
        company = (
            await one(Company, Company.id == job.company_id) if job.company_id else None
        )
        resources = []
        stamps = []
        if profile:
            query = (
                select(CandidateResource)
                .where(CandidateResource.candidate_profile_id == profile.id)
                .order_by(CandidateResource.id)
                .execution_options(populate_existing=True)
            )
            resources = list(
                (
                    await self.session.scalars(
                        query.with_for_update() if lock else query
                    )
                ).all()
            )
            # No evidence body is copied into packet metadata. Timestamps are trigger-maintained
            # on PostgreSQL. Include every row to detect removal/confirmation beyond API pages.
            query = (
                select(
                    CandidateEvidence.id,
                    CandidateEvidence.updated_at,
                    CandidateEvidence.user_confirmed,
                )
                .where(CandidateEvidence.candidate_profile_id == profile.id)
                .order_by(CandidateEvidence.id)
            )
            stamps = [
                list(row)
                for row in (
                    await self.session.execute(
                        query.with_for_update() if lock else query
                    )
                ).all()
            ]
        observations = (
            await self.session.execute(
                select(JobSourceObservation.source, JobSourceObservation.original_url)
                .where(JobSourceObservation.job_id == job.id)
                .order_by(
                    JobSourceObservation.source, JobSourceObservation.original_url
                )
            )
        ).all()
        if job.source_platform == "naukri":
            from backend.app.services.applications.platforms.naukri import (
                reviewed_job_context,
            )

            job, company = reviewed_job_context(job, company)
        adapter = next(
            (p for p in self.platforms if p.recognizes(job, observations)), None
        )
        destination = (
            adapter.destination(job, observations)
            if adapter
            else Destination(kind="unknown")
        )
        saved_candidate = (
            CandidateProfileCreate.model_validate(profile) if profile else None
        )
        links = {
            k: url
            for k, attr in [
                ("github", "github_url"),
                ("linkedin", "linkedin_url"),
                ("portfolio", "portfolio_url"),
            ]
            if profile and (url := safe_url(getattr(profile, attr)))
        }
        resume = select_resume(resources, selected_resume)
        warnings = ["A recently observed job is not guaranteed to remain open"]
        observed = job.last_observed_at
        if observed and observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if observed is None or observed < datetime.now(timezone.utc) - timedelta(
            days=30
        ):
            warnings.append(
                "Job information may be outdated; check that the vacancy is still open before approval"
            )
        if not job.description:
            warnings.append(
                "Job description is missing; role-specific narrative generation may require input"
            )
        # Include material values rather than only the profile version (also catches raw edits).
        from backend.app.knowledge.opportunity import reviewed_context

        context_data = {
                "profile": saved_candidate.model_dump(mode="json")
                if saved_candidate
                else None,
                "profile_id": str(profile.id) if profile else None,
                "profile_version": profile.version if profile else None,
                "job": {
                    k: getattr(job, k)
                    for k in [
                        "id",
                        "company_id",
                        "title",
                        "source_platform",
                        "job_url",
                        "application_url",
                        "description",
                        "skills_required",
                        "location",
                        "remote_type",
                        "employment_type",
                        "experience_level",
                        "salary_min",
                        "salary_max",
                        "salary_currency",
                        "salary_period",
                        "source_verification_status",
                    ]
                },
                "closed": job.status == "archived",
                "reviewed_opportunity": (job.discovery_metadata or {}).get(
                    "application_opportunity"
                ),
                "opportunity_evidence_current": bool(reviewed_context(job, company)),
                "company": [company.name, company.domain, company.metadata_]
                if company
                else None,
                "resources": [
                    [
                        str(r.id),
                        r.label,
                        r.url,
                        r.user_confirmed,
                        r.is_primary,
                        str(r.updated_at),
                    ]
                    for r in resources
                ],
                "evidence": stamps,
                "observations": sorted({(s, u) for s, u in observations}),
            }
        if job.source_platform == "naukri":
            from backend.app.services.applications.platforms.naukri import (
                posting_unavailable,
            )

            context_data["naukri_listing_review"] = {
                "observed_criteria": job.discovery_metadata or {},
                "posting_unavailable": posting_unavailable(job),
            }
        if profile:
            from backend.app.knowledge.missing_input import approved_input_revisions
            revisions = await approved_input_revisions(self.session, profile.id, job.id)
            if revisions:
                context_data["owner_answer_revisions"] = revisions
        context_hash = digest(context_data)
        snapshot = PacketSnapshot(
            preparation_supported=adapter is not None,
            platform=adapter.capabilities().platform if adapter else None,
            company_id=job.company_id,
            company_name=company.name if company else None,
            job_title=job.title,
            source_platform=job.source_platform,
            original_job_url=job.job_url,
            source_observation_urls=sorted({u for _, u in observations if safe_url(u)}),
            destination=destination,
            candidate=saved_candidate,
            professional_links=links,
            resume=resume,
            match=JobDiscoveryMatcher(self.session).match(
                job, CandidateProfileRead.model_validate(profile), company
            )
            if profile
            else None,
            context_digest=context_hash,
            warnings=warnings,
        )
        return job, profile, snapshot

    async def preview(self, job_id, request):
        if any(question.field_type == "multi_select" for question in request.questions):
            from backend.app.services.applications.multi_select import require_available

            await require_available(self.session)
        job, profile, snapshot = await self.context(job_id, request.resume_resource_id)
        fields = []
        for i, question in enumerate([*core_questions(), *request.questions]):
            field = await self.answers.build(
                question,
                job.id,
                profile,
                origin="packet_core" if i < 7 else "user_provided",
                resume=snapshot.resume,
            )
            # Preview IDs are ephemeral; persisted packet IDs are assigned only at creation.
            field.id = uuid4()
            fields.append(field)
        return PacketPreview(
            job_id=job.id,
            candidate_profile_id=profile.id if profile else None,
            candidate_profile_version=profile.version if profile else None,
            snapshot=snapshot,
            fields=fields,
            readiness=readiness(snapshot, fields),
        )
