"""Private runtime URI construction. No admin credentials, connections or DDL."""
import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from sqlalchemy.engine import URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    path = Path(args.env_file).expanduser().absolute()
    if path.exists() and (path.is_symlink() or path.stat().st_mode & 0o077):
        raise SystemExit("private_regular_env_file_required")
    ref = "luvdmwnlwaqgvfwlmlom"
    host = input("Direct db.<ref>.supabase.co or session pooler hostname: ").strip()
    user = input("Restricted runtime username (job_agent_runtime or job_agent_runtime.<ref>): ").strip()
    password = getpass.getpass("Existing restricted runtime password (never admin; not rotated): ")
    uri = URL.create("postgresql+asyncpg", username=user, password=password, host=host, port=5432, database="postgres").render_as_string(hide_password=False)
    from backend.app.core.config import Settings
    from backend.app.db.safety import database_target
    settings = Settings(_env_file=None, ENVIRONMENT="development", DATABASE_URL=uri, DATABASE_SCHEMA="public")
    database_target(settings)
    # Preserve unrelated existing settings, including encryption keys.
    lines = path.read_text().splitlines() if path.exists() else []
    values = {"DATABASE_URL": uri, "DATABASE_SCHEMA": "public", "DB_REQUIRE_TLS": "true", "DB_REMOTE_ONLY": "true",
        "SUPABASE_URL": f"https://{ref}.supabase.co", "SUPABASE_JWKS_URL": f"https://{ref}.supabase.co/auth/v1/.well-known/jwks.json"}
    lines = [line for line in lines if line.partition("=")[0] not in values]
    import json
    # JSON string quoting is dotenv-compatible; URI values never enter a shell.
    lines += [key + "=" + json.dumps(value) for key, value in values.items()]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write("\n".join(lines) + "\n")
    print("runtime_configuration_saved_no_connection_attempted")


if __name__ == "__main__":
    main()
