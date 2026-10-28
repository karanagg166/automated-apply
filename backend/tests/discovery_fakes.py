from datetime import datetime, timedelta, timezone

from backend.app.core.config import Settings
from backend.app.schemas.normalized_job import NormalizedJob


def job(**updates):
    return NormalizedJob.model_validate(
        {
            "source_name": "naukri",
            "source_job_id": "one",
            "original_url": "https://www.naukri.com/jobs/1",
            "title": "Python Engineer",
            "company_name": "Example",
            "company_domain": "example.com",
            "location": "Bengaluru",
            "remote_type": "remote",
            "description": "Build APIs with Python. " * 15,
            "skills_required": ["Python", "Go"],
            **updates,
        }
    )


def actor_config(**updates):
    return {
        "actor_id": "fictional/fixture-actor",
        "build": "0.1.2",
        "enabled": True,
        "reviewed": True,
        "review_expires_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
        "platform_usage_included": True,
        "account_spending_limit_verified": True,
        "schema_evidence_url": "https://example.com/input",
        "pricing_evidence_url": "https://example.com/pricing",
        "permission_evidence_url": "https://example.com/permissions",
        "pricing_model": "PAY_PER_EVENT",
        "estimated_per_item_usd": 0.001,
        "field_map": {
            "query": "searchTerms",
            "locations": "cities",
            "limit": "maximum",
        },
        **updates,
    }


def settings(**updates):
    return Settings(
        _env_file=None,
        APIFY_API_TOKEN="fictional-token",
        APIFY_MONTHLY_LIMIT_USD=2,
        APIFY_PER_RUN_CAP_USD=0.1,
        **updates,
    )


class FakeBudget:
    def __init__(self):
        self.calls, self.finished, self.cooled = [], [], []

    async def reserve(self, *args):
        self.calls.append(args)

    async def attach_run(self, *args):
        pass

    async def finish(self, *args):
        self.finished.append(args)

    async def cooldown(self, *args):
        self.cooled.append(args)
