-- Additive Phase 6A. Apply only through an operator-reviewed migration process.
BEGIN;
CREATE TABLE IF NOT EXISTS job_agent.company_source_observations (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 company_id UUID NOT NULL REFERENCES job_agent.companies(id) ON DELETE CASCADE,
 run_id UUID REFERENCES job_agent.discovery_runs(id) ON DELETE SET NULL,
 source VARCHAR(100) NOT NULL, identity_key VARCHAR(64) NOT NULL,
 content_hash VARCHAR(64) NOT NULL, source_url TEXT NOT NULL,
 observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), attributes JSONB NOT NULL DEFAULT '{}',
 verification_status VARCHAR(50) NOT NULL DEFAULT 'requires_review'
   CHECK (verification_status IN ('requires_review','source_reported','human_confirmed')),
 CONSTRAINT uq_company_snapshot UNIQUE(source,identity_key,content_hash)
);
CREATE INDEX IF NOT EXISTS idx_company_snapshot_company ON job_agent.company_source_observations(company_id,observed_at DESC);
CREATE TABLE IF NOT EXISTS job_agent.startup_shortlist_entries (
 company_id UUID PRIMARY KEY REFERENCES job_agent.companies(id) ON DELETE CASCADE,
 run_id UUID REFERENCES job_agent.discovery_runs(id) ON DELETE SET NULL,
 snapshot JSONB NOT NULL DEFAULT '{}', note TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS job_agent.provider_connection_checks (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), provider VARCHAR(100) NOT NULL,
 operation VARCHAR(50) NOT NULL DEFAULT 'sample_jobs', configuration_fingerprint VARCHAR(64),
 state VARCHAR(50) NOT NULL DEFAULT 'testing'
   CHECK(state IN ('not_configured','configured_not_tested','testing','live_verified','failed','authorization_required','rate_limited','unsupported')),
 checked_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
 http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
 result_count INTEGER CHECK(result_count >= 0), schema_valid BOOLEAN,
 evidence_urls JSONB NOT NULL DEFAULT '[]',
 is_live BOOLEAN NOT NULL DEFAULT true, error_category VARCHAR(100),
 CHECK(state <> 'live_verified' OR (is_live AND schema_valid AND finished_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_provider_check_latest ON job_agent.provider_connection_checks(provider,checked_at DESC);
CREATE TABLE IF NOT EXISTS job_agent.provider_access_windows (
 provider VARCHAR(100) PRIMARY KEY, next_allowed_at TIMESTAMPTZ NOT NULL
);
-- Snapshots are append-only. Explicit retention deletion remains an operator operation.
-- The FK's SET NULL is allowed when an audit run is pruned.
CREATE OR REPLACE FUNCTION job_agent.company_snapshot_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (to_jsonb(NEW)-'run_id') IS DISTINCT FROM (to_jsonb(OLD)-'run_id')
    OR (NEW.run_id IS DISTINCT FROM OLD.run_id AND NEW.run_id IS NOT NULL) THEN
  RAISE EXCEPTION 'Company evidence is append-only';
 END IF;
 RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS company_snapshot_guard ON job_agent.company_source_observations;
CREATE TRIGGER company_snapshot_guard BEFORE UPDATE ON job_agent.company_source_observations
FOR EACH ROW EXECUTE FUNCTION job_agent.company_snapshot_guard();
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['company_source_observations','startup_shortlist_entries','provider_connection_checks','provider_access_windows'] LOOP
  EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,DELETE ON job_agent.%I TO service_role',table_name);
   IF table_name IN ('provider_connection_checks','provider_access_windows') THEN
    EXECUTE format('GRANT UPDATE ON job_agent.%I TO service_role',table_name);
   END IF;
  END IF;
 END LOOP;
END;
$$;
COMMIT;
