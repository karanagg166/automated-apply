"""Apify job source adapter with portal-specific normalizers, safety guards, and strict LinkedIn restrictions."""

from datetime import datetime, timezone
from typing import Any
import httpx

from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.base import JobSourceAdapter


# Catalog of vetted Apify Actors for each portal
ACTOR_CATALOG: dict[str, dict[str, Any]] = {
    "naukri": {
        "actor_id": "muhammetakkurtt/naukri-job-scraper",
        "publisher": "muhammetakkurtt",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.0015,
        "capabilities": ["read_listings", "read_salary", "extract_recruiter_info"],
        "supports_application": False,
    },
    "instahyre": {
        "actor_id": "getascraper/instahyre-jobs-scraper",
        "publisher": "getascraper",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.00105,
        "capabilities": ["read_listings", "read_skills", "read_salary"],
        "supports_application": False,
    },
    "wellfound": {
        "actor_id": "radeance/wellfound-job-listings-scraper",
        "publisher": "radeance",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.01,
        "capabilities": ["read_listings", "read_equity", "read_company_metadata"],
        "supports_application": False,
    },
    "work_at_a_startup": {
        "actor_id": "antishock/workatastartup-jobs-scraper",
        "publisher": "antishock",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.004,
        "capabilities": ["read_listings", "read_salary_equity", "read_batch_founders"],
        "supports_application": False,
    },
    "cutshort": {
        "actor_id": "getascraper/cutshort-scraper",
        "publisher": "getascraper",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.0013,
        "capabilities": ["read_listings", "read_salary_bands", "read_skills"],
        "supports_application": False,
    },
    "hirist": {
        "actor_id": "crawlpilot/hirist-tech-advanced-jobs-scraper",
        "publisher": "crawlpilot",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.02,
        "capabilities": ["read_listings", "read_full_jd", "read_skills"],
        "supports_application": False,
    },
    "foundit": {
        "actor_id": "shahidirfan/Foundit-Jobs-Scraper",
        "publisher": "shahidirfan",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.001,
        "capabilities": ["read_listings", "read_locations", "read_descriptions"],
        "supports_application": False,
    },
    "indeed": {
        "actor_id": "misceres/indeed-scraper",
        "publisher": "misceres",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.006,
        "capabilities": ["read_listings", "read_salaries", "read_company_reviews"],
        "supports_application": False,
    },
    "glassdoor": {
        "actor_id": "memo23/apify-glassdoor-reviews-scraper",
        "publisher": "memo23",
        "pricing_model": "PAY_PER_EVENT",
        "price_per_item_usd": 0.004,
        "capabilities": ["read_listings", "read_employer_intel"],
        "supports_application": False,
    },
}


class ApifyJobAdapter(JobSourceAdapter):
    """Adapter for executing and normalizing Apify job-scraping Actors."""

    source_name = "apify"

    def __init__(
        self,
        api_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.api_token = api_token if api_token is not None else settings.APIFY_API_TOKEN
        self.monthly_limit_usd = settings.APIFY_MONTHLY_LIMIT_USD
        self._client = http_client

    def normalize_portal_record(self, portal: str, item: dict[str, Any]) -> NormalizedJob:
        """Transform raw actor dataset item into NormalizedJob conforming to the unified schema."""
        portal_clean = portal.lower().replace("-", "_")
        now = datetime.now(timezone.utc)

        # 1. Title
        title = (
            item.get("title")
            or item.get("jobTitle")
            or item.get("position")
            or item.get("role")
            or "Software Engineer"
        ).strip()

        # 2. Company
        company_name = (
            item.get("company")
            or item.get("companyName")
            or item.get("employer")
            or item.get("organization")
            or "Unknown Company"
        )
        if isinstance(company_name, dict):
            company_name = company_name.get("name") or "Unknown Company"

        # 3. URL
        url = (
            item.get("jobUrl")
            or item.get("url")
            or item.get("link")
            or item.get("job_url")
            or item.get("applyUrl")
            or f"https://{portal_clean}.com/job/{item.get('id', hash(title + company_name))}"
        )

        # 4. Location & Remote
        raw_location = item.get("location") or item.get("city") or item.get("jobLocation")
        if isinstance(raw_location, dict):
            raw_location = raw_location.get("name") or raw_location.get("city")
        location_str = str(raw_location) if raw_location else None

        is_remote = bool(
            item.get("isRemote")
            or item.get("remote")
            or (location_str and "remote" in location_str.lower())
            or ("remote" in title.lower())
        )

        # 5. Salary
        salary_raw = (
            item.get("salary")
            or item.get("salaryRange")
            or item.get("compensation")
            or item.get("pay")
        )
        if isinstance(salary_raw, dict):
            salary_raw = f"{salary_raw.get('min', '')} - {salary_raw.get('max', '')} {salary_raw.get('currency', '')}"

        # 6. Skills
        skills = item.get("skills") or item.get("skillsRequired") or item.get("tags") or []
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]

        # 7. Description
        desc = (
            item.get("description")
            or item.get("jobDescription")
            or item.get("jd")
            or item.get("summary")
        )

        # 8. Date posted
        date_posted = None
        raw_date = item.get("postedDate") or item.get("datePosted") or item.get("createdAt")
        if raw_date and isinstance(raw_date, str):
            try:
                date_posted = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except Exception:
                pass

        meta = ACTOR_CATALOG.get(portal_clean, {})
        actor_id = meta.get("actor_id", "apify-generic")

        return NormalizedJob(
            source_name=f"apify_{portal_clean}",
            source_job_id=str(item.get("id") or item.get("jobId") or item.get("slug") or ""),
            original_url=url,
            company_name=str(company_name).strip(),
            company_domain=item.get("domain") or item.get("companyDomain"),
            title=title,
            description=str(desc) if desc else None,
            location=location_str,
            is_remote=is_remote,
            remote_type="remote" if is_remote else "unspecified",
            employment_type=item.get("employmentType") or "full_time",
            experience_level=item.get("experience") or item.get("seniority"),
            salary_raw=str(salary_raw) if salary_raw else None,
            skills_required=skills if isinstance(skills, list) else [],
            application_url=item.get("applyUrl") or item.get("applicationUrl") or url,
            date_posted=date_posted,
            last_observed_date=now,
            retrieved_at=now,
            data_provenance={
                "adapter": "ApifyJobAdapter",
                "portal": portal_clean,
                "actor_id": actor_id,
                "pricing_model": meta.get("pricing_model"),
            },
            is_confirmed_current=False,  # Observed via scrape, not confirmed active until verified
        )

    async def fetch_jobs(
        self,
        portal: str = "naukri",
        search_query: str = "software engineer",
        location: str = "India",
        limit: int = 10,
        **kwargs: Any,
    ) -> list[NormalizedJob]:
        portal_clean = portal.lower().replace("-", "_")

        # STRICT SAFETY GUARD: LinkedIn
        if "linkedin" in portal_clean:
            raise PermissionError(
                "STRICT RESTRICTION: LinkedIn automated scraping and application submission is prohibited by Job Pulse Agent policy."
            )

        if portal_clean not in ACTOR_CATALOG:
            raise ValueError(f"Portal '{portal}' is not supported in Apify catalog. Supported: {list(ACTOR_CATALOG.keys())}")

        actor_meta = ACTOR_CATALOG[portal_clean]
        actor_id = actor_meta["actor_id"]

        # Cost check: Estimate expected cost
        expected_cost = actor_meta.get("price_per_item_usd", 0.005) * limit
        if expected_cost > self.monthly_limit_usd:
            raise ValueError(
                f"Projected run cost ${expected_cost:.4f} exceeds configured safety limit ${self.monthly_limit_usd:.2f}."
            )

        if not self.api_token:
            logger.warning(f"No Apify API token configured. Cannot run remote Actor '{actor_id}'.")
            return []

        # Run Actor via Apify HTTP API
        client = self._client or httpx.AsyncClient(timeout=60.0)
        close_client = self._client is None
        username, actor_name = actor_id.split("/")
        url = f"https://api.apify.com/v2/acts/{username}~{actor_name}/runs"

        actor_input = {
            "query": search_query,
            "keyword": search_query,
            "location": location,
            "maxItems": limit,
            "limit": limit,
        }

        try:
            resp = await client.post(
                url,
                json=actor_input,
                headers={"Authorization": f"Bearer {self.api_token}"},
                params={"waitForFinish": 60},
            )
            if resp.status_code not in (200, 201):
                logger.error(f"Apify Actor run returned HTTP {resp.status_code}: {resp.text}")
                return []

            run_data = resp.json().get("data", {})
            dataset_id = run_data.get("defaultDatasetId")
            if not dataset_id:
                return []

            # Retrieve items from dataset
            items_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            items_resp = await client.get(
                items_url,
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
            if items_resp.status_code != 200:
                return []

            raw_items = items_resp.json()
            return [self.normalize_portal_record(portal_clean, item) for item in raw_items]
        except Exception as e:
            logger.error(f"Error executing Apify Actor '{actor_id}': {e}")
            return []
        finally:
            if close_client:
                await client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        """Test connectivity and token validity against Apify API."""
        if not self.api_token:
            return {
                "status": "not_attempted",
                "source": self.source_name,
                "sample_count": 0,
                "message": "Apify API token not configured. Set APIFY_API_TOKEN in .env or provide via MCP.",
                "details": {
                    "catalog_size": len(ACTOR_CATALOG),
                    "supported_portals": list(ACTOR_CATALOG.keys()),
                },
            }

        client = self._client or httpx.AsyncClient(timeout=15.0)
        close_client = self._client is None
        try:
            resp = await client.get(
                "https://api.apify.com/v2/users/me",
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
            if resp.status_code == 200:
                user_info = resp.json().get("data", {})
                return {
                    "status": "passed",
                    "source": self.source_name,
                    "sample_count": len(ACTOR_CATALOG),
                    "message": f"Apify connection verified for user '{user_info.get('username')}'",
                    "details": {
                        "username": user_info.get("username"),
                        "plan": user_info.get("plan", {}).get("id"),
                        "supported_portals": list(ACTOR_CATALOG.keys()),
                    },
                }
            else:
                return {
                    "status": "failed",
                    "source": self.source_name,
                    "sample_count": 0,
                    "message": f"Apify auth failed with HTTP {resp.status_code}: {resp.text}",
                    "details": {},
                }
        except Exception as e:
            return {
                "status": "failed",
                "source": self.source_name,
                "sample_count": 0,
                "message": f"Apify connection test failed: {e}",
                "details": {},
            }
        finally:
            if close_client:
                await client.aclose()
