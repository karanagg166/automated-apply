"""Pydantic schemas for API key pool and credit budget tracking."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyPoolBase(BaseModel):
    provider: str = Field(..., max_length=50, description="Provider identifier, e.g. hunter, apollo, serper")
    account_label: str = Field(..., max_length=100, description="Friendly label for account/key")
    credits_remaining: int = Field(default=0, ge=0)
    monthly_limit: int = Field(default=0, ge=0)
    reset_at: datetime | None = None
    is_active: bool = Field(default=True)


class ApiKeyPoolCreate(ApiKeyPoolBase):
    secret_reference: str = Field(
        ...,
        description="Encrypted secret or env variable reference (e.g. env:HUNTER_API_KEY)",
    )


class ApiKeyPoolRead(ApiKeyPoolBase):
    id: UUID
    secret_reference: str
    cooldown_until: datetime | None = None
    last_error_code: int | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderBudgetSummary(BaseModel):
    provider: str
    is_active: bool
    credits_remaining: int
    monthly_limit: int
    reset_at: datetime | None = None
    in_cooldown: bool = False
    cooldown_until: datetime | None = None


class CreditBudgetStatus(BaseModel):
    timestamp: datetime
    providers: list[ProviderBudgetSummary]
    total_credits_remaining: int


class ProviderUsageRecord(BaseModel):
    provider: str
    endpoint: str | None = None
    credits_consumed: int = Field(default=0, ge=0)
    status_code: int | None = None
    is_success: bool = True
    error_message: str | None = None
