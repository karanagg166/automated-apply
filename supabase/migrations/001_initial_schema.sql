-- ==============================================================================
-- Migration: 001_initial_schema.sql
-- Project: Job Pulse Agent (job-pulse-agent)
-- Purpose: Create isolated 'job_agent' schema and core tables with strict constraints.
-- Note: Does NOT modify, drop, or alter any objects in the 'public' or other schemas.
-- ==============================================================================

-- 1. Create dedicated schema
CREATE SCHEMA IF NOT EXISTS job_agent;

-- 2. Companies table
CREATE TABLE IF NOT EXISTS job_agent.companies (
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

CREATE INDEX IF NOT EXISTS idx_companies_domain ON job_agent.companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_name ON job_agent.companies(name);

-- 3. Jobs table
CREATE TABLE IF NOT EXISTS job_agent.jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES job_agent.companies(id) ON DELETE SET NULL,
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

CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON job_agent.jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON job_agent.jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_match_score ON job_agent.jobs(match_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON job_agent.jobs(created_at DESC);

-- 4. Contacts table
CREATE TABLE IF NOT EXISTS job_agent.contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES job_agent.companies(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON job_agent.contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON job_agent.contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_role_title ON job_agent.contacts(role_title);
CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_company_email 
    ON job_agent.contacts(company_id, email) 
    WHERE email IS NOT NULL;

-- 5. API keys pool (Cost-first credit management)
CREATE TABLE IF NOT EXISTS job_agent.api_keys_pool (
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

CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON job_agent.api_keys_pool(provider, is_active);

-- 6. Provider usage logs (Audit trail of every credit spent)
CREATE TABLE IF NOT EXISTS job_agent.provider_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(50) NOT NULL,
    endpoint VARCHAR(255),
    credits_consumed INT NOT NULL DEFAULT 0,
    status_code INT,
    is_success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provider_usage_provider_date ON job_agent.provider_usage_logs(provider, created_at DESC);

-- 7. Outreach logs (Strict Human-in-the-Loop state machine)
CREATE TABLE IF NOT EXISTS job_agent.outreach_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES job_agent.jobs(id) ON DELETE SET NULL,
    contact_id UUID REFERENCES job_agent.contacts(id) ON DELETE SET NULL,
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

CREATE INDEX IF NOT EXISTS idx_outreach_job_id ON job_agent.outreach_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_outreach_contact_id ON job_agent.outreach_logs(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_approval_status ON job_agent.outreach_logs(approval_status);
