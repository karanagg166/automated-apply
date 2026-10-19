"""Exactly one HTTP invocation; Gmail has no messages.send idempotency key."""

import asyncio

import httpx
from pydantic import ValidationError

from backend.app.integrations.gmail.schemas import GmailAcceptance, SendFailure

ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailSendClient:
    def __init__(self, client=None, timeout=20):
        self.client, self.timeout = client, timeout

    async def send(self, token, raw):
        try:
            async with asyncio.timeout(self.timeout):
                if self.client:
                    response = await self.client.post(
                        ENDPOINT,
                        headers={"Authorization": "Bearer " + token},
                        json={"raw": raw},
                        follow_redirects=False,
                    )
                else:
                    async with httpx.AsyncClient(
                        timeout=self.timeout, follow_redirects=False
                    ) as client:
                        response = await client.post(
                            ENDPOINT,
                            headers={"Authorization": "Bearer " + token},
                            json={"raw": raw},
                        )
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout):
            raise SendFailure(
                "connection_failed_before_send", uncertain=False
            ) from None
        except (httpx.HTTPError, TimeoutError, asyncio.CancelledError):
            # Write/read timeouts, cancellations and lost connections may follow transmission.
            raise SendFailure("transmission_outcome_unknown", uncertain=True) from None
        code = response.status_code
        if 200 <= code < 300:
            try:
                return GmailAcceptance.model_validate(response.json())
            except (ValidationError, ValueError):
                raise SendFailure("invalid_gmail_response", uncertain=True) from None
        if code in {400, 401, 403, 404, 429}:
            category = {
                400: "malformed_request",
                401: "credential_rejected",
                403: "scope_or_policy_denied",
                404: "gmail_resource_missing",
                429: "gmail_quota_exceeded",
            }[code]
            raise SendFailure(category, uncertain=False)
        raise SendFailure("gmail_server_or_unexpected_response", uncertain=True)
