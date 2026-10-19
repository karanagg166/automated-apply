"""Serper search-index API only. Never requests a LinkedIn or company page."""

import httpx
from backend.app.services.people_discovery.base import PublicPerson
from backend.app.schemas.discovery import DiscoveryError, DiscoveryStatus as Status

ROLE_PATTERNS = {
    "founder": ("founder", "co-founder"),
    "co-founder": ("co-founder", "cofounder"),
    "ceo": ("ceo", "chief executive officer"),
    "cto": ("cto", "chief technology officer"),
    "head of engineering": ("head of engineering",),
    "engineering manager": ("engineering manager",),
    "technical recruiter": ("technical recruiter",),
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
        client = self.client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        try:
            response = await client.post(
                "https://google.serper.dev/search",
                json={"q": text, "num": query.limit},
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
            records = response.json()["organic"]
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
                            evidence_text=evidence[:4000],
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
        finally:
            if self.client is None:
                await client.aclose()
