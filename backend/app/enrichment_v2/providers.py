"""Free-tier Tier 2 adapters: Apollo people search, an Apify contact-scraper actor and
SignalHire person lookup. Each one is optional (no key -> skipped), bounded (strict
timeout, 1 MB response cap, no redirects, no env proxies) and maps plan restrictions
to a cooldown instead of retrying. The caller reserves a daily credit before `lookup`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.app.enrichment_v2.extract import (
    EmailCandidate,
    extract_emails,
    provider_candidate,
    rank,
    tag_source,
)

MAX_RESPONSE_BYTES = 1_048_576
PLAN_RESTRICTED_COOLDOWN_SEC = 24 * 3600
AUTH_FAILED_COOLDOWN_SEC = 24 * 3600
ERROR_COOLDOWN_SEC = 10 * 60
RECRUITER_TITLES = ["recruiter", "technical recruiter", "talent acquisition", "talent partner",
                    "hr manager", "human resources", "people operations", "hiring manager",
                    "engineering manager"]
_ACTOR = re.compile(r"^[A-Za-z0-9_-]{1,100}[~/][A-Za-z0-9_-]{1,100}$")
_PLAN_WORDS = re.compile(r"plan|upgrade|not (?:accessible|available)|credits?|subscription|free tier|insufficient",
                         re.IGNORECASE)


@dataclass
class LookupContext:
    company_domain: str
    company_name: str | None = None
    role_title: str | None = None
    linkedin_urls: list[str] = field(default_factory=list)


@dataclass
class ProviderOutcome:
    provider: str
    status: str  # found | not_found | plan_restricted | rate_limited | auth_failed | error | timeout
    candidates: list[EmailCandidate] = field(default_factory=list)
    cooldown_sec: float | None = None
    error: str | None = None
    linkedin_urls: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"provider": self.provider, "outcome": self.status, "candidates": len(self.candidates),
                **({"cooldown_sec": round(self.cooldown_sec)} if self.cooldown_sec else {}),
                **({"error": self.error} if self.error else {})}


class ProviderHTTPError(Exception):
    def __init__(self, status: int, text: str = "", retry_after: float | None = None) -> None:
        super().__init__(f"http_{status}")
        self.status, self.text, self.retry_after = status, text[:300], retry_after


class EnrichmentProvider:
    name = "base"
    base_url = ""

    def __init__(self, key: str | None, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_sec: float = 20.0) -> None:
        self.key = key
        self.transport = transport
        self.timeout_sec = timeout_sec

    def __repr__(self) -> str:  # never print the key
        return f"<{type(self).__name__} configured={self.configured}>"

    @property
    def configured(self) -> bool:
        return bool(self.key)

    def can_lookup(self, context: LookupContext) -> bool:
        return bool(context.company_domain)

    def headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def request(self, method: str, url: str, body: Any = None, *, timeout: float | None = None) -> Any:
        async with httpx.AsyncClient(transport=self.transport, timeout=timeout or self.timeout_sec,
                                     follow_redirects=False, trust_env=False) as client, \
                client.stream(method, url, headers={"Accept": "application/json", **self.headers()},
                              json=body) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ProviderHTTPError(response.status_code, "response_too_large")
            text = bytes(data).decode("utf-8", errors="replace")
            if response.status_code >= 300:
                retry = response.headers.get("retry-after")
                try:
                    retry_after = float(retry) if retry else None
                except ValueError:
                    retry_after = None
                raise ProviderHTTPError(response.status_code, text, retry_after)
            return json.loads(text) if text.strip() else None

    def outcome_for_error(self, exc: Exception) -> ProviderOutcome:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderOutcome(self.name, "timeout", cooldown_sec=ERROR_COOLDOWN_SEC, error="timeout")
        if isinstance(exc, ProviderHTTPError):
            if exc.status in (402, 403) or (exc.status == 422 and _PLAN_WORDS.search(exc.text)):
                return ProviderOutcome(self.name, "plan_restricted", cooldown_sec=PLAN_RESTRICTED_COOLDOWN_SEC,
                                       error=f"http_{exc.status}_plan_restricted")
            if exc.status == 401:
                return ProviderOutcome(self.name, "auth_failed", cooldown_sec=AUTH_FAILED_COOLDOWN_SEC,
                                       error="http_401_auth")
            if exc.status == 429:
                return ProviderOutcome(self.name, "rate_limited",
                                       cooldown_sec=min(max(exc.retry_after or 3600, 60), 86400),
                                       error="http_429")
            if exc.status == 404:
                return ProviderOutcome(self.name, "not_found")
            return ProviderOutcome(self.name, "error", cooldown_sec=ERROR_COOLDOWN_SEC, error=f"http_{exc.status}")
        if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
            return ProviderOutcome(self.name, "error", cooldown_sec=ERROR_COOLDOWN_SEC, error="malformed_response")
        return ProviderOutcome(self.name, "error", cooldown_sec=ERROR_COOLDOWN_SEC,
                               error="network_" + type(exc).__name__)

    async def lookup(self, context: LookupContext) -> ProviderOutcome:
        try:
            return await self._lookup(context)
        except Exception as exc:  # noqa: BLE001 - every provider failure maps to a cooldown
            return self.outcome_for_error(exc)

    async def _lookup(self, context: LookupContext) -> ProviderOutcome:
        raise NotImplementedError


class ApolloProvider(EnrichmentProvider):
    """POST /mixed_people/api_search (people at the company domain with recruiting titles).
    Free plans often refuse this endpoint (403/422 "plan"): mapped to plan_restricted + 24 h cooldown."""
    name = "apollo"
    base_url = "https://api.apollo.io/api/v1"

    def headers(self) -> dict[str, str]:
        return {"x-api-key": self.key or "", "Cache-Control": "no-cache"}

    async def _lookup(self, context: LookupContext) -> ProviderOutcome:
        data = await self.request("POST", f"{self.base_url}/mixed_people/api_search", {
            "q_organization_domains_list": [context.company_domain], "person_titles": RECRUITER_TITLES,
            "page": 1, "per_page": 10})
        if not isinstance(data, dict) or not isinstance(data.get("people"), list):
            raise TypeError("missing people")
        candidates: list[EmailCandidate] = []
        linkedin: list[str] = []
        for person in data["people"][:10]:
            if not isinstance(person, dict):
                continue
            url = person.get("linkedin_url")
            if isinstance(url, str) and url.startswith("https://") and "linkedin.com/in/" in url:
                linkedin.append(url[:300])
            candidate = provider_candidate(person.get("email"), source=self.name,
                                           company_domain=context.company_domain, title=person.get("title"),
                                           first_name=person.get("first_name"))
            if candidate is not None:
                candidates.append(candidate)
        return ProviderOutcome(self.name, "found" if candidates else "not_found", rank(candidates),
                               linkedin_urls=linkedin[:5])


class ApifyProvider(EnrichmentProvider):
    """Runs one contact-scraper actor synchronously on the company homepage (strict timeout,
    bounded crawl). Only addresses on the company domain are kept."""
    name = "apify"
    base_url = "https://api.apify.com/v2"

    def __init__(self, key: str | None, *, actor: str, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_sec: float = 75.0) -> None:
        super().__init__(key, transport=transport, timeout_sec=timeout_sec)
        self.actor = actor

    @property
    def configured(self) -> bool:
        return bool(self.key) and bool(_ACTOR.match(self.actor or ""))

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key or ''}"}

    async def _lookup(self, context: LookupContext) -> ProviderOutcome:
        actor = self.actor.replace("/", "~")
        url = f"{self.base_url}/acts/{actor}/run-sync-get-dataset-items?timeout=60&memory=256&maxItems=20"
        items = await self.request("POST", url, {
            "startUrls": [{"url": f"https://{context.company_domain}/"}], "maxDepth": 1,
            "maxRequestsPerStartUrl": 6, "sameDomain": True, "considerChildFrames": False})
        if not isinstance(items, list):
            raise TypeError("dataset items expected")
        found: list[EmailCandidate] = []
        for item in items[:20]:
            emails = item.get("emails") if isinstance(item, dict) else None
            if isinstance(emails, list):
                text = " ".join(e for e in emails if isinstance(e, str))
                found.extend(extract_emails(text, source="careers_page", company_domain=context.company_domain))
        unique = {c.email: c for c in tag_source(found, self.name)}
        candidates = rank(unique.values())
        return ProviderOutcome(self.name, "found" if candidates else "not_found", candidates)


class SignalHireProvider(EnrichmentProvider):
    """Person API without waterfall for a LinkedIn profile already surfaced (e.g. by Apollo).
    No identifier -> not attempted (no credit spent). Asynchronous (callback) responses are
    never resubmitted: this system has no public webhook by design."""
    name = "signalhire"
    base_url = "https://www.signalhire.com/api/v1"

    def headers(self) -> dict[str, str]:
        return {"apikey": self.key or ""}

    def can_lookup(self, context: LookupContext) -> bool:
        return bool(context.company_domain and context.linkedin_urls)

    async def _lookup(self, context: LookupContext) -> ProviderOutcome:
        identifier = context.linkedin_urls[0]
        data = await self.request("POST", f"{self.base_url}/candidate/search",
                                  {"items": [identifier], "withoutWaterfall": True})
        if isinstance(data, dict) and data.get("requestId"):
            return ProviderOutcome(self.name, "not_found", error="async_callback_unsupported")
        if not isinstance(data, list):
            raise TypeError("synchronous results expected")
        candidates: list[EmailCandidate] = []
        for entry in data[:1]:
            if not isinstance(entry, dict) or entry.get("status") != "success":
                continue
            person = entry.get("candidate") or {}
            current = [e for e in person.get("experience", []) if isinstance(e, dict) and e.get("current")]
            title = current[0].get("position") if current else None
            first = (person.get("fullName") or "").split(" ")[0] or None
            for contact in person.get("contacts", []):
                if isinstance(contact, dict) and contact.get("type") == "email" and contact.get("subType") == "work":
                    candidate = provider_candidate(contact.get("value"), source=self.name,
                                                   company_domain=context.company_domain, title=title,
                                                   first_name=first)
                    if candidate is not None:
                        candidates.append(candidate)
        return ProviderOutcome(self.name, "found" if candidates else "not_found", rank(candidates))
