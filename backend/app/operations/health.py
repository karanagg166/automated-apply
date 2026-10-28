"""Dependency health uses bounded reads. Optional integrations never gate liveness."""

import asyncio
import json

from sqlalchemy import select, text

from backend.app.db.safety import database_target, verify_remote_address


async def database_health(engine, settings):
    if engine.url != database_target(settings):
        raise RuntimeError("database_engine_target_mismatch")
    # A full remote catalog audit needs multiple round trips; the verified
    # Tokyo endpoint takes about 11 seconds including the TLS connection.
    async with asyncio.timeout(30):
        await verify_remote_address(settings)
        async with engine.connect() as connection:
            if settings.ENVIRONMENT == "testing":
                await connection.execute(text("SELECT 1"))
                return
            # Probe only in a read-only transaction. Never apply SQL migrations here.
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            from backend.app.models import Base
            from backend.app.operations.migrations import (
                MANIFEST,
                catalog,
                compare_catalog,
            )

            raw = await connection.get_raw_connection()
            driver = raw.driver_connection
            from backend.app.operations.runtime_security import (
                RUNTIME_ROLE,
                runtime_privileges,
                verify_restricted_runtime,
            )

            if settings.DATABASE_SCHEMA == "public":
                from backend.app.local_agent.public_database import (
                    verify_public_database,
                )
                return await verify_public_database(driver, settings)
            restricted = await driver.fetchval("SELECT current_user") == RUNTIME_ROLE
            expected = json.loads(MANIFEST.read_text())["catalog"]
            actual = await catalog(driver, settings.DATABASE_SCHEMA)
            from backend.app.integrations.gmail.schema import expected_overlay
            expected = expected_overlay(expected, actual, settings.DATABASE_SCHEMA)
            if restricted:
                await verify_restricted_runtime(driver, expected["tables"])
            plan = compare_catalog(
                actual,
                restricted_runtime=restricted,
            )
            if plan.status != "verified":
                raise RuntimeError("database_schema_migration_or_grants_incompatible")
            access = await connection.execute(text("""
                SELECT c.relname,
                    has_schema_privilege(current_user,n.oid,'USAGE') AS schema_access,
                    (NOT c.relrowsecurity OR r.rolsuper OR r.rolbypassrls OR
                     (pg_has_role(current_user,c.relowner,'USAGE') AND NOT c.relforcerowsecurity)) AS rls_access
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_roles r ON r.rolname=current_user
                WHERE n.nspname=:schema AND c.relkind='r'
            """), {"schema": settings.DATABASE_SCHEMA})
            for row in access.mappings():
                if not row["schema_access"] or (not restricted and not row["rls_access"]):
                    raise RuntimeError("database_runtime_access_incompatible")
            privileges = {name: {"SELECT"} for name in expected["tables"]}
            for grant in expected["service_grants"]:
                name, privilege = grant.split(".")
                privileges[name].add(privilege)
            # Legacy tables have no service_role grants in the original migrations.
            # The runtime credential still needs the repository's write operations.
            for name in privileges:
                if not any(key.startswith(name + ".") for key in expected["service_grants"]):
                    privileges[name].update({"INSERT", "UPDATE"})
            if restricted:
                privileges = runtime_privileges(expected["tables"])
            required = [{"table_name": name, "privilege": privilege}
                        for name, values in privileges.items() for privilege in values]
            allowed = await connection.scalar(text("""
                SELECT bool_and(has_table_privilege(current_user,
                    format('%I.%I',CAST(:schema AS text),p.table_name),p.privilege))
                FROM jsonb_to_recordset(CAST(:required AS jsonb))
                    AS p(table_name text, privilege text)
            """), {"schema": settings.DATABASE_SCHEMA, "required": json.dumps(required)})
            if not allowed:
                raise RuntimeError("database_runtime_dml_permissions_missing")
            # Check all expected table/column SELECTs without reading candidate rows.
            from backend.app.integrations.gmail.schema import (
                TABLES as optional_gmail_tables,
            )
            for model_table in Base.metadata.sorted_tables:
                if model_table.name in optional_gmail_tables and model_table.name not in actual["tables"]:
                    continue
                await connection.execute(select(model_table).limit(0))
            actual_database = await connection.scalar(text("SELECT current_database()"))
            if actual_database != database_target(settings).database:
                raise RuntimeError("database_identity_mismatch")
            return {
                "postgresql_version": await connection.scalar(text("SHOW server_version")),
                "schema": settings.DATABASE_SCHEMA,
                "migration_011": "catalog_compatible_history_untracked",
                "migration_012": "catalog_compatible_history_untracked",
                "tls_required": settings.DB_REQUIRE_TLS,
                "runtime_security": "restricted_v1" if restricted else "historical",
            }
