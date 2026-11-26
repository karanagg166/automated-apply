"""Followup 005 (Phase 9): additive, idempotent, recognised by the v2 schema overlay."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

import pytest

from backend.app.operations import runtime_security, v2_schema
from backend.scripts.migrate_v2_core import MIGRATION, phase9_status, strip_pgvector
from backend.tests.test_v2_migration_sql import PG_BIN, free_port

SQL = v2_schema.PHASE9_MIGRATION.read_text()
CODE = re.sub(r"--.*", "", SQL)


def test_phase9_migration_is_additive_and_idempotent() -> None:
    upper = CODE.upper()
    for forbidden in ("DROP TABLE", "DROP COLUMN", "TRUNCATE", "DELETE FROM", "ALTER COLUMN",
                      "DROP CONSTRAINT", "DROP INDEX", "UPDATE PUBLIC."):
        assert forbidden not in upper, forbidden
    assert "candidate_profiles" not in CODE
    assert not re.search(r"CREATE TABLE (?!IF NOT EXISTS)", CODE)
    assert not re.search(r"CREATE (?:UNIQUE )?INDEX (?!IF NOT EXISTS)", CODE)
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", CODE)
    assert "IF NOT EXISTS (SELECT 1 FROM pg_policies" in CODE
    assert "REVOKE CREATE ON SCHEMA public FROM job_agent_owner" in CODE


def test_phase9_inventory_matches_sql() -> None:
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS public\.(\w+)", CODE))
    assert created == set(v2_schema.PHASE9_TABLES)
    assert not created & v2_schema.TABLES
    for table, columns in v2_schema.PHASE9_COLUMNS.items():
        for column in columns:
            assert f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {column} " in CODE, column
    acl_tables = re.search(r"phase9_tables CONSTANT TEXT\[\] := ARRAY\[(.*?)\];", CODE, re.S)
    assert acl_tables is not None
    assert set(re.findall(r"'(\w+)'", acl_tables.group(1))) == set(v2_schema.PHASE9_TABLES)


def test_phase9_overlay_is_all_or_none_and_requires_core() -> None:
    core = dict.fromkeys(v2_schema.TABLES, "true")
    with pytest.raises(RuntimeError, match="phase9_schema_partial_install"):
        v2_schema.installed_tables({**core, "agent_audit_log": "true"})
    with pytest.raises(RuntimeError, match="phase9_schema_partial_install"):
        v2_schema.installed_tables(dict.fromkeys(v2_schema.PHASE9_TABLES, "true"))
    full = {**core, **dict.fromkeys(v2_schema.PHASE9_TABLES, "true")}
    assert v2_schema.installed_tables(full) == v2_schema.ALL_TABLES
    assert v2_schema.phase9_installed(full) and not v2_schema.phase9_installed(core)
    actual = {"tables": {"jobs": "true", **full},
              "columns": {"agent_audit_log.tool_name": "text", "applications.priority": "smallint"},
              "indexes": {"ix_agent_audit_log_created":
                          "CREATE INDEX ix_agent_audit_log_created ON public.agent_audit_log USING btree (created_at DESC)"}}
    merged = v2_schema.expected_overlay({"tables": {"jobs": "true"}, "columns": {}, "indexes": {}}, actual)
    assert set(merged["tables"]) == {"jobs", *v2_schema.ALL_TABLES}
    assert set(merged["columns"]) == {"agent_audit_log.tool_name", "applications.priority"}
    assert "ix_agent_audit_log_created" in merged["indexes"]


def test_runtime_privileges_cover_phase9_tables() -> None:
    privileges = runtime_security.runtime_privileges([*v2_schema.PHASE9_TABLES, "contact_identities"])
    assert privileges["agent_audit_log"] == {"SELECT", "INSERT"}
    assert privileges["agent_conversation_turns"] == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert privileges["watcher_state"] == {"SELECT", "INSERT", "UPDATE"}
    assert privileges["profile_sync_runs"] == {"SELECT", "INSERT", "UPDATE"}


def test_phase9_status_is_pure() -> None:
    columns = {t: list(c) for t, c in v2_schema.PHASE9_COLUMNS.items()}
    assert phase9_status({"phase9_tables_present": sorted(v2_schema.PHASE9_TABLES),
                          "phase9_columns_present": columns})["status"] == "applied"
    assert phase9_status({"phase9_tables_present": [], "phase9_columns_present": {}})["status"] == "missing"
    partial = phase9_status({"phase9_tables_present": ["watcher_state"], "phase9_columns_present": columns})
    assert partial["status"] == "partial" and "agent_audit_log" in partial["missing_tables"]


@pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                    reason="local PostgreSQL binaries not available")
def test_phase9_applies_twice_after_004_as_non_superuser(tmp_path) -> None:
    assert PG_BIN is not None
    data, port = tmp_path / "pg", free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(data), "-U", "admin", "--auth=trust"],
                   check=True, capture_output=True)
    server = subprocess.Popen([str(PG_BIN / "postgres"), "-D", str(data), "-p", str(port), "-k", "",
                               "-c", "listen_addresses=127.0.0.1"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def psql(user: str, db: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        assert PG_BIN is not None
        return subprocess.run([str(PG_BIN / "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", user, "-d", db,
                               "-v", "ON_ERROR_STOP=1", "-q", "-At", *args],
                              check=check, capture_output=True, text=True)

    try:
        for _ in range(100):
            if psql("admin", "postgres", "-c", "SELECT 1", check=False).returncode == 0:
                break
            time.sleep(0.1)
        psql("admin", "postgres", "-c", """
            CREATE ROLE supa LOGIN NOSUPERUSER NOCREATEROLE BYPASSRLS;
            CREATE ROLE job_agent_owner NOLOGIN NOSUPERUSER NOINHERIT;
            CREATE ROLE job_agent_runtime NOLOGIN; CREATE ROLE anon NOLOGIN;
            CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN;
            GRANT job_agent_owner TO supa;""")
        psql("admin", "postgres", "-c", "CREATE DATABASE app OWNER supa")
        psql("admin", "app", "-c", "ALTER SCHEMA public OWNER TO supa; CREATE SCHEMA extensions AUTHORIZATION supa;")
        psql("supa", "app", "-c", "CREATE TABLE public.jobs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), title text);")
        psql("admin", "app", "-c", "ALTER TABLE public.jobs OWNER TO job_agent_owner;")
        core = tmp_path / "004.sql"
        core.write_text(strip_pgvector(MIGRATION.read_text()))
        assert psql("supa", "app", "-f", str(core), check=False).returncode == 0
        psql("supa", "app", "-c", "INSERT INTO public.applications (platform, external_job_id, state) "
                                  "VALUES ('naukri','1','APPLIED')")
        phase9 = tmp_path / "005.sql"
        phase9.write_text(SQL)
        for _ in range(2):
            result = psql("supa", "app", "-f", str(phase9), check=False)
            assert result.returncode == 0, result.stderr[-500:]
        out = psql("admin", "app", "-c", """
            SELECT (SELECT priority FROM public.applications WHERE external_job_id='1'),
                   (SELECT circuit_level FROM public.portal_rules WHERE platform='naukri'),
                   (SELECT count(*) FROM pg_policies WHERE policyname='job_agent_backend'
                      AND tablename IN ('watcher_state','agent_audit_log','agent_conversation_turns','profile_sync_runs')),
                   has_table_privilege('job_agent_runtime','public.agent_audit_log','UPDATE'),
                   has_table_privilege('job_agent_runtime','public.agent_conversation_turns','DELETE'),
                   has_schema_privilege('job_agent_owner','public','CREATE'),
                   (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='watcher_state')""").stdout.strip()
        priority, level, policies, audit_update, turns_delete, still_create, owner = out.split("|")
        assert priority == "2" and level == "0" and policies == "4"
        assert audit_update == "f" and turns_delete == "t" and still_create == "f"
        assert owner == "job_agent_owner"
        bad = psql("supa", "app", "-c", "UPDATE public.applications SET priority=7", check=False)
        assert bad.returncode != 0
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)
