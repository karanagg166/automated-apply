"""Owner-authorized read-only runtime inventory; private output, no message reads.

No DDL, token refresh, Actor execution, applicant data export or Telegram delivery.
Pair with phase3_live_readiness.py for current provider metadata.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def audit(args):
    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.integrations.gmail.schema import MIGRATION, migration_preflight
    from backend.app.local_agent.telegram import BotAPI, TelegramError, authorized
    from backend.app.operations.configuration import load_settings

    output = args.output.resolve()
    if ROOT == output or ROOT in output.parents or output.exists() or args.output.is_symlink():
        raise ValueError("new_private_output_outside_repository_required")
    settings = load_settings(args.env_file)
    database_target(settings)
    result = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "ddl_executed": False, "gmail_message_reads": 0, "actor_runs": 0,
              "migration_sha256": hashlib.sha256(MIGRATION.read_bytes()).hexdigest()}
    connection = await asyncpg.connect(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1),
        **database_connect_args(settings),
    )
    try:
        async with connection.transaction(readonly=True):
            await connection.execute("SET LOCAL statement_timeout='15s'")
            result["gmail_migration"] = await migration_preflight(connection, settings.DATABASE_SCHEMA)
            schema = settings.DATABASE_SCHEMA  # validated by migration_preflight
            result["database"] = {"catalog_and_restricted_runtime": "verified",
                                  "schema": schema, "history": "catalog_inference_only"}
            ledger = await connection.fetchval(
                "SELECT to_regclass('supabase_migrations.schema_migrations') IS NOT NULL"
            )
            result["database"]["supabase_ledger_present"] = ledger
            if ledger:
                # The restricted runtime must not be widened to inspect this ledger.
                result["database"]["ledger_readable"] = await connection.fetchval(
                    "SELECT has_table_privilege(current_user,'supabase_migrations.schema_migrations','SELECT')"
                )
            result["candidate"] = dict(await connection.fetchrow(f"""
                SELECT count(*) AS profile_count,
                       count(*) FILTER (WHERE active_resume_version_id IS NOT NULL) AS active_resume_profiles,
                       count(*) FILTER (WHERE jsonb_array_length(verified_skills)>0) AS profiles_with_verified_skills
                FROM {schema}.candidate_profiles
            """))
            result["resume"] = dict(await connection.fetchrow(f"""
                SELECT count(*) AS stored_count, count(*) FILTER (WHERE confirmed) AS confirmed_count
                FROM {schema}.private_resumes
            """))
            result["missing_input"] = dict(await connection.fetchrow(f"""
                SELECT count(*) AS persisted_requests,
                       count(*) FILTER (WHERE value->>'status'='approved') AS approved_requests
                FROM {schema}.owner_preferences WHERE key LIKE 'needs_input:%'
            """))
            result["legacy_gmail"] = [dict(row) for row in await connection.fetch(
                f"SELECT status,granted_scopes FROM {schema}.connected_accounts"
            )]
            result["discovery"] = [dict(row) for row in await connection.fetch(f"""
                SELECT status, count(*) AS runs,
                       count(*) FILTER (WHERE usage::jsonb ? 'diagnostics') AS instrumented_runs
                FROM {schema}.discovery_runs GROUP BY status
            """)]
            result["gmail_flags"] = {"sync_enabled": settings.GMAIL_READ_SYNC_ENABLED,
                                     "body_reviewed": settings.GMAIL_READ_BODY_REVIEWED}
    finally:
        await connection.close()
    manifest = Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts/com.automated_apply.agent.json"
    native = {"enabled": settings.CHROME_NATIVE_MESSAGING_ENABLED, "manifest_present": manifest.is_file()}
    if manifest.is_file():
        document = json.loads(manifest.read_text())
        wrapper = Path(document.get("path", "/nonexistent"))
        native.update(origin_matches=document.get("allowed_origins") == [f"chrome-extension://{settings.CHROME_EXTENSION_ID}/"],
                      executable_present=wrapper.is_file() and os.access(wrapper, os.X_OK),
                      physical_gesture_verified=False, phase35_deployed=False)
    result["chrome_native"] = native
    owner_message = {"chat": {"id": settings.TELEGRAM_OWNER_CHAT_ID, "type": "private"},
                     "from": {"id": settings.TELEGRAM_OWNER_USER_ID}}
    telegram = {"owner_binding_configured": bool(settings.TELEGRAM_OWNER_CHAT_ID and settings.TELEGRAM_OWNER_USER_ID),
                "owner_allowed": authorized(owner_message, settings),
                "other_user_denied": not authorized({**owner_message, "from": {"id": -1}}, settings),
                "group_denied": not authorized({**owner_message, "chat": {"id": settings.TELEGRAM_OWNER_CHAT_ID, "type": "group"}}, settings),
                "messages_sent": 0}
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            await BotAPI(settings).verify()  # getMe/getWebhookInfo only; no update polling
            telegram["identity_and_no_webhook"] = True
        except TelegramError as exc:
            telegram["error_code"] = exc.code
    result["telegram"] = telegram
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: result[k] for k in ("database", "gmail_migration", "candidate", "resume", "missing_input", "chrome_native", "telegram")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(audit(parser.parse_args()))
