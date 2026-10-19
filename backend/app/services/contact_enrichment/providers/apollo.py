"""Apollo documented synchronous search/match; no personal reveal or waterfall.
Official references and access/credit qualifications: docs/contact-enrichment.md.
"""

from pydantic import ValidationError

from backend.app.services.contact_enrichment.base import ContactProvider, ProviderError
from backend.app.services.contact_enrichment.schemas import (
    Capabilities,
    PersonObservation,
    State,
)
from backend.app.services.contact_enrichment.verification import (
    business_email,
    domain,
    email_kind,
)


class ApolloProvider(ContactProvider):
    name = "apollo"
    base_url = "https://api.apollo.io/api/v1"
    auth_header = "x-api-key"
    capabilities = Capabilities(search_people=True)

    def normalize(self, person, request):
        if not isinstance(person, dict):
            raise ValueError("Invalid person")
        organization = person.get("organization") or {}
        actual_domain = domain(
            organization.get("primary_domain") or organization.get("website_url")
        )
        if not actual_domain or actual_domain != domain(request.company_domain):
            return None
        name = person.get("name")
        if not name and person.get("last_name") and person.get("first_name"):
            name = person["first_name"] + " " + person["last_name"]
        # Search can redact names. Never construct a full name from obfuscated fields.
        if not name:
            return None
        email = business_email(person.get("email"), request.company_domain)
        return PersonObservation(
            full_name=name,
            role_title=person.get("title"),
            company_domain=actual_domain,
            linkedin_url=person.get("linkedin_url"),
            email=email,
            source=self.name,
            provider_person_id=person.get("id"),
            email_status="provider_reported" if email else "unknown",
            email_kind=email_kind(email) if email else "person_specific",
            provider_verification_claim=person.get("email_status"),
            evidence_strength="moderate",
        )

    async def search_people(self, request):
        try:
            self.authorize(request)
            if not request.company_domain:
                return self.result(State.FAILED, errors=["Company domain required"])
            body = {
                "q_organization_domains_list": [request.company_domain],
                "person_titles": request.target_roles,
                "page": 1,
                "per_page": request.max_people,
            }
            data, _ = await self.request("POST", "/mixed_people/api_search", body)
            if not isinstance(data, dict) or not isinstance(data.get("people"), list):
                raise ValueError("Missing people")
            contacts = [
                item
                for p in data["people"][: request.max_people]
                if (item := self.normalize(p, request))
            ]
            unique = {
                (p.linkedin_url or p.provider_person_id or p.full_name): p
                for p in contacts
            }
            return self.result(
                State.COMPLETED if unique else State.NOT_FOUND,
                contacts=list(unique.values()),
                credits_used=0,
            )
        except ProviderError as exc:
            return self.error_result(exc)
        except (ValueError, TypeError, AttributeError, ValidationError):
            return self.result(
                State.FAILED, errors=["Malformed provider person response"]
            )

    async def enrich_person(self, request):
        try:
            self.authorize(request)
            if not request.company_domain or not (
                request.linkedin_url or request.provider_person_id or request.full_name
            ):
                return self.result(
                    State.FAILED,
                    errors=["Company domain and person identifier required"],
                )
            body = {
                "domain": request.company_domain,
                "reveal_personal_emails": False,
                "reveal_phone_number": False,
                "run_waterfall_email": False,
                "run_waterfall_phone": False,
            }
            for field, value in (
                ("name", request.full_name),
                ("linkedin_url", request.linkedin_url),
                ("id", request.provider_person_id),
            ):
                if value:
                    body[field] = value
            data, _ = await self.request("POST", "/people/match", body)
            if not isinstance(data, dict) or "person" not in data:
                raise ValueError("Missing person")
            person = self.normalize(data["person"], request) if data["person"] else None
            return self.result(
                State.COMPLETED if person else State.NOT_FOUND,
                contacts=[person] if person else [],
            )
        except ProviderError as exc:
            return self.error_result(exc)
        except (ValueError, TypeError, AttributeError, ValidationError):
            return self.result(
                State.FAILED, errors=["Malformed provider person response"]
            )

    async def test_connection(self):
        try:
            data, _ = await self.request("GET", "/auth/health")
            if not isinstance(data, dict) or not (
                data.get("is_logged_in") is True and data.get("healthy") is True
            ):
                return self.result(
                    State.AUTHORIZATION_REQUIRED,
                    errors=["Provider did not confirm authentication"],
                )
            return self.result(State.COMPLETED, credits_used=0)
        except ProviderError as exc:
            return self.error_result(exc)
