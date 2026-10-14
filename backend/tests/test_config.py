"""Tests for application configuration and settings validation."""

import pytest
from backend.app.core.config import Settings


def test_settings_default_values():
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
        DATABASE_SCHEMA="job_agent",
    )
    assert settings.DATABASE_SCHEMA == "job_agent"
    assert settings.HUNTER_MONTHLY_LIMIT == 25
    assert settings.APOLLO_MONTHLY_LIMIT == 50
    assert settings.SERPER_MONTHLY_LIMIT == 100


def test_settings_schema_validation():
    # Valid schema names
    s1 = Settings(DATABASE_SCHEMA="job_agent_v2")
    assert s1.DATABASE_SCHEMA == "job_agent_v2"

    # Dangerous or invalid schema names must raise ValueError
    with pytest.raises(ValueError, match="DATABASE_SCHEMA must be alphanumeric"):
        Settings(DATABASE_SCHEMA="job_agent; DROP TABLE users;")

    with pytest.raises(ValueError, match="DATABASE_SCHEMA cannot be empty"):
        Settings(DATABASE_SCHEMA="   ")


def test_provider_monthly_limit_helper():
    settings = Settings(
        HUNTER_MONTHLY_LIMIT=30,
        APOLLO_MONTHLY_LIMIT=60,
    )
    assert settings.get_provider_monthly_limit("hunter") == 30
    assert settings.get_provider_monthly_limit("APOLLO") == 60
    assert settings.get_provider_monthly_limit("unknown_provider") == 0
