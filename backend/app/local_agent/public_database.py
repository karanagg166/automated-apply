"""Separate manifest and full catalog comparison for fresh public installations."""
import hashlib
import json

from backend.app.operations.migrations import ROOT, catalog
from backend.app.operations.runtime_security import verify_restricted_runtime

BUNDLE = ROOT / "supabase/fresh_public"


def verify_bundle():
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    if manifest["project_ref"] != "luvdmwnlwaqgvfwlmlom" or manifest["schema"] != "public":
        raise RuntimeError("public_manifest_identity_invalid")
    for item in [*manifest["sources"], {"file": str((BUNDLE / manifest["bundle"]).relative_to(ROOT)), "sha256": manifest["sha256"]}]:
        if hashlib.sha256((ROOT / item["file"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("public_migration_checksum_mismatch")
    if hashlib.sha256((BUNDLE / "catalog.json").read_bytes()).hexdigest() != manifest.get("catalog_sha256"):
        raise RuntimeError("public_catalog_manifest_checksum_mismatch")
    if hashlib.sha256((BUNDLE / "preserved_function.json").read_bytes()).hexdigest() != manifest.get("preserved_function_sha256"):
        raise RuntimeError("public_preserved_function_manifest_mismatch")
    return manifest


async def verify_preserved_function(connection):
    """A single pinned Supabase event trigger is preserved, never runtime-callable."""
    expected = json.loads((BUNDLE / "preserved_function.json").read_text())
    row = await connection.fetchrow("""
        SELECT p.oid::int AS oid,pg_get_userbyid(p.proowner) AS owner,
          pg_get_functiondef(p.oid) AS definition,
          EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
            WHERE a.grantee<>p.proowner) AS extra_grants,
          has_function_privilege('job_agent_runtime',p.oid,'EXECUTE') AS runtime_execute
        FROM pg_proc p WHERE p.oid=to_regprocedure('public.rls_auto_enable()')
    """)
    if row is None:
        return ()
    if (row["owner"] != expected["owner"] or row["extra_grants"] or row["runtime_execute"]
            or hashlib.sha256(row["definition"].encode()).hexdigest() != expected["sha256"]):
        raise RuntimeError("public_preserved_function_unsafe_or_changed")
    triggers = await connection.fetch("""
        SELECT evtname,evtevent,evtenabled::text AS enabled,evttags,pg_get_userbyid(evtowner) AS owner
        FROM pg_event_trigger WHERE evtfoid=$1::oid
    """, row["oid"])
    event = expected["event_trigger"]
    if (len(triggers) != 1 or triggers[0]["evtname"] != event["name"]
            or triggers[0]["evtevent"] != event["event"] or triggers[0]["enabled"] != "O"
            or sorted(triggers[0]["evttags"] or []) != sorted(event["tags"])
            or triggers[0]["owner"] != "postgres"):
        raise RuntimeError("public_preserved_event_trigger_changed")
    return (row["oid"],)


async def verify_public_database(connection, settings):
    manifest = verify_bundle()
    preserved = await verify_preserved_function(connection)
    await verify_restricted_runtime(connection, manifest["tables"], schema="public", preserved_function_oids=preserved)
    unsafe_defaults = await connection.fetchval("""
        SELECT EXISTS(SELECT 1 FROM pg_default_acl d
            CROSS JOIN LATERAL aclexplode(d.defaclacl) a
            WHERE d.defaclnamespace=(SELECT oid FROM pg_namespace WHERE nspname='public')
              AND d.defaclrole IN (SELECT oid FROM pg_roles WHERE rolname IN ('postgres','job_agent_owner'))
              AND (a.grantee=0 OR a.grantee IN
                  (SELECT oid FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role'))))
    """)
    if unsafe_defaults:
        raise RuntimeError("public_unsafe_default_grants")
    actual = await catalog(connection, "public")
    if preserved:
        actual["functions"].pop("rls_auto_enable()", None)
    expected = json.loads((BUNDLE / "catalog.json").read_text())
    if actual != expected:
        raise RuntimeError("public_catalog_drift_or_unsafe_grants")
    if settings.DB_REQUIRE_TLS:
        tls = await connection.fetchval("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
        if not tls:
            raise RuntimeError("database_tls_required")
    return {"schema": "public", "runtime_security": "restricted_public_v1",
            "migration_bundle": manifest["sha256"], "tls_required": settings.DB_REQUIRE_TLS,
            "postgresql_version": await connection.fetchval("SHOW server_version")}
