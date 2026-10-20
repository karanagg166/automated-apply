"""One database boundary for API, workers and operator commands. No connections or DDL."""

import asyncio
import ipaddress
import re
import socket
import ssl

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(ValueError):
    """Fixed diagnostic codes only; a DSN must never appear in an exception."""


def local_target(host):
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        # Legacy numeric IPv4 spellings can resolve to loopback too.
        return bool(re.fullmatch(r"[0-9.]+", host)) or host.startswith("0x")


def database_target(settings):
    try:
        url = make_url(settings.DATABASE_URL)
        if url.query or "#" in settings.DATABASE_URL:
            raise DatabaseConfigurationError("database_url_parameters_not_permitted")
        if settings.ENVIRONMENT == "testing" and url.drivername == "sqlite+aiosqlite":
            return url
        if (url.drivername != "postgresql+asyncpg" or not url.host
                or not url.database or not url.username or not url.password):
            raise DatabaseConfigurationError("explicit_postgresql_database_required")
        if settings.ENVIRONMENT != "testing":
            if settings.DATABASE_SCHEMA != "job_agent":
                raise DatabaseConfigurationError("database_job_agent_schema_required")
            if settings.DB_REMOTE_ONLY and local_target(url.host):
                raise DatabaseConfigurationError("remote_postgresql_database_required")
            if (settings.DB_REMOTE_ONLY or not local_target(url.host)) and not settings.DB_REQUIRE_TLS:
                raise DatabaseConfigurationError("remote_postgresql_tls_required")
            if settings.DB_ECHO:
                raise DatabaseConfigurationError("database_echo_forbidden_for_real_data")
            # This persistent asyncpg backend uses session state/prepared statements.
            if url.port == 6543:
                raise DatabaseConfigurationError("use_direct_or_session_pooler_connection")
        return url
    except (ArgumentError, TypeError, ValueError) as exc:
        if isinstance(exc, DatabaseConfigurationError):
            raise
        raise DatabaseConfigurationError("invalid_database_configuration") from None


def database_connect_args(settings):
    url = database_target(settings)
    if url.drivername == "sqlite+aiosqlite":
        return {}
    args = {
        "timeout": 10,
        "command_timeout": 30,
        "server_settings": {"search_path": f"{settings.DATABASE_SCHEMA},public"},
    }
    if settings.DB_REQUIRE_TLS and not (settings.ENVIRONMENT == "testing" and local_target(url.host)):
        try:
            args["ssl"] = ssl.create_default_context(cafile=settings.DB_SSL_ROOT_CERT)
        except (OSError, ValueError):
            raise DatabaseConfigurationError("database_tls_certificate_unavailable") from None
    else:
        args["ssl"] = False
    return args


async def verify_remote_address(settings):
    url = database_target(settings)
    if settings.ENVIRONMENT == "testing" or not settings.DB_REMOTE_ONLY:
        return
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            url.host, url.port or 5432, type=socket.SOCK_STREAM,
        )
    except OSError:
        raise DatabaseConfigurationError("database_host_unavailable") from None
    if not addresses or any(local_target(address[4][0]) for address in addresses):
        raise DatabaseConfigurationError("remote_database_dns_resolves_locally")


def require_session_target(session, settings):
    target = database_target(settings)
    if settings.ENVIRONMENT != "testing" and session.get_bind().engine.url != target:
        raise DatabaseConfigurationError("session_database_target_mismatch")
