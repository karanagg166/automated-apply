"""Evidence-based connection center. Configuration never means authenticated."""
import asyncio
from datetime import datetime, timezone
from enum import StrEnum
from shutil import which

from pydantic import Field
from sqlalchemy import select, text

from backend.app.local_agent.contracts import StrictModel
from backend.app.local_agent.models import AgentOperation, TelegramState


class ConnectionState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CREDENTIALS = "credentials_configured"
    AUTHORIZATION = "owner_authorization_required"
    AUTHENTICATED = "authenticated"
    VERIFIED = "capability_verified"
    MANUAL = "manual_only"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    DISABLED = "disabled"


def observed_state(*, configured, enabled=True, identity_verified=False, capability_verified=False,
                   error=False, was_verified=False, owner_authorization=False):
    """Derive each transition from current evidence, never from a key's presence."""
    if not enabled:
        return ConnectionState.DISABLED
    if error:
        return ConnectionState.DEGRADED if configured else ConnectionState.DISCONNECTED
    if not configured:
        return ConnectionState.DISCONNECTED if was_verified else ConnectionState.NOT_CONFIGURED
    if owner_authorization:
        return ConnectionState.AUTHORIZATION
    if identity_verified and capability_verified:
        return ConnectionState.VERIFIED
    if identity_verified:
        return ConnectionState.AUTHENTICATED
    return ConnectionState.CREDENTIALS


class Connection(StrictModel):
    name: str
    group: str
    configuration_status: str
    state: ConnectionState
    identity_verification: str = "unverified"
    capability_verification: str = "unverified"
    capabilities: list[str] = Field(default_factory=list)
    last_verification_time: datetime | None = None
    actual_evidence_type: str = "configuration_inspection"
    blocker: str | None = None
    latest_error_category: str | None = None
    owner_authorization_required: bool = False
    may_consume_paid_credits: bool = False
    safe_next_action: str = "Review docs/phase1/setup.md"
    help_url: str | None = None


def read_private_evidence(path):
    import json
    try:
        if (path.is_file() and not path.is_symlink() and not path.stat().st_mode & 0o077
                and path.stat().st_size <= 65536):
            value = json.loads(path.read_text())
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


async def connection_report(session, settings, *, api_request=False):
    now = datetime.now(timezone.utc)
    output = []

    def add(name, group, configured=False, state=None, **kwargs):
        output.append(Connection(name=name, group=group,
            configuration_status="configured" if configured else "not_configured",
            state=state or observed_state(configured=configured), **kwargs))

    try:
        from backend.app.db.safety import require_session_target, verify_remote_address
        # A dispatched command may already hold the sole pooled connection.
        # Reuse that authenticated session and run the same public catalog/RLS/TLS
        # checks; opening another engine connection would deadlock small pools.
        async with asyncio.timeout(10):
            require_session_target(session, settings)
            await verify_remote_address(settings)
            await session.execute(text("SELECT 1"))
            evidence = None
            if settings.ENVIRONMENT != "testing" and settings.DATABASE_SCHEMA == "public":
                from backend.app.local_agent.public_database import (
                    verify_public_database,
                )
                connection = await session.connection()
                raw = await connection.get_raw_connection()
                evidence = await verify_public_database(raw.driver_connection, settings)
        real = settings.ENVIRONMENT != "testing" and settings.DB_REMOTE_ONLY and evidence is not None
        add("Supabase PostgreSQL", "core", bool(settings.DATABASE_URL),
            ConnectionState.VERIFIED if real else ConnectionState.DEGRADED,
            identity_verification="runtime_project_pin" if real else "test_database_only",
            capability_verification="restricted_sql" if real else "test_only",
            actual_evidence_type="live_tls_catalog_probe" if real else "disposable_test",
            last_verification_time=now, capabilities=["persistence", "private_sql"],
            owner_authorization_required=not real,
            blocker=None if real else "dedicated_live_database_authorization_pending")
    except Exception:
        add("Supabase PostgreSQL", "core", bool(settings.DATABASE_URL), ConnectionState.AUTHORIZATION,
            blocker="owner_authorization_required", latest_error_category="database_not_ready",
            owner_authorization_required=True, safe_next_action="Authenticate owning account; rotate credentials; review migration bundle")
    api_verified = api_request
    if not api_verified:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(settings.LOCAL_AGENT_ENDPOINT + "/health")
                api_verified = response.status_code == 200 and response.json().get("service") == "job-pulse-agent-api"
        except Exception:
            api_verified = False
    add("Local FastAPI", "core", True,
        ConnectionState.VERIFIED if api_verified else ConnectionState.DISCONNECTED,
        capability_verification="current_request" if api_request else "loopback_health_probe" if api_verified else "unverified",
        identity_verification="owner_bearer_verified" if api_request else "loopback_service_probe_only",
        actual_evidence_type="current_authenticated_api_request" if api_request else "loopback_health_probe",
        last_verification_time=now if api_verified else None, capabilities=["preview_commands"])
    import json

    from backend.app.operations.migrations import ROOT
    evidence_path = ROOT / "reports/phase1/mcp.private.json"
    mcp_evidence = {}
    try:
        if evidence_path.is_file() and not evidence_path.is_symlink() and not evidence_path.stat().st_mode & 0o077:
            mcp_evidence = json.loads(evidence_path.read_text())
    except (OSError, ValueError):
        pass
    for name in ("Codex Supabase MCP", "Claude Supabase MCP", "AGY Supabase MCP"):
        verified = name == "Codex Supabase MCP" and mcp_evidence.get("project_url_observed") and mcp_evidence.get("state") == "read_only_results_received"
        client_name = name.split()[0].lower()
        configuration = mcp_evidence.get("client_configurations", {}).get(client_name, {})
        add(name, "core", configured=bool(verified or configuration.get("configured")), state=ConnectionState.VERIFIED if verified else ConnectionState.DISABLED if configuration.get("disabled") else ConnectionState.AUTHORIZATION,
            capabilities=["read_only_project_metadata"] if verified else [],
            actual_evidence_type="live_cli_mcp_read_only_calls" if verified else "configuration_inspection",
            identity_verification="target_project_url_and_catalog" if verified else "unverified",
            capability_verification="read_only_metadata" if verified else "unverified",
            last_verification_time=mcp_evidence.get("verified_at") if verified else None,
            owner_authorization_required=not bool(verified), blocker=None if verified else "oauth_tool_discovery_not_verified",
            safe_next_action="Run named client OAuth and read-only verification; see setup guide")
    native = await session.scalar(select(AgentOperation).where(AgentOperation.actor.like("chrome:%")).order_by(AgentOperation.created_at.desc()).limit(1))
    owner_chrome = read_private_evidence(ROOT / "reports/phase1/owner-chrome.private.json")
    owner_operation = None
    if settings.CHROME_EXTENSION_ID and owner_chrome.get("correlation_id") and owner_chrome.get("submitted") is False:
        owner_operation = await session.scalar(select(AgentOperation).where(
            AgentOperation.result["correlation_id"].as_string() == owner_chrome["correlation_id"],
            AgentOperation.actor == "chrome:" + settings.CHROME_EXTENSION_ID))
    for name in ("Chrome extension", "Native messaging host"):
        add(name, "core", settings.CHROME_NATIVE_MESSAGING_ENABLED,
            ConnectionState.VERIFIED if owner_operation else ConnectionState.AUTHENTICATED if native else ConnectionState.AUTHORIZATION,
            identity_verification="configured_extension_origin" if native else "unverified",
            actual_evidence_type="owner_Chrome_result_correlated_with_backend_audit" if owner_operation else "authenticated_bridge_request" if native else "configuration_inspection",
            capability_verification="owner_reported_Chrome_preview" if owner_operation else "bridge_only_real_chrome_install_unverified" if native else "unverified",
            last_verification_time=owner_operation.created_at if owner_operation else native.created_at if native else None,
            owner_authorization_required=not bool(owner_operation), capabilities=["url_preview"],
            safe_next_action="Google Form and restart acceptance pending; see verification guide" if owner_operation else "Load unpacked extension in real Chrome; install host with displayed extension ID; right-click test")
    poll = await session.get(TelegramState, "primary")
    fresh = bool(poll and poll.evidence_type == "live_poll" and poll.last_poll_at and (now - poll.last_poll_at.replace(tzinfo=timezone.utc)).total_seconds() < 90)
    add("Telegram worker", "core", bool(settings.TELEGRAM_BOT_TOKEN),
        ConnectionState.AUTHENTICATED if fresh else ConnectionState.DISCONNECTED if poll else None,
        identity_verification="getMe_bot_id_verified" if poll and poll.bot_id and poll.evidence_type == "live_poll" else "unverified",
        actual_evidence_type=poll.evidence_type if poll else "configuration_inspection",
        last_verification_time=poll.last_poll_at if poll else None,
        latest_error_category=poll.last_error if poll else None, capabilities=["private_commands", "preview_only"],
        safe_next_action="Configure private bot and numeric owner IDs; start worker; /ping; locked-screen test pending")
    for name, url in (
        ("Naukri", "https://www.naukri.com/"), ("Wellfound", "https://wellfound.com/jobs"),
        ("Instahyre", "https://www.instahyre.com/"), ("YC Work at a Startup", "https://www.workatastartup.com/"),
        ("Internshala", "https://internshala.com/"), ("LinkedIn", "https://www.linkedin.com/jobs/"),
    ):
        add(name, "platforms", state=ConnectionState.MANUAL, capabilities=["manual_application", "url_preview"],
            blocker="authorized_applicant_submission_api_unverified", help_url=url,
            safe_next_action="Open official site manually; no password/session collection")
    add("Public job sources", "platforms", bool(settings.GREENHOUSE_BOARDS), capabilities=["public_read_adapters"],
        blocker="recurring_discovery_disabled", safe_next_action="Review configured boards and saved filters; separately authorize discovery")
    agy_evidence = read_private_evidence(ROOT / "reports/phase1/agy-smoke-owner-approved-followup.private.json") or read_private_evidence(ROOT / "reports/phase1/agy-smoke.private.json")
    agy_auth = read_private_evidence(ROOT / "reports/phase1/agy-auth.private.json")
    agy_authenticated = agy_auth.get("authenticated_read_verified") is True and agy_auth.get("num_turns") == 0
    agy_failed = agy_evidence.get("state") == "failed_no_retry"
    add("AGY CLI", "ai", bool(which(settings.AGY_EXECUTABLE)),
        ConnectionState.DEGRADED if agy_failed else ConnectionState.AUTHENTICATED if agy_authenticated else ConnectionState.CREDENTIALS if which(settings.AGY_EXECUTABLE) else ConnectionState.NOT_CONFIGURED,
        identity_verification="authenticated_quota_metadata_read" if agy_authenticated else "unverified",
        capability_verification="authentication_only_generation_unverified" if agy_authenticated else "unverified",
        capabilities=["structured_answer_adapter"], may_consume_paid_credits=True,
        actual_evidence_type="actual_cli_usage_zero_model_turns_and_failed_generation" if agy_authenticated else "failed_fictional_cli_attempt" if agy_failed else "configuration_inspection",
        last_verification_time=agy_auth.get("verified_at") or agy_evidence.get("timestamp"),
        latest_error_category=agy_evidence.get("error_code"),
        blocker="structured_generation_unverified_no_more_requests_authorized", owner_authorization_required=True,
        safe_next_action="Metadata checks only; do not make further generation requests without explicit owner authorization")
    for name, configured, cost, capabilities in (
        ("Ollama", bool(which("ollama")), False, ["local_generation_if_model_installed"]),
        ("Gemini", bool(settings.GEMINI_API_KEY), True, ["structured_answers"]),
        ("Cohere", False, True, []),
        ("Apollo", bool(settings.APOLLO_API_KEY), True, ["cached_contacts", "enrichment_requires_approval"]),
        ("SignalHire", bool(settings.SIGNALHIRE_API_KEY), True, ["cached_contacts", "enrichment_requires_approval"]),
    ):
        add(name, "ai", configured, capabilities=capabilities, may_consume_paid_credits=cost,
            blocker="free_entitlement_unverified" if cost else "model_and_service_unverified")
    from backend.app.models.connected_account import ConnectedAccount
    account = await session.scalar(select(ConnectedAccount).where(ConnectedAccount.provider == "gmail"))
    add("Gmail", "ai", bool(settings.GMAIL_CLIENT_ID),
        ConnectionState.AUTHENTICATED if account and account.status == "connected" else ConnectionState.AUTHORIZATION,
        owner_authorization_required=not bool(account and account.status == "connected"),
        capabilities=["future_draft_only"], blocker="draft_scope_and_creation_consent_required",
        safe_next_action="Authorize gmail.compose through existing OAuth flow; no drafts or sends in Phase 1",
        help_url="https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create")
    add("Deterministic answers", "ai", True, ConnectionState.VERIFIED,
        capabilities=["grounded_deterministic_answers"], actual_evidence_type="existing_local_implementation",
        capability_verification="local_only")
    return [row.model_dump(mode="json") for row in output]
