"""Capabilities are explicit; directory visibility does not grant bulk collection rights."""

from backend.app.core.config import get_settings
from backend.app.services.job_sources.registry import source_registry

PUBLIC_SOURCES = (
    "hacker_news",
    "greenhouse",
    "remotive",
    "arbeitnow",
    "lever",
    "ashby",
)
# Conservative deployment limits; Remotive recommends no more than four calls daily.
INTERVALS = {
    "apify_metadata": 10,
    "apollo_capability": 10,
    "remotive": 21600,
    "arbeitnow": 60,
    "greenhouse": 60,
    "hacker_news": 60,
    "lever": 60,
    "ashby": 60,
}


def startup_sources(settings=None):
    settings = settings or get_settings()
    jobs = source_registry(settings)
    output = [
        dict(
            provider=name,
            modes=["job_led"],
            availability=jobs[name].availability,
            pricing="free",
            configured=jobs[name].availability == "available",
            authorized=True,
            permission_basis="documented_public_read_api",
            minimum_interval_seconds=INTERVALS[name],
        )
        for name in PUBLIC_SOURCES
    ]
    for name in ("wellfound", "work_at_a_startup"):
        output.append(
            dict(
                provider=name,
                modes=["job_led"],
                availability=jobs[name].availability,
                configured=jobs[name].enabled,
                authorized=jobs[name].enabled,
                pricing="paid",
                permission_basis="operator_reviewed_actor_required",
            )
        )
    output.extend(
        [
            dict(
                provider="yc_directory",
                modes=[],
                availability="unsupported",
                configured=False,
                authorized=False,
                pricing="unknown",
                permission_basis="no_supported_directory_api_or_license_verified",
                manual_reference="https://www.ycombinator.com/companies",
            ),
            dict(
                provider="manual",
                modes=["company_first"],
                availability="manual_import_only",
                configured=True,
                authorized=False,
                pricing="free",
                permission_basis="per_import_rights_confirmation_and_evidence_required",
            ),
            dict(
                provider="public_search",
                modes=["professional_research"],
                availability="available"
                if settings.PEOPLE_SEARCH_ENABLED
                and settings.SERPER_API_KEY
                and settings.PUBLIC_SEARCH_RIGHTS_REVIEWED
                else "configuration_required",
                configured=bool(
                    settings.PEOPLE_SEARCH_ENABLED and settings.SERPER_API_KEY
                ),
                authorized=bool(
                    settings.PUBLIC_SEARCH_RIGHTS_REVIEWED
                    and settings.PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL
                ),
                pricing="paid",
                permission_basis="third_party_retention_rights_required",
            ),
        ]
    )
    return output
