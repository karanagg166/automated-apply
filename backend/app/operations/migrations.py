"""Read-only catalog preflight against a disposable-PostgreSQL verified manifest.

There was no durable migration ledger in 001–009. Object presence is evidence of
schema state, never proof that a historical migration was executed or committed.
"""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "supabase/migrations"
MANIFEST = Path(__file__).with_name("migration_manifest.json")


class MigrationPlan(BaseModel):
    status: str
    history: str = "untracked_catalog_inference_only"
    expected_schema: str = "job_agent"
    missing: list[str] = Field(default_factory=list)
    drift: list[str] = Field(default_factory=list)
    unsafe_grants: list[str] = Field(default_factory=list)
    migrations: list[dict] = Field(default_factory=list)
    ddl_executed: bool = False
    guidance: str = "Review backup and migration files in numerical order; never blindly replay a partial schema"


# Only catalog SELECTs. The caller also enforces a read-only transaction and timeouts.
QUERIES = {
    "tables": """SELECT c.relname AS key, c.relrowsecurity::text AS value
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=$1 AND c.relkind='r' ORDER BY 1""",
    "columns": """SELECT c.relname||'.'||a.attname AS key,
        format_type(a.atttypid,a.atttypmod)||'|'||a.attnotnull::text||'|'||
        coalesce(pg_get_expr(d.adbin,d.adrelid),'') AS value
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname=$1 AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1""",
    "constraints": """SELECT r.relname||'.'||c.conname AS key,
        pg_get_constraintdef(c.oid)||'|'||c.convalidated::text AS value
        FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname=$1 ORDER BY 1""",
    "indexes": """SELECT indexname AS key, indexdef AS value FROM pg_indexes
        WHERE schemaname=$1 ORDER BY 1""",
    "triggers": """SELECT c.relname||'.'||t.tgname AS key,
        pg_get_triggerdef(t.oid)||'|'||t.tgenabled::text AS value
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=$1 AND NOT t.tgisinternal ORDER BY 1""",
    "functions": """SELECT p.proname||'('||pg_get_function_identity_arguments(p.oid)||')' AS key,
        pg_get_functiondef(p.oid) AS value FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=$1 ORDER BY 1""",
    "policies": """SELECT tablename||'.'||policyname AS key,
        cmd||'|'||roles::text||'|'||coalesce(qual,'')||'|'||coalesce(with_check,'') AS value
        FROM pg_policies WHERE schemaname=$1 ORDER BY 1""",
    # information_schema.role_table_grants hides grants to roles the runtime user
    # does not belong to. Read the public catalogs so a dedicated runtime login
    # can verify service-role boundaries without administrator membership.
    "service_grants": """SELECT c.relname||'.'||a.privilege_type AS key, 'granted' AS value
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        JOIN pg_roles r ON r.oid=a.grantee
        WHERE n.nspname=$1 AND c.relkind='r' AND r.rolname='service_role' ORDER BY 1""",
}


async def catalog(connection, schema="job_agent"):
    await connection.execute(
        "SELECT set_config('search_path', 'pg_catalog, public', true)"
    )
    result = {}
    for category, sql in QUERIES.items():
        result[category] = {
            r["key"]: r["value"] for r in await connection.fetch(sql, schema)
        }
    # Effective grants include membership and PUBLIC, not only direct ACL entries.
    unsafe = await connection.fetch(
        """SELECT DISTINCT c.relname AS name
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_roles r WHERE n.nspname=$1 AND c.relkind='r'
        AND r.rolname IN ('anon','authenticated')
        AND has_table_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')""",
        schema,
    )
    public = await connection.fetch(
        """SELECT DISTINCT c.relname AS name
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace,
        LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        WHERE n.nspname=$1 AND c.relkind='r' AND a.grantee=0""",
        schema,
    )
    result["unsafe_grants"] = sorted({r["name"] for r in [*unsafe, *public]})
    return result


def file_inventory():
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if [p.name[:3] for p in paths] != [f"{i:03d}" for i in range(1, 13)]:
        raise ValueError("migration_dependency_order_invalid")
    return [
        {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in paths
    ]


def compare_catalog(actual, manifest=None, *, restricted_runtime=False):
    expected = manifest or json.loads(MANIFEST.read_text())
    if restricted_runtime:
        from backend.app.operations.runtime_security import restricted_manifest

        expected = restricted_manifest(expected)
    missing, drift = [], []
    for category, objects in expected["catalog"].items():
        if category == "unsafe_grants":
            continue
        for key, value in objects.items():
            if key not in actual.get(category, {}):
                missing.append(f"{category}:{key}")
            elif actual[category][key] != value:
                drift.append(f"{category}:{key}")
    inventory = file_inventory()
    if inventory != expected["migrations"]:
        drift.append("migration_files:manifest_requires_disposable_reverification")
    # Any unexpected policy could grant access despite all expected objects existing.
    drift.extend(
        "policies:unexpected:" + k
        for k in actual.get("policies", {})
        if k not in expected["catalog"]["policies"]
    )
    drift.extend("service_grants:unexpected:" + key for key in actual.get("service_grants", {})
                 if key not in expected["catalog"]["service_grants"])
    unsafe = actual.get("unsafe_grants", [])
    status = (
        "verified" if not (missing or drift or unsafe) else "inconsistent_or_partial"
    )
    if not actual.get("tables") and not any(actual.get(k) for k in (
        "columns", "constraints", "indexes", "triggers", "functions", "policies",
    )):
        status = "empty_schema"
    return MigrationPlan(
        status=status,
        missing=missing,
        drift=drift,
        unsafe_grants=unsafe,
        migrations=inventory,
    )


async def inspect_database(settings):
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target

    database_target(settings)
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url, **database_connect_args(settings))
    try:
        async with connection.transaction(readonly=True):
            from backend.app.operations.runtime_security import (
                RUNTIME_ROLE,
                verify_restricted_runtime,
            )

            restricted = await connection.fetchval("SELECT current_user") == RUNTIME_ROLE
            if restricted:
                await verify_restricted_runtime(
                    connection, json.loads(MANIFEST.read_text())["catalog"]["tables"],
                )
            return compare_catalog(
                await catalog(connection, settings.DATABASE_SCHEMA),
                restricted_runtime=restricted,
            )
    finally:
        await connection.close()
