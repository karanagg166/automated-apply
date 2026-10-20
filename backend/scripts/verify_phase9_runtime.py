"""Exercise the proposed ACL/RLS overlay only in a disposable localhost database."""

import asyncio
import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url):
    parsed = urlsplit(url)
    if (parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.path != "/candidate_profile_test" or parsed.query or parsed.fragment):
        raise ValueError("Only disposable localhost candidate_profile_test is permitted")
    cluster = await asyncpg.connect(url)
    # Role names are deliberately fixed by the deployment contract. Never reuse
    # an existing role or touch objects in the supplied database.
    if await cluster.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('job_agent_runtime','job_agent_owner'))"):
        await cluster.close()
        raise ValueError("Dedicated test roles must not already exist")
    database = "candidate_profile_test_phase9_" + uuid.uuid4().hex
    await cluster.execute(f'CREATE DATABASE "{database}"')
    child_url = urlunsplit(parsed._replace(path="/" + database))
    admin = None
    engine = None
    bootstrapped = False
    try:
        admin = await asyncpg.connect(child_url)
        # Refuse a nonempty target and any pre-existing dedicated roles.
        assert not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')")
        assert not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('job_agent_runtime','job_agent_owner'))")
        checked_url = child_url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgres@", "postgres:local-test-unused@")
        check = subprocess.run([sys.executable, "-m", "backend.scripts.check_database"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, env={**os.environ,
                "ENVIRONMENT": "development", "DATABASE_URL": checked_url,
                "DB_REMOTE_ONLY": "false", "DB_REQUIRE_TLS": "false"})
        diagnosis = json.loads(check.stdout)
        assert check.returncode == 2 and diagnosis["actual_connection_verified"]
        assert diagnosis["error"] == "database_schema_missing"
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
                await admin.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await admin.execute("CREATE TABLE public.phase9_other_app(id int PRIMARY KEY, value text)")
        await admin.execute("INSERT INTO public.phase9_other_app VALUES (1,'preserved')")
        await admin.execute("GRANT ALL ON public.phase9_other_app TO anon, authenticated, service_role")
        await admin.execute((ROOT / "docs/sql/phase9-role-bootstrap.sql").read_text())
        bootstrapped = True
        # Supabase's postgres is CREATEROLE, not superuser. PostgreSQL 16+
        # automatically grants the creator ADMIN without INHERIT/SET access.
        # Reproduce that membership even when this fixture uses a superuser.
        await admin.execute("GRANT job_agent_runtime TO postgres WITH ADMIN TRUE, INHERIT FALSE, SET FALSE")
        for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            await admin.execute(path.read_text())
        await admin.execute((ROOT / "docs/sql/phase9-runtime-hardening.sql").read_text())
        await admin.execute((ROOT / "docs/sql/phase10-runtime-addendum.sql").read_text())
        await admin.execute("RESET ROLE")
        # SCRAM containers require a password even for this disposable runtime.
        # Quote it server-side and never print the credential or connection URL.
        runtime_password = secrets.token_urlsafe(32)
        login_sql = await admin.fetchval(
            "SELECT format('ALTER ROLE job_agent_runtime LOGIN PASSWORD %L', $1::text)",
            runtime_password,
        )
        await admin.execute(login_sql)
        from backend.app.core.config import Settings, configure_operator
        from backend.app.operations.health import database_health
        from backend.app.operations.migrations import MANIFEST, catalog, compare_catalog
        from backend.app.operations.runtime_security import verify_restricted_runtime

        runtime_url = f"postgresql://job_agent_runtime:{runtime_password}@127.0.0.1:{parsed.port}/{database}"
        runtime = await asyncpg.connect(runtime_url)
        try:
            async with runtime.transaction(readonly=True):
                tables = json.loads(MANIFEST.read_text())["catalog"]["tables"]
                await verify_restricted_runtime(runtime, tables)
                plan = compare_catalog(await catalog(runtime), restricted_runtime=True)
                assert plan.status == "verified", plan.model_dump()
            settings = Settings(_env_file=None, ENVIRONMENT="development",
                DATABASE_URL=runtime_url.replace("postgresql://", "postgresql+asyncpg://"),
                DB_REMOTE_ONLY=False, DB_REQUIRE_TLS=False, DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0)
            configure_operator(settings)
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True)
            evidence = await database_health(engine, settings)
            assert evidence["runtime_security"] == "restricted_v1"
            async with runtime.transaction():
                company = await runtime.fetchval("INSERT INTO job_agent.companies(name) VALUES ('Fictional Phase9') RETURNING id")
                assert await runtime.fetchval("SELECT name FROM job_agent.companies WHERE id=$1", company) == "Fictional Phase9"
                await runtime.execute("UPDATE job_agent.companies SET name='Fictional Updated' WHERE id=$1", company)
                # Phase 10's separately proposed addendum supports real runtime
                # schedule/task DML and row locking without granting delete/DDL.
                await runtime.execute("INSERT INTO job_agent.automation_schedule(key) VALUES ('primary')")
                await runtime.fetchrow("SELECT * FROM job_agent.automation_schedule WHERE key='primary' FOR UPDATE")
                await runtime.execute("UPDATE job_agent.automation_schedule SET version=2 WHERE key='primary'")
                execution = await runtime.fetchval("INSERT INTO job_agent.automation_executions(request_key,source,trigger_type,schedule_version,configuration) VALUES ('fictional_runtime','arbeitnow','manual',2,'{}') RETURNING id")
                await runtime.execute("UPDATE job_agent.automation_executions SET state='claimed',fence=1 WHERE id=$1", execution)
                assert await runtime.fetchval("SELECT fence FROM job_agent.automation_executions WHERE id=$1", execution) == 1
            for sql in ["SELECT * FROM public.phase9_other_app", "DELETE FROM job_agent.companies",
                        "TRUNCATE job_agent.companies", "CREATE TABLE job_agent.forbidden(id int)",
                        "SET ROLE job_agent_owner", "UPDATE job_agent.application_events SET event_type='bad'"]:
                try:
                    async with runtime.transaction():
                        await runtime.execute(sql)
                except asyncpg.InsufficientPrivilegeError:
                    pass
                else:
                    raise AssertionError("Forbidden runtime operation succeeded")
            for role in ("anon", "authenticated", "service_role"):
                await admin.execute(f'SET ROLE "{role}"')
                try:
                    await admin.fetch("SELECT * FROM job_agent.private_resumes")
                except asyncpg.InsufficientPrivilegeError:
                    pass
                else:
                    raise AssertionError("Shared role could access private resumes")
                finally:
                    await admin.execute("RESET ROLE")
                for table in ("automation_schedule", "automation_executions", "automation_matches"):
                    assert not await admin.fetchval("SELECT has_table_privilege($1,$2,'SELECT,INSERT,UPDATE')", role, "job_agent." + table)
            assert await admin.fetchval("SELECT value FROM public.phase9_other_app") == "preserved"
            # Each injected fault is explicitly reversed in this disposable cluster.
            faults = [
                "ALTER TABLE job_agent.jobs NO FORCE ROW LEVEL SECURITY",
                "GRANT DELETE ON job_agent.application_events TO job_agent_runtime",
                "GRANT SELECT ON job_agent.private_resumes TO authenticated",
                "CREATE POLICY public_read ON job_agent.private_resumes FOR SELECT TO PUBLIC USING (true)",
                "ALTER ROLE job_agent_runtime BYPASSRLS",
                "GRANT job_agent_runtime TO anon",
                "GRANT SELECT ON public.phase9_other_app TO PUBLIC",
                "GRANT UPDATE (name) ON job_agent.companies TO job_agent_runtime",
                "ALTER FUNCTION job_agent.candidate_profile_version() SECURITY DEFINER",
                f'GRANT CREATE ON DATABASE "{database}" TO job_agent_runtime',
            ]
            for fault in faults:
                # Metadata changes must be visible to the separate readiness connection.
                await admin.execute(fault)
                try:
                    await database_health(engine, settings)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Readiness accepted unsafe deployment: " + fault)
                undo = {
                    faults[0]: "ALTER TABLE job_agent.jobs FORCE ROW LEVEL SECURITY",
                    faults[1]: "REVOKE DELETE ON job_agent.application_events FROM job_agent_runtime",
                    faults[2]: "REVOKE SELECT ON job_agent.private_resumes FROM authenticated",
                    faults[3]: "DROP POLICY public_read ON job_agent.private_resumes",
                    faults[4]: "ALTER ROLE job_agent_runtime NOBYPASSRLS",
                    faults[5]: "REVOKE job_agent_runtime FROM anon",
                    faults[6]: "REVOKE SELECT ON public.phase9_other_app FROM PUBLIC",
                    faults[7]: "REVOKE UPDATE (name) ON job_agent.companies FROM job_agent_runtime",
                    faults[8]: "ALTER FUNCTION job_agent.candidate_profile_version() SECURITY INVOKER",
                    faults[9]: f'REVOKE CREATE ON DATABASE "{database}" FROM job_agent_runtime',
                }
                await admin.execute(undo[fault])
            await database_health(engine, settings)
            print("Phase 9 PostgreSQL PASS: restricted runtime readiness and CRUD; 6 forbidden operations; 3 shared roles denied; 10 unsafe deployments rejected; other app preserved")
        finally:
            await runtime.close()
    finally:
        if engine:
            await engine.dispose()
        if admin:
            await admin.close()
        await cluster.execute(f'DROP DATABASE "{database}"')
        if bootstrapped:
            await cluster.execute("DROP ROLE job_agent_runtime, job_agent_owner")
        await cluster.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
