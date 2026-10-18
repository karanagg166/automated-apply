-- Additive Phase 2B migration. No production execution by application startup.
BEGIN;
ALTER TABLE job_agent.jobs
    ADD COLUMN IF NOT EXISTS canonical_key TEXT,
    ADD COLUMN IF NOT EXISTS content_identity VARCHAR(64),
    ADD COLUMN IF NOT EXISTS application_url TEXT,
    ADD COLUMN IF NOT EXISTS remote_type VARCHAR(20) NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS employment_type VARCHAR(50),
    ADD COLUMN IF NOT EXISTS salary_min NUMERIC(16,2),
    ADD COLUMN IF NOT EXISTS salary_max NUMERIC(16,2),
    ADD COLUMN IF NOT EXISTS salary_currency VARCHAR(10),
    ADD COLUMN IF NOT EXISTS salary_period VARCHAR(20),
    ADD COLUMN IF NOT EXISTS first_observed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_observed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_verification_status VARCHAR(50) NOT NULL DEFAULT 'observed',
    ADD COLUMN IF NOT EXISTS discovery_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
-- Nullable keys preserve existing jobs without guessing or merging their identities.
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_canonical_key ON job_agent.jobs(canonical_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_content_identity ON job_agent.jobs(content_identity);
CREATE INDEX IF NOT EXISTS idx_jobs_observed ON job_agent.jobs(last_observed_at DESC);
CREATE TABLE IF NOT EXISTS job_agent.discovery_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(100) NOT NULL, request_hash VARCHAR(64) NOT NULL,
    query_summary JSONB NOT NULL DEFAULT '{}', status VARCHAR(50) NOT NULL DEFAULT 'running',
    rankings JSONB NOT NULL DEFAULT '[]',
    counts JSONB NOT NULL DEFAULT '{}', errors JSONB NOT NULL DEFAULT '[]',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
    provider_run_id VARCHAR(255), usage JSONB NOT NULL DEFAULT '{}',
    idempotency_key VARCHAR(100) UNIQUE
);
CREATE TABLE IF NOT EXISTS job_agent.job_source_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES job_agent.jobs(id) ON DELETE CASCADE,
    source VARCHAR(100) NOT NULL, identity_key VARCHAR(64) NOT NULL,
    source_job_id VARCHAR(255), original_url TEXT NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provenance JSONB NOT NULL DEFAULT '{}', verification_status VARCHAR(50) NOT NULL DEFAULT 'observed',
    CONSTRAINT uq_observation_identity UNIQUE(source, identity_key)
);
CREATE INDEX IF NOT EXISTS idx_observation_job ON job_agent.job_source_observations(job_id);
CREATE TABLE IF NOT EXISTS job_agent.discovered_company_people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES job_agent.companies(id) ON DELETE CASCADE,
    name VARCHAR(255), role VARCHAR(255), linkedin_url TEXT NOT NULL,
    evidence_url TEXT NOT NULL, source VARCHAR(50) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), verification_status VARCHAR(50) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}', CONSTRAINT uq_company_person_url UNIQUE(company_id, linkedin_url)
);
CREATE INDEX IF NOT EXISTS idx_people_company ON job_agent.discovered_company_people(company_id);
CREATE TABLE IF NOT EXISTS job_agent.discovery_monthly_budgets (
    provider VARCHAR(50) NOT NULL, month VARCHAR(7) NOT NULL,
    reserved NUMERIC(16,6) NOT NULL DEFAULT 0 CHECK(reserved >= 0), cooldown_until TIMESTAMPTZ,
    PRIMARY KEY(provider,month)
);
CREATE TABLE IF NOT EXISTS job_agent.discovery_budget_reservations (
    id VARCHAR(100) PRIMARY KEY, provider VARCHAR(50) NOT NULL, month VARCHAR(7) NOT NULL,
    reserved NUMERIC(16,6) NOT NULL CHECK(reserved >= 0), provider_run_id VARCHAR(255), reported_actual NUMERIC(16,6),
    state VARCHAR(50) NOT NULL DEFAULT 'reserved', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE job_agent.discovery_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.job_source_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.discovered_company_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.discovery_monthly_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.discovery_budget_reservations ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['discovery_runs','job_source_observations','discovered_company_people','discovery_monthly_budgets','discovery_budget_reservations'] LOOP
        EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC', table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
    END LOOP;
END;
$$;
COMMIT;
