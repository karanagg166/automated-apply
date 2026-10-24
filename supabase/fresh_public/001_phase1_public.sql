-- REVIEW REQUIRED. Fresh dedicated project luvdmwnlwaqgvfwlmlom only.
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
-- ==============================================================================
-- Migration: 001_initial_schema.sql
-- Project: Job Pulse Agent (job-pulse-agent)
-- Purpose: Create isolated 'public' schema and core tables with strict constraints.
-- Note: Does NOT modify, drop, or alter any objects in the 'public' or other schemas.
-- ==============================================================================

-- 1. Create dedicated schema


-- 2. Companies table
CREATE TABLE IF NOT EXISTS public.companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE,
    linkedin_url TEXT,
    email_pattern VARCHAR(100), -- e.g. {first}.{last}@{domain}
    is_catch_all BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_domain ON public.companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_name ON public.companies(name);

-- 3. Jobs table
CREATE TABLE IF NOT EXISTS public.jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    job_url TEXT NOT NULL UNIQUE,
    source_platform VARCHAR(100) NOT NULL, -- e.g. gmail_alert, greenhouse, lever, linkedin, manual
    location VARCHAR(255),
    is_remote BOOLEAN DEFAULT FALSE,
    experience_level VARCHAR(50), -- e.g. entry, junior, mid, senior
    salary_range VARCHAR(100),
    skills_required TEXT[] DEFAULT '{}',
    description TEXT,
    match_score NUMERIC(5, 2), -- 0.00 to 100.00
    match_explanation TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered', 'reviewed', 'shortlisted', 'applied', 'rejected', 'archived')),
    date_posted TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON public.jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON public.jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_match_score ON public.jobs(match_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON public.jobs(created_at DESC);

-- 4. Contacts table
CREATE TABLE IF NOT EXISTS public.contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role_title VARCHAR(255) NOT NULL,
    linkedin_url TEXT,
    email VARCHAR(255),
    email_status VARCHAR(50) NOT NULL DEFAULT 'unknown'
        CHECK (email_status IN ('unknown', 'candidate', 'provider_reported', 'verified', 'invalid')),
    confidence_score NUMERIC(5, 2) DEFAULT 0.00,
    enrichment_source VARCHAR(100), -- cache, pattern_inference, hunter, apollo, serper, signalhire
    last_verified_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON public.contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON public.contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_role_title ON public.contacts(role_title);
CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_company_email
    ON public.contacts(company_id, email)
    WHERE email IS NOT NULL;

-- 5. API keys pool (Cost-first credit management)
CREATE TABLE IF NOT EXISTS public.api_keys_pool (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(50) NOT NULL, -- hunter, apollo, serper, signalhire
    account_label VARCHAR(100) NOT NULL,
    secret_reference TEXT NOT NULL, -- encrypted ciphertext or env:VAR_NAME
    credits_remaining INT NOT NULL DEFAULT 0 CHECK (credits_remaining >= 0),
    monthly_limit INT NOT NULL DEFAULT 0,
    reset_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    cooldown_until TIMESTAMPTZ,
    last_error_code INT,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_api_keys_provider_account UNIQUE (provider, account_label)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON public.api_keys_pool(provider, is_active);

-- 6. Provider usage logs (Audit trail of every credit spent)
CREATE TABLE IF NOT EXISTS public.provider_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(50) NOT NULL,
    endpoint VARCHAR(255),
    credits_consumed INT NOT NULL DEFAULT 0,
    status_code INT,
    is_success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provider_usage_provider_date ON public.provider_usage_logs(provider, created_at DESC);

-- 7. Outreach logs (Strict Human-in-the-Loop state machine)
CREATE TABLE IF NOT EXISTS public.outreach_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES public.jobs(id) ON DELETE SET NULL,
    contact_id UUID REFERENCES public.contacts(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    resume_version VARCHAR(100),
    gmail_draft_id VARCHAR(255),
    gmail_message_id VARCHAR(255),
    gmail_thread_id VARCHAR(255),
    approval_status VARCHAR(50) NOT NULL DEFAULT 'draft_created'
        CHECK (approval_status IN ('draft_created', 'pending_approval', 'approved', 'sent', 'rejected')),
    approved_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_job_id ON public.outreach_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_outreach_contact_id ON public.outreach_logs(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_approval_status ON public.outreach_logs(approval_status);

-- Phase 1: additive candidate persistence. Apply only after 001.
-- Never apply to shared production without explicit approval.

CREATE TABLE IF NOT EXISTS public.candidate_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    singleton_key VARCHAR(20) NOT NULL DEFAULT 'primary' UNIQUE,
    version INTEGER NOT NULL DEFAULT 1,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(254) NOT NULL,
    phone VARCHAR(50),
    linkedin_url VARCHAR(2048),
    github_url VARCHAR(2048),
    portfolio_url VARCHAR(2048),
    personal_website VARCHAR(2048),
    verified_experience_years DOUBLE PRECISION,
    verified_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    verified_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    education JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects JSONB NOT NULL DEFAULT '[]'::jsonb,
    certifications JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_candidate_primary CHECK (singleton_key = 'primary'),
    CONSTRAINT ck_candidate_version CHECK (version >= 1),
    CONSTRAINT ck_candidate_name CHECK (length(trim(full_name)) BETWEEN 1 AND 200),
    CONSTRAINT ck_candidate_email CHECK (length(email) BETWEEN 3 AND 254 AND email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
    CONSTRAINT ck_candidate_phone CHECK (phone IS NULL OR length(trim(phone)) BETWEEN 1 AND 50),
    CONSTRAINT ck_candidate_experience CHECK (verified_experience_years BETWEEN 0 AND 100),
    CONSTRAINT ck_candidate_summary CHECK (summary IS NULL OR length(trim(summary)) BETWEEN 1 AND 4000),
    CONSTRAINT ck_candidate_urls CHECK (
        (linkedin_url IS NULL OR linkedin_url ~ '^https?://[^[:space:]/]+') AND
        (github_url IS NULL OR github_url ~ '^https?://[^[:space:]/]+') AND
        (portfolio_url IS NULL OR portfolio_url ~ '^https?://[^[:space:]/]+') AND
        (personal_website IS NULL OR personal_website ~ '^https?://[^[:space:]/]+')
    ),
    CONSTRAINT ck_candidate_skills CHECK (jsonb_typeof(verified_skills) = 'array' AND jsonb_array_length(verified_skills) <= 100),
    CONSTRAINT ck_candidate_roles CHECK (jsonb_typeof(verified_roles) = 'array' AND jsonb_array_length(verified_roles) <= 50),
    CONSTRAINT ck_candidate_education CHECK (jsonb_typeof(education) = 'array' AND jsonb_array_length(education) <= 30),
    CONSTRAINT ck_candidate_projects CHECK (jsonb_typeof(projects) = 'array' AND jsonb_array_length(projects) <= 50),
    CONSTRAINT ck_candidate_certifications CHECK (jsonb_typeof(certifications) = 'array' AND jsonb_array_length(certifications) <= 50),
    CONSTRAINT ck_candidate_preferences CHECK (
        jsonb_typeof(preferences) = 'object' AND
        (preferences->>'remote_preference' IS NULL OR preferences->>'remote_preference' IN ('remote','hybrid','onsite','any')) AND
        (preferences->>'minimum_salary' IS NULL OR
            (jsonb_typeof(preferences->'minimum_salary') = 'number' AND (preferences->>'minimum_salary')::numeric BETWEEN 0 AND 1000000000000)) AND
        (preferences->>'salary_currency' IS NULL OR preferences->>'salary_currency' ~ '^[A-Z]{3}$') AND
        (preferences->>'notice_period_days' IS NULL OR preferences->>'notice_period_days' ~ '^[0-9]+$' AND (preferences->>'notice_period_days')::numeric BETWEEN 0 AND 3650) AND
        (preferences->>'prioritize_startups' IS NULL OR jsonb_typeof(preferences->'prioritize_startups') = 'boolean') AND
        (NOT preferences ? 'employment_types' OR (jsonb_typeof(preferences->'employment_types') = 'array' AND preferences->'employment_types' <@ '["full_time","internship","contract"]'::jsonb))
    ),
    CONSTRAINT ck_candidate_json_size CHECK (
        octet_length(verified_skills::text) + octet_length(verified_roles::text) +
        octet_length(education::text) + octet_length(projects::text) +
        octet_length(certifications::text) + octet_length(preferences::text) <= 131072
    )
);

-- Direct SQL writers must also advance the version; equivalent updates stay idempotent.
CREATE OR REPLACE FUNCTION public.candidate_profile_version() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    NEW.created_at := OLD.created_at;
    IF (to_jsonb(NEW) - ARRAY['version','created_at','updated_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['version','created_at','updated_at']) THEN
        NEW.version := OLD.version + 1;
        NEW.updated_at := clock_timestamp();
    ELSE
        NEW.version := OLD.version;
        NEW.updated_at := OLD.updated_at;
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER candidate_profile_version_trigger
BEFORE UPDATE ON public.candidate_profiles
FOR EACH ROW EXECUTE FUNCTION public.candidate_profile_version();

-- No client-side Supabase access. The backend connects as an owner/BYPASSRLS role.
ALTER TABLE public.candidate_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.candidate_profiles FROM PUBLIC;
DO $$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON public.candidate_profiles FROM %I', client_role);
        END IF;
    END LOOP;
END;
$$;

-- Phase 2A: additive only. Apply after 001 and 002; no production execution without approval.

CREATE TABLE IF NOT EXISTS public.candidate_resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_profile_id UUID NOT NULL REFERENCES public.candidate_profiles(id) ON DELETE CASCADE,
    -- Standard GitHub/LinkedIn/portfolio values live exclusively in candidate_profiles.
    resource_type VARCHAR(30) NOT NULL CHECK (resource_type IN ('resume','leetcode','codeforces','geeksforgeeks','hackerrank','kaggle','other')),
    label VARCHAR(200) NOT NULL CHECK (length(trim(label)) BETWEEN 1 AND 200),
    url VARCHAR(2048) NOT NULL CHECK (url ~ '^https://[^/@[:space:]]+([/?#]|$)' AND url !~ '^https://[^/?#]*@'),
    is_primary BOOLEAN NOT NULL DEFAULT false,
    source_type VARCHAR(30) NOT NULL DEFAULT 'user' CHECK (source_type IN ('user','environment_import')),
    user_confirmed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_candidate_resource_url UNIQUE(candidate_profile_id, resource_type, url)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_resource_primary
ON public.candidate_resources(candidate_profile_id, resource_type) WHERE is_primary;

CREATE TABLE IF NOT EXISTS public.candidate_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_profile_id UUID NOT NULL REFERENCES public.candidate_profiles(id) ON DELETE CASCADE,
    evidence_type VARCHAR(30) NOT NULL CHECK (evidence_type IN ('project','experience','achievement','resume_note','other')),
    title VARCHAR(200) NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 4000),
    source_url VARCHAR(2048) CHECK (source_url IS NULL OR source_url ~ '^https://[^/@[:space:]]+([/?#]|$)' AND source_url !~ '^https://[^/?#]*@'),
    source_description VARCHAR(200),
    user_confirmed BOOLEAN NOT NULL DEFAULT false,
    project JSONB CHECK (project IS NULL OR jsonb_typeof(project) = 'object' AND evidence_type = 'project' AND octet_length(project::text) <= 65536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_candidate_evidence_candidate_profile_id ON public.candidate_evidence(candidate_profile_id);

CREATE TABLE IF NOT EXISTS public.application_answer_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_profile_id UUID NOT NULL REFERENCES public.candidate_profiles(id) ON DELETE CASCADE,
    job_id UUID REFERENCES public.jobs(id) ON DELETE SET NULL,
    question TEXT NOT NULL CHECK (length(trim(question)) BETWEEN 1 AND 2000),
    answer TEXT NOT NULL CHECK (length(trim(answer)) BETWEEN 1 AND 10000),
    question_category VARCHAR(40) NOT NULL CHECK (question_category IN ('profile_link','personal_details','short_text','project_explanation','technical_experience','motivation','startup_interest','work_authorization','compensation','file_upload','unknown')),
    writing_style VARCHAR(30) NOT NULL CHECK (writing_style IN ('professional','conversational','technical','concise','founder_focused')),
    provider VARCHAR(30),
    model VARCHAR(150),
    evidence_references JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence_references) = 'array' AND jsonb_array_length(evidence_references) <= 12),
    candidate_profile_version INTEGER NOT NULL CHECK (candidate_profile_version >= 1),
    review_status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft','reviewed','discarded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_answer_drafts_candidate_profile_id ON public.application_answer_drafts(candidate_profile_id);

CREATE TABLE IF NOT EXISTS public.llm_monthly_usage (
    provider VARCHAR(30) NOT NULL CHECK (provider = 'gemini'),
    month VARCHAR(7) NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    cooldown_until TIMESTAMPTZ,
    requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(provider, month)
);

CREATE OR REPLACE FUNCTION public.phase2a_updated_at() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN NEW.updated_at := clock_timestamp(); RETURN NEW; END;
$$;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['candidate_resources','candidate_evidence','application_answer_drafts','llm_monthly_usage'] LOOP
        EXECUTE format('CREATE OR REPLACE TRIGGER phase2a_updated_at BEFORE UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.phase2a_updated_at()', table_name);
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I', table_name, client_role);
            END IF;
        END LOOP;
    END LOOP;
END;
$$;

-- Additive Phase 2B migration. No production execution by application startup.

ALTER TABLE public.jobs
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_canonical_key ON public.jobs(canonical_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_content_identity ON public.jobs(content_identity);
CREATE INDEX IF NOT EXISTS idx_jobs_observed ON public.jobs(last_observed_at DESC);
CREATE TABLE IF NOT EXISTS public.discovery_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(100) NOT NULL, request_hash VARCHAR(64) NOT NULL,
    query_summary JSONB NOT NULL DEFAULT '{}', status VARCHAR(50) NOT NULL DEFAULT 'running',
    rankings JSONB NOT NULL DEFAULT '[]',
    counts JSONB NOT NULL DEFAULT '{}', errors JSONB NOT NULL DEFAULT '[]',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
    provider_run_id VARCHAR(255), usage JSONB NOT NULL DEFAULT '{}',
    idempotency_key VARCHAR(100) UNIQUE
);
CREATE TABLE IF NOT EXISTS public.job_source_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    source VARCHAR(100) NOT NULL, identity_key VARCHAR(64) NOT NULL,
    source_job_id VARCHAR(255), original_url TEXT NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provenance JSONB NOT NULL DEFAULT '{}', verification_status VARCHAR(50) NOT NULL DEFAULT 'observed',
    CONSTRAINT uq_observation_identity UNIQUE(source, identity_key)
);
CREATE INDEX IF NOT EXISTS idx_observation_job ON public.job_source_observations(job_id);
CREATE TABLE IF NOT EXISTS public.discovered_company_people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    name VARCHAR(255), role VARCHAR(255), linkedin_url TEXT NOT NULL,
    evidence_url TEXT NOT NULL, source VARCHAR(50) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), verification_status VARCHAR(50) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}', CONSTRAINT uq_company_person_url UNIQUE(company_id, linkedin_url)
);
CREATE INDEX IF NOT EXISTS idx_people_company ON public.discovered_company_people(company_id);
CREATE TABLE IF NOT EXISTS public.discovery_monthly_budgets (
    provider VARCHAR(50) NOT NULL, month VARCHAR(7) NOT NULL,
    reserved NUMERIC(16,6) NOT NULL DEFAULT 0 CHECK(reserved >= 0), cooldown_until TIMESTAMPTZ,
    PRIMARY KEY(provider,month)
);
CREATE TABLE IF NOT EXISTS public.discovery_budget_reservations (
    id VARCHAR(100) PRIMARY KEY, provider VARCHAR(50) NOT NULL, month VARCHAR(7) NOT NULL,
    reserved NUMERIC(16,6) NOT NULL CHECK(reserved >= 0), provider_run_id VARCHAR(255), reported_actual NUMERIC(16,6),
    state VARCHAR(50) NOT NULL DEFAULT 'reserved', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.discovery_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_source_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovered_company_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovery_monthly_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovery_budget_reservations ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['discovery_runs','job_source_observations','discovered_company_people','discovery_monthly_budgets','discovery_budget_reservations'] LOOP
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
    END LOOP;
END;
$$;

-- Phase 3: additive, backend-only. Apply after 001-004. Never run at app startup.

ALTER TABLE public.contacts
    ADD COLUMN IF NOT EXISTS do_not_contact BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS suppression_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS human_review_notes TEXT,
    ADD COLUMN IF NOT EXISTS human_corrected BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_contacts_suppression ON public.contacts(company_id,do_not_contact);
CREATE TABLE IF NOT EXISTS public.contact_enrichment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    request_hash VARCHAR(64) NOT NULL, target_roles JSONB NOT NULL DEFAULT '[]',
    provider_plan JSONB NOT NULL DEFAULT '[]', state VARCHAR(50) NOT NULL DEFAULT 'running',
    contact_ids JSONB NOT NULL DEFAULT '[]', counts JSONB NOT NULL DEFAULT '{}',
    usage JSONB NOT NULL DEFAULT '[]', errors JSONB NOT NULL DEFAULT '[]',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
    idempotency_key VARCHAR(100) UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_contact_runs_company ON public.contact_enrichment_runs(company_id);
CREATE TABLE IF NOT EXISTS public.contact_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES public.contacts(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    source VARCHAR(100) NOT NULL, evidence_type VARCHAR(50) NOT NULL,
    evidence_url TEXT, observed_role VARCHAR(255), observed_company VARCHAR(255),
    provider_verification_claim VARCHAR(100), strength VARCHAR(20) NOT NULL DEFAULT 'moderate'
        CHECK(strength IN ('weak','moderate','strong')),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{}', user_confirmed BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_contact ON public.contact_evidence(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_company ON public.contact_evidence(company_id);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_expiry ON public.contact_evidence(expires_at);
CREATE TABLE IF NOT EXISTS public.contact_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    contact_id UUID NOT NULL REFERENCES public.contacts(id) ON DELETE CASCADE,
    namespace VARCHAR(100) NOT NULL, identity_key VARCHAR(2048) NOT NULL,
    discovered_person_id UUID REFERENCES public.discovered_company_people(id) ON DELETE SET NULL,
    CONSTRAINT uq_contact_identity UNIQUE(company_id,namespace,identity_key)
);
CREATE INDEX IF NOT EXISTS idx_contact_identity_contact ON public.contact_identities(contact_id);
CREATE TABLE IF NOT EXISTS public.contact_provider_lookups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL, identity_key VARCHAR(64) NOT NULL,
    reservation_id VARCHAR(100) NOT NULL UNIQUE, state VARCHAR(50) NOT NULL DEFAULT 'running',
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_contact_lookup UNIQUE(company_id,provider,identity_key)
);
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['contacts','contact_enrichment_runs','contact_evidence','contact_identities','contact_provider_lookups'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',table_name);
        END IF;
    END LOOP;
END;
$$;

-- Phase 4A: additive backend-only foundation, after 001-005. Never applied at startup.

CREATE TABLE IF NOT EXISTS public.connected_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(30) NOT NULL CHECK(provider='gmail'),
    google_subject VARCHAR(255) NOT NULL,
    account_email VARCHAR(254) NOT NULL,
    encrypted_refresh_token TEXT,
    encrypted_access_token TEXT,
    encryption_key_id VARCHAR(64),
    granted_scopes JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(granted_scopes)='array'),
    status VARCHAR(30) NOT NULL DEFAULT 'disconnected'
        CHECK(status IN ('connected','disconnected','reauthorization_required')),
    token_generation INTEGER NOT NULL DEFAULT 1 CHECK(token_generation >= 1),
    token_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_verified_at TIMESTAMPTZ, last_refresh_at TIMESTAMPTZ, disconnected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_connected_provider UNIQUE(provider),
    CONSTRAINT ck_connected_credentials CHECK(status <> 'connected' OR
        (length(google_subject)>0 AND encrypted_refresh_token IS NOT NULL AND encryption_key_id IS NOT NULL)),
    CONSTRAINT ck_refresh_envelope CHECK(encrypted_refresh_token IS NULL OR
        encrypted_refresh_token ~ '^[A-Za-z0-9_-]{1,40}:[0-9a-f]{24}:gAAAA'),
    CONSTRAINT ck_access_envelope CHECK(encrypted_access_token IS NULL OR
        encrypted_access_token ~ '^[A-Za-z0-9_-]{1,40}:[0-9a-f]{24}:gAAAA')
);
CREATE TABLE IF NOT EXISTS public.oauth_states (
    state_hash VARCHAR(64) PRIMARY KEY CHECK(state_hash ~ '^[0-9a-f]{64}$'),
    provider VARCHAR(30) NOT NULL DEFAULT 'gmail' CHECK(provider='gmail'),
    actor_id VARCHAR(64) NOT NULL CHECK(actor_id='owner'),
    browser_hash VARCHAR(64) NOT NULL CHECK(browser_hash ~ '^[0-9a-f]{64}$'),
    expected_email VARCHAR(254) NOT NULL,
    connection_generation INTEGER NOT NULL CHECK(connection_generation >= 1),
    encrypted_verifier TEXT,
    encryption_key_id VARCHAR(64) NOT NULL,
    redirect_uri VARCHAR(2048) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), consumed_at TIMESTAMPTZ,
    CHECK(expires_at > created_at AND expires_at <= created_at + interval '15 minutes')
);
CREATE INDEX IF NOT EXISTS idx_oauth_state_expiry ON public.oauth_states(expires_at);
ALTER TABLE public.outreach_logs
    ADD COLUMN IF NOT EXISTS connected_account_id UUID REFERENCES public.connected_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS draft_revision INTEGER NOT NULL DEFAULT 1 CHECK(draft_revision >= 1),
    ADD COLUMN IF NOT EXISTS candidate_profile_version INTEGER,
    ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(254),
    ADD COLUMN IF NOT EXISTS evidence_snapshot JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS approval_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS approved_revision INTEGER,
    ADD COLUMN IF NOT EXISTS last_edited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) NOT NULL DEFAULT 'needs_review',
    ADD COLUMN IF NOT EXISTS generation_metadata JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS created_via VARCHAR(20) NOT NULL DEFAULT 'legacy'
        CHECK(created_via IN ('legacy','rest','mcp')),
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100),
    ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_idempotency ON public.outreach_logs(idempotency_key);

-- Defense for direct backend writers: local drafts cannot fabricate provider delivery.
-- Historical sent rows are preserved byte-for-byte; no new send state is introduced.
CREATE OR REPLACE FUNCTION public.phase4a_draft_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.approval_status = 'sent' OR NEW.sent_at IS NOT NULL OR
           NEW.gmail_draft_id IS NOT NULL OR NEW.gmail_message_id IS NOT NULL OR NEW.gmail_thread_id IS NOT NULL THEN
            RAISE EXCEPTION 'Phase 4A supports local drafts only';
        END IF;
    ELSE
        IF (NEW.sent_at,NEW.gmail_draft_id,NEW.gmail_message_id,NEW.gmail_thread_id) IS DISTINCT FROM
           (OLD.sent_at,OLD.gmail_draft_id,OLD.gmail_message_id,OLD.gmail_thread_id) OR
           (NEW.approval_status='sent' AND OLD.approval_status<>'sent') THEN
            RAISE EXCEPTION 'Phase 4A supports local drafts only';
        END IF;
        NEW.created_at := OLD.created_at;
        IF (to_jsonb(NEW)-ARRAY['draft_revision','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['draft_revision','updated_at']) THEN
            NEW.draft_revision := OLD.draft_revision+1;
            NEW.updated_at := clock_timestamp();
        ELSE
            NEW.draft_revision := OLD.draft_revision;
            NEW.updated_at := OLD.updated_at;
        END IF;
        IF (NEW.subject,NEW.body,NEW.recipient_email,NEW.evidence_hash,NEW.evidence_snapshot,NEW.contact_id,NEW.job_id,NEW.connected_account_id) IS DISTINCT FROM
           (OLD.subject,OLD.body,OLD.recipient_email,OLD.evidence_hash,OLD.evidence_snapshot,OLD.contact_id,OLD.job_id,OLD.connected_account_id) THEN
            NEW.approval_status := 'pending_approval'; NEW.approved_at := NULL;
            NEW.approval_hash := NULL; NEW.approved_revision := NULL;
            NEW.last_edited_at := clock_timestamp(); NEW.validation_status := 'requires_review';
        END IF;
    END IF;
    IF NEW.approval_status='approved' AND
       (NEW.approval_hash IS NULL OR NEW.approved_revision IS DISTINCT FROM NEW.draft_revision OR NEW.approved_at IS NULL) THEN
        RAISE EXCEPTION 'Approval must identify the current draft revision';
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER phase4a_draft_guard BEFORE INSERT OR UPDATE ON public.outreach_logs
FOR EACH ROW EXECUTE FUNCTION public.phase4a_draft_guard();

DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['connected_accounts','oauth_states','outreach_logs'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',table_name);
        END IF;
    END LOOP;
END;
$$;

-- Phase 4B: backend-only consent and one permanent send reservation per draft.
-- Additive, replayable; no production/startup application hook. Never edits migration 006.

ALTER TABLE public.oauth_states
    ADD COLUMN IF NOT EXISTS authorization_mode VARCHAR(20) NOT NULL DEFAULT 'metadata'
        CHECK(authorization_mode IN ('metadata','send')),
    ADD COLUMN IF NOT EXISTS expected_subject VARCHAR(255);

CREATE TABLE IF NOT EXISTS public.outreach_send_confirmations (
    token_hash VARCHAR(64) PRIMARY KEY CHECK(token_hash ~ '^[a-f0-9]{64}$'),
    draft_id UUID NOT NULL REFERENCES public.outreach_logs(id),
    connected_account_id UUID NOT NULL REFERENCES public.connected_accounts(id),
    actor_id VARCHAR(64) NOT NULL CHECK(actor_id='owner'),
    draft_revision INTEGER NOT NULL CHECK(draft_revision>=1),
    approval_hash VARCHAR(64) NOT NULL CHECK(approval_hash ~ '^[a-f0-9]{64}$'),
    recipient_email VARCHAR(254) NOT NULL,
    sender_email VARCHAR(254) NOT NULL,
    sender_binding VARCHAR(64) NOT NULL CHECK(sender_binding ~ '^[a-f0-9]{64}$'),
    content_digest VARCHAR(64) NOT NULL CHECK(content_digest ~ '^[a-f0-9]{64}$'),
    evidence_digest VARCHAR(64) NOT NULL CHECK(evidence_digest ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CHECK(expires_at > created_at AND expires_at <= created_at + interval '10 minutes')
);
CREATE INDEX IF NOT EXISTS idx_send_confirmation_expiry ON public.outreach_send_confirmations(expires_at);
CREATE TABLE IF NOT EXISTS public.outreach_send_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL UNIQUE REFERENCES public.outreach_logs(id),
    connected_account_id UUID NOT NULL REFERENCES public.connected_accounts(id),
    confirmation_hash VARCHAR(64) NOT NULL UNIQUE REFERENCES public.outreach_send_confirmations(token_hash),
    actor_id VARCHAR(64) NOT NULL CHECK(actor_id='owner'),
    draft_revision INTEGER NOT NULL CHECK(draft_revision>=1),
    approval_hash VARCHAR(64) NOT NULL CHECK(approval_hash ~ '^[a-f0-9]{64}$'),
    recipient_email VARCHAR(254) NOT NULL,
    sender_email VARCHAR(254) NOT NULL,
    sender_binding VARCHAR(64) NOT NULL CHECK(sender_binding ~ '^[a-f0-9]{64}$'),
    subject TEXT NOT NULL, body TEXT NOT NULL,
    content_digest VARCHAR(64) NOT NULL CHECK(content_digest ~ '^[a-f0-9]{64}$'),
    evidence_digest VARCHAR(64) NOT NULL CHECK(evidence_digest ~ '^[a-f0-9]{64}$'),
    rfc_message_id VARCHAR(255) NOT NULL UNIQUE CHECK(rfc_message_id = '<outreach.' || replace(id::text,'-','') || '@automated-apply.invalid>'),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
    request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    status VARCHAR(30) NOT NULL DEFAULT 'prepared' CHECK(status IN
        ('prepared','attempting','accepted_by_gmail','failed_before_send','outcome_unknown','manually_reconciled')),
    gmail_message_id VARCHAR(255), gmail_thread_id VARCHAR(255),
    attempted_at TIMESTAMPTZ, accepted_at TIMESTAMPTZ,
    failure_category VARCHAR(64) CHECK(failure_category IS NULL OR failure_category IN
        ('connection_failed_before_send','transmission_outcome_unknown','invalid_gmail_response',
         'malformed_request','credential_rejected','scope_or_policy_denied','gmail_resource_missing',
         'gmail_quota_exceeded','gmail_server_or_unexpected_response','context_changed_before_transmission',
         'interrupted_attempt_requires_review')),
    reconciliation_required BOOLEAN NOT NULL DEFAULT false,
    reconciled_at TIMESTAMPTZ, reconciled_by VARCHAR(64), reconciliation_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK(gmail_message_id IS NULL OR gmail_message_id ~ '^[A-Za-z0-9_-]{1,255}$'),
    CHECK(gmail_thread_id IS NULL OR gmail_thread_id ~ '^[A-Za-z0-9_-]{1,255}$'),
    CHECK((status='accepted_by_gmail' AND gmail_message_id IS NOT NULL AND accepted_at IS NOT NULL AND attempted_at IS NOT NULL)
        OR status<>'accepted_by_gmail'),
    CHECK((gmail_message_id IS NULL AND gmail_thread_id IS NULL AND accepted_at IS NULL)
        OR status IN ('accepted_by_gmail','manually_reconciled')),
    CHECK(status NOT IN ('attempting','outcome_unknown') OR (attempted_at IS NOT NULL AND reconciliation_required)),
    CHECK(status NOT IN ('accepted_by_gmail','failed_before_send','manually_reconciled') OR NOT reconciliation_required),
    CHECK(status <> 'manually_reconciled' OR
        (reconciled_by='owner' AND reconciled_at IS NOT NULL AND length(reconciliation_note)>=20)),
    CHECK(accepted_at IS NULL OR gmail_message_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_outreach_send_created ON public.outreach_send_attempts(created_at);

CREATE OR REPLACE FUNCTION public.phase4b_confirmation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Send confirmations are audit records'; END IF;
    IF TG_OP='UPDATE' THEN
        IF OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL OR OLD.expires_at<=clock_timestamp()
           OR (to_jsonb(NEW)-'consumed_at') IS DISTINCT FROM (to_jsonb(OLD)-'consumed_at') THEN
            RAISE EXCEPTION 'Confirmation is immutable and single use';
        END IF;
    ELSIF NEW.consumed_at IS NOT NULL OR NOT EXISTS (
        SELECT 1 FROM public.outreach_logs d JOIN public.connected_accounts a ON a.id=NEW.connected_account_id
        WHERE d.id=NEW.draft_id AND d.approval_status='approved' AND d.draft_revision=NEW.draft_revision
          AND d.approved_revision=d.draft_revision AND d.approval_hash=NEW.approval_hash
          AND d.evidence_hash=NEW.evidence_digest AND d.recipient_email=NEW.recipient_email
          AND a.status='connected' AND a.account_email=NEW.sender_email
          AND a.granted_scopes ? 'https://www.googleapis.com/auth/gmail.send'
    ) THEN RAISE EXCEPTION 'Confirmation requires current approved context';
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER phase4b_confirmation_guard BEFORE INSERT OR UPDATE OR DELETE ON public.outreach_send_confirmations
FOR EACH ROW EXECUTE FUNCTION public.phase4b_confirmation_guard();

CREATE OR REPLACE FUNCTION public.phase4b_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Send attempts are permanent audit records'; END IF;
    IF TG_OP='INSERT' THEN
        IF NEW.status<>'prepared' OR NEW.attempted_at IS NOT NULL OR NEW.gmail_message_id IS NOT NULL OR
           NEW.gmail_thread_id IS NOT NULL OR NEW.accepted_at IS NOT NULL OR NOT EXISTS (
            SELECT 1 FROM public.outreach_send_confirmations c
            JOIN public.outreach_logs d ON d.id=c.draft_id
            JOIN public.connected_accounts a ON a.id=c.connected_account_id
            JOIN public.contacts t ON t.id=d.contact_id
            WHERE c.token_hash=NEW.confirmation_hash AND c.consumed_at IS NOT NULL AND c.expires_at>clock_timestamp()
            AND (c.draft_id,c.connected_account_id,c.actor_id,c.draft_revision,c.approval_hash,c.recipient_email,c.sender_email,c.sender_binding,c.content_digest,c.evidence_digest)
              = (NEW.draft_id,NEW.connected_account_id,NEW.actor_id,NEW.draft_revision,NEW.approval_hash,NEW.recipient_email,NEW.sender_email,NEW.sender_binding,NEW.content_digest,NEW.evidence_digest)
            AND d.approval_status='approved' AND d.draft_revision=NEW.draft_revision AND d.approved_revision=d.draft_revision
            AND d.approval_hash=NEW.approval_hash AND d.evidence_hash=NEW.evidence_digest
            AND d.subject=NEW.subject AND d.body=NEW.body AND d.recipient_email=NEW.recipient_email
            AND d.sent_at IS NULL AND d.gmail_message_id IS NULL
            AND a.status='connected' AND a.account_email=NEW.sender_email AND a.granted_scopes ? 'https://www.googleapis.com/auth/gmail.send'
            AND NOT t.do_not_contact AND t.email_status='verified' AND t.email=NEW.recipient_email
        ) THEN RAISE EXCEPTION 'Send reservation requires consumed exact consent and current approval'; END IF;
    ELSE
        IF (to_jsonb(NEW)-ARRAY['status','gmail_message_id','gmail_thread_id','attempted_at','accepted_at','failure_category','reconciliation_required','updated_at','reconciled_at','reconciled_by','reconciliation_note']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['status','gmail_message_id','gmail_thread_id','attempted_at','accepted_at','failure_category','reconciliation_required','updated_at','reconciled_at','reconciled_by','reconciliation_note']) THEN
            RAISE EXCEPTION 'Send attempt identity is immutable';
        END IF;
        IF NOT ((OLD.status='prepared' AND NEW.status IN ('attempting','failed_before_send')) OR
                (OLD.status='attempting' AND NEW.status IN ('accepted_by_gmail','outcome_unknown','failed_before_send')) OR
                (OLD.status IN ('outcome_unknown','failed_before_send') AND NEW.status='manually_reconciled')) THEN
            RAISE EXCEPTION 'Illegal send transition; retries are forbidden';
        END IF;
        IF OLD.attempted_at IS NOT NULL AND NEW.attempted_at IS DISTINCT FROM OLD.attempted_at THEN
            RAISE EXCEPTION 'Attempt initiation is immutable';
        END IF;
        IF NEW.status<>'manually_reconciled' AND
           (NEW.reconciled_at IS NOT NULL OR NEW.reconciled_by IS NOT NULL OR NEW.reconciliation_note IS NOT NULL) THEN
            RAISE EXCEPTION 'Reconciliation requires explicit audited disposition';
        END IF;
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER phase4b_attempt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.outreach_send_attempts
FOR EACH ROW EXECUTE FUNCTION public.phase4b_attempt_guard();

-- Supersede 006 in place. Keep its material edit invalidation and approval/revision checks.
-- Delivery metadata is permitted only when backed by a matching accepted, immutable attempt.
CREATE OR REPLACE FUNCTION public.phase4a_draft_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.approval_status='sent' OR NEW.sent_at IS NOT NULL OR NEW.gmail_draft_id IS NOT NULL OR
           NEW.gmail_message_id IS NOT NULL OR NEW.gmail_thread_id IS NOT NULL THEN
            RAISE EXCEPTION 'New drafts cannot fabricate send history';
        END IF;
    ELSE
        NEW.created_at := OLD.created_at;
        IF NEW.gmail_draft_id IS DISTINCT FROM OLD.gmail_draft_id THEN RAISE EXCEPTION 'Gmail drafts are unsupported'; END IF;
        IF (NEW.sent_at,NEW.gmail_message_id,NEW.gmail_thread_id) IS DISTINCT FROM
           (OLD.sent_at,OLD.gmail_message_id,OLD.gmail_thread_id) OR (NEW.approval_status='sent' AND OLD.approval_status<>'sent') THEN
            IF NEW.approval_status='sent' OR NOT EXISTS (
                SELECT 1 FROM public.outreach_send_attempts s WHERE s.draft_id=OLD.id AND s.status='accepted_by_gmail'
                AND (s.gmail_message_id,s.gmail_thread_id,s.accepted_at,s.draft_revision,s.subject,s.body,s.recipient_email)
                IS NOT DISTINCT FROM (NEW.gmail_message_id,NEW.gmail_thread_id,NEW.sent_at,OLD.draft_revision,NEW.subject,NEW.body,NEW.recipient_email)
            ) THEN RAISE EXCEPTION 'Delivery fields require a valid accepted send attempt'; END IF;
        END IF;
        IF (to_jsonb(NEW)-ARRAY['draft_revision','updated_at','gmail_message_id','gmail_thread_id','sent_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['draft_revision','updated_at','gmail_message_id','gmail_thread_id','sent_at']) THEN
            NEW.draft_revision := OLD.draft_revision+1; NEW.updated_at := clock_timestamp();
        ELSE NEW.draft_revision := OLD.draft_revision; NEW.updated_at := OLD.updated_at;
        END IF;
        IF (NEW.subject,NEW.body,NEW.recipient_email,NEW.evidence_hash,NEW.evidence_snapshot,NEW.contact_id,NEW.job_id,NEW.connected_account_id) IS DISTINCT FROM
           (OLD.subject,OLD.body,OLD.recipient_email,OLD.evidence_hash,OLD.evidence_snapshot,OLD.contact_id,OLD.job_id,OLD.connected_account_id) THEN
            NEW.approval_status := 'pending_approval'; NEW.approved_at := NULL; NEW.approval_hash := NULL; NEW.approved_revision := NULL;
            NEW.last_edited_at := clock_timestamp(); NEW.validation_status := 'requires_review';
        END IF;
    END IF;
    IF NEW.approval_status='approved' AND
       (NEW.approval_hash IS NULL OR NEW.approved_revision IS DISTINCT FROM NEW.draft_revision OR NEW.approved_at IS NULL) THEN
        RAISE EXCEPTION 'Approval must identify the current draft revision';
    END IF;
    RETURN NEW;
END;
$$;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['outreach_send_confirmations','outreach_send_attempts'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('REVOKE ALL ON public.%I FROM service_role',table_name);
            EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO service_role',table_name);
        END IF;
    END LOOP;
END;
$$;

-- Phase 5A: additive, backend-only manual application preparation. No production execution hook.

-- Composite ownership prevents a packet from selecting another candidate's resource.
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_resource_owner ON public.candidate_resources(id,candidate_profile_id);
CREATE TABLE IF NOT EXISTS public.application_packets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.jobs(id),
    candidate_profile_id UUID NOT NULL REFERENCES public.candidate_profiles(id),
    candidate_profile_version INTEGER NOT NULL CHECK(candidate_profile_version>=1),
    resume_resource_id UUID,
    FOREIGN KEY(resume_resource_id,candidate_profile_id) REFERENCES public.candidate_resources(id,candidate_profile_id),
    application_url VARCHAR(2048),
    platform VARCHAR(50) NOT NULL,
    lifecycle_state VARCHAR(40) NOT NULL DEFAULT 'created' CHECK(lifecycle_state IN
        ('created','preparing','needs_input','ready_for_review','reviewed','approved_for_manual_handoff',
         'external_application_opened','user_reported_submitted','provider_confirmed_submitted','withdrawn','abandoned')),
    tracking_state VARCHAR(40) NOT NULL DEFAULT 'not_applied' CHECK(tracking_state IN
        ('not_applied','applied_manually','application_incomplete','application_rejected','interview_scheduled','offer_received','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
    approved_revision INTEGER CHECK(approved_revision IS NULL OR approved_revision=revision),
    readiness_state VARCHAR(40) NOT NULL CHECK(readiness_state IN
        ('needs_profile','needs_input','needs_resume','needs_review','ready_for_manual_handoff','manual_action_required','completed_by_user','unsupported')),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
    request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=262144),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_application_packet_candidate_job UNIQUE(job_id,candidate_profile_id)
);
CREATE INDEX IF NOT EXISTS ix_application_packet_platform_state ON public.application_packets(platform,lifecycle_state,created_at);

CREATE TABLE IF NOT EXISTS public.application_packet_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packet_id UUID NOT NULL REFERENCES public.application_packets(id),
    position INTEGER NOT NULL CHECK(position BETWEEN 0 AND 99),
    question TEXT NOT NULL CHECK(length(trim(question)) BETWEEN 1 AND 2000),
    category VARCHAR(40) NOT NULL CHECK(category IN
        ('personal_information','contact_information','professional_profile_url','education','experience','technical_skills',
         'resume_upload','salary','notice_period','work_authorization','project_explanation','motivation','free_text','multiple_choice','yes_no','unknown')),
    field_type VARCHAR(30) NOT NULL CHECK(field_type IN ('text','textarea','url','file','multiple_choice','yes_no')),
    required BOOLEAN NOT NULL,
    max_characters INTEGER NOT NULL CHECK(max_characters BETWEEN 1 AND 10000),
    max_words INTEGER CHECK(max_words BETWEEN 1 AND 1500),
    constraints VARCHAR(1000),
    options JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(options)='array' AND jsonb_array_length(options)<=50),
    writing_style VARCHAR(30) NOT NULL CHECK(writing_style IN ('professional','conversational','technical','concise','founder_focused')),
    proposed_answer TEXT CHECK(proposed_answer IS NULL OR length(trim(proposed_answer)) BETWEEN 1 AND 10000),
    human_answer TEXT CHECK(human_answer IS NULL OR length(trim(human_answer)) BETWEEN 1 AND 10000),
    provenance JSONB NOT NULL CHECK(jsonb_typeof(provenance)='object' AND octet_length(provenance::text)<=16384),
    validation_status VARCHAR(30) NOT NULL CHECK(validation_status IN ('draft_ready','needs_input','file_upload_required','provider_unavailable','validation_failed')),
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','reviewed')),
    requires_review BOOLEAN NOT NULL DEFAULT true,
    missing_information JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(missing_information)='array'),
    answer_revision INTEGER NOT NULL DEFAULT 1 CHECK(answer_revision>=1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_packet_field_position UNIQUE(packet_id,position),
    CHECK(field_type NOT IN ('multiple_choice','yes_no') OR jsonb_array_length(options)>0),
    CHECK(COALESCE(human_answer,proposed_answer) IS NULL OR length(COALESCE(human_answer,proposed_answer))<=max_characters)
);
CREATE INDEX IF NOT EXISTS ix_application_packet_fields_packet_id ON public.application_packet_fields(packet_id);

CREATE TABLE IF NOT EXISTS public.application_submission_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packet_id UUID NOT NULL UNIQUE REFERENCES public.application_packets(id),
    packet_revision INTEGER NOT NULL CHECK(packet_revision>=1),
    -- There is no authorized submission provider in Phase 5A. Extend in a future migration only.
    confirmation_source VARCHAR(30) NOT NULL DEFAULT 'user_reported' CHECK(confirmation_source='user_reported'),
    receipt_reference VARCHAR(255),
    evidence_confidence VARCHAR(40) NOT NULL DEFAULT 'self_reported_unverified' CHECK(evidence_confidence='self_reported_unverified'),
    human_confirmed BOOLEAN NOT NULL CHECK(human_confirmed),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
    request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.application_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packet_id UUID NOT NULL REFERENCES public.application_packets(id),
    event_type VARCHAR(50) NOT NULL CHECK(event_type IN
        ('packet_created','packet_refreshed','questions_added','answer_generated','answer_edited','packet_reviewed','packet_approved','tracking_updated','user_reported_submission')),
    previous_state VARCHAR(40), next_state VARCHAR(40) NOT NULL,
    packet_revision INTEGER NOT NULL CHECK(packet_revision>=1),
    origin VARCHAR(20) NOT NULL CHECK(origin IN ('owner_rest','system')),
    evidence_id UUID REFERENCES public.application_submission_evidence(id),
    note VARCHAR(1000), created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_events_packet_revision ON public.application_events(packet_id,packet_revision);

CREATE OR REPLACE FUNCTION public.application_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Application history is append only'; END;
$$;
CREATE OR REPLACE TRIGGER application_events_immutable BEFORE UPDATE OR DELETE ON public.application_events
FOR EACH ROW EXECUTE FUNCTION public.application_append_only();
CREATE OR REPLACE TRIGGER application_submission_immutable BEFORE UPDATE OR DELETE ON public.application_submission_evidence
FOR EACH ROW EXECUTE FUNCTION public.application_append_only();

CREATE OR REPLACE FUNCTION public.application_packet_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE material_changed boolean;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application packets retain audit history'; END IF;
    IF NEW.lifecycle_state='provider_confirmed_submitted' THEN
        RAISE EXCEPTION 'No authorized submission provider exists in Phase 5A';
    END IF;
    IF TG_OP='INSERT' THEN
        IF NEW.lifecycle_state<>'created' OR NEW.revision<>1 OR NEW.approved_revision IS NOT NULL OR NEW.tracking_state<>'not_applied' THEN
            RAISE EXCEPTION 'Application packets start as unsubmitted drafts';
        END IF;
    ELSE
        IF (NEW.id,NEW.job_id,NEW.candidate_profile_id,NEW.idempotency_key,NEW.request_hash,NEW.created_at)
           IS DISTINCT FROM (OLD.id,OLD.job_id,OLD.candidate_profile_id,OLD.idempotency_key,OLD.request_hash,OLD.created_at) THEN
            RAISE EXCEPTION 'Application identity is immutable';
        END IF;
        material_changed := (NEW.snapshot,NEW.resume_resource_id,NEW.application_url,NEW.candidate_profile_version,NEW.platform)
           IS DISTINCT FROM (OLD.snapshot,OLD.resume_resource_id,OLD.application_url,OLD.candidate_profile_version,OLD.platform);
        IF material_changed THEN
            NEW.approved_revision := NULL;
            IF NEW.lifecycle_state IN ('approved_for_manual_handoff','external_application_opened') THEN
                NEW.lifecycle_state := 'needs_input'; NEW.readiness_state := 'needs_review';
            END IF;
            IF NEW.revision=OLD.revision AND OLD.lifecycle_state<>'preparing' THEN NEW.revision:=OLD.revision+1; END IF;
        END IF;
        IF NEW.revision<OLD.revision OR NEW.revision>OLD.revision+1 THEN RAISE EXCEPTION 'Invalid application revision'; END IF;
        IF OLD.lifecycle_state IN ('user_reported_submitted','withdrawn','abandoned') AND material_changed THEN
            RAISE EXCEPTION 'Closed application content is immutable';
        END IF;
        IF OLD.lifecycle_state IN ('withdrawn','abandoned') AND NEW.lifecycle_state<>OLD.lifecycle_state THEN
            RAISE EXCEPTION 'Closed application cannot reopen';
        END IF;
        IF OLD.lifecycle_state='user_reported_submitted' AND NEW.lifecycle_state NOT IN ('user_reported_submitted','withdrawn') THEN
            RAISE EXCEPTION 'Submission history cannot be erased';
        END IF;
        IF NEW.lifecycle_state='external_application_opened' AND OLD.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') THEN
            RAISE EXCEPTION 'Opening requires approval';
        END IF;
        NEW.updated_at:=clock_timestamp();
    END IF;
    IF NEW.lifecycle_state='user_reported_submitted' AND NOT EXISTS (
        SELECT 1 FROM public.application_submission_evidence e WHERE e.packet_id=NEW.id AND e.human_confirmed
    ) THEN RAISE EXCEPTION 'Manual submission requires explicit self-reported evidence'; END IF;
    IF NEW.tracking_state IN ('applied_manually','application_rejected','interview_scheduled','offer_received') AND NOT EXISTS (
        SELECT 1 FROM public.application_submission_evidence e WHERE e.packet_id=NEW.id
    ) THEN RAISE EXCEPTION 'Post-submission tracking requires evidence'; END IF;
    IF NEW.approved_revision IS NOT NULL THEN
        IF NEW.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') OR NEW.approved_revision<>NEW.revision
           OR NEW.candidate_profile_version<>(SELECT version FROM public.candidate_profiles WHERE id=NEW.candidate_profile_id)
           OR NEW.application_url IS NULL OR NEW.resume_resource_id IS NULL
           OR NEW.snapshot->'destination'->>'valid' IS DISTINCT FROM 'true'
           OR NEW.snapshot->'destination'->>'source_confidence' IS DISTINCT FROM 'source_consistent'
           OR NEW.application_url IS DISTINCT FROM NEW.snapshot->'destination'->>'application_url'
           OR NEW.resume_resource_id::text IS DISTINCT FROM NEW.snapshot->'resume'->'selected'->>'resource_id'
           OR NOT EXISTS (SELECT 1 FROM public.candidate_resources r WHERE r.id=NEW.resume_resource_id
                          AND r.candidate_profile_id=NEW.candidate_profile_id AND r.user_confirmed AND r.resource_type='resume'
                          AND r.url=NEW.snapshot->'resume'->'selected'->>'url')
           OR EXISTS (SELECT 1 FROM public.application_packet_fields f WHERE f.packet_id=NEW.id AND
                ((f.required AND f.validation_status<>'file_upload_required' AND
                 (COALESCE(f.human_answer,f.proposed_answer) IS NULL OR f.validation_status<>'draft_ready'))
                OR (COALESCE(f.human_answer,f.proposed_answer) IS NOT NULL AND f.requires_review AND f.review_status<>'reviewed'))) THEN
            RAISE EXCEPTION 'Approval requires current profile, resume, destination and reviewed answers';
        END IF;
    ELSIF NEW.lifecycle_state IN ('approved_for_manual_handoff','external_application_opened') THEN
        RAISE EXCEPTION 'Handoff requires revision approval';
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER application_packet_guard BEFORE INSERT OR UPDATE OR DELETE ON public.application_packets
FOR EACH ROW EXECUTE FUNCTION public.application_packet_guard();

CREATE OR REPLACE FUNCTION public.application_field_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p public.application_packets;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application fields retain audit history'; END IF;
    SELECT * INTO p FROM public.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF p.lifecycle_state IN ('user_reported_submitted','withdrawn','abandoned') THEN RAISE EXCEPTION 'Closed application fields are immutable'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (NEW.id,NEW.packet_id,NEW.position,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.packet_id,OLD.position,OLD.created_at) THEN
            RAISE EXCEPTION 'Application field identity is immutable';
        END IF;
        IF p.lifecycle_state<>'preparing' THEN
            UPDATE public.application_packets SET revision=revision+1,approved_revision=NULL,lifecycle_state='needs_input',readiness_state='needs_review' WHERE id=NEW.packet_id;
        END IF;
        IF (to_jsonb(NEW)-ARRAY['answer_revision','review_status','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['answer_revision','review_status','updated_at']) THEN
            NEW.answer_revision:=OLD.answer_revision+1; NEW.review_status:='pending';
        END IF;
        NEW.updated_at:=clock_timestamp();
    ELSIF p.approved_revision IS NOT NULL THEN RAISE EXCEPTION 'Invalidate approval before adding fields'; END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER application_field_guard BEFORE INSERT OR UPDATE OR DELETE ON public.application_packet_fields
FOR EACH ROW EXECUTE FUNCTION public.application_field_guard();

CREATE OR REPLACE FUNCTION public.application_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p public.application_packets;
BEGIN
    SELECT * INTO p FROM public.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF NEW.packet_revision<>p.revision THEN RAISE EXCEPTION 'History must reference the current packet revision'; END IF;
    IF TG_TABLE_NAME='application_events' THEN
        IF NEW.next_state<>p.lifecycle_state THEN RAISE EXCEPTION 'Event state must match packet'; END IF;
        IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.application_submission_evidence e WHERE e.id=NEW.evidence_id AND e.packet_id=NEW.packet_id
        ) THEN RAISE EXCEPTION 'Evidence belongs to a different application'; END IF;
    ELSIF p.lifecycle_state<>'preparing' THEN RAISE EXCEPTION 'Submission evidence requires an explicit revision claim'; END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER application_event_guard BEFORE INSERT ON public.application_events
FOR EACH ROW EXECUTE FUNCTION public.application_history_guard();
CREATE OR REPLACE TRIGGER application_evidence_guard BEFORE INSERT ON public.application_submission_evidence
FOR EACH ROW EXECUTE FUNCTION public.application_history_guard();

DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['application_packets','application_packet_fields','application_events','application_submission_evidence'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('GRANT SELECT,INSERT ON public.%I TO service_role',table_name);
            IF table_name IN ('application_packets','application_packet_fields') THEN
                EXECUTE format('GRANT UPDATE ON public.%I TO service_role',table_name);
            END IF;
        END IF;
    END LOOP;
END;
$$;

-- Additive Phase 6A. Apply only through an operator-reviewed migration process.

CREATE TABLE IF NOT EXISTS public.company_source_observations (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 run_id UUID REFERENCES public.discovery_runs(id) ON DELETE SET NULL,
 source VARCHAR(100) NOT NULL, identity_key VARCHAR(64) NOT NULL,
 content_hash VARCHAR(64) NOT NULL, source_url TEXT NOT NULL,
 observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), attributes JSONB NOT NULL DEFAULT '{}',
 verification_status VARCHAR(50) NOT NULL DEFAULT 'requires_review'
   CHECK (verification_status IN ('requires_review','source_reported','human_confirmed')),
 CONSTRAINT uq_company_snapshot UNIQUE(source,identity_key,content_hash)
);
CREATE INDEX IF NOT EXISTS idx_company_snapshot_company ON public.company_source_observations(company_id,observed_at DESC);
CREATE TABLE IF NOT EXISTS public.startup_shortlist_entries (
 company_id UUID PRIMARY KEY REFERENCES public.companies(id) ON DELETE CASCADE,
 run_id UUID REFERENCES public.discovery_runs(id) ON DELETE SET NULL,
 snapshot JSONB NOT NULL DEFAULT '{}', note TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.provider_connection_checks (
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
CREATE INDEX IF NOT EXISTS idx_provider_check_latest ON public.provider_connection_checks(provider,checked_at DESC);
CREATE TABLE IF NOT EXISTS public.provider_access_windows (
 provider VARCHAR(100) PRIMARY KEY, next_allowed_at TIMESTAMPTZ NOT NULL
);
-- Snapshots are append-only. Explicit retention deletion remains an operator operation.
-- The FK's SET NULL is allowed when an audit run is pruned.
CREATE OR REPLACE FUNCTION public.company_snapshot_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (to_jsonb(NEW)-'run_id') IS DISTINCT FROM (to_jsonb(OLD)-'run_id')
    OR (NEW.run_id IS DISTINCT FROM OLD.run_id AND NEW.run_id IS NOT NULL) THEN
  RAISE EXCEPTION 'Company evidence is append-only';
 END IF;
 RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS company_snapshot_guard ON public.company_source_observations;
CREATE TRIGGER company_snapshot_guard BEFORE UPDATE ON public.company_source_observations
FOR EACH ROW EXECUTE FUNCTION public.company_snapshot_guard();
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['company_source_observations','startup_shortlist_entries','provider_connection_checks','provider_access_windows'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,DELETE ON public.%I TO service_role',table_name);
   IF table_name IN ('provider_connection_checks','provider_access_windows') THEN
    EXECUTE format('GRANT UPDATE ON public.%I TO service_role',table_name);
   END IF;
  END IF;
 END LOOP;
END;
$$;

-- Additive owner-only data. Apply only to an explicitly authorized target.

CREATE TABLE IF NOT EXISTS public.private_resumes (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), label VARCHAR(200) NOT NULL,
 ciphertext BYTEA NOT NULL, sha256 VARCHAR(64) NOT NULL,
 confirmed BOOLEAN NOT NULL DEFAULT false, resource_id UUID,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.owner_notifications (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), dedup_key VARCHAR(200) UNIQUE NOT NULL,
 kind VARCHAR(50) NOT NULL, title VARCHAR(200) NOT NULL, body TEXT NOT NULL,
 href VARCHAR(200) NOT NULL, read_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.owner_preferences (
 key VARCHAR(50) PRIMARY KEY, value JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.notification_deliveries (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 notification_id UUID NOT NULL REFERENCES public.owner_notifications(id) ON DELETE CASCADE,
 channel VARCHAR(30) NOT NULL, status VARCHAR(40) NOT NULL,
 attempt_count INTEGER NOT NULL DEFAULT 0, last_error VARCHAR(100), next_attempt_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT uq_notification_channel UNIQUE(notification_id,channel)
);
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['private_resumes','owner_notifications','owner_preferences','notification_deliveries'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',table_name);
  END IF;
 END LOOP;
END;
$$;

-- Additive owner-only resume checks and explicit review. Never run at API startup.

CREATE TABLE public.resume_drive_sources (
 key VARCHAR(20) PRIMARY KEY DEFAULT 'primary', file_id VARCHAR(200) NOT NULL,
 canonical_url VARCHAR(2048) NOT NULL, generation INTEGER NOT NULL DEFAULT 1,
 sync_enabled BOOLEAN NOT NULL DEFAULT false, interval_hours INTEGER NOT NULL DEFAULT 24,
 status VARCHAR(40) NOT NULL DEFAULT 'not_checked', last_error VARCHAR(80),
 last_checked_at TIMESTAMPTZ, last_changed_at TIMESTAMPTZ,
 file_name VARCHAR(200), last_downloaded_at TIMESTAMPTZ,
 source_modified_at TIMESTAMPTZ, source_etag VARCHAR(500), drive_revision VARCHAR(200),
 latest_version_id UUID, active_version_id UUID,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT ck_resume_source_primary CHECK (key = 'primary'),
 CONSTRAINT ck_resume_sync_interval CHECK (interval_hours BETWEEN 1 AND 168)
);
CREATE TABLE public.drive_resume_versions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), file_id VARCHAR(200) NOT NULL,
 canonical_url VARCHAR(2048) NOT NULL, file_name VARCHAR(200) NOT NULL,
 source_modified_at TIMESTAMPTZ, source_etag VARCHAR(500), drive_revision VARCHAR(200),
 sha256 VARCHAR(64) NOT NULL, downloaded_at TIMESTAMPTZ NOT NULL,
 private_resume_id UUID UNIQUE NOT NULL REFERENCES public.private_resumes(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT uq_drive_resume_bytes UNIQUE(sha256)
);
CREATE TABLE public.resume_profile_reviews (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 version_id UUID UNIQUE NOT NULL REFERENCES public.drive_resume_versions(id),
 base_profile_version INTEGER, review_ciphertext BYTEA NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'pending',
 review_cycle INTEGER NOT NULL DEFAULT 1,
 approved_profile_version INTEGER, approved_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT ck_resume_review_status CHECK (status IN ('pending','approved'))
);
-- This relationship makes a resume-only approval a material profile change, using
-- the existing version trigger. Existing profile facts and old packets are preserved.
ALTER TABLE public.candidate_profiles ADD COLUMN active_resume_version_id UUID;
-- Phase 7 introduced private resources in application code. Extend the original
-- PostgreSQL HTTPS-only constraints narrowly, so private PDF approval works there too.
ALTER TABLE public.candidate_resources DROP CONSTRAINT candidate_resources_source_type_check;
ALTER TABLE public.candidate_resources DROP CONSTRAINT candidate_resources_url_check;
ALTER TABLE public.candidate_resources ADD CONSTRAINT candidate_resources_source_type_check
 CHECK (source_type IN ('user','environment_import','private_upload'));
ALTER TABLE public.candidate_resources ADD CONSTRAINT candidate_resources_url_check CHECK (
 (source_type IN ('user','environment_import') AND url ~ '^https://[^/@[:space:]]+([/?#]|$)' AND url !~ '^https://[^/?#]*@')
 OR (source_type = 'private_upload' AND resource_type = 'resume'
     AND url ~ '^private-resume:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
);
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['resume_drive_sources','drive_resume_versions','resume_profile_reviews'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',table_name);
  END IF;
 END LOOP;
END;
$$;

-- Additive local-reviewed scheduling foundation. Does not activate a worker.

SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
CREATE TABLE public.automation_schedule (
 key varchar(20) PRIMARY KEY DEFAULT 'primary',
 enabled boolean NOT NULL DEFAULT false,
 version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
 configuration jsonb NOT NULL DEFAULT '{}',
 next_run_at timestamptz, last_run_at timestamptz, heartbeat_at timestamptz,
 CONSTRAINT ck_automation_primary CHECK (key = 'primary')
);
CREATE TABLE public.automation_executions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 request_key varchar(100) NOT NULL, source varchar(100) NOT NULL,
 trigger_type varchar(20) NOT NULL,
 state varchar(20) NOT NULL DEFAULT 'pending',
 schedule_version integer NOT NULL,
 configuration jsonb NOT NULL,
 fence integer NOT NULL DEFAULT 0 CHECK (fence >= 0),
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
 available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz,
 diagnostic varchar(100), outcome jsonb NOT NULL DEFAULT '{}',
 discovery_run_id uuid REFERENCES public.discovery_runs(id),
 CONSTRAINT uq_automation_request_source UNIQUE (request_key, source),
 CONSTRAINT ck_automation_state CHECK (state IN ('pending','claimed','running','completed','partial','failed','blocked')),
 CONSTRAINT ck_automation_trigger CHECK (trigger_type IN ('manual','scheduled'))
);
CREATE INDEX ix_automation_executions_state ON public.automation_executions(state);
CREATE UNIQUE INDEX uq_automation_active_source ON public.automation_executions(source)
 WHERE state IN ('pending','claimed','running');
CREATE TABLE public.automation_matches (
 job_id uuid PRIMARY KEY REFERENCES public.jobs(id),
 profile_id uuid NOT NULL, profile_version integer NOT NULL CHECK (profile_version >= 1),
 evidence_hash varchar(64) NOT NULL, result jsonb NOT NULL,
 scored_at timestamptz NOT NULL DEFAULT now()
);
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['automation_schedule','automation_executions','automation_matches'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON public.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO service_role',table_name);
  END IF;
 END LOOP;
END;
$$;

CREATE TABLE public.agent_policies (key varchar(20) PRIMARY KEY, version integer NOT NULL CHECK(version>=1), preferences jsonb NOT NULL);
CREATE TABLE public.agent_policy_events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), version integer NOT NULL UNIQUE, preferences jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.agent_operations (key varchar(180) PRIMARY KEY, actor varchar(120) NOT NULL, command varchar(50) NOT NULL, payload_hash varchar(64) NOT NULL, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.agent_telegram_state (key varchar(20) PRIMARY KEY, next_update_id bigint NOT NULL DEFAULT 0, bot_id varchar(40), last_poll_at timestamptz, last_error varchar(80), evidence_type varchar(40) NOT NULL DEFAULT 'unverified');
CREATE TABLE public.agent_telegram_deliveries (update_id bigint PRIMARY KEY, reply text NOT NULL, state varchar(20) NOT NULL CHECK(state IN ('pending','sending','sent')));
ALTER TABLE public.agent_operations OWNER TO job_agent_owner;
ALTER TABLE public.agent_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_operations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_operations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.agent_operations TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.agent_operations FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.agent_policies OWNER TO job_agent_owner;
ALTER TABLE public.agent_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_policies FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_policies FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.agent_policies TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.agent_policies FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.agent_policy_events OWNER TO job_agent_owner;
ALTER TABLE public.agent_policy_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_policy_events FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_policy_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.agent_policy_events TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.agent_policy_events FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.agent_telegram_deliveries OWNER TO job_agent_owner;
ALTER TABLE public.agent_telegram_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_telegram_deliveries FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_telegram_deliveries FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.agent_telegram_deliveries TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.agent_telegram_deliveries FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.agent_telegram_state OWNER TO job_agent_owner;
ALTER TABLE public.agent_telegram_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_telegram_state FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_telegram_state FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.agent_telegram_state TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.agent_telegram_state FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.api_keys_pool OWNER TO job_agent_owner;
ALTER TABLE public.api_keys_pool ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys_pool FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.api_keys_pool FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.api_keys_pool TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.api_keys_pool FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.application_answer_drafts OWNER TO job_agent_owner;
ALTER TABLE public.application_answer_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_answer_drafts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.application_answer_drafts FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.application_answer_drafts TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.application_answer_drafts FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.application_events OWNER TO job_agent_owner;
ALTER TABLE public.application_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_events FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.application_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.application_events TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.application_events FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.application_packet_fields OWNER TO job_agent_owner;
ALTER TABLE public.application_packet_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_packet_fields FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.application_packet_fields FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.application_packet_fields TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.application_packet_fields FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.application_packets OWNER TO job_agent_owner;
ALTER TABLE public.application_packets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_packets FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.application_packets FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.application_packets TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.application_packets FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.application_submission_evidence OWNER TO job_agent_owner;
ALTER TABLE public.application_submission_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_submission_evidence FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.application_submission_evidence FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.application_submission_evidence TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.application_submission_evidence FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.automation_executions OWNER TO job_agent_owner;
ALTER TABLE public.automation_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_executions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.automation_executions FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.automation_executions TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.automation_executions FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.automation_matches OWNER TO job_agent_owner;
ALTER TABLE public.automation_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_matches FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.automation_matches FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.automation_matches TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.automation_matches FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.automation_schedule OWNER TO job_agent_owner;
ALTER TABLE public.automation_schedule ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_schedule FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.automation_schedule FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.automation_schedule TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.automation_schedule FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.candidate_evidence OWNER TO job_agent_owner;
ALTER TABLE public.candidate_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidate_evidence FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.candidate_evidence FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.candidate_evidence TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.candidate_evidence FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.candidate_profiles OWNER TO job_agent_owner;
ALTER TABLE public.candidate_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidate_profiles FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.candidate_profiles FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.candidate_profiles TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.candidate_profiles FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.candidate_resources OWNER TO job_agent_owner;
ALTER TABLE public.candidate_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidate_resources FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.candidate_resources FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.candidate_resources TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.candidate_resources FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.companies OWNER TO job_agent_owner;
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.companies FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.companies FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.companies TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.companies FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.company_source_observations OWNER TO job_agent_owner;
ALTER TABLE public.company_source_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_source_observations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.company_source_observations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.company_source_observations TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.company_source_observations FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.connected_accounts OWNER TO job_agent_owner;
ALTER TABLE public.connected_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.connected_accounts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.connected_accounts FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.connected_accounts TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.connected_accounts FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.contact_enrichment_runs OWNER TO job_agent_owner;
ALTER TABLE public.contact_enrichment_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contact_enrichment_runs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.contact_enrichment_runs FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.contact_enrichment_runs TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.contact_enrichment_runs FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.contact_evidence OWNER TO job_agent_owner;
ALTER TABLE public.contact_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contact_evidence FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.contact_evidence FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.contact_evidence TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.contact_evidence FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.contact_identities OWNER TO job_agent_owner;
ALTER TABLE public.contact_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contact_identities FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.contact_identities FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.contact_identities TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.contact_identities FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.contact_provider_lookups OWNER TO job_agent_owner;
ALTER TABLE public.contact_provider_lookups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contact_provider_lookups FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.contact_provider_lookups FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.contact_provider_lookups TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.contact_provider_lookups FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.contacts OWNER TO job_agent_owner;
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.contacts FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.contacts TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.contacts FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.discovered_company_people OWNER TO job_agent_owner;
ALTER TABLE public.discovered_company_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovered_company_people FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.discovered_company_people FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.discovered_company_people TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.discovered_company_people FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.discovery_budget_reservations OWNER TO job_agent_owner;
ALTER TABLE public.discovery_budget_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovery_budget_reservations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.discovery_budget_reservations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.discovery_budget_reservations TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.discovery_budget_reservations FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.discovery_monthly_budgets OWNER TO job_agent_owner;
ALTER TABLE public.discovery_monthly_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovery_monthly_budgets FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.discovery_monthly_budgets FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.discovery_monthly_budgets TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.discovery_monthly_budgets FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.discovery_runs OWNER TO job_agent_owner;
ALTER TABLE public.discovery_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovery_runs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.discovery_runs FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.discovery_runs TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.discovery_runs FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.drive_resume_versions OWNER TO job_agent_owner;
ALTER TABLE public.drive_resume_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.drive_resume_versions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.drive_resume_versions FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.drive_resume_versions TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.drive_resume_versions FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.job_source_observations OWNER TO job_agent_owner;
ALTER TABLE public.job_source_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_source_observations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.job_source_observations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.job_source_observations TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.job_source_observations FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.jobs OWNER TO job_agent_owner;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.jobs FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.jobs TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.jobs FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.llm_monthly_usage OWNER TO job_agent_owner;
ALTER TABLE public.llm_monthly_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.llm_monthly_usage FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.llm_monthly_usage FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.llm_monthly_usage TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.llm_monthly_usage FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.notification_deliveries OWNER TO job_agent_owner;
ALTER TABLE public.notification_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_deliveries FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.notification_deliveries FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.notification_deliveries TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.notification_deliveries FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.oauth_states OWNER TO job_agent_owner;
ALTER TABLE public.oauth_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_states FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.oauth_states FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.oauth_states TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.oauth_states FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.outreach_logs OWNER TO job_agent_owner;
ALTER TABLE public.outreach_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_logs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.outreach_logs FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.outreach_logs TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.outreach_logs FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.outreach_send_attempts OWNER TO job_agent_owner;
ALTER TABLE public.outreach_send_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_send_attempts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.outreach_send_attempts FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.outreach_send_attempts TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.outreach_send_attempts FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.outreach_send_confirmations OWNER TO job_agent_owner;
ALTER TABLE public.outreach_send_confirmations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_send_confirmations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.outreach_send_confirmations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.outreach_send_confirmations TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.outreach_send_confirmations FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.owner_notifications OWNER TO job_agent_owner;
ALTER TABLE public.owner_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.owner_notifications FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.owner_notifications FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.owner_notifications TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.owner_notifications FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.owner_preferences OWNER TO job_agent_owner;
ALTER TABLE public.owner_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.owner_preferences FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.owner_preferences FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.owner_preferences TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.owner_preferences FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.private_resumes OWNER TO job_agent_owner;
ALTER TABLE public.private_resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.private_resumes FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.private_resumes FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.private_resumes TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.private_resumes FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.provider_access_windows OWNER TO job_agent_owner;
ALTER TABLE public.provider_access_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_access_windows FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.provider_access_windows FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.provider_access_windows TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.provider_access_windows FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.provider_connection_checks OWNER TO job_agent_owner;
ALTER TABLE public.provider_connection_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_connection_checks FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.provider_connection_checks FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.provider_connection_checks TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.provider_connection_checks FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.provider_usage_logs OWNER TO job_agent_owner;
ALTER TABLE public.provider_usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_usage_logs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.provider_usage_logs FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.provider_usage_logs TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.provider_usage_logs FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.resume_drive_sources OWNER TO job_agent_owner;
ALTER TABLE public.resume_drive_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resume_drive_sources FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.resume_drive_sources FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.resume_drive_sources TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.resume_drive_sources FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.resume_profile_reviews OWNER TO job_agent_owner;
ALTER TABLE public.resume_profile_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resume_profile_reviews FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.resume_profile_reviews FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.resume_profile_reviews TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.resume_profile_reviews FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER TABLE public.startup_shortlist_entries OWNER TO job_agent_owner;
ALTER TABLE public.startup_shortlist_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.startup_shortlist_entries FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.startup_shortlist_entries FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.startup_shortlist_entries TO job_agent_runtime;
CREATE POLICY job_agent_backend ON public.startup_shortlist_entries FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
ALTER FUNCTION public.application_append_only() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.application_append_only() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.application_append_only() TO job_agent_runtime;
ALTER FUNCTION public.application_field_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.application_field_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.application_field_guard() TO job_agent_runtime;
ALTER FUNCTION public.application_history_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.application_history_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.application_history_guard() TO job_agent_runtime;
ALTER FUNCTION public.application_packet_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.application_packet_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.application_packet_guard() TO job_agent_runtime;
ALTER FUNCTION public.candidate_profile_version() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.candidate_profile_version() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.candidate_profile_version() TO job_agent_runtime;
ALTER FUNCTION public.company_snapshot_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.company_snapshot_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.company_snapshot_guard() TO job_agent_runtime;
ALTER FUNCTION public.phase2a_updated_at() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.phase2a_updated_at() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.phase2a_updated_at() TO job_agent_runtime;
ALTER FUNCTION public.phase4a_draft_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.phase4a_draft_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.phase4a_draft_guard() TO job_agent_runtime;
ALTER FUNCTION public.phase4b_attempt_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.phase4b_attempt_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.phase4b_attempt_guard() TO job_agent_runtime;
ALTER FUNCTION public.phase4b_confirmation_guard() OWNER TO job_agent_owner;
REVOKE ALL ON FUNCTION public.phase4b_confirmation_guard() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.phase4b_confirmation_guard() TO job_agent_runtime;
REVOKE CREATE ON SCHEMA public FROM job_agent_owner;
COMMIT;
