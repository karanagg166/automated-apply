"""Real-data execution fails before opening unsafe targets; fixtures stay isolated."""

import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.core.config import Settings
from backend.app.db.safety import (
    DatabaseConfigurationError,
    database_connect_args,
    database_target,
    require_session_target,
    verify_remote_address,
)
from backend.app.operations.configuration import OperationRejected, target_identity
from backend.app.operations.readiness import environment_readiness

REMOTE = "postgresql+asyncpg://owner:private-password@approved.example/postgres"  # pragma: allowlist secret — fictional test only


def config(**overrides):
    return Settings(_env_file=None, **{
        "ENVIRONMENT": "development", "DATABASE_URL": REMOTE, **overrides,
    })


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
@pytest.mark.parametrize("url", ["", "sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite:///owner.sqlite",
                                  "sqlite:///owner.sqlite", "postgresql+asyncpg:///postgres"])
def test_real_data_rejects_missing_or_sqlite_configuration(environment, url):
    with pytest.raises(DatabaseConfigurationError) as exc:
        database_target(config(ENVIRONMENT=environment, DATABASE_URL=url))
    assert "owner.sqlite" not in str(exc.value)


@pytest.mark.parametrize("host", ["localhost", "localhost.", "db.localhost", "db.local", "127.0.0.1",
                                    "0.0.0.0", "[::1]", "[::ffff:127.0.0.1]", "10.0.0.1",
                                    "169.254.169.254", "127.1", "2130706433", "0x7f000001"])
def test_remote_only_rejects_local_targets(host):
    with pytest.raises(DatabaseConfigurationError, match="remote_postgresql_database_required"):
        database_target(config(DATABASE_URL=f"postgresql+asyncpg://owner:private-password@{host}/postgres"))  # pragma: allowlist secret — fictional test only


@pytest.mark.parametrize("suffix", ["?ssl=disable", "?sslmode=disable", "?host=localhost", "#ignored"])
def test_dsn_cannot_override_tls_or_target(suffix):
    with pytest.raises(DatabaseConfigurationError):
        database_target(config(DATABASE_URL=REMOTE + suffix))


def test_remote_development_requires_certificate_verified_tls():
    with pytest.raises(DatabaseConfigurationError, match="tls_required"):
        database_target(config(DB_REQUIRE_TLS=False))
    with pytest.raises(DatabaseConfigurationError, match="tls_required"):
        database_target(config(DB_REQUIRE_TLS=False, DB_REMOTE_ONLY=False))
    args = database_connect_args(config())
    assert args["ssl"].verify_mode == ssl.CERT_REQUIRED and args["ssl"].check_hostname
    assert args["server_settings"]["search_path"] == "job_agent,public"
    assert args["timeout"] == 10


def test_missing_ca_fails_without_disabling_verification():
    assert config(DB_SSL_ROOT_CERT="").DB_SSL_ROOT_CERT is None
    with pytest.raises(DatabaseConfigurationError, match="tls_certificate_unavailable"):
        database_connect_args(config(DB_SSL_ROOT_CERT="/no-such-private-ca.pem"))


async def test_remote_dns_cannot_resolve_to_local_postgresql(monkeypatch):
    import asyncio
    import socket

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5432)),
    ]))
    with pytest.raises(DatabaseConfigurationError, match="dns_resolves_locally"):
        await verify_remote_address(config())


def test_transaction_pooler_requires_explicit_compatibility_work():
    with pytest.raises(DatabaseConfigurationError, match="session_pooler"):
        database_target(config(DATABASE_URL=REMOTE.replace("/postgres", ":6543/postgres")))


def test_sqlite_is_only_an_explicit_test_fixture():
    settings = config(ENVIRONMENT="testing", DATABASE_URL="sqlite+aiosqlite:///:memory:")
    assert database_target(settings).drivername == "sqlite+aiosqlite"
    assert database_connect_args(settings) == {}


def test_missing_database_has_no_default_local_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL")
    settings = Settings(_env_file=None, ENVIRONMENT="development")
    assert settings.DATABASE_URL == ""
    assert environment_readiness(settings).status == "needs_configuration"


def test_cached_factory_cannot_bypass_database_safety(monkeypatch):
    import backend.app.db.session as module

    monkeypatch.setattr(module, "get_settings", lambda: config(DATABASE_URL="sqlite+aiosqlite:///owner.sqlite"))
    monkeypatch.setattr(module, "create_async_engine", lambda *a, **kw: pytest.fail("Must reject before creating any engine"))
    for getter in (module.get_engine, module.get_session_factory):
        with pytest.raises(DatabaseConfigurationError):
            getter()


def test_session_pooler_project_is_part_of_target_identity():
    one = config(DATABASE_URL="postgresql+asyncpg://postgres.project_one:private@pooler.example/postgres")
    two = config(DATABASE_URL="postgresql+asyncpg://postgres.project_two:private@pooler.example/postgres")
    assert target_identity(one) != target_identity(two)
    rotated = one.model_copy(update={"DATABASE_URL": one.DATABASE_URL.replace(":private@", ":rotated@")})
    assert target_identity(one) == target_identity(rotated)


def test_cached_sqlite_engine_cannot_be_reused_after_remote_configuration(monkeypatch):
    import backend.app.db.session as module

    monkeypatch.setattr(module, "get_settings", lambda: config())
    for getter in (module.get_engine, module.get_session_factory):
        with pytest.raises(DatabaseConfigurationError, match="target_changed_restart_required"):
            getter()


async def test_resume_cannot_use_an_injected_sqlite_session_for_real_data(db_session):
    with pytest.raises(DatabaseConfigurationError, match="session_database_target_mismatch"):
        require_session_target(db_session, config())


async def test_development_startup_aborts_when_database_probe_fails(monkeypatch):
    import backend.app.main as main

    monkeypatch.setattr(main, "settings", config())
    monkeypatch.setattr(main, "get_engine", lambda: object())
    monkeypatch.setattr(main, "database_health", AsyncMock(side_effect=RuntimeError(REMOTE)))
    close = AsyncMock()
    monkeypatch.setattr(main, "close_db_engine", close)
    with pytest.raises(RuntimeError, match="^Database startup probe failed$"):
        async with main.lifespan(main.app):
            pytest.fail("An unavailable remote database must never reach API readiness")
    close.assert_awaited_once()


async def test_live_local_pilots_cannot_create_sqlite_state(tmp_path):
    from backend.scripts import (
        local_public_pilot,
        public_source_smoke,
        startup_discovery_demo,
    )

    with pytest.raises(OperationRejected, match="online_postgresql_required"):
        await local_public_pilot.execute(SimpleNamespace(authorize_public_read=True, state_dir=str(tmp_path / "state")))
    assert not (tmp_path / "state").exists()
    with pytest.raises(OperationRejected, match="online_postgresql_required"):
        await public_source_smoke.main()
    with pytest.raises(OperationRejected, match="online_postgresql_required"):
        await startup_discovery_demo.demo(SimpleNamespace(live=True))
