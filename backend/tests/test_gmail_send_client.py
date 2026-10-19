"""One call to the documented Gmail endpoint; no retries, body/header logs or delivery claims."""

import asyncio

import httpx
import pytest

from backend.app.integrations.gmail.schemas import SendFailure
from backend.app.integrations.gmail.send_client import ENDPOINT, GmailSendClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,payload,category,uncertain",
    [
        (200, {"id": "mock-message", "threadId": "mock-thread"}, None, False),
        (202, {"id": "mock-message"}, None, False),
        (400, {}, "malformed_request", False),
        (401, {}, "credential_rejected", False),
        (403, {}, "scope_or_policy_denied", False),
        (404, {}, "gmail_resource_missing", False),
        (429, {}, "gmail_quota_exceeded", False),
        (500, {}, "gmail_server_or_unexpected_response", True),
        (503, {}, "gmail_server_or_unexpected_response", True),
        (302, {}, "gmail_server_or_unexpected_response", True),
        (200, [], "invalid_gmail_response", True),
        (200, {"id": 123}, "invalid_gmail_response", True),
        (200, {}, "invalid_gmail_response", True),
        (204, None, "invalid_gmail_response", True),
    ],
)
async def test_response_classification(code, payload, category, uncertain, caplog):
    requests = []

    def respond(req):
        requests.append(req)
        return httpx.Response(code, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = GmailSendClient(http)
        if category:
            with pytest.raises(SendFailure) as err:
                await client.send("private-token", "private-body")
            assert err.value.category == category and err.value.uncertain == uncertain
        else:
            accepted = await client.send("private-token", "private-body")
            assert accepted.id == "mock-message"
            assert "delivered" not in accepted.model_dump()
    assert len(requests) == 1 and str(requests[0].url) == ENDPOINT
    assert requests[0].method == "POST"
    assert requests[0].content == b'{"raw":"private-body"}'
    assert "private-token" not in caplog.text and "private-body" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,uncertain",
    [
        (httpx.ConnectTimeout, False),
        (httpx.ConnectError, False),
        (httpx.PoolTimeout, False),
        (httpx.ReadTimeout, True),
        (httpx.WriteTimeout, True),
        (httpx.ReadError, True),
        (httpx.RemoteProtocolError, True),
        (asyncio.CancelledError, True),
    ],
)
async def test_transport_uncertainty(failure, uncertain):
    calls = []

    def respond(req):
        calls.append(req)
        raise failure("secret must not escape")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(SendFailure) as err:
            await GmailSendClient(http).send("token", "body")
    assert err.value.uncertain == uncertain and len(calls) == 1
    assert "secret" not in str(err.value)


@pytest.mark.asyncio
async def test_overall_timeout_is_uncertain_and_never_retried():
    calls = []

    async def slow(request):
        calls.append(request)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"id": "late-message"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as http:
        with pytest.raises(SendFailure) as err:
            await GmailSendClient(http, timeout=0.01).send("token", "body")
    assert err.value.uncertain and len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_json_success_is_uncertain():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"private invalid JSON")
        )
    ) as http:
        with pytest.raises(SendFailure) as err:
            await GmailSendClient(http).send("token", "body")
    assert err.value.category == "invalid_gmail_response" and err.value.uncertain
    assert "private" not in str(err.value)
