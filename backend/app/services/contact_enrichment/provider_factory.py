"""No implicit provider substitution or credential rotation."""

from backend.app.services.contact_enrichment.providers.apollo import ApolloProvider
from backend.app.services.contact_enrichment.providers.signalhire import (
    SignalHireProvider,
)

PROVIDERS = {"apollo": ApolloProvider, "signalhire": SignalHireProvider}


def get_provider(name, settings, client=None):
    if name not in PROVIDERS:
        raise ValueError("Unsupported contact provider")
    prefix = name.upper()
    return PROVIDERS[name](
        api_key=getattr(settings, prefix + "_API_KEY"),
        enabled=getattr(settings, prefix + "_ENRICHMENT_ENABLED"),
        client=client,
        timeout=settings.CONTACT_PROVIDER_TIMEOUT_SECONDS,
    )
