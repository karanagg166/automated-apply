-- Phase 1: additive candidate persistence. Apply only after 001.
-- Never apply to shared production without explicit approval.
BEGIN;

CREATE TABLE IF NOT EXISTS job_agent.candidate_profiles (
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
CREATE OR REPLACE FUNCTION job_agent.candidate_profile_version() RETURNS trigger
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
BEFORE UPDATE ON job_agent.candidate_profiles
FOR EACH ROW EXECUTE FUNCTION job_agent.candidate_profile_version();

-- No client-side Supabase access. The backend connects as an owner/BYPASSRLS role.
ALTER TABLE job_agent.candidate_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON job_agent.candidate_profiles FROM PUBLIC;
DO $$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON job_agent.candidate_profiles FROM %I', client_role);
        END IF;
    END LOOP;
END;
$$;
COMMIT;
