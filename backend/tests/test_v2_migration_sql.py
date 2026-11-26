"""Followup 004: additive, idempotent, and accepted by the strict catalog verifier."""

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from backend.app.operations import v2_schema
from backend.scripts.migrate_v2_core import MIGRATION, strip_pgvector

SQL = MIGRATION.read_text()


def statements(sql):
    return [s.strip() for s in re.split(r";\s*\n", sql) if s.strip()]


def test_migration_is_additive():
    upper = SQL.upper()
    for forbidden in ("DROP TABLE", "DROP COLUMN", "TRUNCATE", "DELETE FROM", "ALTER COLUMN", "DROP CONSTRAINT"):
        assert forbidden not in upper, forbidden
    assert "candidate_profiles" not in re.sub(r"--.*", "", SQL)


def test_every_create_is_idempotent():
    code = re.sub(r"--.*", "", SQL)
    assert len(re.findall(r"CREATE TABLE IF NOT EXISTS", code)) == 12  # Phase 6A: + mail_events
    assert not re.search(r"CREATE TABLE (?!IF NOT EXISTS)", code)
    assert not re.search(r"CREATE (?:UNIQUE )?INDEX (?!IF NOT EXISTS)", code)
    assert "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions" in code
    assert "ON CONFLICT (platform) DO NOTHING" in code
    assert code.count("ON CONFLICT (singleton_key) DO NOTHING") == 2  # worker_control + telegram_v2_state seeds
    assert "IF NOT EXISTS (SELECT 1 FROM pg_policies" in code


def test_migration_tables_match_overlay_inventory():
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS public\.(\w+)", SQL))
    assert created == set(v2_schema.TABLES)
    assert "application_events" not in created  # existing packet history table is untouched


def test_naukri_defaults_are_seeded():
    assert "max_applies_per_day INT NOT NULL DEFAULT 50" in SQL
    assert "max_applies_per_hour INT NOT NULL DEFAULT 10" in SQL
    assert "max_job_age_days INT NOT NULL DEFAULT 7" in SQL
    assert "max_applicants INT NOT NULL DEFAULT 300" in SQL
    assert "DEFAULT 'allow_lower_bound'" in SQL
    assert "('naukri', true)" in SQL


def test_strip_pgvector_removes_only_vector_blocks():
    stripped = strip_pgvector(SQL)
    assert "CREATE EXTENSION" not in stripped and "vector(" not in stripped
    assert "vector_cosine_ops" not in stripped and "public.semantic_cache (" not in stripped
    assert "CREATE TABLE IF NOT EXISTS public.applications" in stripped


def test_overlay_requires_all_or_none():
    with pytest.raises(RuntimeError, match="partial_install"):
        v2_schema.installed_tables({"applications": "true"})
    expected = {"tables": {"jobs": "true"}, "columns": {}, "indexes": {}}
    actual = {"tables": {"jobs": "true", **dict.fromkeys(v2_schema.TABLES, "true")},
              "columns": {"applications.state": "text", "jobs.id": "uuid"},
              "indexes": {"ix_applications_dedup_key": "CREATE INDEX ix_applications_dedup_key ON public.applications USING btree (dedup_key)"}}
    merged = v2_schema.expected_overlay(expected, actual)
    assert set(merged["tables"]) == {"jobs", *v2_schema.TABLES}
    assert merged["columns"] == {"applications.state": "text"}
    assert "ix_applications_dedup_key" in merged["indexes"]


PG_BIN = next((Path(p) for p in ("/opt/homebrew/opt/postgresql@17/bin", "/opt/homebrew/opt/postgresql@14/bin")
               if (Path(p) / "initdb").exists()), None)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                    reason="local PostgreSQL binaries not available")
def test_migration_applies_twice_on_disposable_postgres(tmp_path):
    data, port = tmp_path / "pg", free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(data), "-U", "postgres", "--auth=trust"],
                   check=True, capture_output=True)
    server = subprocess.Popen([str(PG_BIN / "postgres"), "-D", str(data), "-p", str(port), "-k", "",
                               "-c", "listen_addresses=127.0.0.1"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    psql = [str(PG_BIN / "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q", "-At"]
    try:
        for _ in range(100):
            if subprocess.run([*psql, "-c", "SELECT 1"], check=False, capture_output=True).returncode == 0:
                break
            time.sleep(0.1)
        bootstrap = """
            CREATE ROLE job_agent_owner NOLOGIN; CREATE ROLE job_agent_runtime NOLOGIN CONNECTION LIMIT 5;
            GRANT job_agent_owner TO postgres;
            CREATE TABLE public.jobs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), title text);
            ALTER TABLE public.jobs OWNER TO job_agent_owner;
            INSERT INTO public.jobs (title) VALUES ('kept-1'), ('kept-2');
        """
        subprocess.run([*psql, "-c", bootstrap], check=True, capture_output=True)
        migration = tmp_path / "004.sql"
        migration.write_text(strip_pgvector(SQL))
        for _ in range(2):
            subprocess.run([*psql, "-f", str(migration)], check=True, capture_output=True, text=True)
        query = """SELECT (SELECT count(*) FROM public.jobs),
                          (SELECT count(*) FROM public.portal_rules),
                          (SELECT string_agg(platform || ':' || enabled, ',' ORDER BY platform) FROM public.portal_rules),
                          (SELECT count(*) FROM pg_policies WHERE policyname='job_agent_backend'),
                          (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='applications'),
                          has_table_privilege('job_agent_runtime','public.application_state_events','UPDATE'),
                          has_table_privilege('job_agent_runtime','public.applications','UPDATE')"""
        out = subprocess.run([*psql, "-c", query], check=True, capture_output=True, text=True).stdout.strip()
        jobs, rules, platforms, policies, owner, events_update, apps_update = out.split("|")
        assert jobs == "2" and rules == "10"  # Phase 5: 10-portal roster, only naukri enabled
        assert platforms == ("greenhouse:false,himalayas:false,hiringcafe:false,instahyre:false,internshala:false,"
                             "lever:false,naukri:true,we_work_remotely:false,wellfound:false,work_at_a_startup:false")
        assert policies == "11"  # 12 tables minus semantic_cache (pgvector block stripped)
        assert owner == "job_agent_owner" and events_update == "f" and apps_update == "t"
        duplicate = subprocess.run(
            [*psql, "-c", ("INSERT INTO public.applications (platform, external_job_id, state) VALUES "
                          "('naukri','051126000230','SUBMISSION_UNKNOWN'),('naukri','051126000230','DISCOVERED')")],
            check=False, capture_output=True, text=True)
        assert duplicate.returncode != 0 and "uq_applications_platform_external" in duplicate.stderr
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)
