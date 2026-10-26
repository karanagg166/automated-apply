"""Single reviewed remote activation, only after explicit owner DDL approval.

Never called by startup, CI or an agent prompt. Existing credentials are retained.
The only runtime password created is the first credential of a new NOLOGIN role.
"""
import argparse
import asyncio
import getpass
import hashlib
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
APPROVED_BUNDLE = "2887a98812a797c3ef9d10f37fe5f14959778d802e126d0170776059ccee6a9e"  # pragma: allowlist secret -- public reviewed SQL digest
PROJECT = "luvdmwnlwaqgvfwlmlom"


def check_approval(owner_approved, project, checksum, content):
    if not owner_approved:
        raise ValueError("explicit_owner_ddl_approval_required")
    if project != PROJECT:
        raise ValueError("wrong_supabase_project")
    if checksum != APPROVED_BUNDLE or hashlib.sha256(content).hexdigest() != checksum:
        raise ValueError("approved_migration_checksum_mismatch")


def save_private_configuration(path, values):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_nlink != 1:
        raise ValueError("private_regular_configuration_required")
    lines = [line for line in path.read_text().splitlines() if line.partition("=")[0] not in values]
    lines += [key + "=" + json.dumps(value) for key, value in values.items()]
    descriptor, temporary = tempfile.mkstemp(prefix=".phase1-config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write("\n".join(lines) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def activate(args, password):
    import asyncpg
    from sqlalchemy.engine import URL

    from backend.app.core.config import Settings
    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.local_agent.public_database import (
        verify_bundle,
        verify_public_database,
    )
    from backend.scripts.phase1.inspect_online_database import (
        inspect_database,
        validate_target,
    )

    bundle = (ROOT / "supabase/fresh_public/001_phase1_public.sql").read_bytes()
    check_approval(args.owner_approved_remote_ddl, args.project_ref, args.bundle_sha256, bundle)
    verify_bundle()
    linked = (ROOT / "supabase/.temp/project-ref").read_text().strip()
    if linked != PROJECT:
        raise ValueError("checkout_link_project_mismatch")
    validate_target(args.host, args.user)
    ca = str(Path(args.ca_file).expanduser().resolve())
    inventory = await inspect_database(args.host, args.user, password, ca)
    if any(row["schema"] == "public" for row in inventory["tables"]) or inventory["migrations"]:
        raise ValueError("fresh_dedicated_project_required")
    if any(row["rolname"] in {"job_agent_owner", "job_agent_runtime"} for row in inventory["roles"]):
        raise ValueError("application_roles_already_exist_no_reapply")
    # Preserve the old local settings privately for safe service-state migration.
    config = Path(args.env_file).expanduser().resolve()
    if not config.is_file() or config.is_symlink() or config.stat().st_mode & 0o077:
        raise ValueError("private_configuration_required")
    previous = ROOT / "reports/phase1/pre-online-runtime.private.env"
    if not previous.exists():
        descriptor = os.open(previous, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(config.read_text())
    evidence = {"project_ref": PROJECT, "bundle_sha256": APPROVED_BUNDLE,
        "verified_at": datetime.now(timezone.utc).isoformat(), "state": "ddl_reserved",
        "remote_ddl_attempts": 1, "existing_credentials_rotated": False}
    marker = ROOT / "reports/phase1/online-activation.private.json"
    descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(evidence, file, indent=2)

    import ssl
    context = ssl.create_default_context(cafile=ca)
    admin_uri = URL.create("postgresql", username=args.user, password=password,
        host=args.host, port=5432, database="postgres").render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_uri, ssl=context, timeout=15, command_timeout=90)
    try:
        # The bundle owns its transaction. No automatic retry follows any failure.
        await admin.execute(bundle.decode())
        evidence["state"] = "bundle_committed_runtime_initialization_pending"
        marker.write_text(json.dumps(evidence, indent=2) + "\n")
        role = await admin.fetchrow("SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit FROM pg_roles WHERE rolname='job_agent_runtime'")
        if not role or any(role.values()):
            raise ValueError("new_runtime_role_initialization_precondition_failed")
        runtime_password = secrets.token_urlsafe(40)
        runtime_user = "job_agent_runtime" if args.host.startswith("db.") else "job_agent_runtime." + PROJECT
        runtime_uri = URL.create("postgresql+asyncpg", username=runtime_user, password=runtime_password,
            host=args.host, port=5432, database="postgres").render_as_string(hide_password=False)
        pending = ROOT / "reports/phase1/online-runtime-pending.private.env"
        descriptor = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write("DATABASE_URL=" + json.dumps(runtime_uri) + "\nDB_SSL_ROOT_CERT=" + json.dumps(ca) + "\n")
            file.flush()
            os.fsync(file.fileno())
        statement = await admin.fetchval("SELECT format('ALTER ROLE job_agent_runtime LOGIN PASSWORD %L', $1::text)", runtime_password)
        await admin.execute(statement)
        settings = Settings(_env_file=None, DATABASE_URL=runtime_uri, DATABASE_SCHEMA="public",
            DB_REMOTE_ONLY=True, DB_REQUIRE_TLS=True, DB_SSL_ROOT_CERT=ca)
        database_target(settings)
        runtime = await asyncpg.connect(runtime_uri.replace("postgresql+asyncpg://", "postgresql://", 1), **database_connect_args(settings))
        try:
            async with runtime.transaction():
                verification = await verify_public_database(runtime, settings)
                if not await runtime.fetchval("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"):
                    raise ValueError("runtime_tls_not_verified")
            # This is harmless connection evidence, never a job/application/profile fixture.
            await runtime.execute("INSERT INTO public.agent_policies(key,version,preferences) VALUES('phase1_acceptance',1,'{}'::jsonb)")
        finally:
            await runtime.close()
        again = await asyncpg.connect(runtime_uri.replace("postgresql+asyncpg://", "postgresql://", 1), **database_connect_args(settings))
        try:
            if not await again.fetchval("SELECT EXISTS(SELECT 1 FROM public.agent_policies WHERE key='phase1_acceptance')"):
                raise ValueError("runtime_reconnect_persistence_failed")
        finally:
            await again.close()
        # Runtime intentionally has no DELETE; exact acceptance cleanup uses admin.
        await admin.execute("DELETE FROM public.agent_policies WHERE key='phase1_acceptance'")
        values = {"DATABASE_URL": runtime_uri, "DATABASE_SCHEMA": "public", "DB_REMOTE_ONLY": "true",
            "DB_REQUIRE_TLS": "true", "DB_SSL_ROOT_CERT": ca, "DB_POOL_SIZE": "1", "DB_MAX_OVERFLOW": "0",
            "SUPABASE_PROJECT_REF": PROJECT, "SUPABASE_URL": f"https://{PROJECT}.supabase.co",
            "SUPABASE_JWKS_URL": f"https://{PROJECT}.supabase.co/auth/v1/.well-known/jwks.json",
            "GMAIL_SENDING_ENABLED": "false", "AUTOMATION_EXECUTION_ENABLED": "false",
            "APPLICATION_SUBMISSION_ENABLED": "false", "AGY_ENABLED": "false", "AGY_QUOTA_AUTHORIZED": "false"}
        save_private_configuration(config, values)
        evidence.update(state="restricted_online_runtime_verified", runtime_verification=verification,
            restricted_login_tls_verified=True, reconnect_persistence_verified=True, acceptance_row_cleaned=True,
            private_runtime_configuration_saved=True, services_restarted=False)
    except Exception:
        evidence["state"] = evidence["state"] + "_stopped_no_retry"
        raise
    finally:
        marker.write_text(json.dumps(evidence, indent=2) + "\n")
        await admin.close()
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-approved-remote-ddl", action="store_true", required=True)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--ca-file", required=True)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    try:
        bundle = (ROOT / "supabase/fresh_public/001_phase1_public.sql").read_bytes()
        check_approval(args.owner_approved_remote_ddl, args.project_ref, args.bundle_sha256, bundle)
        print("Owner-approved single migration. Existing passwords are retained; the new runtime role receives its first credential.")
        password = getpass.getpass("Existing Supabase database password (hidden, not saved): ")
        print(json.dumps(asyncio.run(activate(args, password)), indent=2))
    except Exception:
        print("online_activation_stopped_no_retry_inspect_private_activation_evidence")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
