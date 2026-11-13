-- Fictional data only; the harness rejects every nonfixture database URL.
DROP TABLE IF EXISTS application_packets,jobs,companies,candidate_profiles,owner_preferences;
CREATE TABLE candidate_profiles (
    id uuid PRIMARY KEY,singleton_key text UNIQUE NOT NULL,version integer NOT NULL,
    verified_skills jsonb NOT NULL,verified_experience_years double precision,preferences jsonb NOT NULL,
    full_name text,email text,phone text
);
CREATE TABLE owner_preferences(key text PRIMARY KEY,value jsonb NOT NULL);
CREATE TABLE companies(id uuid PRIMARY KEY,name text NOT NULL,domain text,metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE jobs (
    id uuid PRIMARY KEY,company_id uuid,title text NOT NULL,job_url text NOT NULL,
    application_url text,source_platform text NOT NULL DEFAULT 'naukri',status text NOT NULL DEFAULT 'discovered',
    source_verification_status text NOT NULL DEFAULT 'observed',description text,
    skills_required text[] NOT NULL DEFAULT ARRAY['Rust']::text[],location text,
    is_remote boolean NOT NULL DEFAULT true,remote_type text DEFAULT 'remote',experience_level text DEFAULT 'junior',
    employment_type text,salary_min numeric(16,2),salary_max numeric(16,2),salary_currency text,salary_period text,
    date_posted timestamptz,discovery_metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00Z'
);
CREATE TABLE application_packets (
    id uuid PRIMARY KEY,job_id uuid NOT NULL,candidate_profile_id uuid NOT NULL,lifecycle_state text NOT NULL,
    readiness_state text NOT NULL DEFAULT 'needs_input',created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO candidate_profiles VALUES (
    '00000000-0000-0000-0000-000000000002','primary',4,'["Rust"]',0,
    '{"target_titles":["Rust Developer"],"remote_preference":"remote","current_compensation":{"amount":999,"currency":"INR","period":"year","kind":"ctc"}}',
    'Private Fictional Name','private-fictional@example.com','fictional-phone-value'
);
INSERT INTO owner_preferences VALUES ('phase1_profile_confirmation',
    '{"profile_id":"00000000-0000-0000-0000-000000000002","profile_version":4,"confirmed_at":"2026-11-14T00:00:00Z"}');
