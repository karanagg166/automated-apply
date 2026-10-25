"""Disposable PostgreSQL bootstrap/security verification. Never accepts remote hosts."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def verify(bootstrap=False, with_managed_function=False):
    import asyncpg
    url = os.environ["PHASE1_DISPOSABLE_DATABASE_URL"]
    target = urlsplit(url)
    if target.hostname != "127.0.0.1" or target.path != "/candidate_profile_test" or target.username != "postgres":
        raise RuntimeError("isolated_localhost_postgres_required")
    admin = await asyncpg.connect(url)
    try:
        from backend.app.core.config import Settings
        from backend.app.local_agent.public_database import (
            verify_bundle,
            verify_public_database,
        )
        manifest = verify_bundle()
        if bootstrap:
            for name in ("anon", "authenticated", "service_role"):
                if not await admin.fetchval("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=$1)", name):
                    await admin.execute(f"CREATE ROLE {name}")
            if with_managed_function:
                managed = json.loads((ROOT / "supabase/fresh_public/preserved_function.json").read_text())
                await admin.execute(managed["definition"])
                await admin.execute("CREATE EVENT TRIGGER ensure_rls ON ddl_command_end WHEN TAG IN ('CREATE TABLE','CREATE TABLE AS','SELECT INTO') EXECUTE FUNCTION public.rls_auto_enable()")
                for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                    await admin.execute(f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON {kind} TO postgres, anon, authenticated, service_role")
                # A different pre-existing function must still block the bundle.
                await admin.execute("CREATE FUNCTION public.unreviewed_function() RETURNS int LANGUAGE sql AS 'SELECT 1'")
                try:
                    await admin.execute((ROOT / "supabase/fresh_public/001_phase1_public.sql").read_text())
                except asyncpg.RaiseError as exc:
                    assert "fresh_dedicated_project_required" in str(exc)
                    await admin.execute("ROLLBACK")
                else:
                    raise AssertionError("unreviewed_public_function_accepted")
                await admin.execute("DROP FUNCTION public.unreviewed_function()")
            await admin.execute((ROOT / "supabase/fresh_public/001_phase1_public.sql").read_text())
        settings = Settings(_env_file=None, DATABASE_SCHEMA="public", DB_REQUIRE_TLS=False)
        async with admin.transaction():
            await admin.execute("SET LOCAL ROLE job_agent_runtime")
            await verify_public_database(admin, settings)
        # Genuine role-denial tests, each rolled back in a disposable transaction.
        denied = 0
        for statement in (
            "CREATE TABLE public.forbidden(id integer)",
            "SELECT * FROM auth.users",  # system schema absent on vanilla PostgreSQL
            "DELETE FROM public.agent_operations",
            "UPDATE public.agent_policy_events SET version=100",
            "ALTER TABLE public.agent_policies DISABLE ROW LEVEL SECURITY",
        ):
            try:
                async with admin.transaction():
                    await admin.execute("SET LOCAL ROLE job_agent_runtime")
                    await admin.execute(statement)
                    raise AssertionError("runtime_forbidden_operation_succeeded")
            except (asyncpg.InsufficientPrivilegeError, asyncpg.UndefinedTableError, asyncpg.InvalidSchemaNameError):
                denied += 1
        faults = {
            "anonymous_grant": "GRANT SELECT ON public.agent_operations TO anon",
            "disabled_rls": "ALTER TABLE public.agent_operations DISABLE ROW LEVEL SECURITY",
            "privileged_runtime": "ALTER ROLE job_agent_runtime BYPASSRLS",
            "policy_widened": "CREATE POLICY unsafe ON public.agent_operations TO PUBLIC USING (true)",
            "runtime_extra_delete": "GRANT DELETE ON public.agent_operations TO job_agent_runtime",
            "unsafe_default_grant": "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO anon",
            "cross_schema_access": "CREATE SCHEMA phase1_other; CREATE TABLE phase1_other.private_row(id integer); GRANT USAGE ON SCHEMA phase1_other TO job_agent_runtime; GRANT SELECT ON phase1_other.private_row TO job_agent_runtime",
        }
        if with_managed_function:
            faults.update({
                "managed_function_client_grant": "GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO anon",
                "managed_function_runtime_grant": "GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO job_agent_runtime",
                "managed_function_definition_drift": "ALTER FUNCTION public.rls_auto_enable() RESET search_path",
                "managed_event_trigger_disabled": "ALTER EVENT TRIGGER ensure_rls DISABLE",
                "managed_event_trigger_extra": "CREATE EVENT TRIGGER unexpected_rls ON ddl_command_end WHEN TAG IN ('CREATE TABLE') EXECUTE FUNCTION public.rls_auto_enable()",
            })
        rejected = []
        for name, statement in faults.items():
            transaction = admin.transaction()
            await transaction.start()
            try:
                await admin.execute(statement)
                await admin.execute("SET LOCAL ROLE job_agent_runtime")
                try:
                    await verify_public_database(admin, settings)
                except RuntimeError:
                    rejected.append(name)
                finally:
                    # Savepoint rollback instead of committing a fault.
                    await admin.execute("RESET ROLE")
            finally:
                await transaction.rollback()
        assert len(rejected) == len(faults), rejected
        try:
            async with admin.transaction():
                await verify_public_database(admin, settings)
        except RuntimeError as exc:
            assert str(exc) == "database_runtime_role_authority_incompatible"
        else:
            raise AssertionError("admin_runtime_accepted")
        # TLS requirement cannot be weakened even on a reachable PostgreSQL connection.
        async with admin.transaction():
            await admin.execute("SET LOCAL ROLE job_agent_runtime")
            try:
                await verify_public_database(admin, Settings(_env_file=None, DATABASE_SCHEMA="public", DB_REQUIRE_TLS=True))
            except RuntimeError as exc:
                assert str(exc) == "database_tls_required"
            else:
                raise AssertionError("non_tls_connection_accepted")
        # Confirm the fresh-only bundle refuses a second application, atomically.
        try:
            await admin.execute((ROOT / "supabase/fresh_public/001_phase1_public.sql").read_text())
        except asyncpg.RaiseError as exc:
            assert "fresh_dedicated_project_required" in str(exc)
            await admin.execute("ROLLBACK")
        else:
            raise AssertionError("nonempty_database_accepted")
        print(json.dumps({"state": "passed", "evidence": "actual_disposable_postgresql17",
            "tables": len(manifest["tables"]), "denied_runtime_operations": denied,
            "rejected_security_faults": rejected, "remote_ddl": False}, indent=2))
    finally:
        await admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--with-supabase-managed-function", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify(args.bootstrap, args.with_supabase_managed_function))
