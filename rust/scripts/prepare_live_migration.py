"""Build the reviewed additive SQL package. Never connects to a database."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "rust/agent-runtime/sql" / name for name in (
    "001_runtime.sql", "002_control.sql", "003_telegram.sql", "004_graph.sql", "005_backend_access.sql"
)]
TARGET = ROOT / "supabase/runtime/001_rust_agent_runtime.review.sql"
HEADER = """-- Target: approved project luvdmwnlwaqgvfwlmlom, public schema only.
-- Deploy the matching backend catalog recognizer BEFORE applying this package.
-- Review backup/rollback inventory and run through the owner database connection.
-- This does not enable a worker, modify application history or grant submissions.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '60s';
DO $preflight$
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'explicit_owner_migration_connection_required';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='job_agent_owner' AND NOT rolcanlogin)
       OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='job_agent_runtime'
                     AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls)
    THEN RAISE EXCEPTION 'restricted_application_roles_required'; END IF;
    IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND c.relname IN (
                  'rust_agent_runs','rust_agent_events','rust_agent_control',
                  'rust_agent_control_events','rust_telegram_runtime','rust_telegram_outbox'))
    THEN RAISE EXCEPTION 'rust_runtime_schema_already_or_partially_installed'; END IF;
    PERFORM value FROM public.owner_preferences
      WHERE key='application_queue_policy' AND value->>'state'='STOPPED' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'stopped_application_queue_required'; END IF;
END $preflight$;
"""


def render():
    return HEADER + "\n".join(
        "\n-- Source: " + str(path.relative_to(ROOT)) + "\n" + path.read_text()
        for path in SOURCES
    ) + "\nCOMMIT;\n"


if __name__ == "__main__":
    content = render()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content)
    print("review_package_sha256:" + hashlib.sha256(content.encode()).hexdigest())
