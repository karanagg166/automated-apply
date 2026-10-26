"""Private fictional lifecycle configuration; isolated localhost PostgreSQL only."""
import argparse
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "reports/phase1/disposable.private.env")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("existing_disposable_configuration_preserved")
    import asyncpg
    from sqlalchemy.engine import URL
    target = urlsplit(os.environ["PHASE1_DISPOSABLE_DATABASE_URL"])
    if target.hostname != "127.0.0.1" or target.path != "/candidate_profile_test" or target.username != "postgres":
        raise SystemExit("disposable_localhost_database_required")
    connection = await asyncpg.connect(os.environ["PHASE1_DISPOSABLE_DATABASE_URL"])
    try:
        from backend.app.core.config import Settings
        from backend.app.local_agent.public_database import verify_public_database
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE job_agent_runtime")
            await verify_public_database(connection, Settings(_env_file=None, DATABASE_SCHEMA="public", DB_REQUIRE_TLS=False))
        password = secrets.token_urlsafe(32)
        statement = await connection.fetchval("SELECT format('ALTER ROLE job_agent_runtime LOGIN PASSWORD %L', $1::text)", password)
        await connection.execute(statement)
        uri = URL.create("postgresql+asyncpg", username="job_agent_runtime", password=password,
            host="127.0.0.1", port=target.port, database="candidate_profile_test").render_as_string(hide_password=False)
        values = {"ENVIRONMENT": "development", "DATABASE_URL": uri, "DATABASE_SCHEMA": "public", "DB_REMOTE_ONLY": "false", "DB_REQUIRE_TLS": "false",
            "DB_POOL_SIZE": "1", "DB_MAX_OVERFLOW": "0", "JOB_AGENT_API_TOKEN": secrets.token_urlsafe(40), "SECRET_KEY": secrets.token_urlsafe(40),
            "LOCAL_AGENT_ENDPOINT": "http://127.0.0.1:18081", "CHROME_NATIVE_MESSAGING_ENABLED": "true", "CHROME_EXTENSION_ID": "a" * 32,
            "APPLICATION_SUBMISSION_ENABLED": "false", "GMAIL_SENDING_ENABLED": "false", "AUTOMATION_EXECUTION_ENABLED": "false", "AGY_ENABLED": "false"}
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as file:
            output.chmod(0o600)
            file.write("\n".join(key + "=" + json.dumps(value) for key, value in values.items()) + "\n")
        print("fictional_disposable_configuration_created")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
