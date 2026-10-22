"""Application configuration using Pydantic Settings."""

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.urls import PublicHTTPSURL


class Settings(BaseSettings):
    """Strongly typed application settings loaded from environment variables."""

    # Application Environment
    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = (
        "development"
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    DEBUG: bool = False
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000

    # Deployment boundaries: REST stays single-owner, same-origin and HTTPS in live environments.
    API_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    API_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    API_REQUIRE_TLS: bool = True
    STAGING_DATABASE_ID: str | None = None
    APPLICATION_SUBMISSION_ENABLED: Literal[False] = False
    BROWSER_ASSISTANT_ENABLED: bool = False
    BROWSER_MOCK_SUBMISSION_ENABLED: bool = False
    BROWSER_OWNER_APPROVAL_KEY: SecretStr | None = Field(default=None, min_length=32)
    BROWSER_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    BROWSER_PROFILE_ROOT: str = "reports/browser-profiles"
    BROWSER_CHANNEL: Literal["chrome", "chromium"] = "chrome"
    BROWSER_HEADLESS: bool = False

    # Security
    RESUME_ENCRYPTION_KEY: SecretStr | None = None
    UI_FIXTURE_MODE: bool = False
    JOB_AGENT_API_TOKEN: SecretStr | None = None
    SECRET_KEY: str = Field(
        default="insecure-dev-secret-key-must-be-changed-in-production-32-chars",
        description="Key used for secret reference token encryption and internal tokens",
    )

    # Supabase / PostgreSQL Direct Database Connection
    DATABASE_URL: str = Field(
        default="",
        repr=False,
        description="Async SQLAlchemy database connection string",
    )
    DATABASE_SCHEMA: str = Field(
        default="job_agent",
        description="Dedicated isolated PostgreSQL schema for job-pulse-agent",
    )
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_ECHO: bool = False
    DB_REQUIRE_TLS: bool = True
    DB_REMOTE_ONLY: bool = True
    DB_SSL_ROOT_CERT: str | None = None

    # Optional Supabase REST API Configuration
    SUPABASE_URL: str | None = None
    SUPABASE_ANON_KEY: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None

    # Optional candidate defaults. Never written at startup.
    CANDIDATE_RESUME_DRIVE_URL: PublicHTTPSURL | None = None
    CANDIDATE_RESUME_DRIVE_FILE_ID: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{10,200}$")
    RESUME_DRIVE_SYNC_ENABLED: bool = False
    RESUME_DRIVE_SYNC_INTERVAL_HOURS: int = Field(default=24, ge=1, le=168)
    RESUME_DRIVE_SYNC_REQUIRES_REVIEW: Literal[True] = True
    CANDIDATE_GITHUB_URL: PublicHTTPSURL | None = None
    CANDIDATE_ORIGINAL_LINKEDIN_URL: PublicHTTPSURL | None = None
    CANDIDATE_PORTFOLIO_URL: PublicHTTPSURL | None = None
    CANDIDATE_LEETCODE_URL: PublicHTTPSURL | None = None
    CANDIDATE_CODEFORCES_URL: PublicHTTPSURL | None = None
    CANDIDATE_GFG_URL: PublicHTTPSURL | None = None
    CANDIDATE_HACKERRANK_URL: PublicHTTPSURL | None = None

    APPROVED_ANSWER_REUSE_ENABLED: bool = False
    LLM_LOCAL_FALLBACK_ENABLED: bool = False
    GEMINI_ENABLED: bool = False
    GEMINI_APPROVED_MONTHLY_REQUESTS: int = Field(default=0, ge=0, le=10000)
    LLM_PROVIDER: Literal["gemini", "ollama", "cohere"] = "gemini"
    OLLAMA_ENABLED: bool = False
    OLLAMA_MODEL: str | None = Field(default=None, max_length=150, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    COHERE_EVALUATION_ENABLED: bool = False
    COHERE_TRIAL_KEY_CONFIRMED: bool = False
    COHERE_DATA_SHARING_APPROVED: bool = False
    COHERE_API_KEY: SecretStr | None = None
    COHERE_MODEL: str | None = Field(default=None, max_length=150, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    LLM_MODEL: str | None = None
    GEMINI_API_KEY: SecretStr | None = None
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=1000, ge=64, le=8192)
    LLM_MAX_INPUT_CHARS: int = Field(default=16000, ge=1000, le=64000)
    LLM_TIMEOUT_SECONDS: float = Field(default=30, ge=1, le=120, allow_inf_nan=False)
    LLM_MONTHLY_MAX_REQUESTS: int = Field(default=200, ge=0, le=10000)
    LLM_MAX_CONCURRENCY: int = Field(default=2, ge=1, le=8)

    @field_validator(
        "DB_SSL_ROOT_CERT",
        "CANDIDATE_RESUME_DRIVE_URL",
        "CANDIDATE_RESUME_DRIVE_FILE_ID",
        "RESUME_ENCRYPTION_KEY",
        "CANDIDATE_GITHUB_URL",
        "CANDIDATE_ORIGINAL_LINKEDIN_URL",
        "CANDIDATE_PORTFOLIO_URL",
        "CANDIDATE_LEETCODE_URL",
        "CANDIDATE_CODEFORCES_URL",
        "CANDIDATE_GFG_URL",
        "CANDIDATE_HACKERRANK_URL",
        "GEMINI_API_KEY",
        "OLLAMA_MODEL",
        "COHERE_MODEL",
        "COHERE_API_KEY",
        "BROWSER_OWNER_APPROVAL_KEY",
        "LLM_MODEL",
        mode="before",
    )
    @classmethod
    def empty_optional(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("LLM_MODEL")
    @classmethod
    def model_identifier(cls, value):
        if value is not None and not re.fullmatch(
            r"(?:models/)?gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value
        ):
            raise ValueError("LLM_MODEL must be a Gemini model identifier, not a URL")
        return value

    # FastMCP Server
    FASTMCP_SERVER_NAME: str = "Job Pulse Agent Tools"
    FASTMCP_MOUNT_PATH: str = "/mcp"
    MCP_REMOTE_ENABLED: bool = False
    MCP_API_TOKEN: SecretStr | None = None
    MCP_ALLOW_DRAFT_CREATION: bool = False
    MCP_MAX_REQUEST_BYTES: int = Field(default=65536, ge=1024, le=1048576)
    MCP_MAX_CONCURRENCY: int = Field(default=3, ge=1, le=16)
    MCP_REQUEST_TIMEOUT_SECONDS: float = Field(default=30, ge=1, le=120, allow_inf_nan=False)
    MCP_ALLOWED_HOSTS: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "[::1]"])
    MCP_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    MCP_REQUIRE_TLS: bool = True

    @field_validator("MCP_ALLOWED_HOSTS", "MCP_ALLOWED_ORIGINS", "API_ALLOWED_HOSTS", "API_ALLOWED_ORIGINS")
    @classmethod
    def explicit_mcp_trust(cls, values, info):
        from urllib.parse import urlsplit
        for value in values:
            if not value or any(c.isspace() for c in value) or "*" in value:
                raise ValueError("MCP trust lists must contain explicit hosts/origins")
            if info.field_name.endswith("ORIGINS"):
                url = urlsplit(value)
                if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                        or url.password or url.path or url.query or url.fragment):
                    raise ValueError("Invalid MCP origin")
            elif any(c in value for c in "/@?#"):
                raise ValueError("MCP_ALLOWED_HOSTS contains an invalid hostname")
        if info.field_name == "MCP_ALLOWED_HOSTS" and not values:
            raise ValueError("MCP_ALLOWED_HOSTS cannot be empty")
        return values

    # Separate randomly generated Fernet keys; never derive OAuth encryption from SECRET_KEY.
    OAUTH_ENCRYPTION_KEYS: dict[str, SecretStr] = Field(default_factory=dict)
    OAUTH_ACTIVE_KEY_ID: str | None = None
    GMAIL_REDIRECT_URI: str | None = None
    GMAIL_EXPECTED_EMAIL: str | None = None
    OAUTH_STATE_TTL_SECONDS: int = Field(default=600, ge=60, le=900)

    @field_validator("GMAIL_REDIRECT_URI")
    @classmethod
    def oauth_redirect(cls, value):
        from urllib.parse import urlsplit
        if not value:
            return None
        url = urlsplit(value)
        if (url.username or url.password or url.query or url.fragment
                or url.path != "/api/v1/integrations/gmail/oauth/callback"
                or not url.hostname
                or (url.scheme != "https" and not
                    (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))):
            raise ValueError("GMAIL_REDIRECT_URI must be the exact HTTPS callback (HTTP loopback only)")
        return value

    @field_validator("FASTMCP_MOUNT_PATH")
    @classmethod
    def fixed_mcp_path(cls, value):
        if value != "/mcp":
            raise ValueError("Phase 4A has one MCP endpoint at /mcp/")
        return value

    # Default Monthly Credit Caps per Provider (Cost-first architecture safety)
    HUNTER_MONTHLY_LIMIT: int = Field(default=25, ge=0)
    APOLLO_MONTHLY_LIMIT: int = Field(default=50, ge=0)
    SERPER_MONTHLY_LIMIT: int = Field(default=100, ge=0)
    SIGNALHIRE_MONTHLY_LIMIT: int = Field(default=5, ge=0)

    # External Provider API Keys (Empty by default in dev/test)
    HUNTER_API_KEY: str | None = None
    APOLLO_API_KEY: SecretStr | None = None
    SERPER_API_KEY: str | None = None
    SIGNALHIRE_API_KEY: SecretStr | None = None

    APOLLO_ENRICHMENT_ENABLED: bool = False
    SIGNALHIRE_ENRICHMENT_ENABLED: bool = False
    APOLLO_PER_RUN_LIMIT: int = Field(default=5, ge=0, le=100)
    SIGNALHIRE_PER_RUN_LIMIT: int = Field(default=2, ge=0, le=100)
    # Account-specific maximum cost must be confirmed before paid execution.
    APOLLO_CREDITS_PER_LOOKUP: int = Field(default=0, ge=0, le=100)
    SIGNALHIRE_CREDITS_PER_LOOKUP: int = Field(default=0, ge=0, le=100)
    CONTACT_ENRICHMENT_MAX_PEOPLE_PER_RUN: int = Field(default=10, ge=1, le=25)
    CONTACT_ENRICHMENT_MAX_CONCURRENCY: int = Field(default=2, ge=1, le=8)
    CONTACT_CACHE_TTL_DAYS: int = Field(default=30, ge=1, le=90)
    CONTACT_RETENTION_DAYS: int = Field(default=90, ge=1, le=365)
    CONTACT_PROVIDER_TIMEOUT_SECONDS: float = Field(default=20, ge=1, le=60, allow_inf_nan=False)

    # Apify Integration Configuration
    APIFY_API_TOKEN: str | None = Field(
        default=None, description="Apify API token for running actors"
    )
    APIFY_MONTHLY_LIMIT_USD: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
        description="Monthly dollar spending cap for Apify actor runs",
    )

    # Discovery is opt-in for every billable source. No actor is bundled as vetted.
    GREENHOUSE_BOARDS: dict[str, str] = Field(default_factory=dict)
    APIFY_SOURCES: dict[str, dict] = Field(default_factory=dict)
    APIFY_PER_RUN_CAP_USD: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    PEOPLE_SEARCH_ENABLED: bool = False
    # Retention rights are separate from credentials and paid authorization.
    PUBLIC_SEARCH_RIGHTS_REVIEWED: bool = False
    LINKEDIN_SEARCH_RETENTION_AUTHORIZED: bool = False
    # Exact company domains mapped to operator-reviewed permission evidence URLs.
    PUBLIC_SEARCH_ALLOWED_DOMAINS: dict[str, str] = Field(default_factory=dict)
    PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL: str | None = None
    PROVIDER_VERIFICATION_TTL_HOURS: int = Field(24, ge=1, le=168)
    DISCOVERY_TIMEOUT_SECONDS: float = Field(
        default=90, ge=5, le=180, allow_inf_nan=False
    )
    DISCOVERY_MAX_CONCURRENCY: int = Field(default=2, ge=1, le=8)

    # Outbound communication always needs a fresh owner confirmation.
    GMAIL_SENDING_ENABLED: bool = False
    GMAIL_SEND_MAX_PER_DAY: int = Field(default=10, ge=0, le=100)
    GMAIL_SEND_MAX_PER_HOUR: int = Field(default=3, ge=0, le=20)
    GMAIL_SEND_MAX_RECIPIENTS: Literal[1] = 1
    GMAIL_SEND_TIMEOUT_SECONDS: float = Field(default=20, ge=1, le=60, allow_inf_nan=False)
    GMAIL_REQUIRE_EXPLICIT_CONFIRMATION: Literal[True] = True
    GMAIL_CONFIRMATION_TTL_SECONDS: int = Field(default=300, ge=30, le=600)

    # Gmail Integration Configuration (OAuth)
    GMAIL_CLIENT_ID: str | None = Field(
        default=None, description="Google OAuth 2.0 Client ID"
    )
    GMAIL_CLIENT_SECRET: str | None = Field(
        default=None, description="Google OAuth 2.0 Client Secret"
    )
    GMAIL_REFRESH_TOKEN: str | None = Field(
        default=None, description="Google OAuth 2.0 Refresh Token"
    )

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("APPLICATION_SUBMISSION_ENABLED", "GMAIL_REQUIRE_EXPLICIT_CONFIRMATION", "GMAIL_SEND_MAX_RECIPIENTS", "RESUME_DRIVE_SYNC_REQUIRES_REVIEW", mode="before")
    @classmethod
    def fixed_environment_controls(cls, value, info):
        # dotenv values are strings; preserve the literal invariants after parsing.
        if isinstance(value, str):
            if info.field_name == "APPLICATION_SUBMISSION_ENABLED" and value.lower() == "false":
                return False
            if info.field_name == "GMAIL_REQUIRE_EXPLICIT_CONFIRMATION" and value.lower() == "true":
                return True
            if info.field_name == "RESUME_DRIVE_SYNC_REQUIRES_REVIEW" and value.lower() == "true":
                return True
            if info.field_name == "GMAIL_SEND_MAX_RECIPIENTS" and value == "1":
                return 1
        return value

    @field_validator("DATABASE_SCHEMA")
    @classmethod
    def validate_schema_name(cls, v: str) -> str:
        """Prevent dangerous characters or empty schema names."""
        cleaned = v.strip().lower()
        if not cleaned:
            raise ValueError("DATABASE_SCHEMA cannot be empty")
        if not cleaned.replace("_", "").isalnum():
            raise ValueError(
                "DATABASE_SCHEMA must be alphanumeric with underscores only"
            )
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


_operator_settings: Settings | None = None


def configure_operator(settings: Settings) -> None:
    """CLI bootstrap only, before ORM imports; do not implicitly load repository secrets."""
    global _operator_settings
    _operator_settings = settings
    get_settings.cache_clear()


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return _operator_settings or Settings()
