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
    BROWSER_OBSERVED = "browser_session_observed"
    OWNER_ACTION = "owner_action_required"


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
    platform: str | None = None


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
        async with asyncio.timeout(20):
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
            owner_authorization_required=True, safe_next_action="Authenticate owning account; verify TLS and restricted SQL access; review migration bundle. Existing credentials are preserved.")
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
    cli = read_private_evidence(ROOT / "reports/phase1/supabase-cli.private.json")
    cli_verified = (cli.get("project_ref") == settings.SUPABASE_PROJECT_REF
        and cli.get("cli_account_access_verified") is True and cli.get("status") == "ACTIVE_HEALTHY")
    add("Supabase CLI", "core", bool(which("supabase")),
        ConnectionState.VERIFIED if cli_verified else ConnectionState.AUTHORIZATION,
        identity_verification="exact_project_listed" if cli_verified else "unverified",
        capability_verification="management_metadata_only" if cli_verified else "unverified",
        actual_evidence_type="actual_isolated_cli_project_list" if cli_verified else "configuration_inspection",
        last_verification_time=cli.get("verified_at") if cli_verified else None,
        capabilities=["management_metadata"] if cli_verified else [],
        owner_authorization_required=not cli_verified,
        blocker=None if cli_verified else "isolated_cli_project_check_pending",
        safe_next_action="Run supabase_account.py check using the existing private profile; preserve default account.")
    evidence_path = ROOT / "reports/phase1/mcp.private.json"
    mcp_evidence = {}
    try:
        if evidence_path.is_file() and not evidence_path.is_symlink() and not evidence_path.stat().st_mode & 0o077:
            mcp_evidence = json.loads(evidence_path.read_text())
    except (OSError, ValueError):
        pass
    for name in ("Codex Supabase MCP", "VS Code Supabase MCP", "AGY Supabase MCP"):
        verified = name == "Codex Supabase MCP" and mcp_evidence.get("project_url_observed") and mcp_evidence.get("state") == "read_only_results_received"
        vscode = read_private_evidence(ROOT / "reports/phase1/vscode-mcp.private.json") if name.startswith("VS Code") else {}
        if vscode:
            verified = (vscode.get("state") == "verified" and vscode.get("project_url_observed") is True
                and vscode.get("project_ref") == settings.SUPABASE_PROJECT_REF and bool(vscode.get("discovered_tools")))
        client_name = "vs code" if name.startswith("VS Code") else name.split()[0].lower()
        configuration = mcp_evidence.get("client_configurations", {}).get(client_name, {})
        add(name, "core", configured=bool(verified or configuration.get("configured")), state=ConnectionState.VERIFIED if verified else ConnectionState.DISABLED if configuration.get("disabled") else ConnectionState.AUTHORIZATION,
            capabilities=["read_only_project_metadata"] if verified else [],
            actual_evidence_type="actual_vscode_extension_api_no_model" if verified and vscode else "live_cli_mcp_read_only_calls" if verified else "configuration_inspection",
            identity_verification="target_project_url_and_catalog" if verified else "unverified",
            capability_verification="read_only_metadata" if verified else "unverified",
            last_verification_time=(vscode or mcp_evidence).get("verified_at") if verified else None,
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
    from backend.app.local_agent.platforms import platform_connections
    for portal in await platform_connections(session):
        add(portal["name"], "platforms", configured=bool(portal["last_verification_time"]),
            state=ConnectionState(portal["state"]), platform=portal["platform"],
            capabilities=portal["capabilities"], last_verification_time=portal["last_verification_time"],
            actual_evidence_type=portal["evidence_type"],
            identity_verification="account_identity_unverified", capability_verification="manual_handoff_only_no_applicant_api",
            blocker="applicant_api_unsupported_or_unverified_owner_acceptance_pending" if portal["owner_acceptance_required"] else None,
            help_url=portal["login_url"], owner_authorization_required=portal["owner_acceptance_required"],
            safe_next_action="Connect in your Chrome tab, sign in manually, then click Check this portal session in the extension. A visible indicator does not verify account identity or API access.")
    add("LinkedIn", "platforms", state=ConnectionState.MANUAL, capabilities=["manual_handoff", "url_preview"],
        help_url="https://www.linkedin.com/jobs/", safe_next_action="Open official links manually")
    add("Public job sources", "platforms", bool(settings.GREENHOUSE_BOARDS), capabilities=["public_read_adapters"],
        blocker="recurring_discovery_disabled", safe_next_action="Review configured boards and saved filters; separately authorize discovery")
    agy_evidence = read_private_evidence(ROOT / "reports/phase1/agy-smoke-phase1b-owner-approved.private.json") or read_private_evidence(ROOT / "reports/phase1/agy-smoke-owner-approved-followup.private.json") or read_private_evidence(ROOT / "reports/phase1/agy-smoke.private.json")
    agy_diagnostic = read_private_evidence(ROOT / "reports/phase1/agy-schema-diagnostic.private.json")
    agy_diagnostic = read_private_evidence(ROOT / "reports/phase1/agy-protocol.private.json") or agy_diagnostic
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
        latest_error_category=agy_diagnostic.get("error_category") or agy_diagnostic.get("diagnostic_error_code") or agy_evidence.get("error_code"),
        blocker="tool_free_cli_restrictions_unverified" if agy_diagnostic.get("available_tool_count", 0) else "structured_generation_unverified_no_more_requests_authorized", owner_authorization_required=True,
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
    gmail_identity = bool(account and account.status == "connected" and account.last_verified_at
                          and account.account_email == settings.GMAIL_EXPECTED_EMAIL and account.encrypted_refresh_token)
    compose = gmail_identity and "https://www.googleapis.com/auth/gmail.compose" in account.granted_scopes
    add("Gmail identity", "ai", bool(settings.GMAIL_CLIENT_ID),
        ConnectionState.VERIFIED if gmail_identity else ConnectionState.AUTHORIZATION,
        identity_verification="oauth_bound_expected_account" if gmail_identity else "unverified",
        capability_verification="identity_and_encrypted_refresh_storage" if gmail_identity else "unverified",
        last_verification_time=account.last_verified_at if gmail_identity else None,
        actual_evidence_type="persisted_verified_oauth_identity" if gmail_identity else "configuration_inspection",
        owner_authorization_required=not gmail_identity,
        capabilities=["verified_secondary_identity", "encrypted_refresh_storage"] if gmail_identity else [],
        blocker=None if gmail_identity else "identity_consent_required",
        safe_next_action="Preserve secondary identity; compose authorization is tracked separately.")
    add("Gmail compose", "ai", bool(settings.GMAIL_CLIENT_ID),
        ConnectionState.VERIFIED if compose else ConnectionState.AUTHORIZATION,
        identity_verification="oauth_bound_expected_account" if compose else "unverified",
        capability_verification="compose_scope_stored_no_draft_test" if compose else "unverified",
        last_verification_time=account.last_verified_at if compose else None,
        actual_evidence_type="persisted_verified_oauth_scope" if compose else "configuration_inspection",
        owner_authorization_required=not bool(compose),
        capabilities=["draft_scope_granted_sending_disabled"] if compose else [],
        blocker=None if compose else "compose_schema_approval_and_google_consent_pending",
        safe_next_action="Authorize gmail.compose through existing OAuth flow; no drafts or sends in Phase 1",
        help_url="https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create")
    from backend.app.dashboard.models import PrivateResume
    from backend.app.models.application_answer import CandidateResource
    from backend.app.models.candidate_profile import CandidateProfile
    profile = await session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
    resume = await session.scalar(select(CandidateResource).where(CandidateResource.candidate_profile_id == profile.id,
        CandidateResource.resource_type == "resume", CandidateResource.is_primary.is_(True), CandidateResource.user_confirmed.is_(True))) if profile else None
    stored_file = await session.scalar(select(PrivateResume).where(PrivateResume.resource_id == resume.id,
        PrivateResume.confirmed.is_(True))) if resume else None
    from backend.app.dashboard.models import OwnerPreference
    from backend.app.local_agent.profile_confirmation import confirmation_matches
    confirmation = await session.get(OwnerPreference, "phase1_profile_confirmation")
    reviewed = confirmation_matches(profile, confirmation.value if confirmation else {})
    profile_ready = bool(reviewed and profile.verified_skills and profile.verified_experience_years is not None
                         and profile.preferences.get("target_titles") and profile.preferences.get("preferred_locations"))
    add("Candidate profile", "core", bool(profile), ConnectionState.VERIFIED if profile_ready else ConnectionState.OWNER_ACTION,
        identity_verification="owner_confirmed_current_version" if reviewed else "unverified",
        capability_verification="reviewed_required_profile_fields_present" if profile_ready else "profile_review_or_required_fields_missing",
        last_verification_time=confirmation.value.get("confirmed_at") if reviewed else None,
        actual_evidence_type="version_bound_owner_confirmation" if reviewed else "current_sql_inventory_no_personal_details",
        capabilities=["saved_canonical_profile"] if profile else [],
        owner_authorization_required=not profile_ready, blocker=None if profile_ready else "owner_fact_review_pending",
        safe_next_action="Review Profile and Resumes in the dashboard. Confirm skills, experience, roles, locations, URLs and the canonical file. Missing facts are never inferred.")
    integrity = False
    if stored_file and settings.RESUME_ENCRYPTION_KEY:
        import hashlib

        from cryptography.fernet import Fernet, InvalidToken
        try:
            raw = Fernet(settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode()).decrypt(stored_file.ciphertext)
            integrity = raw.startswith(b"%PDF-") and hashlib.sha256(raw).hexdigest() == stored_file.sha256
        except (InvalidToken, ValueError):
            pass
    add("Resume", "core", bool(stored_file), ConnectionState.VERIFIED if integrity else ConnectionState.DEGRADED if stored_file else ConnectionState.OWNER_ACTION,
        identity_verification="owner_confirmed_canonical_file" if stored_file else "unverified",
        capability_verification="decrypted_pdf_hash_verified" if integrity else "canonical_file_unverified",
        actual_evidence_type="current_encrypted_file_integrity_check" if stored_file else "current_sql_inventory_no_personal_details",
        last_verification_time=now if integrity else None,
        capabilities=["private_canonical_resume"] if integrity else [],
        owner_authorization_required=not bool(stored_file),
        blocker=None if integrity else "file_integrity_failed" if stored_file else "canonical_resume_confirmation_pending",
        safe_next_action="Download and review the existing private PDF in Profile; select it and save the reviewed profile. Drive changes require separate fact review.")
    add("Deterministic answers", "ai", True, ConnectionState.VERIFIED,
        capabilities=["grounded_deterministic_answers"], actual_evidence_type="existing_local_implementation",
        capability_verification="local_only")
    return [row.model_dump(mode="json") for row in output]
