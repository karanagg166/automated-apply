"""Dependency health uses bounded reads. Optional integrations never gate liveness."""

import asyncio
import json

from sqlalchemy import select, text

from backend.app.db.safety import database_target, verify_remote_address


async def database_health(engine, settings):
    if engine.url != database_target(settings):
        raise RuntimeError("database_engine_target_mismatch")
    async with asyncio.timeout(10):
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
            plan = compare_catalog(await catalog(raw.driver_connection, settings.DATABASE_SCHEMA))
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
                if not row["schema_access"] or not row["rls_access"]:
                    raise RuntimeError("database_runtime_access_incompatible")
            expected = json.loads(MANIFEST.read_text())["catalog"]
            privileges = {name: {"SELECT"} for name in expected["tables"]}
            for grant in expected["service_grants"]:
                name, privilege = grant.split(".")
                privileges[name].add(privilege)
            # Legacy tables have no service_role grants in the original migrations.
            # The runtime credential still needs the repository's write operations.
            for name in privileges:
                if not any(key.startswith(name + ".") for key in expected["service_grants"]):
                    privileges[name].update({"INSERT", "UPDATE"})
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
            for model_table in Base.metadata.sorted_tables:
                await connection.execute(select(model_table).limit(0))
            actual_database = await connection.scalar(text("SELECT current_database()"))
            if actual_database != database_target(settings).database:
                raise RuntimeError("database_identity_mismatch")
            return {
                "postgresql_version": await connection.scalar(text("SHOW server_version")),
                "schema": settings.DATABASE_SCHEMA,
                "migration_011": "catalog_compatible_history_untracked",
                "tls_required": settings.DB_REQUIRE_TLS,
            }
