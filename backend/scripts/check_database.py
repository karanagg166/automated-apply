"""Read-only runtime connectivity and migration compatibility evidence. Never DDL."""

import argparse
import asyncio
import json
import socket
import ssl
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import configure_operator
from backend.app.db.safety import (
    DatabaseConfigurationError,
    database_target,
    local_target,
)
from backend.app.db.session import close_db_engine, get_engine
from backend.app.operations.configuration import load_settings, target_identity


def diagnostic_error(exc):
    """Return fixed codes only, including for nested driver/TLS exceptions."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, DatabaseConfigurationError):
            return str(exc)  # This class only contains fixed, credential-free codes.
        if isinstance(exc, ssl.SSLError):
            return "database_tls_failed"
        code = getattr(exc, "sqlstate", None)
        if code and code.startswith("28"):
            return "database_authentication_failed"
        if code == "42501":
            return "database_permission_denied"
        if isinstance(exc, (TimeoutError, ConnectionError, socket.gaierror)):
            return "database_network_failed"
        if isinstance(exc, RuntimeError) and str(exc) in {
            "database_schema_migration_or_grants_incompatible",
            "database_runtime_access_incompatible", "database_runtime_dml_permissions_missing",
            "database_identity_mismatch", "database_engine_target_mismatch",
            "database_runtime_role_authority_incompatible",
            "database_runtime_schema_permissions_incompatible",
            "database_runtime_table_inventory_incompatible",
            "database_runtime_table_permissions_incompatible",
            "database_runtime_shared_grants_incompatible",
            "database_runtime_cross_schema_access_incompatible",
            "database_runtime_function_access_incompatible",
        }:
            return str(exc)
        exc = getattr(exc, "orig", None) or exc.__cause__ or exc.__context__
    return "database_configuration_connection_or_schema_incompatible"


async def run(env_file):
    settings = load_settings(env_file)
    target = database_target(settings)
    if settings.ENVIRONMENT == "testing":
        raise ValueError("runtime_database_check_requires_non_test_configuration")
    configure_operator(settings)
    # ORM metadata must be imported after choosing the explicit operator config.
    from backend.app.operations.health import database_health

    evidence = {"actual_connection_verified": False, "ddl_executed": False,
                "remote_postgresql_verified": False}
    try:
        engine = get_engine()
        # Establish connectivity independently of application-schema readiness.
        from backend.app.db.safety import verify_remote_address

        await verify_remote_address(settings)
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            identity = (await connection.execute(text("""
                SELECT current_database() AS database,
                       current_setting('server_version') AS version,
                       EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent') AS schema_exists
            """))).mappings().one()
            evidence.update(actual_connection_verified=True,
                remote_postgresql_verified=not local_target(target.host),
                postgresql_version=identity["version"], target_id=target_identity(settings))
            if identity["database"] != target.database:
                return {**evidence, "status": "blocked", "error": "database_identity_mismatch"}
            if not identity["schema_exists"]:
                return {**evidence, "status": "blocked", "error": "database_schema_missing"}
        return {**evidence, **(await database_health(engine, settings)), "status": "ready"}
    except Exception as exc:
        return {**evidence, "status": "blocked", "error": diagnostic_error(exc)}
    finally:
        await close_db_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.env_file))
        print(json.dumps(result))
        code = 0 if result["status"] == "ready" else 2
    except Exception as exc:
        print(json.dumps({"actual_connection_verified": False, "ddl_executed": False,
                          "error": diagnostic_error(exc)}))
        code = 2
    raise SystemExit(code)
