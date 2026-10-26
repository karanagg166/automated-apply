"""Separately approved, single-run OAuth discriminator migration; no key changes."""
import argparse
import asyncio
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PROJECT = "luvdmwnlwaqgvfwlmlom"


def check_followup_approval(args, target, followup):
    if (not args.owner_approved_remote_ddl or args.sha256 != followup["sha256"]
            or args.project_ref != PROJECT or target.host != f"db.{PROJECT}.supabase.co"
            or target.username != "job_agent_runtime"):
        raise ValueError("exact_followup_approval_and_verified_direct_target_required")


async def apply(args, password):
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.local_agent.public_database import (
        BUNDLE,
        verify_bundle,
        verify_public_database,
    )
    from backend.app.operations.configuration import load_settings
    settings = load_settings(args.env_file)
    target = database_target(settings)
    followup = verify_bundle()["followups"][0]
    check_followup_approval(args, target, followup)
    if not settings.DB_REQUIRE_TLS:
        raise ValueError("verified_tls_required")
    runtime = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1),
        **database_connect_args(settings))
    try:
        async with runtime.transaction(readonly=True):
            before = await verify_public_database(runtime, settings)
            if before["verified_followups"]:
                raise ValueError("followup_already_applied_no_reapply")
    finally:
        await runtime.close()
    uri = target.set(drivername="postgresql", username="postgres", password=password).render_as_string(hide_password=False)
    admin = await asyncpg.connect(uri, **database_connect_args(settings))
    marker = ROOT / "reports/phase1/online-compose-followup.private.json"
    evidence = {"state": "reserved", "project_ref": PROJECT, "sha256": followup["sha256"],
        "verified_at": datetime.now(timezone.utc).isoformat(), "remote_ddl_attempts": 1,
        "credentials_changed": False, "stage": "before_ddl"}
    reserved = False
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        reserved = True
        with os.fdopen(descriptor, "w") as file:
            json.dump(evidence, file, indent=2)
        await admin.execute((BUNDLE / followup["file"]).read_text())
        evidence.update(state="committed", stage="runtime_verification")
        runtime = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1),
            **database_connect_args(settings))
        try:
            async with runtime.transaction(readonly=True):
                result = await verify_public_database(runtime, settings)
                if result["verified_followups"] != [followup["file"]]:
                    raise RuntimeError("compose_followup_catalog_not_verified")
        finally:
            await runtime.close()
        evidence.update(state="verified", runtime_verification=result,
            gmail_sending_enabled=settings.GMAIL_SENDING_ENABLED, stage="complete")
    except Exception as exc:
        evidence.update(state=evidence["state"] + "_stopped_no_retry",
            error_type=type(exc).__name__, sqlstate=getattr(exc, "sqlstate", None))
        raise
    finally:
        # Never overwrite an earlier marker when exclusive reservation failed.
        if reserved:
            marker.write_text(json.dumps(evidence, indent=2) + "\n")
        await admin.close()
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-approved-remote-ddl", action="store_true", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Existing Supabase database password (hidden, not saved): ")
    try:
        print(json.dumps(asyncio.run(apply(args, password)), indent=2))
    except Exception as exc:
        print(json.dumps({"state": "stopped_no_retry", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
