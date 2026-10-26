"""Owner-terminal PostgreSQL inventory; verified TLS, read-only transaction, no DDL."""
import argparse
import asyncio
import getpass
import hashlib
import json
import os
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PROJECT = "luvdmwnlwaqgvfwlmlom"


def validate_target(host, user):
    direct = host == f"db.{PROJECT}.supabase.co" and user == "postgres"
    pooled = bool(re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", host)) and user == f"postgres.{PROJECT}"
    if not (direct or pooled):
        raise ValueError("wrong_supabase_project_or_admin_inventory_target")


async def inspect_database(host, user, password, certificate=None):
    import asyncpg
    from sqlalchemy.engine import URL
    validate_target(host, user)
    context = ssl.create_default_context(cafile=certificate)
    # URL.create correctly percent-encodes #, @, : and other password characters.
    uri = URL.create("postgresql", username=user, password=password, host=host, port=5432, database="postgres").render_as_string(hide_password=False)
    connection = await asyncpg.connect(uri, ssl=context, timeout=15, command_timeout=20)
    try:
        ssl_object = connection._transport.get_extra_info("ssl_object")
        if not ssl_object or not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("verified_postgresql_tls_required")
        output = {"project_ref": PROJECT, "verified_at": datetime.now(timezone.utc).isoformat(),
            "tls_hostname_and_ca_verified": True,
            "peer_certificate_sha256": hashlib.sha256(ssl_object.getpeercert(binary_form=True)).hexdigest(),
            "remote_ddl_executed": False}
        async with connection.transaction(readonly=True):
            queries = {
                "identity": "SELECT current_database() AS database, current_user AS role, version() AS version",
                "schemas": "SELECT nspname, pg_get_userbyid(nspowner) AS owner, nspacl::text AS acl FROM pg_namespace WHERE nspname NOT LIKE 'pg_toast%' ORDER BY nspname",
                "tables": "SELECT n.nspname AS schema,c.relname,c.relkind,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner,c.relacl::text AS acl FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND c.relkind IN ('r','p','v','m','f','S') ORDER BY 1,2",
                "roles": "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles ORDER BY rolname",
                "memberships": "SELECT pg_get_userbyid(roleid) AS role,pg_get_userbyid(member) AS member,admin_option FROM pg_auth_members",
                "policies": "SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check FROM pg_policies ORDER BY 1,2,3",
                "extensions": "SELECT extname,extversion,nspname FROM pg_extension JOIN pg_namespace ON pg_namespace.oid=extnamespace ORDER BY extname",
                "default_grants": "SELECT pg_get_userbyid(defaclrole) AS owner,defaclnamespace::regnamespace::text AS schema,defaclobjtype,defaclacl::text AS acl FROM pg_default_acl",
                "event_triggers": "SELECT evtname,evtevent,evtenabled,evtfoid::regprocedure::text AS function,pg_get_userbyid(evtowner) AS owner,evttags FROM pg_event_trigger",
                "public_functions": "SELECT p.oid::regprocedure::text AS name,pg_get_userbyid(p.proowner) AS owner,p.prosecdef,p.proacl::text AS acl,pg_get_functiondef(p.oid) AS definition FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind='f'",
            }
            for name, query in queries.items():
                output[name] = [dict(row) for row in await connection.fetch(query)]
            exists = await connection.fetchval("SELECT to_regclass('supabase_migrations.schema_migrations') IS NOT NULL")
            output["migrations"] = [dict(row) for row in await connection.fetch("SELECT version,name FROM supabase_migrations.schema_migrations ORDER BY version")] if exists else []
        return output
    finally:
        await connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host")
    parser.add_argument("--user")
    parser.add_argument("--ca-file")
    args = parser.parse_args()
    print("Read-only inventory of luvdmwnlwaqgvfwlmlom. Existing credentials are preserved; no DDL or runtime activation.")
    host = args.host or input("Exact direct/session-pooler host from this project's Connect dialog: ").strip()
    user = args.user or input("Existing postgres username (pooler includes project reference): ").strip()
    try:
        validate_target(host, user)
        certificate = args.ca_file
        if certificate is None:
            official = Path.home() / "Library/Application Support/Automated Apply/supabase-cli/supabase-prod-ca-2021.crt"
            certificate = str(official) if official.is_file() else None
        if certificate and not Path(certificate).expanduser().is_file():
            raise ValueError("certificate_unavailable")
        password = getpass.getpass("Existing database password (hidden; never rotated or saved): ")
        output = asyncio.run(inspect_database(host, user, password, str(Path(certificate).expanduser()) if certificate else None))
        path = ROOT / "reports/phase1/online-database-inventory.private.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump(output, file, default=str, indent=2)
        print(json.dumps({"state": "read_only_tls_inventory_saved", "project_ref": PROJECT,
            "public_table_count": sum(row["schema"] == "public" for row in output["tables"]),
            "public_function_count": len(output["public_functions"]), "remote_ddl_executed": False}))
    except Exception as exc:
        import asyncpg
        category = "tls_certificate_verification_failed" if isinstance(exc, ssl.SSLCertVerificationError) else "postgresql_authentication_failed" if isinstance(exc, asyncpg.InvalidPasswordError) else "inventory_failed_no_configuration_changed"
        path = ROOT / "reports/phase1/online-database-attempt.private.json"
        descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump({"verified_at": datetime.now(timezone.utc).isoformat(), "project_ref": PROJECT,
                "state": category, "remote_ddl_executed": False}, file)
        print(category)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
