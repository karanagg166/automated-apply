"""Shared startup orchestration and cached reads used by REST and MCP."""

import asyncio
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.models.company import Company
from backend.app.models.discovery import DiscoveryRun, JobSourceObservation, now
from backend.app.models.job import Job
from backend.app.models.startup import CompanySourceObservation, StartupShortlistEntry
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.schemas.discovery import RunRequest
from backend.app.schemas.job import JobRead
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.services.discovery_budget import insert_for
from backend.app.services.job_discovery_service import JobDiscoveryService, run_output
from backend.app.services.saved_data import SavedDataService
from backend.app.services.startup_discovery.evidence import ingest_company
from backend.app.services.startup_discovery.intelligence import (
    company_size,
    hiring_intelligence,
)
from backend.app.services.startup_discovery.normalizer import (
    location_allowed,
    role_allowed,
    size_allowed,
    utc,
)
from backend.app.services.startup_discovery.ranking import rank_startup
from backend.app.services.startup_discovery.schemas import StartupFilters
from backend.app.services.startup_discovery.source_registry import startup_sources


class StartupDiscoveryService:
    def __init__(self, session, factory=None, settings=None):
        self.session, self.factory = session, factory
        self.settings = settings or get_settings()

    async def profile(self, enabled=True):
        if enabled:
            try:
                return await CandidateProfileService(self.session).get_profile()
            except ProfileNotFoundError:
                pass
        return None

    async def company(self, company_id):
        company = await self.session.get(Company, company_id)
        if company is None:
            raise LookupError("Startup not found")
        return company

    def source_config(self, provider):
        source = next(
            (
                s
                for s in startup_sources(self.settings)
                if s["provider"] == provider
            ),
            None,
        )
        if source is None:
            raise ValueError("Unknown startup source")
        return source

    async def preview(self, request):
        source = self.source_config(request.source)
        profile = await self.profile(request.filters.use_profile)
        return dict(
            source=source,
            mode=request.mode,
            filters=request.filters.model_dump(),
            profile_version=profile.version if profile else None,
            effective_roles=request.filters.roles
            or (profile.preferences.target_titles if profile else []),
            effective_locations=request.filters.locations
            or (profile.preferences.preferred_locations if profile else []),
            provider_calls=0,
            writes=0,
            company_first_available=request.mode in source["modes"],
            message="Company-first collection requires a permission-confirmed import; no directory crawl is available",
        )

    async def run(self, request):
        # Validate without an unused profile read holding the sole runtime
        # connection while independent parent/child run claims acquire theirs.
        self.source_config(request.source)
        orchestrator = JobDiscoveryService(self.session, self.factory, self.settings)
        run_id, claimed = await orchestrator.claim(
            request.model_copy(update={"source": "startup_" + request.source})
        )
        if not claimed:
            return run_output(run_id)
        try:
            async with asyncio.timeout(self.settings.DISCOVERY_TIMEOUT_SECONDS + 10):
                ids, child, status, errors = [], None, "success", []
                if request.mode == "company_first":
                    if request.source != "manual":
                        status, errors = (
                            "unsupported",
                            [
                                "No permitted company-directory provider is configured; use a rights-confirmed manual import"
                            ],
                        )
                    elif not request.companies:
                        status = "manual_input_required"
                    else:
                        for item in request.companies:
                            company = await ingest_company(self.session, item, run_id)
                            ids.append(company.id)
                else:
                    if request.source not in {
                        s["provider"]
                        for s in startup_sources(self.settings)
                        if "job_led" in s["modes"]
                    }:
                        status, errors = (
                            "unsupported",
                            ["This provider does not support job-led discovery"],
                        )
                    else:
                        child = await orchestrator.run(
                            RunRequest(
                                source=request.source,
                                query=request.query,
                                idempotency_key="startup_child_" + str(run_id),
                                allow_paid=request.allow_paid,
                                use_profile=request.filters.use_profile,
                            )
                        )
                        status, errors = child["status"], child["errors"]
                        job_ids = [UUID(value) for value in child.get("job_ids", [])]
                        if job_ids:
                            ids = list(
                                (
                                    await self.session.scalars(
                                        select(Job.company_id)
                                        .where(
                                            Job.id.in_(job_ids),
                                            Job.company_id.is_not(None),
                                        )
                                        .distinct()
                                    )
                                ).all()
                            )
                # Persist the company observations and final audit in one transaction.
                shortlist = (
                    await self.search(
                        request.filters.model_copy(update={"page": 1, "limit": 100}),
                        company_ids=ids,
                    )
                    if ids
                    else {"startups": []}
                )
                run = await self.session.get(DiscoveryRun, run_id)
                run.query_summary = {
                    "mode": request.mode,
                    "filters": request.filters.model_dump(mode="json"),
                    "child_run_id": child["id"] if child else None,
                    "company_ids": [str(value) for value in ids],
                }
                run.status, run.errors, run.rankings = (
                    status,
                    errors,
                    shortlist["startups"],
                )
                run.counts = {
                    "companies_observed": len(set(ids)),
                    "companies_matching": len(shortlist["startups"]),
                }
                run.finished_at = now()
                await self.session.commit()
                return run_output(run)
        except BaseException as exc:
            await self.session.rollback()

            async def finish_failed(error):
                async with self.factory() as audit:
                    run = await audit.get(DiscoveryRun, run_id)
                    run.status = (
                        "cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else "failed"
                    )
                    run.errors = [
                        "Startup discovery failed; inspect child run diagnostics before retrying with a new key"
                    ]
                    run.finished_at = now()
                    await audit.commit()
                    return run_output(run)

            result = await asyncio.shield(finish_failed(exc))
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            return result

    async def read_run(self, run_id):
        run = await self.session.get(DiscoveryRun, run_id)
        if run is None or not run.source.startswith("startup_"):
            raise LookupError("Startup run not found")
        return {**run_output(run, self.settings), "query": run.query_summary}

    async def detail(self, company_id, filters=None, profile=None):
        filters = filters or StartupFilters(max_employees=None)
        company = await self.company(company_id)
        observations = list(
            (
                await self.session.scalars(
                    select(CompanySourceObservation)
                    .where(CompanySourceObservation.company_id == company_id)
                    .order_by(
                        CompanySourceObservation.observed_at.desc(),
                        CompanySourceObservation.id,
                    )
                    .limit(100)
                )
            ).all()
        )
        jobs = list(
            (
                await self.session.scalars(
                    select(Job)
                    .where(Job.company_id == company_id)
                    .order_by(Job.last_observed_at.desc().nullslast(), Job.id)
                    .limit(501)
                )
            ).all()
        )
        if len(jobs) > 500:
            raise ValueError("Narrow the company job history to at most 500 records")
        job_observations = (
            list(
                (
                    await self.session.scalars(
                        select(JobSourceObservation)
                        .where(JobSourceObservation.job_id.in_([j.id for j in jobs]))
                        .order_by(JobSourceObservation.last_observed_at.desc())
                        .limit(2000)
                    )
                ).all()
            )
            if jobs
            else []
        )
        # Do not silently promote legacy unproven company metadata into verified attributes.
        attributes = {}
        for observation in sorted(
            observations,
            key=lambda o: (
                o.verification_status == "human_confirmed",
                utc(o.observed_at),
                str(o.id),
            ),
        ):
            if (
                not observation.attributes.get("historical")
                and utc(observation.observed_at) >= now() - timedelta(days=180)
                and observation.verification_status
                in {"source_reported", "human_confirmed"}
            ):
                attributes.update(
                    {
                        k: v
                        for k, v in observation.attributes.items()
                        if v not in (None, [], "unknown")
                    }
                )
        size = company_size(observations)
        hiring = hiring_intelligence(
            jobs, observations, filters.freshness_days, job_observations
        )
        contacts = await SavedDataService(self.session).contacts(
            company_id, 100, company_size=size
        )
        if profile is None:
            profile = await self.profile(filters.use_profile)
        fresh_ids = {s["job_id"] for s in hiring["hiring_evidence"] if s["fresh"]}
        fresh_jobs = [j for j in jobs if str(j.id) in fresh_ids]
        roles = filters.roles or (profile.preferences.target_titles if profile else [])
        relevant_jobs = [
            j
            for j in fresh_jobs
            if role_allowed(j.title, roles)
        ]
        ranking = rank_startup(
            self.session,
            company,
            relevant_jobs,
            attributes,
            size,
            hiring,
            contacts,
            profile,
            filters,
        )
        if (company.metadata_ or {}).get("identity_review_required"):
            ranking["missing_information"].append("company_identity_requires_review")
        return dict(
            company_id=str(company.id),
            identity_review_required=bool(
                (company.metadata_ or {}).get("identity_review_required")
            ),
            company_name=company.name,
            company_domain=company.domain,
            attributes=attributes,
            **size,
            **hiring,
            **ranking,
            current_job_count=len(fresh_jobs),
            sources=sorted(
                {o.source for o in observations} | {o.source for o in job_observations}
            ),
            leader_evidence_count=sum(
                c["confidence"] == "supported"
                and any(
                    role in c["role_title"].casefold()
                    for role in (
                        "founder",
                        "cto",
                        "chief technology",
                        "head of engineering",
                        "vp engineering",
                    )
                )
                for c in contacts
            ),
            technical_staff_count=sum(
                c["confidence"] == "supported" and c["priority"] not in {"review_required", "suppressed"}
                and any(role in (c.get("role_title") or "").casefold() for role in
                        ("engineer", "developer", "cto", "chief technology", "technical recruiter"))
                for c in contacts
            ),
            professional_contact_count=sum(
                c["priority"] not in {"review_required", "suppressed"}
                and c["confidence"] == "supported"
                for c in contacts
            ),
            available_evidence_count=len(observations),
            next_steps={
                "jobs": f"/api/v1/startups/{company.id}/jobs",
                "people_research": "/api/v1/discovery/people/search",
                "contacts": f"/api/v1/companies/{company.id}/recommended-contacts",
                "contact_enrichment_preview": f"/api/v1/companies/{company.id}/contacts/preview",
                "outreach": "/api/v1/outreach/drafts",
                "application_preview_template": "/api/v1/jobs/{job_id}/application-preview",
            },
        )

    async def search(self, filters, company_ids=None, shortlisted=False):
        from backend.app.dashboard.states import matches_status, packet_map

        statement = select(Company.id).order_by(Company.id)
        if company_ids is not None:
            statement = statement.where(Company.id.in_(company_ids))
        if shortlisted:
            statement = statement.where(
                Company.id.in_(select(StartupShortlistEntry.company_id))
            )
        if filters.source:
            statement = statement.where(
                Company.id.in_(
                    select(CompanySourceObservation.company_id).where(
                        CompanySourceObservation.source == filters.source
                    )
                )
                | Company.id.in_(
                    select(Job.company_id).where(Job.source_platform == filters.source)
                )
            )
        ids = list((await self.session.scalars(statement.limit(501))).all())
        if len(ids) > 500:
            raise ValueError("Narrow source filters to at most 500 companies")
        profile, items = await self.profile(filters.use_profile), []
        packets = await packet_map(self.session)
        shortlisted_ids = set((await self.session.scalars(select(StartupShortlistEntry.company_id))).all())
        for company_id in ids:
            item = await self.detail(company_id, filters, profile)
            item["shortlisted"] = company_id in shortlisted_ids
            if filters.query and filters.query.casefold() not in (item["company_name"] + " " + (item["company_domain"] or "")).casefold():
                continue
            company_jobs = list((await self.session.scalars(select(Job).where(Job.company_id == company_id))).all())
            if filters.application_status != "all":
                if filters.application_status == "not_applied" and not company_jobs:
                    pass
                elif filters.application_status == "shortlisted" and item["shortlisted"]:
                    pass
                elif not any(matches_status(j, packets.get(j.id), filters.application_status) for j in company_jobs):
                    continue
            item["application_history"] = [dict(job_id=str(j.id), title=j.title,
                lifecycle_state=packets[j.id].lifecycle_state if j.id in packets else None,
                status=j.status) for j in company_jobs]
            if (
                not size_allowed(item, filters)
                or item["exclusion_reasons"]
                or item["startup_match_score"] < filters.minimum_score
            ):
                continue
            attrs = item["attributes"]
            country = (attrs.get("country") or "").strip().casefold()
            country = {"in": "india", "ind": "india"}.get(country, country)
            wanted = (filters.country or "").strip().casefold()
            wanted = {"in": "india", "ind": "india"}.get(wanted, wanted)
            if wanted and country != wanted:
                continue
            if filters.industries and not any(ind.casefold() in (attrs.get("industry") or "").casefold() for ind in filters.industries):
                continue
            if filters.has_technical_staff and not item["technical_staff_count"]:
                continue
            if filters.verified_yc and not attrs.get("yc_batch"):
                continue
            if filters.early_stage and str(attrs.get("stage", "")).casefold() not in {"pre-seed", "seed", "early", "early-stage", "series a"}:
                continue
            if filters.observed_after and not any(j.last_observed_at and utc(j.last_observed_at) > utc(filters.observed_after) for j in company_jobs):
                continue
            if filters.has_business_email:
                contacts = await SavedDataService(self.session).contacts(company_id, 100)
                if not any(c.get("email_send_ready") and not c.get("do_not_contact") for c in contacts):
                    continue
            if filters.stages and attrs.get("stage") not in filters.stages:
                continue
            if filters.yc_batch and attrs.get("yc_batch") != filters.yc_batch:
                continue
            if filters.hiring_status and item["hiring_status"] != filters.hiring_status:
                continue
            if filters.has_leader_evidence and not item["leader_evidence_count"]:
                continue
            if (
                filters.roles
                and not item["matching_roles"]
                and not any(
                    any(
                        role.casefold() in e["title"].casefold()
                        for role in filters.roles
                    )
                    for e in item["hiring_evidence"]
                    if e["fresh"]
                )
            ):
                continue
            if filters.skills and not set(
                v.casefold() for v in filters.skills
            ).intersection(v.casefold() for v in attrs.get("technology_stack", [])):
                # Job skill evidence can also satisfy an explicit technology filter.
                skill_jobs = (
                    await self.session.scalars(
                        select(Job).where(Job.company_id == company_id).limit(500)
                    )
                ).all()
                if not any(
                    set(v.casefold() for v in filters.skills).intersection(
                        v.casefold() for v in j.skills_required or []
                    )
                    for j in skill_jobs
                ):
                    continue
            locations = [attrs.get("location") or ""] + [
                e["location"] or "" for e in item["hiring_evidence"] if e["fresh"]
            ]
            remotes = [attrs.get("remote_policy")] + [
                e["remote_policy"] for e in item["hiring_evidence"] if e["fresh"]
            ]
            if not location_allowed(locations, remotes, filters):
                continue
            items.append(item)
        items.sort(
            key=lambda i: (
                -i["startup_match_score"],
                i["company_name"].casefold(),
                i["company_id"],
            )
        )
        return dict(
            total=len(items),
            page=filters.page,
            limit=filters.limit,
            startups=items[
                (filters.page - 1) * filters.limit : filters.page * filters.limit
            ],
        )

    async def jobs(self, company_id):
        await self.company(company_id)
        jobs = (
            await self.session.scalars(
                select(Job)
                .where(Job.company_id == company_id)
                .order_by(Job.last_observed_at.desc().nullslast(), Job.id)
                .limit(100)
            )
        ).all()
        return {
            "jobs": [JobRead.model_validate(j).model_dump(mode="json") for j in jobs]
        }

    async def evidence(self, company_id):
        await self.company(company_id)
        rows = (
            await self.session.scalars(
                select(CompanySourceObservation)
                .where(CompanySourceObservation.company_id == company_id)
                .order_by(
                    CompanySourceObservation.observed_at.desc(),
                    CompanySourceObservation.id,
                )
                .limit(100)
            )
        ).all()
        return {
            "observations": [
                dict(
                    id=str(o.id),
                    source=o.source,
                    source_url=o.source_url,
                    observed_at=utc(o.observed_at).isoformat(),
                    verification_status=o.verification_status,
                    attributes=o.attributes,
                    stale=utc(o.observed_at) < now() - timedelta(days=180),
                )
                for o in rows
            ]
        }

    async def shortlist(self, company_id, request):
        if request.run_id:
            await self.read_run(request.run_id)
        snapshot = await self.detail(company_id)
        inserted = (
            await self.session.execute(
                insert_for(self.session)(StartupShortlistEntry)
                .values(
                    company_id=company_id,
                    run_id=request.run_id,
                    snapshot=snapshot,
                    note=request.note,
                )
                .on_conflict_do_nothing()
                .returning(StartupShortlistEntry.company_id)
            )
        ).scalar_one_or_none()
        await self.session.commit()
        return {
            "company_id": str(company_id),
            "created": inserted is not None,
            "snapshot": (
                await self.session.get(StartupShortlistEntry, company_id)
            ).snapshot,
        }
