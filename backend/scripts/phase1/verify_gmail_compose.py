"""Real disposable PostgreSQL coverage for the compose intent constraint."""
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def require(condition, error):
    if not condition:
        raise AssertionError(error)


async def main():
    import asyncpg

    from backend.app.core.config import Settings
    from backend.app.local_agent.public_database import BUNDLE, verify_public_database
    url = os.environ["PHASE1_DISPOSABLE_DATABASE_URL"]
    target = urlsplit(url)
    if target.hostname != "127.0.0.1" or target.path != "/candidate_profile_test" or target.username != "postgres":
        raise RuntimeError("isolated_localhost_postgres_required")
    connection = await asyncpg.connect(url)
    settings = Settings(_env_file=None, DATABASE_SCHEMA="public", DB_REQUIRE_TLS=False)
    insert = """INSERT INTO public.oauth_states(state_hash,actor_id,browser_hash,
        expected_email,connection_generation,encryption_key_id,redirect_uri,
        expires_at,authorization_mode) VALUES(repeat('c',64),'owner',repeat('b',64),
        'alex@example.org',1,'fictional','http://127.0.0.1/callback',now()+interval '5 minutes',$1)"""
    try:
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE job_agent_runtime")
            require(not (await verify_public_database(connection, settings))["verified_followups"], "original_catalog_required")
        try:
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE job_agent_runtime")
                await connection.execute(insert, "compose")
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError("original_constraint_did_not_reproduce")
        sql = (BUNDLE / "followups/002_gmail_compose.sql").read_text()
        await connection.execute(sql)
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE job_agent_runtime")
            result = await verify_public_database(connection, settings)
            require(result["verified_followups"] == ["followups/002_gmail_compose.sql"], "followup_not_verified")
        for mode in ("metadata", "send", "compose", "arbitrary"):
            transaction = connection.transaction()
            await transaction.start()
            try:
                await connection.execute("SET LOCAL ROLE job_agent_runtime")
                try:
                    await connection.execute(insert, mode)
                except asyncpg.CheckViolationError:
                    require(mode == "arbitrary", "supported_mode_rejected")
                else:
                    require(mode != "arbitrary", "unknown_mode_accepted")
            finally:
                await transaction.rollback()
        try:
            await connection.execute(sql)
        except asyncpg.RaiseError:
            await connection.execute("ROLLBACK")
        else:
            raise AssertionError("followup_replay_accepted")
        async with connection.transaction():
            await connection.execute("ALTER TABLE public.oauth_states DROP CONSTRAINT oauth_states_authorization_mode_check")
            await connection.execute("SET LOCAL ROLE job_agent_runtime")
            try:
                await verify_public_database(connection, settings)
            except RuntimeError as exc:
                require(str(exc) == "public_catalog_drift_or_unsafe_grants", "unexpected_security_error")
            else:
                raise AssertionError("missing_mode_constraint_accepted")
            # Explicit rollback of this temporary fault, including the DDL.
            raise RollbackFault()
    except RollbackFault:
        pass
    finally:
        await connection.close()
    print(json.dumps({"state": "passed", "evidence": "actual_disposable_postgresql17",
        "original_failure_reproduced": True, "compose_and_existing_modes_accepted": True,
        "unknown_mode_rejected": True, "replay_rejected": True,
        "missing_constraint_rejected": True, "fixtures_rolled_back": True, "remote_ddl": False}))


class RollbackFault(Exception):
    pass


if __name__ == "__main__":
    asyncio.run(main())
