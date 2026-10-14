"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly typed application settings loaded from environment variables."""

    # Application Environment
    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    DEBUG: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Security
    SECRET_KEY: str = Field(
        default="insecure-dev-secret-key-must-be-changed-in-production-32-chars",
        description="Key used for secret reference token encryption and internal tokens",
    )

    # Supabase / PostgreSQL Direct Database Connection
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
        description="Async SQLAlchemy database connection string",
    )
    DATABASE_SCHEMA: str = Field(
        default="job_agent",
        description="Dedicated isolated PostgreSQL schema for job-pulse-agent",
    )
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_ECHO: bool = False

    # Optional Supabase REST API Configuration
    SUPABASE_URL: str | None = None
    SUPABASE_ANON_KEY: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None

    # FastMCP Server
    FASTMCP_SERVER_NAME: str = "Job Pulse Agent Tools"
    FASTMCP_MOUNT_PATH: str = "/mcp"

    # Default Monthly Credit Caps per Provider (Cost-first architecture safety)
    HUNTER_MONTHLY_LIMIT: int = Field(default=25, ge=0)
    APOLLO_MONTHLY_LIMIT: int = Field(default=50, ge=0)
    SERPER_MONTHLY_LIMIT: int = Field(default=100, ge=0)
    SIGNALHIRE_MONTHLY_LIMIT: int = Field(default=5, ge=0)

    # Provider API Keys (Empty by default in dev/test)
    HUNTER_API_KEY: str | None = None
    APOLLO_API_KEY: str | None = None
    SERPER_API_KEY: str | None = None
    SIGNALHIRE_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("DATABASE_SCHEMA")
    @classmethod
    def validate_schema_name(cls, v: str) -> str:
        """Prevent dangerous characters or empty schema names."""
        cleaned = v.strip().lower()
        if not cleaned:
            raise ValueError("DATABASE_SCHEMA cannot be empty")
        if not cleaned.replace("_", "").isalnum():
            raise ValueError("DATABASE_SCHEMA must be alphanumeric with underscores only")
        return cleaned

    def get_provider_monthly_limit(self, provider: str) -> int:
        """Retrieve configured monthly limit for a given provider name."""
        provider_clean = provider.strip().upper()
        mapping = {
            "HUNTER": self.HUNTER_MONTHLY_LIMIT,
            "APOLLO": self.APOLLO_MONTHLY_LIMIT,
            "SERPER": self.SERPER_MONTHLY_LIMIT,
            "SIGNALHIRE": self.SIGNALHIRE_MONTHLY_LIMIT,
        }
        return mapping.get(provider_clean, 0)


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
