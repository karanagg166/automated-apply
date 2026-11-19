"""Native disposable PG fixture for the additive Rust package; never loads owner config."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import asyncpg

from backend.app.core.config import Settings
from backend.app.local_agent.public_database import verify_public_database
from backend.app.operations.migrations import catalog
from backend.app.operations.rust_schema import MANIFEST, PACKAGE, TABLES
from rust.scripts.prepare_live_migration import SOURCES, render

ROOT = Path(__file__).resolve().parents[2]


async def verify(port, write_manifest):
    package_sql = PACKAGE.read_text()
    assert package_sql == render(), "review_package_source_drift"
    connection = await asyncpg.connect(host="127.0.0.1", port=port,
                                      user="bootstrap_admin", database="rust_schema_fixture")
    owner = None
    settings = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="public", DB_REQUIRE_TLS=False)
    checks = []
    try:
        await connection.execute(
            "CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; "
            "CREATE ROLE postgres LOGIN NOSUPERUSER CREATEDB CREATEROLE BYPASSRLS; "
            "ALTER DATABASE rust_schema_fixture OWNER TO postgres; "
            "GRANT USAGE ON SCHEMA public TO postgres;"
        )
        owner = await asyncpg.connect(host="127.0.0.1", port=port,
                                      user="postgres", database="rust_schema_fixture")
        assert not await owner.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname='postgres'")
        await owner.execute((ROOT / "supabase/fresh_public/001_phase1_public.sql").read_text())
        baseline = json.loads((ROOT / "supabase/fresh_public/manifest.json").read_text())
        for followup in baseline.get("followups", []):
            await owner.execute((ROOT / "supabase/fresh_public" / followup["file"]).read_text())

        async def accepted():
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE job_agent_runtime")
                await verify_public_database(connection, settings)

        await accepted()
        checks.append("existing_catalog_still_accepted")
        async def refusal(expected_error):
            try:
                await owner.execute(package_sql)
            except asyncpg.RaiseError as error:
                assert str(error) == expected_error
                await owner.execute("ROLLBACK")
            else:
                raise AssertionError("unstopped_control_migration_not_rejected")
            assert not await owner.fetchval(
                "SELECT to_regclass('public.rust_agent_runs') IS NOT NULL"
            )

        await owner.execute(
            """INSERT INTO public.owner_preferences(key,value)
               VALUES('application_queue_policy','{"state":"RUNNING"}')"""
        )
        await refusal("stopped_application_queue_required")
        checks.append("running_queue_refused_without_partial_ddl")
        await owner.execute(
            """UPDATE public.owner_preferences SET value='{"state":"STOPPED"}'
               WHERE key='application_queue_policy'"""
        )
        for saved in ({"state": "RUNNING"}, {"state": "PAUSED"}, {"revision": 7}):
            await owner.execute(
                """INSERT INTO public.owner_preferences(key,value)
                   VALUES('naukri_automation',$1::jsonb)
                   ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""",
                json.dumps(saved),
            )
            await refusal("stopped_legacy_preparation_required")
        checks.append("unstopped_legacy_preparation_refused_without_partial_ddl")
        await owner.execute(
            """UPDATE public.owner_preferences SET value='{"state":"STOPPED","revision":8}'
               WHERE key='naukri_automation'"""
        )
        await owner.execute(package_sql)
        assert not await owner.fetchval(
            "SELECT has_schema_privilege('job_agent_owner', 'public', 'CREATE')"
        )
        checks.append("non_superuser_owner_schema_create_revoked")
        assert await owner.fetchval("SELECT mode FROM public.rust_agent_control") == "STOPPED"
        assert await owner.fetchval(
            "SELECT value->>'revision' FROM public.owner_preferences WHERE key='naukri_automation'"
        ) == "8"
        checks.append("atomic_additive_install_starts_stopped")

        actual = await catalog(connection, "public")
        indexes = {row["indexname"] for row in await connection.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename=ANY($1::text[])", sorted(TABLES))}
        overlay = {}
        for section, values in actual.items():
            if section == "unsafe_grants":
                overlay[section] = []
            elif section == "indexes":
                overlay[section] = {key: value for key, value in values.items() if key in indexes}
            else:
                overlay[section] = {key: value for key, value in values.items() if key.split(".", 1)[0] in TABLES}
        expected = {"package_sha256": hashlib.sha256(PACKAGE.read_bytes()).hexdigest(),
                    "sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCES},
                    "catalog": overlay}
        if write_manifest:
            MANIFEST.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
        else:
            assert json.loads(MANIFEST.read_text()) == expected, "rust_schema_manifest_drift"
        await accepted()
        checks.append("complete_exact_catalog_and_restricted_role_accepted")

        async def denied(role, sql):
            try:
                async with connection.transaction():
                    assert role in {"job_agent_runtime", "anon", "authenticated", "service_role"}
                    await connection.execute("SET LOCAL ROLE " + role)
                    await connection.execute(sql)
            except asyncpg.InsufficientPrivilegeError:
                return
            raise AssertionError("unexpected_runtime_or_client_authority")

        await denied("job_agent_runtime", "CREATE TABLE public.unauthorized_fixture(id int)")
        await denied("job_agent_runtime", "DELETE FROM public.rust_agent_runs")
        await denied("job_agent_runtime", "UPDATE public.rust_agent_events SET state='tampered'")
        await denied("job_agent_runtime", "UPDATE public.rust_agent_control_events SET mode='RUNNING'")
        checks.append("no_runtime_ddl_delete_or_audit_update")
        for role in ("anon", "authenticated", "service_role"):
            await denied(role, "SELECT * FROM public.rust_agent_runs")
        checks.append("shared_clients_cannot_read_new_tables")
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE job_agent_runtime")
            await connection.execute("INSERT INTO public.rust_agent_runs(id,request_key,run)VALUES('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','{}')")
            await connection.execute("UPDATE public.rust_agent_runs SET revision=revision+1")
            await connection.execute("INSERT INTO public.rust_agent_events(run_id,revision,role,state,model_calls,tool_calls,reserved_tokens)VALUES('00000000-0000-0000-0000-000000000001',1,'discovery','fixture',0,0,0)")
        checks.append("runtime_can_persist_runs_and_append_events")

        for mutation in ("DROP TABLE public.rust_telegram_outbox", "ALTER TABLE public.rust_agent_runs DISABLE ROW LEVEL SECURITY",
                         "ALTER TABLE public.rust_agent_runs ADD COLUMN unexpected_fixture text"):
            transaction = connection.transaction()
            await transaction.start()
            try:
                await connection.execute(mutation)
                try:
                    await connection.execute("SET LOCAL ROLE job_agent_runtime")
                    await verify_public_database(connection, settings)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("schema_or_acl_drift_not_rejected")
            finally:
                await transaction.rollback()
            checks.append("refuses_" + mutation.split()[0].lower() + "_drift")
        await accepted()
        print(json.dumps({"fixture_only": True, "checks_passed": len(checks), "checks": checks,
                          "owner_database_accessed": False, "package_sha256": expected["package_sha256"]}))
    finally:
        if owner is not None:
            await owner.close()
        await connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    binary = Path("/opt/homebrew/opt/postgresql@17/bin")
    assert all((binary / name).is_file() for name in ("initdb", "pg_ctl", "createdb")), "native_postgresql17_required"
    root = Path(tempfile.mkdtemp(prefix="rust-schema-fictional-pg-"))
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C"}
    started = False
    try:
        with (root / "setup.log").open("wb") as log:
            subprocess.run([str(binary / "initdb"), "-D", str(root / "data"), "-U", "bootstrap_admin", "--no-locale", "-E", "UTF8", "--auth=trust"], env=environment, stdout=log, stderr=log, check=True)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            started = True
            subprocess.run([str(binary / "pg_ctl"), "-D", str(root / "data"), "-l", str(root / "postgres.log"), "-w", "-t", "15", "-o", f"-h 127.0.0.1 -p {port} -k {root} -c max_connections=8 -c shared_buffers=16MB", "start"], env=environment, stdout=log, stderr=log, check=True)
            subprocess.run([str(binary / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "bootstrap_admin", "rust_schema_fixture"], env=environment, stdout=log, stderr=log, check=True)
        asyncio.run(verify(port, args.write_manifest))
    finally:
        stopped = not started or subprocess.run([str(binary / "pg_ctl"), "-D", str(root / "data"), "-w", "-t", "15", "-m", "fast", "stop"], env=environment, capture_output=True).returncode == 0
        if stopped:
            shutil.rmtree(root)
        else:
            print("fictional_fixture_shutdown_failed_preserved")


if __name__ == "__main__":
    main()
