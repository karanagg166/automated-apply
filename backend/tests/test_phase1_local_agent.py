"""Offline contract/security tests. SQLite here is a disposable test fixture only."""
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.ai.base import ProviderError
from backend.app.ai.providers.agy import (
    AGENT,
    AgyProvider,
    bounded_process,
    parse_output,
)
from backend.app.core.config import Settings
from backend.app.db.safety import DatabaseConfigurationError, database_target
from backend.app.local_agent.contracts import PolicyUpdate, page_kind
from backend.app.local_agent.models import (
    PolicyEvent,
)
from backend.app.local_agent.policies import (
    evaluate,
    get_policy,
    initial_policy,
    update_policy,
)
from backend.app.local_agent.public_database import verify_bundle
from backend.app.local_agent.registry import Connection, ConnectionState


def settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize("field,value", [("LOCAL_AGENT_ENDPOINT", "http://0.0.0.0:8000"), ("LOCAL_AGENT_ENDPOINT", "https://evil.example:8000"), ("LOCAL_AGENT_ENDPOINT", "http://127.0.0.1:8000/path"), ("CHROME_EXTENSION_ID", "*"), ("AGY_MODEL", "--run-command"), ("TELEGRAM_OWNER_USER_ID", -1), ("APPLICATION_SUBMISSION_ENABLED", True)])
def test_environment_rejections(field, value):
    with pytest.raises(ValidationError):
        settings(**{field: value})


@pytest.mark.parametrize("url,kind", [("https://docs.google.com/forms/d/e/fictional/viewform", "google_forms"), ("https://forms.gle/example", "google_forms"), ("https://docs.google.com.evil.example/forms/", "employer_forms"), ("https://www.naukri.com/job/123", "naukri"), ("https://example.org/jobs/123", "employer_forms")])
def test_page_classification(url, kind):
    assert page_kind(url) == kind


@pytest.mark.asyncio
async def test_policies_versions_and_audit(db_session):
    current = await get_policy(db_session)
    current["platforms"]["naukri"] = "disabled"
    value = PolicyUpdate(expected_version=current["version"], default=current["default"], platforms=current["platforms"])
    saved = await update_policy(db_session, value)
    assert saved["version"] == 2
    assert await db_session.scalar(select(func.count()).select_from(PolicyEvent)) == 1
    with pytest.raises(ValueError, match="policy_version_conflict"):
        await update_policy(db_session, value)
    assert (await get_policy(db_session))["platforms"]["naukri"] == "disabled"


@pytest.mark.parametrize("platform", ["gmail", "linkedin", "naukri", "google_forms"])
@pytest.mark.parametrize("preference", ["approve", "automatic_preferred", "draft_only", "manual_only", "disabled"])
def test_capabilities_override_preferences(platform, preference):
    policy = initial_policy()
    policy["platforms"][platform] = preference
    result = evaluate(policy, platform, "unverified")
    assert result["submission_allowed"] is False
    assert result["email_send_allowed"] is False
    assert result["paid_calls_allowed"] is False
    assert result["preview_allowed"] == (preference != "disabled")


@pytest.mark.asyncio
async def test_api_auth_identity_policy_and_history(async_client, phase2_auth):
    assert (await async_client.get("/api/v1/local-agent/policy")).status_code == 401
    # The extension/native command routes were retired in Phase 9E.
    for path in ("/api/v1/local-agent/chrome", "/api/v1/local-agent/commands"):
        assert (await async_client.post(path, headers=phase2_auth, json={})).status_code in {404, 405}
    history = await async_client.get("/api/v1/local-agent/history", headers=phase2_auth)
    assert history.status_code == 200 and history.json() == []
    headers = phase2_auth | {"X-Agent-Client": "a" * 32}
    policy = initial_policy() | {"expected_version": 1}
    assert (await async_client.put("/api/v1/local-agent/policy", headers=headers, json=policy)).status_code == 403
    saved = await async_client.put("/api/v1/local-agent/policy", headers=phase2_auth, json=policy)
    assert saved.status_code == 200 and saved.json()["version"] == 2


def model_answer():
    reference = {"source_type": "candidate_evidence", "source_id": "fictional-1"}
    return {"answer": "I built a fictional Python service.", "evidence_references": [reference], "claims": [{"text": "I built a fictional Python service.", "source": reference, "quote": "built a fictional Python service"}]}


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b'{}', b'{"answer":"invented"}', b'{"tool_calls":["run_shell"]}', b'{"response":{},"usage":[]}', b'null\n[]', b"x" * 65537])
def test_agy_bad_output(raw):
    with pytest.raises(ProviderError):
        parse_output(raw)


@pytest.mark.asyncio
async def test_agy_fake_process_security_and_contract():
    calls = []
    async def runner(argv, payload, cwd, env, timeout):
        from pathlib import Path
        calls.append(argv)
        assert "--sandbox" in argv and "--disable-slash-commands" in argv
        assert "--dangerously-skip-permissions" not in argv
        assert argv[argv.index("--effort") + 1] == "high"
        assert "--input-format" in argv and "fictional" in payload
        assert "DATABASE_URL" not in env and "TELEGRAM_BOT_TOKEN" not in env
        agent = Path(cwd) / ".agents/agents/automated-apply-answer.md"
        assert agent.read_text() == AGENT and "tools: []" in AGENT and "subagent: false" in AGENT
        return json.dumps({"result": model_answer(), "usage": {"input_tokens": 10, "output_tokens": 20}}).encode()
    config = settings(AGY_ENABLED=True, AGY_QUOTA_AUTHORIZED=True, AGY_MODEL="fictional-high", AGY_EXECUTABLE="/usr/bin/true")
    provider = AgyProvider(config, runner)
    result = await provider.generate_structured_answer("fictional skill", {}, {"style_instruction": "concise", "max_characters": 500})
    assert len(calls) == 1 and result.usage.input_tokens == 10


@pytest.mark.asyncio
async def test_agy_no_unapproved_call():
    async def forbidden(*args):
        pytest.fail("no quota authorization must not execute CLI")
    with pytest.raises(ProviderError, match="not_authorized"):
        await AgyProvider(settings(), forbidden).generate_structured_answer("fictional", {}, {})


@pytest.mark.asyncio
async def test_agy_missing_private_profile_fails_before_cli(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configuration = tmp_path / ".gemini/antigravity-cli/settings.json"
    configuration.parent.mkdir(parents=True)
    configuration.write_text('{}')
    config = settings(AGY_ENABLED=True, AGY_QUOTA_AUTHORIZED=True,
        AGY_MODEL="fictional-high", AGY_EXECUTABLE="/usr/bin/true")
    with pytest.raises(ProviderError, match="restricted_agent_profile_unavailable"):
        await AgyProvider(config).generate_structured_answer("fictional", {}, {"style_instruction": "concise", "max_characters": 500})


@pytest.mark.parametrize("configuration", [{"useG1Credits": True}, {"modelProvider": "gemini"}, {"gcp": {"project": "fictional"}}, {"customModelsConfig": {"models": []}}])
def test_agy_paid_billing_configuration_rejected(tmp_path, configuration):
    from backend.app.ai.providers.agy import verify_no_overage
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(configuration))
    with pytest.raises(ProviderError, match="paid_overage_configuration_forbidden"):
        verify_no_overage(path)


def test_agy_no_overage_documented_default_and_explicit_false(tmp_path):
    from backend.app.ai.providers.agy import verify_no_overage
    path = tmp_path / "settings.json"
    for value in ({}, {"useG1Credits": False}):
        path.write_text(json.dumps(value))
        assert verify_no_overage(path)["useG1Credits"] is False


@pytest.mark.asyncio
async def test_agy_timeout_and_exit(tmp_path):
    import sys
    with pytest.raises(ProviderError, match="timeout"):
        await bounded_process([sys.executable, "-c", "import time; time.sleep(10)"], "", str(tmp_path), {}, .05)
    with pytest.raises(ProviderError, match="cli_nonzero_exit"):
        await bounded_process([sys.executable, "-c", "raise SystemExit(2)"], "", str(tmp_path), {}, 2)


def test_public_schema_pins_and_bundle():
    assert verify_bundle()["schema"] == "public"
    with pytest.raises(DatabaseConfigurationError, match="wrong_supabase_project"):
        database_target(settings(ENVIRONMENT="development", DATABASE_SCHEMA="public", DATABASE_URL="postgresql+asyncpg://job_agent_runtime:fake@db.wrong.supabase.co:5432/postgres"))
    with pytest.raises(DatabaseConfigurationError, match="privileged_runtime_role_forbidden"):
        database_target(settings(ENVIRONMENT="development", DATABASE_SCHEMA="public", DATABASE_URL="postgresql+asyncpg://postgres:fake@db.luvdmwnlwaqgvfwlmlom.supabase.co:5432/postgres"))


def test_database_tls_failure_is_fixed_code(monkeypatch):
    import ssl

    from backend.app.db.safety import database_connect_args
    def fail(*args, **kwargs):
        raise ssl.SSLError("private certificate path must not escape")
    monkeypatch.setattr(ssl, "create_default_context", fail)
    config = settings(ENVIRONMENT="development", DATABASE_SCHEMA="public", DATABASE_URL="postgresql+asyncpg://job_agent_runtime:fake@db.luvdmwnlwaqgvfwlmlom.supabase.co:5432/postgres")
    with pytest.raises(DatabaseConfigurationError, match="^database_tls_certificate_unavailable$"):
        database_connect_args(config)


@pytest.mark.parametrize("state", list(ConnectionState))
def test_registry_serializes_all_required_states(state):
    row = Connection(name="fictional", group="core", configuration_status="not_configured", state=state)
    assert row.model_dump(mode="json")["state"] == state.value


def test_registry_evidence_transitions_never_promote_key_presence():
    from backend.app.local_agent.registry import observed_state
    assert observed_state(configured=False) == ConnectionState.NOT_CONFIGURED
    assert observed_state(configured=True) == ConnectionState.CREDENTIALS
    assert observed_state(configured=True, capability_verified=True) == ConnectionState.CREDENTIALS
    assert observed_state(configured=True, owner_authorization=True) == ConnectionState.AUTHORIZATION
    assert observed_state(configured=True, identity_verified=True) == ConnectionState.AUTHENTICATED
    assert observed_state(configured=True, identity_verified=True, capability_verified=True) == ConnectionState.VERIFIED
    assert observed_state(configured=True, error=True, was_verified=True) == ConnectionState.DEGRADED
    assert observed_state(configured=False, was_verified=True) == ConnectionState.DISCONNECTED
    assert observed_state(configured=True, enabled=False, identity_verified=True, capability_verified=True) == ConnectionState.DISABLED


@pytest.mark.asyncio
async def test_search_preferences_persist_without_discovery(async_client, phase2_auth):
    payload = {"target_titles": ["Backend Engineer"], "technology_stacks": ["Python"],
        "minimum_experience": 1, "maximum_experience": 3, "minimum_employees": 2,
        "maximum_employees": 10, "excluded_companies": ["Fictional Blocked Labs"],
        "employment_types": ["full_time"], "remote_preference": "remote",
        "minimum_salary": 1000, "maximum_salary": 2000, "salary_currency": "INR",
        "salary_period": "month", "source_platforms": ["greenhouse"], "saved_jobs_only": True}
    saved = await async_client.put("/api/v1/local-agent/search-preferences", headers=phase2_auth, json=payload)
    assert saved.status_code == 200
    loaded = await async_client.get("/api/v1/local-agent/search-preferences", headers=phase2_auth)
    assert all(loaded.json()[key] == value for key, value in payload.items())
    assert loaded.json()["duplicate_prevention"] and loaded.json()["require_known_properties"]
    assert (await async_client.put("/api/v1/local-agent/search-preferences", headers=phase2_auth, json=payload | {"maximum_experience": 0})).status_code == 422
    assert (await async_client.put("/api/v1/local-agent/search-preferences", headers=phase2_auth, json={"duplicate_prevention": False})).status_code == 422


@pytest.mark.asyncio
async def test_gmail_compose_uses_no_send_scope():
    from urllib.parse import parse_qs, urlsplit

    from backend.app.integrations.google_oauth import (
        COMPOSE_SCOPES,
        SEND_SCOPE,
        GoogleOAuth,
    )
    config = settings(GMAIL_CLIENT_ID="fictional-client", GMAIL_CLIENT_SECRET="fictional-secret",
        GMAIL_REDIRECT_URI="http://127.0.0.1:8000/api/v1/integrations/gmail/oauth/callback")
    url = GoogleOAuth(config).authorization_url("fictional-state", "fictional-verifier", "alex@example.org", compose=True)
    scopes = set(parse_qs(urlsplit(url).query)["scope"][0].split())
    assert scopes == COMPOSE_SCOPES and SEND_SCOPE not in scopes


@pytest.mark.parametrize("trusted", [[], ["/different"], "invalid"])
def test_agy_workspace_trust_cannot_be_inferred(monkeypatch, tmp_path, trusted):
    from pathlib import Path

    from backend.app.ai.providers.agy import verify_workspace_authorization
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configuration = tmp_path / ".gemini/antigravity-cli/settings.json"
    configuration.parent.mkdir(parents=True)
    configuration.write_text(json.dumps({"trustedWorkspaces": trusted}))
    with pytest.raises(ProviderError, match="owner_workspace_authorization_required"):
        verify_workspace_authorization(tmp_path / "dedicated")
    configuration.write_text(json.dumps({"trustedWorkspaces": [str(tmp_path / "dedicated")]}))
    verify_workspace_authorization(tmp_path / "dedicated")


def test_connection_evidence_requires_private_regular_bounded_json(tmp_path):
    from backend.app.local_agent.registry import read_private_evidence
    path = tmp_path / "proof.json"
    path.write_text('{"authenticated_read_verified":true}')
    path.chmod(0o644)
    assert read_private_evidence(path) == {}
    path.chmod(0o600)
    assert read_private_evidence(path)["authenticated_read_verified"] is True
    link = tmp_path / "link.json"
    link.symlink_to(path)
    assert read_private_evidence(link) == {}
    path.write_text("x" * 65537)
    assert read_private_evidence(path) == {}


