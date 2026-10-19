"""Opt-in Apify discovery. No default actor IDs, pricing assertions or invented URLs."""

import asyncio
import re
import uuid
from typing import Annotated, Any, Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from backend.app.core.config import get_settings
from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.discovery import (
    DiscoveryQuery,
    DiscoveryResult,
    DiscoveryError,
    DiscoveryStatus as Status,
)
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.normalization import (
    parse_date,
    remote_policy,
    employment,
    salary_fields,
)

# Kept for import compatibility; nothing in this catalog is represented as vetted.
ACTOR_CATALOG = {
    name: {"available": False, "review_required": True}
    for name in (
        "naukri",
        "instahyre",
        "wellfound",
        "work_at_a_startup",
        "cutshort",
        "hirist",
        "foundit",
        "indeed",
        "glassdoor",
    )
}


class ActorConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+[~/][A-Za-z0-9_-]+$")
    ]
    build: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    enabled: bool = False
    reviewed: bool = False
    schema_evidence_url: PublicHTTPSURL
    pricing_evidence_url: PublicHTTPSURL
    permission_evidence_url: PublicHTTPSURL
    # Only the actor pricing model with a documented provider-side charge cap is allowed.
    pricing_model: Literal["PAY_PER_EVENT"]
    estimated_per_item_usd: float = Field(ge=0, le=100, allow_inf_nan=False)
    estimated_start_usd: float = Field(0, ge=0, le=100, allow_inf_nan=False)
    field_map: dict[
        Literal["query", "keywords", "location", "locations", "limit"],
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,80}$")],
    ]
    fixed_input: dict[str, Any] = Field(default_factory=dict)

    def build_input(self, query):
        values = {
            "query": " ".join(query.keywords),
            "keywords": query.keywords,
            "location": ", ".join(query.locations),
            "locations": query.locations,
            "limit": query.limit,
        }
        if "limit" not in self.field_map or len(set(self.field_map.values())) != len(
            self.field_map
        ):
            raise ValueError("Actor mapping must have a unique bounded limit field")
        return {
            **self.fixed_input,
            **{field: values[key] for key, field in self.field_map.items()},
        }


class ApifyJobAdapter(JobSourceAdapter):
    source_name = "apify"

    def __init__(
        self,
        api_token=None,
        http_client=None,
        source_name=None,
        configuration=None,
        budget=None,
        settings=None,
    ):
        self.settings = settings or get_settings()
        self.api_token = (
            api_token if api_token is not None else self.settings.APIFY_API_TOKEN
        )
        self.source_name = source_name or "apify"
        self.monthly_limit_usd = self.settings.APIFY_MONTHLY_LIMIT_USD
        self._client, self.budget = http_client, budget
        self.configuration = (
            configuration
            if configuration is not None
            else self.settings.APIFY_SOURCES.get(self.source_name, {})
        )

    def actor(self):
        try:
            actor = ActorConfiguration.model_validate(self.configuration)
            actor.build_input(DiscoveryQuery())
            return actor
        except ValueError:
            raise DiscoveryError(
                Status.CONFIGURATION_REQUIRED,
                "Reviewed actor schema, permissions, pinned build, pricing and input mapping required",
            ) from None

    def validate_configuration(self):
        if not self.api_token:
            return ["Apify token not configured"]
        try:
            actor = self.actor()
        except DiscoveryError as exc:
            return [str(exc)]
        if not actor.enabled or not actor.reviewed:
            return ["Paid source is disabled or actor review is incomplete"]
        if (
            self.settings.APIFY_PER_RUN_CAP_USD <= 0
            or self.monthly_limit_usd < self.settings.APIFY_PER_RUN_CAP_USD
        ):
            return ["A positive per-run and monthly budget is required"]
        return []

    def normalize_portal_record(self, portal, item):
        if portal not in ACTOR_CATALOG:
            raise ValueError("Unknown Apify source")
        if not isinstance(item, dict):
            raise ValueError("Dataset item must be an object")
        company = item.get("companyName") or item.get("company")
        company_data = company if isinstance(company, dict) else {}
        company = company_data.get("name") if company_data else company
        skills = item.get("skills") or []
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]
        location = item.get("location")
        if isinstance(location, list):
            location = ", ".join(location)
        raw = item.get("salary") or item.get("compensation")
        intelligence = {
            key: company_data[key]
            for key in ("stage", "batch", "technologies", "remote_policy")
            if key in company_data
        }
        from backend.app.core.job_urls import canonical_job_url

        for key in ("profile_url", "founder_urls"):
            if key in company_data:
                urls = (
                    company_data[key]
                    if isinstance(company_data[key], list)
                    else [company_data[key]]
                )
                intelligence[key] = [canonical_job_url(url) for url in urls[:20]]
        if intelligence:
            intelligence.update(
                {"source": portal, "verification_status": "source_reported"}
            )
        return NormalizedJob(
            source_name=portal,
            source_job_id=str(
                item.get("id") or item.get("jobId") or item.get("slug") or ""
            )
            or None,
            original_url=item.get("url")
            or item.get("jobUrl")
            or item.get("job_url")
            or item.get("link"),
            application_url=item.get("applyUrl") or item.get("applicationUrl"),
            company_name=company,
            company_domain=item.get("companyDomain") or company_data.get("domain"),
            title=item.get("title") or item.get("jobTitle") or item.get("role"),
            description=item.get("description") or item.get("jobDescription"),
            location=location,
            remote_type="remote"
            if item.get("isRemote") is True
            else remote_policy(location),
            employment_type=employment(item.get("employmentType")),
            experience_level=item.get("seniority"),
            salary_raw=str(raw) if raw else None,
            **salary_fields(raw),
            equity=item.get("equity"),
            skills_required=skills,
            date_posted=parse_date(item.get("postedDate") or item.get("datePosted")),
            company_intelligence=intelligence,
            data_provenance={
                "adapter": type(self).__name__,
                "portal": portal,
                "actor_id": self.configuration.get("actor_id"),
            },
            source_verification_status="source_reported",
            is_confirmed_current=False,
        )

    async def discover(self, query, *, allow_paid=False, reservation_id=None, **kwargs):
        portal = kwargs.pop("portal", self.source_name)
        if "linkedin" in portal:
            raise PermissionError(
                "STRICT RESTRICTION: LinkedIn requests are not permitted through Apify"
            )
        if portal != self.source_name or portal not in ACTOR_CATALOG:
            return DiscoveryResult(
                source=self.source_name,
                status=Status.UNSUPPORTED,
                errors=[
                    "Select an explicit configured platform; platform overrides are forbidden"
                ],
            )
        if query.page != 1:
            return DiscoveryResult(
                source=portal,
                status=Status.UNSUPPORTED,
                errors=[
                    "Actor pagination is not configured; use bounded first-page discovery"
                ],
            )
        errors = []
        if not self.api_token:
            return DiscoveryResult(
                source=portal,
                status=Status.MISSING_CREDENTIALS,
                errors=["Apify token not configured"],
            )
        errors = self.validate_configuration()
        if errors:
            return DiscoveryResult(
                source=portal, status=Status.CONFIGURATION_REQUIRED, errors=errors
            )
        if not allow_paid or self.budget is None:
            return DiscoveryResult(
                source=portal,
                status=Status.AUTH_REQUIRED,
                errors=[
                    "Use authenticated REST discovery with explicit paid approval and durable budget"
                ],
            )
        actor = self.actor()
        cap = self.settings.APIFY_PER_RUN_CAP_USD
        estimate = (
            actor.estimated_start_usd + query.limit * actor.estimated_per_item_usd
        )
        if estimate > cap:
            return DiscoveryResult(
                source=portal,
                status=Status.BUDGET_EXHAUSTED,
                errors=["Estimated cost exceeds per-run cap"],
            )
        reservation_id = reservation_id or uuid.uuid4().hex
        try:
            await self.budget.reserve(
                "apify", reservation_id, cap, self.monthly_limit_usd
            )
        except DiscoveryError as exc:
            return DiscoveryResult(source=portal, status=exc.status, errors=[str(exc)])
        result = DiscoveryResult(
            source=portal,
            status=Status.UPSTREAM_ERROR,
            usage={
                "reserved_usd": cap,
                "estimated_usd": estimate,
                "accounting": "full_cap_retained",
                "billing_final": False,
            },
        )
        client = self._client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        headers = {"Authorization": f"Bearer {self.api_token}"}
        run = {}

        async def request(method, path, **options):
            response = await client.request(
                method,
                "https://api.apify.com/v2/" + path,
                headers=headers,
                timeout=20,
                follow_redirects=False,
                **options,
            )
            if response.status_code == 429:
                await self.budget.cooldown("apify")
                raise DiscoveryError(
                    Status.RATE_LIMITED, "Apify rate limited; cooldown recorded"
                )
            if response.status_code in (401, 403):
                raise DiscoveryError(
                    Status.AUTH_REQUIRED, "Apify authorization required"
                )
            if response.status_code not in (200, 201):
                raise DiscoveryError(
                    Status.UPSTREAM_ERROR, f"Apify returned HTTP {response.status_code}"
                )
            return response.json()

        try:
            async with asyncio.timeout(70):
                run = (
                    await request(
                        "POST",
                        f"actors/{actor.actor_id.replace('/', '~')}/runs",
                        json=actor.build_input(query),
                        params={
                            "build": actor.build,
                            "waitForFinish": 15,
                            "timeout": 60,
                            "maxTotalChargeUsd": cap,
                            "maxItems": query.limit,
                            "restartOnError": "false",
                        },
                    )
                )["data"]
                run_id = run["id"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
                    raise ValueError("Invalid run identifier")
                result.provider_run_id = run_id
                await self.budget.attach_run(reservation_id, run_id)
                for _ in range(3):
                    if run.get("status") not in (
                        "READY",
                        "QUEUED",
                        "RUNNING",
                        "TIMING-OUT",
                        "ABORTING",
                    ):
                        break
                    run = (
                        await request(
                            "GET", f"actor-runs/{run_id}", params={"waitForFinish": 10}
                        )
                    )["data"]
                if run.get("status") != "SUCCEEDED":
                    raise DiscoveryError(
                        Status.UPSTREAM_ERROR,
                        "Actor did not succeed: " + str(run.get("status", "UNKNOWN")),
                    )
                dataset = run["defaultDatasetId"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", dataset):
                    raise ValueError("Invalid dataset identifier")
                offset = 0
                while offset < query.limit:
                    page_size = min(50, query.limit - offset)
                    items = await request(
                        "GET",
                        f"datasets/{dataset}/items",
                        params={"offset": offset, "limit": page_size, "format": "json"},
                    )
                    if not isinstance(items, list):
                        raise ValueError("Dataset must be an array")
                    for index, item in enumerate(items[:page_size]):
                        try:
                            job = self.normalize_portal_record(portal, item)
                            job.data_provenance.update(
                                {"provider_run_id": run_id, "actor_build": actor.build}
                            )
                            result.jobs.append(job)
                        except (
                            ValueError,
                            TypeError,
                            KeyError,
                            AttributeError,
                            OverflowError,
                        ):
                            result.rejected_count += 1
                            result.errors.append(
                                f"Dataset record {offset + index}: invalid listing evidence"
                            )
                    offset += page_size
                    if len(items) < page_size:
                        break
                result.status = (
                    Status.PARTIAL
                    if result.rejected_count
                    else Status.SUCCESS
                    if result.jobs
                    else Status.NO_RESULTS
                )
                actual = run.get("usageTotalUsd")
                import math

                if (
                    isinstance(actual, (int, float))
                    and not isinstance(actual, bool)
                    and math.isfinite(actual)
                    and actual >= 0
                ):
                    result.usage["reported_actual_usd"] = actual
        except DiscoveryError as exc:
            result.status = exc.status
            result.errors.append(str(exc))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError):
            result.status = Status.UPSTREAM_ERROR
            result.errors.append("Apify transport, timeout or invalid response")
        finally:
            # A disconnected caller cannot leave an unbounded run. The provider timeout remains the fallback.
            if result.provider_run_id and run.get("status") in (
                "READY",
                "QUEUED",
                "RUNNING",
                "TIMING-OUT",
                "ABORTING",
            ):
                try:
                    await asyncio.shield(
                        request("POST", f"actor-runs/{result.provider_run_id}/abort")
                    )
                except (httpx.HTTPError, DiscoveryError, ValueError):
                    result.errors.append(
                        "Abort could not be confirmed; provider timeout and reserved cap remain"
                    )
            await asyncio.shield(
                self.budget.finish(
                    reservation_id,
                    str(result.status),
                    result.usage.get("reported_actual_usd"),
                )
            )
            if self._client is None:
                await client.aclose()
        return result

    async def fetch_jobs(
        self, portal=None, search_query="", location="", limit=20, **kwargs
    ):
        if portal and "linkedin" in portal:
            raise PermissionError(
                "STRICT RESTRICTION: LinkedIn requests are not permitted through Apify"
            )
        result = await self.discover(
            DiscoveryQuery(
                keywords=[search_query] if search_query else [],
                locations=[location] if location else [],
                limit=limit,
            ),
            portal=portal or self.source_name,
            **kwargs,
        )
        if result.status not in (Status.SUCCESS, Status.NO_RESULTS, Status.PARTIAL):
            raise DiscoveryError(result.status, "; ".join(result.errors))
        return result.jobs

    async def test_connection(self):
        # Checking configuration never launches a billable actor or implies a live portal connection.
        return {
            "status": "not_attempted",
            "source": self.source_name,
            "sample_count": 0,
            "message": "; ".join(self.validate_configuration())
            or "Configuration valid; live connection not verified",
            "details": {"live_verified": False},
        }
