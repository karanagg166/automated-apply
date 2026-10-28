"""Typed official Apify API metadata, with one credential/account identity.

Metadata inspection is separate from the existing reviewed, capped job runner.
No cookie/session inputs, implicit MCP credential reuse or account rotation.
"""

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.discovery import DiscoveryError, DiscoveryStatus

ACTOR_ID = re.compile(r"^[A-Za-z0-9_-]+(?:[~/][A-Za-z0-9_-]+)?$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
INVESTIGATED_ACTORS = (
    "harvestapi/linkedin-company-search",
    "harvestapi/linkedin-company",
    "harvestapi/linkedin-company-employees",
)
DENIED_INPUT = re.compile(
    r"cookie|password|session|chrome.?profile|li_at|csrf|access.?token|linkedin", re.I
)


class ActorMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str
    title: str | None = None
    observed_at: datetime
    pricing: list[dict[str, Any]] = Field(default_factory=list)
    input_schema: dict[str, Any] | None = None
    schema_digest: str | None = None
    collection_status: Literal["disabled_pending_review"] = "disabled_pending_review"
    source_url: str


class ApifyTransport(Protocol):
    async def actor(self, actor_id: str) -> ActorMetadata: ...
    async def account_limits(self) -> dict: ...
    async def run_status(self, run_id: str) -> dict: ...
    async def dataset(
        self, dataset_id: str, *, offset: int = 0, limit: int = 25
    ) -> list[dict]: ...


def safe_actor(actor_id):
    if (
        not isinstance(actor_id, str)
        or not ACTOR_ID.fullmatch(actor_id)
        or len(actor_id) > 200
    ):
        raise DiscoveryError(
            DiscoveryStatus.CONFIGURATION_REQUIRED, "apify_actor_id_invalid"
        )
    return actor_id.replace("/", "~")


def execution_input_allowed(actor_id, payload):
    safe_actor(actor_id)
    if DENIED_INPUT.search(actor_id) or DENIED_INPUT.search(
        json.dumps(payload, sort_keys=True)
    ):
        raise DiscoveryError(
            DiscoveryStatus.AUTH_REQUIRED, "apify_collection_method_not_authorized"
        )


def input_schema(document):
    # OpenAPI $refs stay local; never fetch remote schema references or execute defaults.
    if not isinstance(document, dict):
        return None
    candidates = []
    for path in document.get("paths", {}).values():
        if not isinstance(path, dict):
            continue
        operation = path.get("post", {})
        schema = (
            operation.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if isinstance(schema, dict) and schema not in candidates:
            candidates.append(schema)
    if len(candidates) != 1:
        return None
    schema = candidates[0]
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
            return None
        schema = (
            document.get("components", {})
            .get("schemas", {})
            .get(ref.rsplit("/", 1)[-1])
        )
    return schema if isinstance(schema, dict) else None


class OfficialApifyAPI:
    def __init__(
        self, token=None, client=None, *, allowed_runs=(), allowed_datasets=()
    ):
        self.token = (
            token.get_secret_value() if hasattr(token, "get_secret_value") else token
        )
        self.client = client
        from backend.app.integrations.logging import install_provider_log_filter

        install_provider_log_filter()
        self.allowed_runs, self.allowed_datasets = (
            set(allowed_runs),
            set(allowed_datasets),
        )

    async def get(self, path, params=None, *, authenticated=False):
        if authenticated and not self.token:
            raise DiscoveryError(
                DiscoveryStatus.MISSING_CREDENTIALS, "apify_local_token_not_configured"
            )

        async def request(client):
            async with asyncio.timeout(20):
                async with client.stream(
                    "GET",
                    "https://api.apify.com/v2/" + path,
                    params=params,
                    headers={"Authorization": "Bearer " + self.token}
                    if authenticated
                    else {},
                    timeout=15,
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        state = {
                            401: DiscoveryStatus.AUTH_REQUIRED,
                            403: DiscoveryStatus.AUTH_REQUIRED,
                            429: DiscoveryStatus.RATE_LIMITED,
                        }.get(response.status_code, DiscoveryStatus.UPSTREAM_ERROR)
                        raise DiscoveryError(
                            state, "apify_metadata_http_" + str(response.status_code)
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1048576:
                            raise DiscoveryError(
                                DiscoveryStatus.UPSTREAM_ERROR,
                                "apify_response_byte_cap",
                            )
                    return json.loads(body)

        try:
            if self.client:
                return await request(self.client)
            async with httpx.AsyncClient(trust_env=False) as client:
                return await request(client)
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR,
                "apify_metadata_transport_or_schema_error",
            ) from None

    async def actor(self, actor_id):
        actor = safe_actor(actor_id)
        payload = await self.get("actors/" + actor)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR, "apify_actor_metadata_invalid"
            )
        document = await self.get(f"actors/{actor}/builds/default/openapi.json")
        schema = input_schema(document)
        pricing = data.get("pricingInfos", [])
        if not isinstance(pricing, list) or not all(
            isinstance(p, dict) for p in pricing
        ):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR, "apify_pricing_metadata_invalid"
            )
        return ActorMetadata(
            actor_id=actor_id,
            title=data.get("title"),
            observed_at=datetime.now(timezone.utc),
            pricing=pricing,
            input_schema=schema,
            schema_digest=hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()
            if schema
            else None,
            source_url="https://api.apify.com/v2/actors/" + actor,
        )

    async def discover_actors(self, query, limit=10):
        if (
            not isinstance(query, str)
            or not 1 <= len(query) <= 100
            or not 1 <= limit <= 20
        ):
            raise ValueError("Bounded actor discovery required")
        payload = await self.get("store", {"search": query, "limit": limit})
        items = (
            payload.get("data", {}).get("items") if isinstance(payload, dict) else None
        )
        if not isinstance(items, list):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR, "apify_store_schema_invalid"
            )
        # Metadata only. Search ranking is not collection authorization.
        return [
            {
                k: item.get(k)
                for k in ("id", "name", "username", "title", "pricingInfos")
            }
            for item in items[:limit]
            if isinstance(item, dict)
        ]

    async def account_limits(self):
        # Raw payloads may contain personal account data; expose only limits and accounting.
        limits = await self.get("users/me/limits", authenticated=True)
        usage = await self.get("users/me/usage/monthly", authenticated=True)
        if not all(
            isinstance(p, dict) and isinstance(p.get("data"), dict)
            for p in (limits, usage)
        ):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR, "apify_account_metadata_invalid"
            )
        return {
            "provider": "apify",
            "transport": "official_api",
            "authenticated": True,
            "limits": limits["data"],
            "usage": usage["data"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "execution_authorized": False,
        }

    async def run_status(self, run_id):
        if not IDENTIFIER.fullmatch(run_id) or run_id not in self.allowed_runs:
            raise DiscoveryError(
                DiscoveryStatus.AUTH_REQUIRED, "apify_run_not_authorized"
            )
        payload = await self.get("actor-runs/" + run_id, authenticated=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR, "apify_run_schema_invalid"
            )
        return {
            k: payload["data"].get(k)
            for k in ("id", "actId", "status", "defaultDatasetId", "usageTotalUsd")
        }

    async def dataset(self, dataset_id, *, offset=0, limit=25):
        if (
            not IDENTIFIER.fullmatch(dataset_id)
            or dataset_id not in self.allowed_datasets
        ):
            raise DiscoveryError(
                DiscoveryStatus.AUTH_REQUIRED, "apify_dataset_not_authorized"
            )
        if not 0 <= offset <= 10000 or not 1 <= limit <= 100:
            raise ValueError("Bounded dataset page required")
        items = await self.get(
            f"datasets/{dataset_id}/items",
            {"offset": offset, "limit": limit, "format": "json"},
            authenticated=True,
        )
        if (
            not isinstance(items, list)
            or not all(isinstance(p, dict) for p in items)
            or len(items) > limit
        ):
            raise DiscoveryError(
                DiscoveryStatus.UPSTREAM_ERROR, "apify_dataset_schema_invalid"
            )
        return items


class ApifyRoutePool:
    """Ordered reviewed routes, one account/budget. No failover after dispatch."""

    def __init__(self, routes):
        if not routes:
            self.routes = []
            return
        first = routes[0]
        if any(
            route.api_token != first.api_token
            or route.budget is not first.budget
            or route.source_name != first.source_name
            or route.monthly_limit_usd != first.monthly_limit_usd
            for route in routes
        ):
            raise ValueError(
                "Apify routes must share one credential, budget and source"
            )
        self.routes = routes
        self.source_name = first.source_name

    def validate_configuration(self):
        return (
            []
            if any(not route.validate_configuration() for route in self.routes)
            else ["No reviewed Apify route"]
        )

    async def test_connection(self):
        return {
            "status": "not_attempted",
            "source": getattr(self, "source_name", "apify"),
            "sample_count": 0,
            "details": {"live_verified": False, "route_count": len(self.routes)},
        }

    async def discover(self, query, *, allow_paid=False, reservation_id=None):
        from backend.app.schemas.discovery import DiscoveryResult

        # Failover is allowed only for locally rejected routes that made zero calls.
        for adapter in self.routes:
            if adapter.validate_configuration():
                continue
            return await adapter.discover(
                query, allow_paid=allow_paid, reservation_id=reservation_id
            )
        return DiscoveryResult(
            source=getattr(self, "source_name", "apify"),
            status=DiscoveryStatus.CONFIGURATION_REQUIRED,
            errors=["No reviewed route with verified account/cost limits"],
        )
