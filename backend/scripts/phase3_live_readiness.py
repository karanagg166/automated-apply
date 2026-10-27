"""Bounded read-only readiness checks; private output outside Git, no Actor runs."""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(args):
    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.integrations.google_oauth import READ_SCOPES, SCOPES
    from backend.app.operations.configuration import load_settings
    from backend.app.schemas.discovery import DiscoveryError
    from backend.app.services.contact_enrichment.apollo_capabilities import inspect
    from backend.app.services.contact_enrichment.base import ProviderError
    from backend.app.services.contact_enrichment.providers.apollo import ApolloProvider
    from backend.app.services.providers.apify import (
        INVESTIGATED_ACTORS,
        OfficialApifyAPI,
    )

    output = args.output.resolve()
    if (
        output == ROOT
        or ROOT in output.parents
        or output.exists()
        or output.is_symlink()
    ):
        raise ValueError("new_private_output_outside_repository_required")
    settings = load_settings(args.env_file)
    provider_settings = load_settings(args.provider_env_file or args.env_file)
    result = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "acceptance": "PARTIAL",
        "actor_runs": 0,
        "gmail_message_reads": 0,
        "email_sends": 0,
        "employer_submissions": 0,
        "ddl_executed": False,
        "local_mcp": "no_apify_server_in_codex_config",
        "database": {},
        "apify": {},
        "apollo": {},
    }
    database_target(settings)
    connection = await asyncpg.connect(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1),
        **database_connect_args(settings),
    )
    try:
        async with connection.transaction(readonly=True):
            await connection.execute("SET LOCAL statement_timeout='15s'")
            schema = settings.DATABASE_SCHEMA
            if schema not in {"public", "job_agent"}:
                raise ValueError("approved_application_schema_required")
            role = await connection.fetchrow(
                "SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
            )
            tls = await connection.fetchval(
                "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
            )
            result["database"] = {
                "connected": True,
                "schema": schema,
                "tls": tls,
                "restricted_role": not any(dict(role).values()),
                "postgres_major": int(
                    await connection.fetchval("SHOW server_version_num")
                )
                // 10000,
            }
            read_installed = await connection.fetchval(
                "SELECT to_regclass($1) IS NOT NULL", schema + ".gmail_read_accounts"
            )
            rows = await connection.fetch(
                f"SELECT status,granted_scopes FROM {schema}.connected_accounts"
            )
            result["gmail"] = {
                "read_schema_installed": read_installed,
                "legacy_account_count": len(rows),
                "legacy_permissions": [
                    {
                        "status": row["status"],
                        "metadata_only": set(
                            json.loads(row["granted_scopes"])
                            if isinstance(row["granted_scopes"], str)
                            else row["granted_scopes"]
                        )
                        == SCOPES,
                        "readonly_only": set(
                            json.loads(row["granted_scopes"])
                            if isinstance(row["granted_scopes"], str)
                            else row["granted_scopes"]
                        )
                        == READ_SCOPES,
                    }
                    for row in rows
                ],
                "read_accounts_synced": 0,
                "body_access_enabled": False,
                "reason": "No Phase 3 account grant or approved live schema migration; mailbox sync not attempted",
            }
    finally:
        await connection.close()
    api = OfficialApifyAPI(provider_settings.APIFY_API_TOKEN)
    if provider_settings.APIFY_API_TOKEN:
        try:
            account = await api.account_limits()
            result["apify"]["account"] = account
        except DiscoveryError as exc:
            result["apify"]["account"] = {
                "status": str(exc.status),
                "error_code": str(exc),
            }
    else:
        result["apify"]["account"] = {"status": "missing_local_credentials"}
    result["apify"]["actors"] = []
    for actor in INVESTIGATED_ACTORS:
        try:
            result["apify"]["actors"].append(
                (await api.actor(actor)).model_dump(mode="json")
            )
        except DiscoveryError as exc:
            result["apify"]["actors"].append(
                {"actor_id": actor, "status": str(exc.status), "error_code": str(exc)}
            )
    if provider_settings.APOLLO_API_KEY:
        try:
            result["apollo"] = await inspect(
                ApolloProvider(provider_settings.APOLLO_API_KEY, enabled=True),
                "enrich_person",
                provider_settings.APOLLO_CREDIT_POOL,
            )
        except ProviderError as exc:
            result["apollo"] = {
                "status": exc.state,
                "error_code": exc.message,
                "enrichment_calls": 0,
            }
    else:
        result["apollo"] = {
            "status": "missing_local_credentials",
            "enrichment_calls": 0,
            "eligibility_verified": False,
        }
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(result, file, indent=2)
    print(
        json.dumps(
            {
                "acceptance": result["acceptance"],
                "database_connected": result["database"]["connected"],
                "apify_authenticated": result["apify"]["account"].get(
                    "authenticated", False
                ),
                "actors_with_input_schema": sum(
                    bool(a.get("input_schema")) for a in result["apify"]["actors"]
                ),
                "apollo_status": result["apollo"].get("status", "inspected"),
                "gmail_message_reads": 0,
                "actor_runs": 0,
                "ddl_executed": False,
                "private_evidence_written": True,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--provider-env-file")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(verify(parser.parse_args()))
