"""Offline cross-service configuration checks; never connect or print secret values."""

import re
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.operations.configuration import suitable_secret
from backend.app.operations.readiness import Check, environment_readiness


class FrontendSettings(BaseSettings):
    FRONTEND_ORIGIN: str = ""
    BACKEND_ORIGIN: str = ""
    FRONTEND_PASSWORD_HASH: SecretStr | None = None
    FRONTEND_SESSION_SECRET: SecretStr | None = None
    FRONTEND_LOCAL_HTTP: bool = False
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True)


def https_origin(value):
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.port != 0
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def workspace_readiness(settings, frontend):
    report = environment_readiness(settings).model_dump()
    checks = []

    def add(name, good, required=True, details=None):
        checks.append(Check(
            name=name,
            status="configured_not_verified" if good else "missing_configuration",
            required=required,
            details=details or [],
        ))

    password = frontend.FRONTEND_PASSWORD_HASH
    password = password.get_secret_value() if password else ""
    session = frontend.FRONTEND_SESSION_SECRET
    session = session.get_secret_value() if session else ""
    api = settings.JOB_AGENT_API_TOKEN
    api = api.get_secret_value() if api else ""
    add("frontend_owner_password", bool(re.fullmatch(r"[a-f0-9]{32}:[a-f0-9]{128}", password)))
    add("frontend_session_secret", suitable_secret(session))
    add("independent_session_secret", bool(session and session not in {api, settings.SECRET_KEY}))
    add("frontend_https_origin", https_origin(frontend.FRONTEND_ORIGIN) and not frontend.FRONTEND_LOCAL_HTTP)
    add("backend_https_origin", https_origin(frontend.BACKEND_ORIGIN))
    host = urlsplit(frontend.BACKEND_ORIGIN).netloc if https_origin(frontend.BACKEND_ORIGIN) else ""
    add("backend_allowed_host", bool(host and host in settings.API_ALLOWED_HOSTS))
    callback = settings.GMAIL_REDIRECT_URI
    same_origin = False
    if callback and https_origin(frontend.FRONTEND_ORIGIN):
        parsed, origin = urlsplit(callback), urlsplit(frontend.FRONTEND_ORIGIN)
        same_origin = (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc)
    add("gmail_same_origin_callback", same_origin, required=False, details=[
        "Optional until Gmail is configured. Route the exact callback to FastAPI on the frontend hostname; verify the browser binding through HTTPS before consent."
    ])
    # Misconfigured OAuth must not be presented as usable once an operator enables it.
    if settings.GMAIL_CLIENT_ID or settings.GMAIL_CLIENT_SECRET or callback:
        checks[-1].required = True
    report["checks"].extend(check.model_dump() for check in checks)
    if any(c.required and c.status != "configured_not_verified" for c in checks):
        report["status"] = "needs_configuration"
    report.update(
        scope="offline_workspace_configuration_only",
        staging_deployed=False,
        owner_login_verified=False,
        backup_restore_verified=False,
        guidance="Verify isolated target identity, backup restore and explicit owner deployment authorization separately. Configuration is never deployment evidence.",
    )
    return report
