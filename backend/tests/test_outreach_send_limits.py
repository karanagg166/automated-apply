"""Gmail send settings stay disabled and cannot be loosened (read + draft only)."""

import pytest

from backend.app.core.config import Settings


def test_disabled_default_and_confirmation_cannot_be_disabled():
    from pydantic import ValidationError

    settings = Settings(_env_file=None)
    assert settings.GMAIL_READ_DRAFT_ONLY
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

