"""Evidence-based connection center. Configuration never means authenticated."""
from datetime import datetime, timezone
from enum import StrEnum
from shutil import which

from pydantic import Field
from sqlalchemy import select

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


async def connection_report(session, settings, *, api_request=False):
    now = datetime.now(timezone.utc)
    output = []

    def add(name, group, configured=False, state=None, **kwargs):
        output.append(Connection(name=name, group=group,
            configuration_status="configured" if configured else "not_configured",
            state=state or observed_state(configured=configured), **kwargs))

    try:
        from backend.app.db.session import get_engine
        from backend.app.operations.health import database_health
        evidence = await database_health(get_engine(), settings)
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
    for name in ("Chrome extension", "Native messaging host"):
        add(name, "core", settings.CHROME_NATIVE_MESSAGING_ENABLED,
            ConnectionState.AUTHENTICATED if native else ConnectionState.AUTHORIZATION,
            identity_verification="configured_extension_origin" if native else "unverified",
            actual_evidence_type="authenticated_bridge_request" if native else "configuration_inspection",
            capability_verification="bridge_only_real_chrome_install_unverified" if native else "unverified",
            last_verification_time=native.created_at if native else None,
            owner_authorization_required=not bool(native) or name == "Chrome extension", capabilities=["url_preview"],
            safe_next_action="Load unpacked extension in real Chrome; install host with displayed extension ID; right-click test")
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
    agy_evidence = {}
    try:
        smoke = ROOT / "reports/phase1/agy-smoke.private.json"
        if smoke.is_file() and not smoke.is_symlink() and not smoke.stat().st_mode & 0o077:
            agy_evidence = json.loads(smoke.read_text())
    except (OSError, ValueError):
        pass
    agy_failed = agy_evidence.get("state") == "failed_no_retry"
    add("AGY CLI", "ai", bool(which(settings.AGY_EXECUTABLE)),
        ConnectionState.DEGRADED if agy_failed else ConnectionState.CREDENTIALS if which(settings.AGY_EXECUTABLE) else ConnectionState.NOT_CONFIGURED,
        capabilities=["structured_answer_adapter"], may_consume_paid_credits=True,
        actual_evidence_type="interrupted_fictional_cli_attempt" if agy_failed else "configuration_inspection",
        last_verification_time=agy_evidence.get("timestamp"),
        latest_error_category=agy_evidence.get("error_code"),
        blocker="restricted_profile_and_quota_authorization_required", owner_authorization_required=True)
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
