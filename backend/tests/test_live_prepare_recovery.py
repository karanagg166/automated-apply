"""Fictional transport failures. No installed native host or browser is changed."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.local_agent.contracts import Command
from backend.app.local_agent.native_host import forward
from backend.tests.test_chrome_profiles import settings


def native_settings():
    return settings(CHROME_NATIVE_MESSAGING_ENABLED=True, JOB_AGENT_API_TOKEN="fictional-native-token")


def test_native_retries_only_confirmed_rollback_with_same_identity(monkeypatch):
    monkeypatch.setattr("backend.app.local_agent.native_host.time.sleep", lambda _: None)
    calls = []
    command = Command(command="get_application_task")

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(503, headers={"X-Automated-Apply-Transaction": "rolled-back"})
        return httpx.Response(200, json={"version": 1, "request_id": str(command.request_id),
            "ok": True, "capability": "extension_task", "data": {"submitted": False}})

    result = forward(command, native_settings(), httpx.Client(transport=httpx.MockTransport(respond)))
    assert result["ok"] and len(calls) == 2 and calls[0] == calls[1]


@pytest.mark.parametrize("command,marker", [("get_application_task", False), ("authorize_form", True), ("record_form_fill", True)])
def test_native_never_replays_ambiguous_or_authorization_operations(command, marker):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503, headers={"X-Automated-Apply-Transaction": "rolled-back"} if marker else {})

    with pytest.raises(ValueError, match="backend_not_ready"):
        forward(Command(command=command), native_settings(), httpx.Client(transport=httpx.MockTransport(respond)))
    assert len(calls) == 1


def test_native_timeout_outcome_is_unknown_and_not_retried():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("fictional timeout")

    with pytest.raises(ValueError, match="backend_timeout"):
        forward(Command(command="get_application_task"), native_settings(), httpx.Client(transport=httpx.MockTransport(respond)))
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("sqlstate,safe", [("55P03", True), ("40001", True), ("40P01", True), ("08006", False), (None, False)])
async def test_database_abort_marker_requires_postgres_proof(monkeypatch, sqlstate, safe):
    from fastapi import HTTPException
    from sqlalchemy.exc import DBAPIError

    from backend.app.db import session as module

    class Session:
        rolled_back = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def connection(self):
            return None

        async def rollback(self):
            self.rolled_back = True

    session = Session()
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    dependency = module.get_db_session()
    await anext(dependency)
    error = DBAPIError("redacted", {}, SimpleNamespace(sqlstate=sqlstate))
    with pytest.raises(HTTPException) as failure:
        await dependency.athrow(error)
    assert session.rolled_back
    assert bool(failure.value.headers) is safe


@pytest.mark.asyncio
async def test_monitor_retains_database_and_liveness_when_api_fails():
    from backend.scripts.monitor_naukri_acceptance import dependency_sample

    async def fail():
        raise TimeoutError("private diagnostic must never escape")

    async def database():
        return {"automation": {"state": "RUNNING", "revision": 3}, "worker_heartbeat_at": "fictional"}

    async def healthy():
        return {"status": "healthy"}

    sample = await dependency_sample(fail, database, healthy, fail)
    assert sample["api"]["status"] == sample["ready"]["status"] == "FAIL"
    assert sample["database"]["status"] == sample["health"]["status"] == "PASS"
    assert "database_agrees" not in sample and "private diagnostic" not in json.dumps(sample)


@pytest.mark.asyncio
async def test_readiness_outage_and_recovery_are_observed_each_time(async_client, monkeypatch):
    import backend.app.main as main

    calls = []

    async def connectivity(*_):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError

    monkeypatch.setattr(main, "database_connectivity", connectivity)
    assert (await async_client.get("/ready")).status_code == 503
    assert (await async_client.get("/health")).status_code == 200
    assert (await async_client.get("/ready")).status_code == 200
    assert len(calls) == 2


async def test_real_readiness_requires_completed_startup_audit(async_client, monkeypatch):
    import backend.app.main as main

    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"ENVIRONMENT": "development"}))
    monkeypatch.setattr(main.app.state, "database_audit_verified", False, raising=False)

    async def forbidden(*_):
        pytest.fail("A runtime probe cannot replace the required startup audit")

    monkeypatch.setattr(main, "database_connectivity", forbidden)
    assert (await async_client.get("/ready")).status_code == 503


@pytest.mark.parametrize("field,value,error", [
    (None, None, None), ("role", "privileged-fixture", "runtime_identity"),
    ("tls", False, "tls_required"), ("access", False, "access_incompatible"),
    ("database", "another-fixture", "identity_mismatch"),
])
async def test_runtime_readiness_requires_identity_tls_and_core_grants(monkeypatch, field, value, error):
    from backend.app.core.config import Settings
    from backend.app.db.safety import database_target
    from backend.app.operations import health

    ref = "luvdmwnlwaqgvfwlmlom"
    config = Settings(_env_file=None, ENVIRONMENT="development", DATABASE_SCHEMA="public",
        DATABASE_URL=f"postgresql+asyncpg://job_agent_runtime:fictional@db.{ref}.supabase.co/postgres",
        SUPABASE_PROJECT_REF=ref, DB_REQUIRE_TLS=True)
    row = {"database": "postgres", "role": "job_agent_runtime", "tls": True, "access": True}
    if field:
        row[field] = value

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, *_):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: row))

    async def no_dns(*_):
        pass

    monkeypatch.setattr(health, "verify_remote_address", no_dns)
    engine = SimpleNamespace(url=database_target(config), connect=Connection)
    if error:
        with pytest.raises(RuntimeError, match=error):
            await health.database_connectivity(engine, config)
    else:
        await health.database_connectivity(engine, config)
