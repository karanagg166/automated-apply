"""Strict owner requests and sanitized provider results."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_revision: StrictInt = Field(ge=1)
    approval_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    sender_account_id: UUID
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class GmailAcceptance(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,255}$")
    threadId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,255}$")


class SendFailure(Exception):
    """Fixed category only; uncertain transmission must never be retried."""

    def __init__(self, category, *, uncertain):
        self.category, self.uncertain = category, uncertain
        super().__init__(category)
