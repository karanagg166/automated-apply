"""Secret-free configuration loading and explicit database target boundaries."""

import hashlib
import re

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from backend.app.core.config import Settings


class OperationRejected(ValueError):
    """Only fixed diagnostic codes, never configuration values, cross the CLI boundary."""


def load_settings(env_file=None):
    try:
        # Operators choose an env file explicitly. Never inherit the repository's .env.
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors()})
        raise OperationRejected(
            "invalid_configuration_fields:" + ",".join(fields)
        ) from None


def target_identity(settings):
    try:
        url = make_url(settings.DATABASE_URL)
        if (url.drivername != "postgresql+asyncpg" or not url.host or not url.database or url.query):
            raise ValueError
        # Password-independent identity; intentionally does not reveal host/user/database.
        identity = f"{url.host.lower()}:{url.port or 5432}/{url.database}/{settings.DATABASE_SCHEMA}"
        return hashlib.sha256(identity.encode()).hexdigest()
    except (ValueError, TypeError, ArgumentError):
        raise OperationRejected("postgresql_target_required") from None


def require_staging(settings, confirmation):
    if settings.ENVIRONMENT != "staging":
        raise OperationRejected(
            "staging_environment_required_production_connections_forbidden"
        )
    if settings.DATABASE_SCHEMA != "job_agent":
        raise OperationRejected("migrations_require_job_agent_schema")
    identity = target_identity(settings)
    if (
        not settings.STAGING_DATABASE_ID
        or identity != settings.STAGING_DATABASE_ID
        or confirmation != identity
    ):
        raise OperationRejected("staging_database_identity_confirmation_required")
    # A pin prevents accidental target substitution. The owner must independently confirm
    # that this identity is an isolated staging DB; a label is not proof of isolation.
    return identity


def suitable_secret(value):
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return bool(
        value
        and len(value) >= 32
        and len(set(value)) >= 12
        and not re.search(
            r"insecure|change.this|YOUR_|dummy|fictional|example|test-secret",
            value,
            re.I,
        )
    )
