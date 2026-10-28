"""Serper search-index API only. Never requests a LinkedIn or company page."""

import httpx

from backend.app.schemas.discovery import DiscoveryError
from backend.app.schemas.discovery import DiscoveryStatus as Status
from backend.app.services.people_discovery.base import PublicPerson

ROLE_PATTERNS = {
    "founder": ("founder", "co-founder"),
    "co-founder": ("co-founder", "cofounder"),
    "ceo": ("ceo", "chief executive officer"),
    "cto": ("cto", "chief technology officer"),
    "head of engineering": ("head of engineering",),
    "vp engineering": ("vp engineering", "vp of engineering"),
    "engineering manager": ("engineering manager",),
    "technical recruiter": ("technical recruiter",),
    "software engineer": ("software engineer",),
    "software developer": ("software developer",),
    "technical staff": ("software engineer", "software developer", "platform engineer"),
    "talent acquisition": ("talent acquisition",),
    "recruiter": ("recruiter", "recruiting"),
}


class PublicSearchAdapter:
    def __init__(self, api_key, http_client=None):
        self.api_key, self.client = api_key, http_client

    async def search(self, query):
        text = (
            f'site:linkedin.com/in/ "{query.company_name}" ('
            + " OR ".join(query.roles)
            + ")"
        )
        if query.company_domain:
            text += " " + query.company_domain
        if query.location:
            text += " " + query.location
        records = await self.results(text, query.limit)
        try:
            if not isinstance(records, list):
                raise ValueError("Invalid search results")
            people, errors = [], []
            for i, record in enumerate(records[: query.limit]):
                try:
                    title = record.get("title") or ""
                    evidence = title + " " + (record.get("snippet") or "")
                    folded = evidence.casefold()
                    import re

                    role = next(
                        (
                            role
                            for role in query.roles
                            if any(
                                re.search(r"\b" + re.escape(word) + r"\b", folded)
                                for word in ROLE_PATTERNS[role]
                            )
                        ),
                        None,
                    )
                    # A title is provider evidence, never independent identity verification.
                    name = re.split(r"\s+[|–—-]\s+", title)[0].strip()
                    if name == title or not name or len(name) > 100:
                        name = None
                    company_match = query.company_name.casefold() in folded
                    people.append(
                        PublicPerson(
                            name=name,
                            role=role,
                            linkedin_url=record["link"],
                            evidence_url=record["link"],
                            source="public_search",
                            evidence_text=f"Search-index candidate for {query.company_name}; reported role: {role or 'unknown'}; independent identity review required",
                            verification_status="source_reported"
                            if company_match and role
                            else "requires_review",
                        )
                    )
                except (ValueError, KeyError, TypeError, AttributeError):
                    errors.append(f"Search record {i}: invalid public profile evidence")
            return people, errors
        except DiscoveryError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DiscoveryError(
                Status.UPSTREAM_ERROR, "Public search response could not be processed"
            ) from None

    async def results(self, text, limit):
        """The single fixed-host public search client; never fetch result URLs."""
        client = self.client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        try:
            response = await client.post(
                "https://google.serper.dev/search",
                json={"q": text, "num": limit},
                headers={"X-API-KEY": self.api_key},
                timeout=15,
                follow_redirects=False,
            )
            if response.status_code == 429:
                raise DiscoveryError(Status.RATE_LIMITED, "Public search rate limited")
            if response.status_code in (401, 403):
                raise DiscoveryError(
                    Status.AUTH_REQUIRED, "Public search authorization required"
                )
            if response.status_code != 200:
                raise DiscoveryError(Status.UPSTREAM_ERROR, "Public search unavailable")
            payload = response.json()
            records = payload.get("organic", [])
            if not isinstance(records, list):
                raise DiscoveryError(
                    Status.UPSTREAM_ERROR, "Invalid search result collection"
                )
            return records[:limit]
        except DiscoveryError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise DiscoveryError(
                Status.UPSTREAM_ERROR, "Public search response could not be processed"
            ) from None
        finally:
            if self.client is None:
                await client.aclose()

    async def search_official(self, query):
        import re
        from urllib.parse import urlsplit

        from backend.app.models.discovery import now
        from backend.app.services.people_discovery.base import OfficialPersonEvidence

        records = await self.results(
            f'site:{query.company_domain} "{query.company_name}" ('
            + " OR ".join(query.roles)
            + ")",
            query.limit,
        )
        people = []
        for record in records:
            if not isinstance(record, dict):
                continue
            url = record.get("link", "")
            if urlsplit(url).hostname not in {
                query.company_domain,
                "www." + query.company_domain,
            }:
                continue
            title = record.get("title") or ""
            text = title + " " + (record.get("snippet") or "")
            role = next(
                (
                    r
                    for r in query.roles
                    if re.search(r"\b" + re.escape(r) + r"\b", text, re.I)
                ),
                None,
            )
            name = re.split(r"\s+[|–—-]\s+", title)[0].strip()
            if (
                not role
                or name == title
                or not 2 <= len(name.split()) <= 5
                or query.company_name.casefold() not in text.casefold()
            ):
                continue
            try:
                people.append(
                    OfficialPersonEvidence(
                        full_name=name,
                        role_title=role,
                        evidence_url=url,
                        permission_evidence_url="https://serper.dev/terms",
                        observed_at=now(),
                        human_confirmed=False,
                    )
                )
            except ValueError:
                continue
        return people, []
