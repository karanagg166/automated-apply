-- Phase 2A: additive only. Apply after 001 and 002; no production execution without approval.
BEGIN;
CREATE TABLE IF NOT EXISTS job_agent.candidate_resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_profile_id UUID NOT NULL REFERENCES job_agent.candidate_profiles(id) ON DELETE CASCADE,
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
ON job_agent.candidate_resources(candidate_profile_id, resource_type) WHERE is_primary;

CREATE TABLE IF NOT EXISTS job_agent.candidate_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_profile_id UUID NOT NULL REFERENCES job_agent.candidate_profiles(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS ix_candidate_evidence_candidate_profile_id ON job_agent.candidate_evidence(candidate_profile_id);

CREATE TABLE IF NOT EXISTS job_agent.application_answer_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_profile_id UUID NOT NULL REFERENCES job_agent.candidate_profiles(id) ON DELETE CASCADE,
    job_id UUID REFERENCES job_agent.jobs(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS ix_application_answer_drafts_candidate_profile_id ON job_agent.application_answer_drafts(candidate_profile_id);

CREATE TABLE IF NOT EXISTS job_agent.llm_monthly_usage (
    provider VARCHAR(30) NOT NULL CHECK (provider = 'gemini'),
    month VARCHAR(7) NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(provider, month)
);

CREATE OR REPLACE FUNCTION job_agent.phase2a_updated_at() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN NEW.updated_at := clock_timestamp(); RETURN NEW; END;
$$;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['candidate_resources','candidate_evidence','application_answer_drafts','llm_monthly_usage'] LOOP
        EXECUTE format('CREATE OR REPLACE TRIGGER phase2a_updated_at BEFORE UPDATE ON job_agent.%I FOR EACH ROW EXECUTE FUNCTION job_agent.phase2a_updated_at()', table_name);
        EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC', table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
                EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I', table_name, client_role);
            END IF;
        END LOOP;
    END LOOP;
END;
$$;
COMMIT;
