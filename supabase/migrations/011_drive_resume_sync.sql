-- Additive owner-only resume checks and explicit review. Never run at API startup.
BEGIN;
CREATE TABLE job_agent.resume_drive_sources (
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
CREATE TABLE job_agent.drive_resume_versions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), file_id VARCHAR(200) NOT NULL,
 canonical_url VARCHAR(2048) NOT NULL, file_name VARCHAR(200) NOT NULL,
 source_modified_at TIMESTAMPTZ, source_etag VARCHAR(500), drive_revision VARCHAR(200),
 sha256 VARCHAR(64) NOT NULL, downloaded_at TIMESTAMPTZ NOT NULL,
 private_resume_id UUID UNIQUE NOT NULL REFERENCES job_agent.private_resumes(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT uq_drive_resume_bytes UNIQUE(sha256)
);
CREATE TABLE job_agent.resume_profile_reviews (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 version_id UUID UNIQUE NOT NULL REFERENCES job_agent.drive_resume_versions(id),
 base_profile_version INTEGER, review_ciphertext BYTEA NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'pending',
 review_cycle INTEGER NOT NULL DEFAULT 1,
 approved_profile_version INTEGER, approved_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT ck_resume_review_status CHECK (status IN ('pending','approved'))
);
-- This relationship makes a resume-only approval a material profile change, using
-- the existing version trigger. Existing profile facts and old packets are preserved.
ALTER TABLE job_agent.candidate_profiles ADD COLUMN active_resume_version_id UUID;
-- Phase 7 introduced private resources in application code. Extend the original
-- PostgreSQL HTTPS-only constraints narrowly, so private PDF approval works there too.
ALTER TABLE job_agent.candidate_resources DROP CONSTRAINT candidate_resources_source_type_check;
ALTER TABLE job_agent.candidate_resources DROP CONSTRAINT candidate_resources_url_check;
ALTER TABLE job_agent.candidate_resources ADD CONSTRAINT candidate_resources_source_type_check
 CHECK (source_type IN ('user','environment_import','private_upload'));
ALTER TABLE job_agent.candidate_resources ADD CONSTRAINT candidate_resources_url_check CHECK (
 (source_type IN ('user','environment_import') AND url ~ '^https://[^/@[:space:]]+([/?#]|$)' AND url !~ '^https://[^/?#]*@')
 OR (source_type = 'private_upload' AND resource_type = 'resume'
     AND url ~ '^private-resume:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
);
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['resume_drive_sources','drive_resume_versions','resume_profile_reviews'] LOOP
  EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON job_agent.%I TO service_role',table_name);
  END IF;
 END LOOP;
END;
$$;
COMMIT;
