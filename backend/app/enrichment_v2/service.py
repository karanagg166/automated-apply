"""EnrichmentService: the cost-protected Tier 0 -> 1 -> 2 recruiter email waterfall."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backend.app.enrichment_v2.config import PROVIDERS, EnrichmentConfig
from backend.app.enrichment_v2.extract import (
    CAREERS_PATHS,
    EmailCandidate,
    PageFetcher,
    UnsafeTarget,
    company_cache_key,
    extract_emails,
    infer_company_domain,
    rank,
)
from backend.app.enrichment_v2.providers import (
    ApifyProvider,
    ApolloProvider,
    EnrichmentProvider,
    LookupContext,
    ProviderOutcome,
    SignalHireProvider,
)
from backend.app.enrichment_v2.store import EnrichmentStore, MemoryEnrichmentStore

logger = logging.getLogger(__name__)

FOUND_TTL = timedelta(days=30)
NOT_FOUND_TTL = timedelta(days=7)
# Some configured provider was skipped for a transient reason (cap/cooldown/error):
# retry the domain after tomorrow's credit reset instead of parking it for a week.
TRANSIENT_NOT_FOUND_TTL = timedelta(days=1)
FOUND, NO_EMAIL_FOUND = "FOUND", "NO_EMAIL_FOUND"


@dataclass
class EnrichmentResult:
    status: str  # FOUND | NO_EMAIL_FOUND
    email: str | None = None
    source: str | None = None
    company_domain: str | None = None
    cached: bool = False
    first_name: str | None = None
    candidates: list[EmailCandidate] = field(default_factory=list)
    credits_spent: dict[str, int] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.status == FOUND and bool(self.email)

    def public(self) -> dict[str, Any]:
        return {"status": self.status, "email": self.email, "source": self.source,
                "company_domain": self.company_domain, "cached": self.cached,
                "candidates": [c.public() for c in self.candidates[:5]],
                "credits_spent": dict(self.credits_spent), "attempts": list(self.attempts)}


def period_key(now: datetime, timezone: str = "Asia/Kolkata") -> str:
    return now.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d")


def build_providers(config: EnrichmentConfig, transport: httpx.AsyncBaseTransport | None = None
                    ) -> list[EnrichmentProvider]:
    """Waterfall order: Apollo (also surfaces LinkedIn ids) -> Apify -> SignalHire."""
    return [ApolloProvider(config.keys.get("apollo"), transport=transport),
            ApifyProvider(config.keys.get("apify"), actor=config.apify_actor, transport=transport),
            SignalHireProvider(config.keys.get("signalhire"), transport=transport)]


class EnrichmentService:
    def __init__(self, store: EnrichmentStore | None = None, *, config: EnrichmentConfig | None = None,
                 providers: Sequence[EnrichmentProvider] | None = None, fetcher: PageFetcher | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store or MemoryEnrichmentStore()
        self.config = config or EnrichmentConfig()
        self.providers = list(providers if providers is not None else build_providers(self.config))
        self.fetcher = fetcher if fetcher is not None else PageFetcher()
        self.clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    async def for_store(cls, store: Any, *, env: dict[str, str] | None = None,
                        transport: httpx.AsyncBaseTransport | None = None) -> EnrichmentService:
        from backend.app.enrichment_v2.store import enrichment_store_for

        config = EnrichmentConfig.from_env(env)
        return cls(await enrichment_store_for(store), config=config,
                   providers=build_providers(config, transport))

    def cap(self, provider: str) -> int:
        return self.config.caps.get(provider, 0)

    # --- the waterfall ----------------------------------------------------------------
    async def find_recruiter_email(self, company_name: str | None = None, company_domain: str | None = None,
                                   job_url: str | None = None, jd_text: str | None = None,
                                   role_title: str | None = None, *, allow_paid: bool = True,
                                   allow_fetch: bool = True) -> EnrichmentResult:
        now = self.clock()
        jd_raw = extract_emails(jd_text, source="jd_text")
        domain = infer_company_domain(company_domain, job_url, jd_text, jd_raw)
        key = company_cache_key(domain, company_name)
        result = EnrichmentResult(NO_EMAIL_FOUND, company_domain=domain)
        jd_candidates = extract_emails(jd_text, source="jd_text", company_domain=domain)

        # Tier 0: domain cache (0 credits, no network).
        negative_cached = False
        if key is not None:
            entry = await self.store.get_cache(key)
            if entry is not None and entry.valid(now):
                if entry.status == FOUND:
                    cached = rank(c for raw in entry.emails if (c := EmailCandidate.from_public(raw)))
                    if cached:
                        return self._found(result, cached, source=f"cache:{entry.source or 'unknown'}",
                                           cached=True)
                negative_cached = entry.status == NO_EMAIL_FOUND
                result.attempts.append({"tier": 0, "outcome": "negative_cache_hit" if negative_cached
                                        else "cache_entry_empty"})

        # Tier 1a: verbatim addresses in the JD (always free, even under a negative cache).
        if jd_candidates:
            return await self._store_found(result, key, jd_candidates, "jd_text", role_title)
        if negative_cached:
            result.cached = True
            return result

        # Tier 1b: the company's own public careers/contact pages (SSRF-guarded, bounded).
        if domain and allow_fetch and self.config.fetch_pages:
            page_candidates = await self._careers_pages(domain, result)
            if page_candidates:
                return await self._store_found(result, key, page_candidates, "careers_page", role_title)

        # Tier 2: free-tier APIs, each credit-capped and reserved before the call.
        transient = False
        if domain and allow_paid and not self.config.disabled:
            context = LookupContext(company_domain=domain, company_name=company_name, role_title=role_title)
            for provider in self.providers:
                outcome, skipped_transiently = await self._try_provider(provider, context, now, result)
                transient = transient or skipped_transiently
                if outcome is not None and outcome.linkedin_urls:
                    context.linkedin_urls.extend(u for u in outcome.linkedin_urls if u not in context.linkedin_urls)
                if outcome is not None and outcome.candidates:
                    return await self._store_found(result, key, outcome.candidates, provider.name, role_title)

        if key is not None:
            await self.store.put_cache(key, status=NO_EMAIL_FOUND, emails=[], source="waterfall_exhausted",
                                       expires_at=now + (TRANSIENT_NOT_FOUND_TTL if transient else NOT_FOUND_TTL),
                                       role_family=role_title)
        return result

    async def _careers_pages(self, domain: str, result: EnrichmentResult) -> list[EmailCandidate]:
        found: dict[str, EmailCandidate] = {}
        for path in CAREERS_PATHS:
            url = f"https://{domain}{path}"
            try:
                text = await self.fetcher.fetch(url)
            except UnsafeTarget as exc:
                result.attempts.append({"tier": 1, "page": path, "outcome": f"blocked:{exc}"})
                return []
            except (httpx.HTTPError, UnicodeError) as exc:
                result.attempts.append({"tier": 1, "page": path, "outcome": "fetch_" + type(exc).__name__})
                continue
            for candidate in extract_emails(text, source="careers_page", company_domain=domain):
                found.setdefault(candidate.email, candidate)
            result.attempts.append({"tier": 1, "page": path, "outcome": "ok" if text else "no_content"})
            if any(c.kind == "recruiting" for c in found.values()):
                break
        return rank(found.values())

    async def _try_provider(self, provider: EnrichmentProvider, context: LookupContext, now: datetime,
                            result: EnrichmentResult) -> tuple[ProviderOutcome | None, bool]:
        """(outcome, skipped_for_a_transient_reason)."""
        name = provider.name
        if not provider.configured:
            result.attempts.append({"tier": 2, "provider": name, "outcome": "unconfigured"})
            return None, False
        until = await self.store.cooldown_until(name)
        if until is not None and until > now:
            result.attempts.append({"tier": 2, "provider": name, "outcome": "cooldown",
                                    "until": until.isoformat()})
            return None, True
        if not provider.can_lookup(context):
            result.attempts.append({"tier": 2, "provider": name, "outcome": "needs_identifier"})
            return None, False
        period = period_key(now, self.config.timezone)
        if not await self.store.reserve_credit(name, period, self.cap(name)):
            result.attempts.append({"tier": 2, "provider": name, "outcome": "daily_cap_reached",
                                    "cap": self.cap(name)})
            return None, True
        result.credits_spent[name] = result.credits_spent.get(name, 0) + 1
        outcome = await provider.lookup(context)
        if outcome.cooldown_sec:
            await self.store.set_cooldown(name, period, self.cap(name),
                                          now + timedelta(seconds=outcome.cooldown_sec), outcome.error)
        result.attempts.append({"tier": 2, **outcome.public()})
        logger.info("enrichment provider=%s outcome=%s candidates=%d", name, outcome.status,
                    len(outcome.candidates))
        return outcome, outcome.status not in ("found", "not_found")

    async def _store_found(self, result: EnrichmentResult, key: str | None, candidates: list[EmailCandidate],
                           source: str, role_title: str | None) -> EnrichmentResult:
        ranked = rank(candidates)
        if key is not None:
            await self.store.put_cache(key, status=FOUND, emails=[c.public() for c in ranked[:5]], source=source,
                                       expires_at=self.clock() + FOUND_TTL, role_family=role_title)
        return self._found(result, ranked, source=source, cached=False)

    @staticmethod
    def _found(result: EnrichmentResult, ranked: list[EmailCandidate], *, source: str,
               cached: bool) -> EnrichmentResult:
        best = ranked[0]
        result.status, result.email, result.source = FOUND, best.email, source
        result.first_name, result.cached, result.candidates = best.first_name, cached, ranked
        return result

    # --- status -----------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        now = self.clock()
        period = period_key(now, self.config.timezone)
        providers = []
        for name in PROVIDERS:
            row = await self.store.credit(name, period)
            until = await self.store.cooldown_until(name)
            provider = next((p for p in self.providers if p.name == name), None)
            configured = bool(provider and provider.configured)
            cooling = bool(until and until > now)
            providers.append({
                "provider": name, "configured": configured, "daily_cap": self.cap(name),
                "used_today": row.used if row else 0, "period_key": period,
                "cooldown_until": until if cooling else None,
                "last_error": row.last_error if row else None,
                "state": "unconfigured" if not configured else "cooldown" if cooling
                else "cap_reached" if row and row.used >= self.cap(name) else "available",
                "key_env": self.config.public()["providers"][name]["key_env"]})
        return {"backend": self.store.backend, "disabled": self.config.disabled,
                "fetch_pages": self.config.fetch_pages, "providers": providers,
                "cached_domains": await self.store.cached_domains(now)}
