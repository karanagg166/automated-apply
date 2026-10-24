"""Deterministic fresh-project public DDL, never an apply command."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'supabase/fresh_public'


def build():
    OUT.mkdir(exist_ok=True)
    sources = sorted((ROOT / 'supabase/migrations').glob('*.sql'))
    source_hashes = [{"file": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources]
    # Historical files remain immutable. Translation applies to schema references only.
    body = '\n'.join(p.read_text().replace('job_agent.', 'public.').replace("'job_agent'", "'public'") for p in sources)
    body = body.replace('CREATE SCHEMA IF NOT EXISTS job_agent;', '')
    body = re.sub(r'^(BEGIN;|COMMIT;)\s*$', '', body, flags=re.M)
    guard = '''-- REVIEW REQUIRED. Fresh dedicated project luvdmwnlwaqgvfwlmlom only.
-- Derived from immutable 001-012; never replay on an existing application database.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '60s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S')
     AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.objid=c.oid AND d.deptype='e'))
 OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='public' AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.objid=p.oid AND d.deptype='e'))
 OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')
 OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('job_agent_owner','job_agent_runtime'))
 THEN RAISE EXCEPTION 'fresh_dedicated_project_required'; END IF;
END $$;
CREATE ROLE job_agent_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE job_agent_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5;
GRANT job_agent_owner TO postgres;
GRANT USAGE, CREATE ON SCHEMA public TO job_agent_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA public TO job_agent_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE job_agent_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated, service_role;
ALTER ROLE job_agent_runtime SET search_path = pg_catalog, public;
ALTER ROLE job_agent_runtime SET statement_timeout = '30s';
ALTER ROLE job_agent_runtime SET lock_timeout = '2s';
ALTER ROLE job_agent_runtime SET idle_in_transaction_session_timeout = '30s';
'''
    phase1 = '''
CREATE TABLE public.agent_policies (key varchar(20) PRIMARY KEY, version integer NOT NULL CHECK(version>=1), preferences jsonb NOT NULL);
CREATE TABLE public.agent_policy_events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), version integer NOT NULL UNIQUE, preferences jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.agent_operations (key varchar(180) PRIMARY KEY, actor varchar(120) NOT NULL, command varchar(50) NOT NULL, payload_hash varchar(64) NOT NULL, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.agent_telegram_state (key varchar(20) PRIMARY KEY, next_update_id bigint NOT NULL DEFAULT 0, bot_id varchar(40), last_poll_at timestamptz, last_error varchar(80), evidence_type varchar(40) NOT NULL DEFAULT 'unverified');
CREATE TABLE public.agent_telegram_deliveries (update_id bigint PRIMARY KEY, reply text NOT NULL, state varchar(20) NOT NULL CHECK(state IN ('pending','sending','sent')));
'''
    old = json.loads((ROOT / 'backend/app/operations/migration_manifest.json').read_text())
    tables = sorted([*old['catalog']['tables'], 'agent_policies','agent_policy_events','agent_operations','agent_telegram_state','agent_telegram_deliveries'])
    append_only = {'application_events','application_submission_evidence','company_source_observations','drive_resume_versions','provider_usage_logs','startup_shortlist_entries','agent_policy_events','agent_operations'}
    acl = []
    for table in tables:
        privs = ['SELECT','INSERT'] + ([] if table in append_only else ['UPDATE']) + (['DELETE'] if table == 'contact_identities' else [])
        acl += [f'ALTER TABLE public.{table} OWNER TO job_agent_owner;',f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;',f'ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;',f'REVOKE ALL ON public.{table} FROM PUBLIC, anon, authenticated, service_role;',f'GRANT {", ".join(privs)} ON public.{table} TO job_agent_runtime;',f'CREATE POLICY job_agent_backend ON public.{table} FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);']
    for function in old['catalog']['functions']:
        acl += [f'ALTER FUNCTION public.{function} OWNER TO job_agent_owner;',f'REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC, anon, authenticated, service_role;',f'GRANT EXECUTE ON FUNCTION public.{function} TO job_agent_runtime;']
    # No runtime DELETE of previews; cleanup uses an explicit administrative retention operation.
    acl += ['REVOKE CREATE ON SCHEMA public FROM job_agent_owner;', 'COMMIT;']
    sql = guard + body + phase1 + '\n'.join(acl) + '\n'
    # Normalize only the derived bundle, never immutable historical sources.
    sql = '\n'.join(line.rstrip() for line in sql.splitlines()) + '\n'
    path = OUT / '001_phase1_public.sql'
    path.write_text(sql)
    manifest = {'project_ref':'luvdmwnlwaqgvfwlmlom','schema':'public','sources':source_hashes,'bundle':path.name,'sha256':hashlib.sha256(sql.encode()).hexdigest(),'tables':tables,'runtime_role':'job_agent_runtime','remote_applied':False}
    if (OUT / 'catalog.json').exists():
        manifest['catalog_sha256'] = hashlib.sha256((OUT / 'catalog.json').read_bytes()).hexdigest()
    (OUT / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'project_ref':manifest['project_ref'],'tables':len(tables),'sha256':manifest['sha256'],'remote_applied':False}))

if __name__ == '__main__':
    build()
