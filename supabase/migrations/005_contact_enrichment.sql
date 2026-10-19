-- Phase 3: additive, backend-only. Apply after 001-004. Never run at app startup.
BEGIN;
ALTER TABLE job_agent.contacts
    ADD COLUMN IF NOT EXISTS do_not_contact BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS suppression_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS human_review_notes TEXT,
    ADD COLUMN IF NOT EXISTS human_corrected BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_contacts_suppression ON job_agent.contacts(company_id,do_not_contact);
CREATE TABLE IF NOT EXISTS job_agent.contact_enrichment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES job_agent.companies(id) ON DELETE CASCADE,
    request_hash VARCHAR(64) NOT NULL, target_roles JSONB NOT NULL DEFAULT '[]',
    provider_plan JSONB NOT NULL DEFAULT '[]', state VARCHAR(50) NOT NULL DEFAULT 'running',
    contact_ids JSONB NOT NULL DEFAULT '[]', counts JSONB NOT NULL DEFAULT '{}',
    usage JSONB NOT NULL DEFAULT '[]', errors JSONB NOT NULL DEFAULT '[]',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
    idempotency_key VARCHAR(100) UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_contact_runs_company ON job_agent.contact_enrichment_runs(company_id);
CREATE TABLE IF NOT EXISTS job_agent.contact_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES job_agent.contacts(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES job_agent.companies(id) ON DELETE CASCADE,
    source VARCHAR(100) NOT NULL, evidence_type VARCHAR(50) NOT NULL,
    evidence_url TEXT, observed_role VARCHAR(255), observed_company VARCHAR(255),
    provider_verification_claim VARCHAR(100), strength VARCHAR(20) NOT NULL DEFAULT 'moderate'
        CHECK(strength IN ('weak','moderate','strong')),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{}', user_confirmed BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_contact ON job_agent.contact_evidence(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_company ON job_agent.contact_evidence(company_id);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_expiry ON job_agent.contact_evidence(expires_at);
CREATE TABLE IF NOT EXISTS job_agent.contact_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES job_agent.companies(id) ON DELETE CASCADE,
    contact_id UUID NOT NULL REFERENCES job_agent.contacts(id) ON DELETE CASCADE,
    namespace VARCHAR(100) NOT NULL, identity_key VARCHAR(2048) NOT NULL,
    discovered_person_id UUID REFERENCES job_agent.discovered_company_people(id) ON DELETE SET NULL,
    CONSTRAINT uq_contact_identity UNIQUE(company_id,namespace,identity_key)
);
CREATE INDEX IF NOT EXISTS idx_contact_identity_contact ON job_agent.contact_identities(contact_id);
CREATE TABLE IF NOT EXISTS job_agent.contact_provider_lookups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES job_agent.companies(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL, identity_key VARCHAR(64) NOT NULL,
    reservation_id VARCHAR(100) NOT NULL UNIQUE, state VARCHAR(50) NOT NULL DEFAULT 'running',
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_contact_lookup UNIQUE(company_id,provider,identity_key)
);
ALTER TABLE job_agent.contacts ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['contacts','contact_enrichment_runs','contact_evidence','contact_identities','contact_provider_lookups'] LOOP
        EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON job_agent.%I TO service_role',table_name);
        END IF;
    END LOOP;
END;
$$;
COMMIT;
