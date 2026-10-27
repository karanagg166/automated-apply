"""Apollo account evidence: health, endpoint limits and credit balance are distinct.

Unknown schemas, unavailable stats or unreviewed free-account eligibility block
lookups. Only documented zero-credit introspection endpoints are used here.
"""

import json
from datetime import datetime, timedelta, timezone

from backend.app.services.contact_enrichment.base import ProviderError
from backend.app.services.contact_enrichment.schemas import State

ENDPOINTS = {
    "enrich_person": "api/v1/people/match",
    "search_people": "api/v1/mixed_people/api_search",
}


def number(value):
    if type(value) is not int or value < 0:
        raise ValueError("Nonnegative integral allowance required")
    return value


def endpoint_limits(payload, endpoint):
    if not isinstance(payload, dict):
        raise ValueError("Unknown endpoint stats schema")
    matches = []
    for key, value in payload.items():
        if key == endpoint:
            matches.append(value)
            continue
        try:
            components = json.loads(key)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(components, list)
            and all(isinstance(v, str) for v in components)
            and "/".join(components) == endpoint
        ):
            matches.append(value)
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError("Endpoint access not reported")
    result = {}
    for period in ("minute", "hour", "day"):
        row = matches[0].get(period)
        if not isinstance(row, dict):
            raise ValueError("Incomplete endpoint rate limits")
        limit, consumed, left = (
            number(row.get(k)) for k in ("limit", "consumed", "left_over")
        )
        if consumed > limit or left > limit or left > limit - consumed:
            raise ValueError("Inconsistent endpoint allowance")
        result[period] = {"limit": limit, "consumed": consumed, "remaining": left}
    return result


def credit_balance(payload, pool):
    # Pool identity must be reviewed for this account; never sum unrelated credit types.
    if not isinstance(payload, dict) or not pool:
        raise ValueError("Credit pool review required")
    row = payload.get(pool)
    if not isinstance(row, dict):
        raise ValueError("Unknown credit balance schema")
    limit, consumed, left = (
        number(row.get(k)) for k in ("limit", "consumed", "left_over")
    )
    if consumed > limit or left > limit - consumed:
        raise ValueError("Inconsistent credit allowance")
    return {"pool": pool, "limit": limit, "consumed": consumed, "remaining": left}


async def inspect(provider, operation, pool):
    endpoint = ENDPOINTS[operation]
    health, _ = await provider.request("GET", "/auth/health")
    if (
        not isinstance(health, dict)
        or health.get("healthy") is not True
        or health.get("is_logged_in") is not True
    ):
        raise ProviderError(
            State.AUTHORIZATION_REQUIRED, "Apollo authentication not confirmed"
        )
    stats, _ = await provider.request(
        "POST", "/usage_stats/api_usage_stats", {"endpoints": [endpoint]}
    )
    credits, _ = await provider.request("POST", "/usage_stats/credit_usage_stats", {})
    try:
        rates = endpoint_limits(stats, endpoint)
        balance = credit_balance(credits, pool)
    except ValueError:
        raise ProviderError(
            State.AUTHORIZATION_REQUIRED,
            "Apollo endpoint or credit evidence unavailable; no lookup dispatched",
        ) from None
    return {
        "provider": "apollo",
        "operation": operation,
        "endpoint": endpoint,
        "authenticated": True,
        "rate_limits": rates,
        "credits": balance,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "eligibility_verified": False,
        "lookup_authorized": False,
        "source": "official_api",
        "paid_upgrade_authorized": False,
    }


def eligibility(settings, operation):
    reviewed = settings.APOLLO_ELIGIBILITY_REVIEWED_AT
    if reviewed:
        reviewed = (
            reviewed.replace(tzinfo=timezone.utc)
            if reviewed.tzinfo is None
            else reviewed.astimezone(timezone.utc)
        )
    if not (
        settings.APOLLO_FREE_ACCOUNT_CONFIRMED
        and settings.APOLLO_WORK_EMAIL_CONFIRMED
        and ENDPOINTS[operation] in settings.APOLLO_REVIEWED_ENDPOINTS
        and settings.APOLLO_ELIGIBILITY_EVIDENCE_URL
        and reviewed
        and datetime.now(timezone.utc) - timedelta(hours=24)
        <= reviewed
        <= datetime.now(timezone.utc)
    ):
        raise ProviderError(
            State.AUTHORIZATION_REQUIRED,
            "Apollo free-account eligibility, work email and endpoint review required",
        )


async def preflight(provider, settings, operation, maximum_cost):
    eligibility(settings, operation)
    result = await inspect(provider, operation, settings.APOLLO_CREDIT_POOL)
    if any(row["remaining"] < 1 for row in result["rate_limits"].values()):
        raise ProviderError(State.RATE_LIMITED, "Apollo endpoint allowance exhausted")
    if result["credits"]["remaining"] < maximum_cost:
        raise ProviderError(State.BUDGET_EXHAUSTED, "Apollo credit allowance exhausted")
    result.update(eligibility_verified=True, lookup_authorized=True)
    return result
