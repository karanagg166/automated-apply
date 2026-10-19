"""Owner caps count all durable reservations, including uncertain transmissions."""

import pytest

from backend.app.core.config import Settings
from backend.app.integrations.gmail.schemas import SendFailure
from backend.app.services.outreach_drafting import DraftConflict
from backend.tests.phase4b_fakes import approved_target, request_from


def test_disabled_default_and_confirmation_cannot_be_disabled():
    from pydantic import ValidationError

    settings = Settings(_env_file=None)
    assert (
        not settings.GMAIL_SENDING_ENABLED
        and settings.GMAIL_REQUIRE_EXPLICIT_CONFIRMATION
    )
    for changes in (
        {"GMAIL_REQUIRE_EXPLICIT_CONFIRMATION": False},
        {"GMAIL_SEND_MAX_RECIPIENTS": 2},
        {"GMAIL_SEND_TIMEOUT_SECONDS": float("inf")},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **changes)


@pytest.mark.asyncio
async def test_disabled_sending_blocks_preview(sending_bundle):
    service, draft, client, *_ = sending_bundle
    service.settings.GMAIL_SENDING_ENABLED = False
    with pytest.raises(DraftConflict, match="disabled"):
        await service.preview(draft["id"])
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["hour", "day"])
@pytest.mark.parametrize("unknown", [False, True])
async def test_caps_count_accepted_and_uncertain(sending_bundle, period, unknown):
    service, draft, client, *_ = sending_bundle
    setattr(
        service.settings,
        "GMAIL_SEND_MAX_PER_HOUR" if period == "hour" else "GMAIL_SEND_MAX_PER_DAY",
        1,
    )
    if unknown:
        client.failure = SendFailure("transmission_outcome_unknown", uncertain=True)
    await service.send(draft["id"], request_from(await service.preview(draft["id"])))
    second, *_ = await approved_target(service.session, service.settings, suffix="two")
    with pytest.raises(DraftConflict, match="hourly" if period == "hour" else "daily"):
        await service.preview(second["id"])
    assert len(client.calls) == 1
