"""SignalHire Person API withoutWaterfall mode; no callbacks or personal fields stored."""

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


class SignalHireProvider(ContactProvider):
    name = "signalhire"
    base_url = "https://www.signalhire.com/api/v1"
    auth_header = "apikey"
    capabilities = Capabilities(get_usage=True)

    async def enrich_person(self, request):
        try:
            self.authorize(request)
            identifier = request.linkedin_url or request.provider_person_id
            if not identifier or not request.company_domain:
                return self.result(
                    State.UNSUPPORTED,
                    errors=["LinkedIn URL or provider UID and company domain required"],
                )
            data, status = await self.request(
                "POST",
                "/candidate/search",
                {"items": [identifier], "withoutWaterfall": True},
            )
            if status == 204:
                return self.result(State.RUNNING)
            if status == 201 and isinstance(data, dict) and data.get("requestId"):
                return self.result(
                    State.QUEUED,
                    provider_run_id=str(data["requestId"])[:255],
                    errors=[
                        "Unexpected asynchronous response; callback retrieval is unavailable; do not resubmit"
                    ],
                )
            if not isinstance(data, list) or len(data) > 1:
                raise ValueError("Invalid synchronous results")
            if not data:
                return self.result(State.NOT_FOUND)
            entry = data[0]
            if entry.get("item") != identifier:
                raise ValueError("Response identifier mismatch")
            state = entry.get("status")
            if state != "success":
                return self.result(
                    {
                        "failed": State.NOT_FOUND,
                        "credits_are_over": State.BUDGET_EXHAUSTED,
                        "duplicate_query": State.RUNNING,
                    }.get(state, State.FAILED)
                )
            candidate = entry["candidate"]
            current = [
                e
                for e in candidate.get("experience", [])
                if e.get("current") is True
                and domain(e.get("website")) == domain(request.company_domain)
            ]
            if not current:
                return self.result(
                    State.NOT_FOUND,
                    errors=["Current company association not established"],
                )
            linkedin = next(
                (
                    s.get("link")
                    for s in candidate.get("social", [])
                    if s.get("type") == "li"
                ),
                None,
            )
            emails = [
                c
                for c in candidate.get("contacts", [])
                if c.get("type") == "email"
                and c.get("subType") == "work"
                and business_email(c.get("value"), request.company_domain)
            ]
            email = (
                business_email(emails[0]["value"], request.company_domain)
                if emails
                else None
            )
            person = PersonObservation(
                full_name=candidate["fullName"],
                role_title=current[0].get("position"),
                company_domain=request.company_domain,
                linkedin_url=linkedin,
                email=email,
                source=self.name,
                provider_person_id=candidate.get("uid"),
                email_status="provider_reported" if email else "unknown",
                email_kind=email_kind(email) if email else "person_specific",
                provider_verification_claim=("rating:" + str(emails[0].get("rating")))
                if emails
                else None,
            )
            return self.result(State.COMPLETED, contacts=[person])
        except ProviderError as exc:
            return self.error_result(exc)
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError):
            return self.result(
                State.FAILED, errors=["Malformed provider person response"]
            )

    async def get_usage(self):
        try:
            data, _ = await self.request("GET", "/credits")
            if (
                not isinstance(data, dict)
                or type(data.get("credits")) is not int
                or data["credits"] < 0
            ):
                raise ValueError("Invalid credits")
            return self.result(
                State.COMPLETED, credits_remaining=data["credits"], credits_used=0
            )
        except ProviderError as exc:
            return self.error_result(exc)
        except (ValueError, TypeError):
            return self.result(
                State.FAILED, errors=["Malformed provider credit response"]
            )

    async def test_connection(self):
        return await self.get_usage()
