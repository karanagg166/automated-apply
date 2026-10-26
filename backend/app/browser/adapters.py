"""Applicant execution policy. The only executable adapter is a fictional loopback site.

A real employer adapter must document permission, form semantics and independent
receipt verification before joining this registry; employer API access is insufficient.
"""

from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from backend.app.browser.runner import origin
from backend.app.browser.submission_contracts import MockNarrativeReceipt, MockReceipt

FORM_STATE = Path(__file__).with_name("form_state.js").read_text()


class ManualHandoffAdapter:
    key = "manual_handoff"
    submission_enabled = False


class LocalMockEmployerAdapter:
    key = "local_mock_v1"
    submission_enabled = True
    fixture = "automated-apply-employer-v1"
    action_path = "/mock/applications"
    receipt_schema = MockReceipt
    expected_controls = (
        ("name", "text"),
        ("email", "email"),
        ("resume", "file"),
        ("consent", "checkbox"),
    )

    def __init__(self, application_url):
        # Derive the origin from parsed fields, never a path found on the website.
        parsed = urlsplit(application_url)
        self.base = f"http://127.0.0.1:{parsed.port}"
        self.action = self.base + self.action_path

    def validate_form(self, state):
        if (
            state["fixture"] != self.fixture
            or state["action"] != self.action
            or state["method"] != "POST"
            or state["enctype"] != "multipart/form-data"
        ):
            raise HTTPException(
                409, "The form does not match the documented mock adapter"
            )
        expected = list(self.expected_controls)
        controls = [(control["name"], control["kind"]) for control in state["controls"]]
        entry_names = [name for name, _ in state["entries"]]
        # Each version has only its documented controls and two reserved identifiers.
        # Reject unknown/duplicate uploads or data rather than approving invisible contents.
        if controls != expected or sorted(entry_names) != sorted(
            name for name, _ in expected
        ):
            raise HTTPException(
                409,
                "Unexpected controls or hidden payload require a separately reviewed adapter",
            )

    async def receipt(self, attempt_id, payload_digest):
        # Independent server record, never page text, successful clicks or navigations.
        async with httpx.AsyncClient(
            timeout=5, trust_env=False, follow_redirects=False
        ) as client:
            async with client.stream(
                "GET", self.base + "/mock/receipts/" + str(attempt_id)
            ) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise ValueError("receipt_unavailable")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8192:
                        raise ValueError("receipt_too_large")
        receipt = self.receipt_schema.model_validate_json(raw)
        if (
            str(receipt.attempt_id) != str(attempt_id)
            or receipt.payload_digest != payload_digest
        ):
            raise ValueError("receipt_mismatch")
        return receipt.model_dump(mode="json")


class LocalMockNarrativeAdapter(LocalMockEmployerAdapter):
    """Testing-only V2 adds one reviewed narrative; V1's protocol stays exact."""

    key = "local_mock_v2"
    fixture = "automated-apply-employer-v2"
    action_path = "/mock/v2/applications"
    receipt_schema = MockNarrativeReceipt
    expected_controls = (
        ("name", "text"),
        ("email", "email"),
        ("motivation", "textarea"),
        ("resume", "file"),
        ("consent", "checkbox"),
    )


def execution_adapter(application_url, settings):
    parsed = urlsplit(application_url or "")
    if (
        settings.ENVIRONMENT == "testing"
        and settings.BROWSER_MOCK_SUBMISSION_ENABLED
        and parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port is not None
        and parsed.path in {"/mock/apply", "/mock/v2/apply"}
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
        and origin(application_url) in settings.BROWSER_ALLOWED_ORIGINS
    ):
        adapter = (
            LocalMockNarrativeAdapter
            if parsed.path == "/mock/v2/apply"
            else LocalMockEmployerAdapter
        )
        return adapter(application_url)
    return ManualHandoffAdapter()
