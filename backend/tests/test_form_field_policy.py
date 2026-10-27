"""Native inspection is untrusted even when its caller is authenticated."""

import pytest

from backend.app.browser.field_policy import manual_only
from backend.app.browser.service import FormService
from backend.tests import test_browser_forms as fixture

browser_target = fixture.browser_target


@pytest.mark.parametrize(
    "label",
    [
        "Government ID number",
        "Gender",
        "Ethnicity",
        "Religion",
        "Disability status",
        "Veteran status",
        "Sexual orientation",
        "Pronouns",
        "Passport",
        "Aadhaar number",
        "PAN card",
        "Credit card",
        "OTP",
        "Bank account",
        "I certify my email",
        "Applicant declaration",
        "Agree to privacy policy",
        "Tax ID",
        "Date of birth",
    ],
)
def test_sensitive_or_legal_fields_are_manual(label):
    assert manual_only(label)


@pytest.mark.parametrize(
    "label",
    [
        "Full name",
        "Email",
        "Portfolio URL",
        "Expected salary",
        "Notice period",
        "Are you authorized to work in India?",
    ],
)
def test_ordinary_facts_remain_supported(label):
    assert not manual_only(label)


@pytest.mark.asyncio
async def test_forged_native_group_cannot_turn_email_into_consent(
    db_session, browser_target
):
    job, packet, _ = browser_target
    plan = await FormService(db_session, fixture.config()).inspect(
        packet.id,
        fixture.inspection(
            job.application_url,
            [
                {
                    "field_id": "f0",
                    "kind": "checkbox",
                    "label": "I consent",
                    "group_label": "Email",
                    "options": ["alex@example.com"],
                }
            ],
        ),
        "manual_extension",
    )
    assert plan.actions[0].needs_input and plan.actions[0].value is None


@pytest.mark.asyncio
async def test_partial_receipt_does_not_claim_all_required_fields_filled(
    db_session, browser_target
):
    from backend.app.browser.contracts import FillReceipt

    job, packet, _ = browser_target
    service = FormService(db_session, fixture.config())
    plan = await service.inspect(
        packet.id, fixture.inspection(job.application_url), "manual_extension"
    )
    await service.review(plan.id, ["f0", "f1"])
    await service.consume(plan.id, "manual_extension")
    result = await service.receipt(
        FillReceipt(
            plan_id=plan.id,
            state="form_filled",
            results=[{"field_id": "f0", "status": "filled"}],
        )
    )
    assert result == {"status": "needs_input", "submitted": False}
