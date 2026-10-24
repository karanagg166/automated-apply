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
    return manifest


async def verify_public_database(connection, settings):
    manifest = verify_bundle()
    await verify_restricted_runtime(connection, manifest["tables"], schema="public")
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
