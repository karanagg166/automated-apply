"""Fictional data only; HTTP access is blocked globally in conftest."""

from backend.app.core.config import Settings
from backend.app.services.contact_enrichment.providers.apollo import ApolloProvider
from backend.app.services.contact_enrichment.providers.signalhire import (
    SignalHireProvider,
)
from backend.app.services.contact_enrichment.schemas import (
    PersonObservation,
    State,
)

URL = "https://www.linkedin.com/in/alex-fictional/"


def settings(**kwargs):
    values = dict(
        _env_file=None,
        APOLLO_API_KEY="fictional-apollo-key",
        SIGNALHIRE_API_KEY="fictional-signalhire-key",
        APOLLO_ENRICHMENT_ENABLED=True,
        SIGNALHIRE_ENRICHMENT_ENABLED=True,
        APOLLO_CREDITS_PER_LOOKUP=1,
        SIGNALHIRE_CREDITS_PER_LOOKUP=1,
    )
    return Settings(**{**values, **kwargs})


def person(**kwargs):
    return PersonObservation(
        **{
            **dict(
                full_name="Alex Fictional",
                role_title="CTO",
                company_domain="fictional.example.com",
                linkedin_url=URL,
                email="alex@fictional.example.com",
                email_status="provider_reported",
                source="apollo",
            ),
            **kwargs,
        }
    )


def apollo_response(**kwargs):
    return {
        "person": {
            **dict(
                id="fictional-id",
                name="Alex Fictional",
                title="CTO",
                linkedin_url=URL,
                email="alex@fictional.example.com",
                email_status="verified",
                organization={"primary_domain": "fictional.example.com"},
            ),
            **kwargs,
        }
    }


def signal_response(**kwargs):
    return [
        {
            "item": URL,
            "status": "success",
            "candidate": {
                **dict(
                    uid="a" * 32,
                    fullName="Alex Fictional",
                    social=[{"type": "li", "link": URL}],
                    experience=[
                        {
                            "current": True,
                            "website": "https://fictional.example.com",
                            "position": "CTO",
                        }
                    ],
                    contacts=[
                        {
                            "type": "email",
                            "subType": "work",
                            "value": "alex@fictional.example.com",
                            "rating": 100,
                        },
                        {
                            "type": "email",
                            "subType": "personal",
                            "value": "private@gmail.com",
                        },
                        {"type": "phone", "value": "+1999999999"},
                    ],
                ),
                **kwargs,
            },
        }
    ]


class FakeApollo(ApolloProvider):
    def __init__(self, result=None):
        super().__init__("fictional-key", True)
        self.calls = []
        self.response = result or self.result(State.COMPLETED, contacts=[person()])

    async def enrich_person(self, request):
        self.calls.append(request)
        return self.response

    async def search_people(self, request):
        self.calls.append(request)
        return self.response


class FakeSignal(SignalHireProvider):
    def __init__(self, result=None):
        super().__init__("fictional-key", True)
        self.calls = []
        self.response = result or self.result(
            State.COMPLETED, contacts=[person(source="signalhire")]
        )

    async def enrich_person(self, request):
        self.calls.append(request)
        return self.response
