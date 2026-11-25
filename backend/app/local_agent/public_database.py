"""Separate manifest and full catalog comparison for fresh public installations."""
import hashlib
import json
import re
from copy import deepcopy

from backend.app.operations.migrations import ROOT, catalog
from backend.app.operations.runtime_security import verify_restricted_runtime

BUNDLE = ROOT / "supabase/fresh_public"


def canonical_catalog(value):
    """Compare two known PostgreSQL deparses without accepting predicate drift.

    pg_dump/restore can move a literal varchar[]->text[] cast to each literal,
    and flatten the pure email-length AND group. Keep all labels, operators,
    validation flags, clauses, function bodies, ownership and ACLs unchanged.
    """
    result = deepcopy(value)

    def literal_array(match):
        literals = match[1].split(", ")
        if not all(re.fullmatch(r"'(?:[^']|'')*'::character varying", item)
                   for item in literals):
            return match[0]
        return "(ARRAY[" + ", ".join("(" + item + ")::text" for item in literals) + "])"

    for section in ("constraints", "indexes"):
        for key, definition in result.get(section, {}).items():
            if not isinstance(definition, str):
                continue
            definition = re.sub(r"\(\(ARRAY\[(.*?)\]\)::text\[\]\)", literal_array, definition)
            if section == "constraints" and key == "candidate_profiles.ck_candidate_email":
                definition = definition.replace(
                    "CHECK ((((length((email)::text) >= 3) AND (length((email)::text) <= 254)) AND ",
                    "CHECK (((length((email)::text) >= 3) AND (length((email)::text) <= 254) AND ",
                    1,
                )
            result[section][key] = definition
    return result


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
    for followup in manifest.get("followups", []):
        if hashlib.sha256((BUNDLE / followup["file"]).read_bytes()).hexdigest() != followup["sha256"]:
            raise RuntimeError("public_followup_checksum_mismatch")
    return manifest


def verified_catalog_version(actual, expected, followups):
    """Accept only complete pinned states, never arbitrary constraint widening."""
    candidate = deepcopy(expected)
    observed = canonical_catalog(actual)
    if observed == canonical_catalog(candidate):
        return []
    applied = []
    for followup in followups:
        changes = followup.get("changes") or [{
            "section": "constraints", "key": followup["constraint"],
            "before": followup["before"], "after": followup["after"],
        }]
        for change in changes:
            section, key = change["section"], change["key"]
            if candidate[section].get(key) != change["before"]:
                raise RuntimeError("public_followup_precondition_mismatch")
            candidate[section][key] = change["after"]
        applied.append(followup["file"])
        if observed == canonical_catalog(candidate):
            return applied
    raise RuntimeError("public_catalog_drift_or_unsafe_grants")


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
    from backend.app.integrations.gmail.schema import TABLES, expected_overlay
    installed = await connection.fetchval("SELECT to_regclass('public.gmail_read_accounts') IS NOT NULL OR to_regclass('public.gmail_read_oauth_states') IS NOT NULL")
    tables = set(manifest["tables"]) | (TABLES if installed else set())
    from backend.app.operations.rust_schema import TABLES as RUST_TABLES
    from backend.app.operations.rust_schema import installed_tables
    present = await connection.fetch("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname=ANY($1::text[])", sorted(RUST_TABLES))
    tables |= installed_tables({row["relname"] for row in present})
    from backend.app.operations import v2_schema
    v2_present = await connection.fetch("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname=ANY($1::text[])", sorted(v2_schema.TABLES))
    tables |= v2_schema.installed_tables({row["relname"] for row in v2_present})
    await verify_restricted_runtime(connection, tables, schema="public", preserved_function_oids=preserved)
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
    expected = expected_overlay(expected, actual, "public")
    from backend.app.operations.rust_schema import expected_overlay as rust_overlay
    expected = rust_overlay(expected, actual)
    expected = v2_schema.expected_overlay(expected, actual)
    followups = verified_catalog_version(actual, expected, manifest.get("followups", []))
    if settings.DB_REQUIRE_TLS:
        tls = await connection.fetchval("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
        if not tls:
            raise RuntimeError("database_tls_required")
    return {"schema": "public", "runtime_security": "restricted_public_v1",
            "migration_bundle": manifest["sha256"], "tls_required": settings.DB_REQUIRE_TLS,
            "verified_followups": followups,
            "postgresql_version": await connection.fetchval("SHOW server_version")}
