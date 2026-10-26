"""Typed configuration evidence. Populated variables never imply live verification."""

from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field

from backend.app.core.config import Settings
from backend.app.db.safety import DatabaseConfigurationError, database_target
from backend.app.integrations.token_store import TokenStore
from backend.app.operations.configuration import (
    OperationRejected,
    suitable_secret,
    target_identity,
)

CheckStatus = Literal[
    "configured_not_verified",
    "missing_configuration",
    "missing_credentials",
    "unsafe_configuration",
    "disabled",
    "not_connected",
    "verified",
]


class Check(BaseModel):
    name: str
    status: CheckStatus
    required: bool = False
    details: list[str] = Field(default_factory=list)


class ReadinessReport(BaseModel):
    environment: str
    status: Literal["needs_configuration", "configured_not_verified"]
    checks: list[Check]
    production_ready: Literal[False] = False
    database_connected: Literal[False] = False
    target_id: str | None = None


def environment_readiness(settings: Settings) -> ReadinessReport:
    live = settings.ENVIRONMENT in {"staging", "production"}
    checks = []

    def add(name, good, required=False, details=None, missing="missing_configuration"):
        checks.append(
            Check(
                name=name,
                status="configured_not_verified" if good else missing,
                required=required,
                details=details or [],
            )
        )

    identity = None
    try:
        database_target(settings)
        identity = target_identity(settings)
    except (OperationRejected, DatabaseConfigurationError):
        pass
    add("database", bool(identity), True, ["No connection attempted"])
    add("database_tls", settings.DB_REQUIRE_TLS, settings.ENVIRONMENT != "testing", missing="unsafe_configuration")
    add(
        "database_schema",
        settings.DATABASE_SCHEMA in {"public", "job_agent"},
        True,
        ["Historical 001–012 use job_agent; fresh public uses its separate verified bundle"],
    )
    if settings.ENVIRONMENT == "staging":
        add(
            "staging_target",
            bool(identity and identity == settings.STAGING_DATABASE_ID),
            True,
            [
                "Owner must confirm isolation independently; the fingerprint is not authorization"
            ],
        )
    add("api_authentication", suitable_secret(settings.JOB_AGENT_API_TOKEN), live)
    add("secret_key", suitable_secret(settings.SECRET_KEY), live)
    try:
        Fernet(settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode())
        resume_encryption = True
    except (AttributeError, ValueError, TypeError):
        resume_encryption = False
    add("private_resume_encryption", resume_encryption, live)
    try:
        TokenStore(settings)
        encryption = True
    except ValueError:
        encryption = False
    add("oauth_keyring", encryption, False)
    add(
        "gemini",
        bool(settings.GEMINI_API_KEY and settings.LLM_MODEL),
        False,
        [
            "Model syntax validated; model availability, quota and factual quality unverified",
            f"Monthly request cap: {settings.LLM_MONTHLY_MAX_REQUESTS}",
            f"Output token cap: {settings.LLM_MAX_OUTPUT_TOKENS}",
        ],
        missing="missing_credentials",
    )
    add(
        "provider_budgets",
        settings.APIFY_MONTHLY_LIMIT_USD >= 0,
        True,
        [
            "Per-call approval and durable reservations still required; configured limits are not balances"
        ],
    )
    add(
        "public_sources",
        True,
        False,
        ["Free documented endpoints; never probed by this check"],
    )
    add(
        "greenhouse",
        bool(settings.GREENHOUSE_BOARDS),
        False,
        ["Configure only employer-verified board references"],
    )
    add(
        "public_professional_search",
        bool(
            settings.PEOPLE_SEARCH_ENABLED
            and settings.SERPER_API_KEY
            and settings.PUBLIC_SEARCH_RIGHTS_REVIEWED
            and settings.PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL
        ),
        details=[
            "Paid call approval required; LinkedIn retention remains separately gated"
        ],
    )
    add(
        "gmail_oauth",
        bool(
            encryption
            and settings.GMAIL_CLIENT_ID
            and settings.GMAIL_CLIENT_SECRET
            and settings.GMAIL_REDIRECT_URI
            and settings.GMAIL_EXPECTED_EMAIL
            and (not live or urlsplit(settings.GMAIL_REDIRECT_URI).scheme == "https")
        ),
        False,
    )
    checks.append(
        Check(
            name="gmail",
            status="not_connected",
            details=["Database account state not inspected"],
        )
    )
    add(
        "debug_disabled",
        not settings.DEBUG and not settings.DB_ECHO and settings.LOG_LEVEL != "DEBUG",
        live,
        missing="unsafe_configuration",
    )
    add(
        "rest_transport",
        bool(
            settings.API_ALLOWED_HOSTS
            and "*" not in settings.API_ALLOWED_HOSTS
            and settings.API_REQUIRE_TLS
            and not settings.API_ALLOWED_ORIGINS
        ),
        live,
        ["HTTPS and explicit hosts required; browser cross-origin access is disabled"],
        "unsafe_configuration",
    )
    mcp_safe = not settings.MCP_REMOTE_ENABLED or (
        settings.ENVIRONMENT == "production"
        and settings.MCP_REQUIRE_TLS
        and suitable_secret(settings.MCP_API_TOKEN)
        and settings.MCP_API_TOKEN != settings.JOB_AGENT_API_TOKEN
    )
    add("mcp_boundary", mcp_safe, live, missing="unsafe_configuration")
    add(
        "gmail_sending_disabled",
        not settings.GMAIL_SENDING_ENABLED,
        settings.ENVIRONMENT == "staging",
        missing="unsafe_configuration",
    )
    add(
        "application_submission_prohibited",
        not settings.APPLICATION_SUBMISSION_ENABLED,
        True,
    )
    blocked = any(c.required and c.status != "configured_not_verified" for c in checks)
    return ReadinessReport(
        environment=settings.ENVIRONMENT,
        status="needs_configuration" if blocked else "configured_not_verified",
        checks=checks,
        target_id=identity,
    )


def require_safe_startup(settings: Settings) -> None:
    if settings.ENVIRONMENT == "development":
        database_target(settings)
    if settings.ENVIRONMENT not in {"staging", "production"}:
        return
    failed = [
        c.name
        for c in environment_readiness(settings).checks
        if c.required and c.status != "configured_not_verified"
    ]
    if failed:
        raise OperationRejected("unsafe_deployment_configuration:" + ",".join(failed))
