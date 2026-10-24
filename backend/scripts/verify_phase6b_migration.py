"""Verify catalog preflight, drift and read-only enforcement in disposable local PostgreSQL."""

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.operations.migrations import (
    MANIFEST,
    MIGRATIONS,
    catalog,
    compare_catalog,
    file_inventory,
)


async def verify(url, write_manifest=False):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/candidate_profile_test"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Only disposable localhost candidate_profile_test is permitted"
        )
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_phase6b_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    connection = None
    try:
        connection = await asyncpg.connect(
            urlunsplit(parsed._replace(path="/" + database))
        )
        for role in ("anon", "authenticated", "service_role"):
            if not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            ):
                await connection.execute(
                    f'CREATE ROLE "{role}" NOLOGIN'
                    + (" BYPASSRLS" if role == "service_role" else "")
                )
        for path in sorted(MIGRATIONS.glob("*.sql")):
            await connection.execute(path.read_text())
        async with connection.transaction(readonly=True):
            snapshot = await catalog(connection)
        manifest = {
            "postgresql_major": int(await connection.fetchval("SHOW server_version_num")) // 10000,
            "migrations": file_inventory(),
            "catalog": snapshot,
        }
        if write_manifest:
            MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        assert compare_catalog(snapshot).status == "verified"
        try:
            async with connection.transaction(readonly=True):
                await connection.execute("CREATE TABLE job_agent.forbidden(value text)")
        except asyncpg.ReadOnlySQLTransactionError:
            pass
        else:
            raise AssertionError("Read-only transaction permitted DDL")
        await connection.execute("DROP INDEX job_agent.idx_provider_check_latest")
        await connection.execute(
            "ALTER TABLE job_agent.provider_connection_checks DISABLE ROW LEVEL SECURITY"
        )
        await connection.execute(
            "GRANT SELECT ON job_agent.candidate_profiles TO authenticated"
        )
        async with connection.transaction(readonly=True):
            drift = compare_catalog(await catalog(connection))
        assert "indexes:idx_provider_check_latest" in drift.missing
        assert "tables:provider_connection_checks" in drift.drift
        assert "candidate_profiles" in drift.unsafe_grants
        print(
            "Phase 6B PostgreSQL PASS: current migration catalog parity; drift, RLS, effective grants; read-only DDL rejected"
        )
    finally:
        if connection:
            await connection.close()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1",
            database,
        )
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"], args.write_manifest))
