"""V2 adds a narrative without widening V1 or accepting another protocol's receipt."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from backend.app.browser.adapters import (
    LocalMockEmployerAdapter,
    LocalMockNarrativeAdapter,
    execution_adapter,
)


def form(adapter):
    return {
        "fixture": adapter.fixture,
        "action": adapter.action,
        "method": "POST",
        "enctype": "multipart/form-data",
        "controls": [
            {"name": name, "kind": kind} for name, kind in adapter.expected_controls
        ],
        "entries": [[name, "fixture value"] for name, _ in adapter.expected_controls],
    }


def test_versions_preserve_exact_distinct_form_controls():
    v1 = LocalMockEmployerAdapter("http://127.0.0.1:8767/mock/apply")
    v2 = LocalMockNarrativeAdapter("http://127.0.0.1:8767/mock/v2/apply")
    v1.validate_form(form(v1))
    v2.validate_form(form(v2))
    for adapter, other in [(v1, v2), (v2, v1)]:
        with pytest.raises(HTTPException):
            adapter.validate_form(form(other))
    extra = form(v2)
    extra.update(fixture=v1.fixture, action=v1.action)
    with pytest.raises(HTTPException):
        v1.validate_form(extra)
    missing = form(v2)
    missing["controls"].pop(2)
    missing["entries"].pop(2)
    with pytest.raises(HTTPException):
        v2.validate_form(missing)
    hidden = form(v2)
    hidden["entries"].append(["hidden_salary", "invented salary"])
    with pytest.raises(HTTPException):
        v2.validate_form(hidden)


@pytest.mark.parametrize(
    "adapter_class", [LocalMockEmployerAdapter, LocalMockNarrativeAdapter]
)
@pytest.mark.asyncio
async def test_receipt_version_is_bound_to_the_selected_adapter(
    monkeypatch, adapter_class
):
    adapter = adapter_class("http://127.0.0.1:8767/mock/v2/apply")
    attempt = uuid4()
    receipt = {
        "status": "accepted",
        "attempt_id": str(attempt),
        "payload_digest": "a" * 64,
        "receipt_reference": "MOCK-" + attempt.hex,
        "fixture": adapter.fixture,
    }
    original = httpx.AsyncClient

    def transport(request):
        assert request.method == "GET"
        assert str(request.url) == f"http://127.0.0.1:8767/mock/receipts/{attempt}"
        return httpx.Response(200, json=receipt)

    monkeypatch.setattr(
        "backend.app.browser.adapters.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs),
    )
    assert (await adapter.receipt(attempt, "a" * 64))["fixture"] == adapter.fixture
    receipt["fixture"] = (
        "automated-apply-employer-v2"
        if adapter_class is LocalMockEmployerAdapter
        else "automated-apply-employer-v1"
    )
    with pytest.raises(ValueError):
        await adapter.receipt(attempt, "a" * 64)


@pytest.mark.parametrize(
    "environment,enabled,url",
    [
        ("production", True, "http://127.0.0.1:8767/mock/v2/apply"),
        ("development", True, "http://127.0.0.1:8767/mock/v2/apply"),
        ("testing", False, "http://127.0.0.1:8767/mock/v2/apply"),
        ("testing", True, "http://127.0.0.1:8767/mock/v2/apply?job=other"),
        ("testing", True, "http://localhost:8767/mock/v2/apply"),
    ],
)
def test_narrative_execution_retains_testing_and_destination_gates(
    environment, enabled, url
):
    settings = SimpleNamespace(
        ENVIRONMENT=environment,
        BROWSER_MOCK_SUBMISSION_ENABLED=enabled,
        BROWSER_ALLOWED_ORIGINS=["http://127.0.0.1:8767"],
    )
    assert not execution_adapter(url, settings).submission_enabled
