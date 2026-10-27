"""Async bounded HTTP, explicit capabilities and sanitized provider outcomes."""

import json
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from backend.app.services.contact_enrichment.schemas import (
    Capabilities,
    ContactEnrichmentRequest,
    ContactEnrichmentResult,
    State,
)


class ProviderError(Exception):
    def __init__(self, state, message, retry_after=None):
        self.state, self.message, self.retry_after = state, message, retry_after
        super().__init__(message)


class ContactProvider(ABC):
    name: str
    base_url: str
    auth_header: str
    capabilities = Capabilities()

    def __init__(self, api_key=None, enabled=False, client=None, timeout=20):
        self.api_key = (
            api_key.get_secret_value()
            if hasattr(api_key, "get_secret_value")
            else api_key
        )
        self.enabled, self.client, self.timeout = enabled, client, timeout
        from backend.app.integrations.logging import install_provider_log_filter
        install_provider_log_filter()

    def validate_configuration(self):
        return (
            State.COMPLETED
            if self.enabled and self.api_key and self.api_key.strip()
            else State.NOT_CONFIGURED
        )

    def get_capabilities(self):
        return self.capabilities

    def result(self, status, **values):
        return ContactEnrichmentResult(status=status, provider=self.name, **values)

    def error_result(self, error):
        return self.result(
            error.state, errors=[error.message], retry_after_seconds=error.retry_after
        )

    def authorize(self, request):
        if self.validate_configuration() != State.COMPLETED:
            raise ProviderError(
                State.NOT_CONFIGURED, "Provider disabled or credentials missing"
            )
        if not request.allow_paid:
            raise ProviderError(
                State.AUTHORIZATION_REQUIRED,
                "Explicit provider lookup authorization required",
            )

    @asynccontextmanager
    async def http(self):
        if self.client is not None:
            yield self.client
        else:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False
            ) as client:
                yield client

    async def request(self, method, path, body=None):
        if self.validate_configuration() != State.COMPLETED:
            raise ProviderError(
                State.NOT_CONFIGURED, "Provider disabled or credentials missing"
            )
        try:
            async with self.http() as client:
                async with client.stream(
                    method,
                    self.base_url + path,
                    headers={
                        self.auth_header: self.api_key,
                        "Accept": "application/json",
                    },
                    json=body,
                    timeout=self.timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code >= 300:
                        status = response.status_code
                        state = {
                            401: State.AUTHORIZATION_REQUIRED,
                            403: State.AUTHORIZATION_REQUIRED,
                            402: State.BUDGET_EXHAUSTED,
                            404: State.NOT_FOUND,
                            429: State.RATE_LIMITED,
                        }.get(status, State.FAILED)
                        retry = 60
                        raw = response.headers.get("Retry-After", "60")
                        try:
                            retry = int(raw)
                        except ValueError:
                            try:
                                retry = int(
                                    (
                                        parsedate_to_datetime(raw)
                                        - datetime.now(timezone.utc)
                                    ).total_seconds()
                                )
                            except (TypeError, ValueError, OverflowError):
                                pass
                        raise ProviderError(
                            state,
                            f"Provider HTTP {status}",
                            min(max(retry, 1), 86400) if status == 429 else None,
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 1048576:
                            raise ProviderError(
                                State.FAILED, "Provider response exceeds size limit"
                            )
                    return (json.loads(data) if data else None), response.status_code
        except (httpx.TimeoutException, httpx.TransportError):
            raise ProviderError(
                State.UNCERTAIN if method == "POST" else State.FAILED,
                "Provider transport interrupted; do not retry a billable request",
            ) from None
        except (ValueError, TypeError):
            raise ProviderError(State.FAILED, "Malformed provider response") from None

    async def search_people(self, request: ContactEnrichmentRequest):
        return self.result(
            State.UNSUPPORTED,
            errors=["Person search is not implemented by this adapter"],
        )

    @abstractmethod
    async def enrich_person(
        self, request: ContactEnrichmentRequest
    ) -> ContactEnrichmentResult: ...

    async def get_usage(self):
        return self.result(
            State.UNSUPPORTED,
            errors=["Provider credit balance unavailable through this adapter"],
        )

    @abstractmethod
    async def test_connection(self) -> ContactEnrichmentResult: ...
