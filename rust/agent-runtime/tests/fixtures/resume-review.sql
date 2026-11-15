-- Fictional dedicated PostgreSQL fixture; production table shapes, no live grants.
DROP TABLE IF EXISTS drive_resume_versions;
CREATE TABLE resume_drive_sources (
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
CREATE TABLE drive_resume_versions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), file_id VARCHAR(200) NOT NULL,
 canonical_url VARCHAR(2048) NOT NULL, file_name VARCHAR(200) NOT NULL,
 source_modified_at TIMESTAMPTZ, source_etag VARCHAR(500), drive_revision VARCHAR(200),
 sha256 VARCHAR(64) NOT NULL, downloaded_at TIMESTAMPTZ NOT NULL,
 private_resume_id UUID UNIQUE NOT NULL REFERENCES private_resumes(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT uq_drive_resume_bytes UNIQUE(sha256)
);
CREATE TABLE resume_profile_reviews (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 version_id UUID UNIQUE NOT NULL REFERENCES drive_resume_versions(id),
 base_profile_version INTEGER, review_ciphertext BYTEA NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'pending',
 review_cycle INTEGER NOT NULL DEFAULT 1,
 approved_profile_version INTEGER, approved_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT ck_resume_review_status CHECK (status IN ('pending','approved'))
);

CREATE OR REPLACE FUNCTION fixture_resume_profile_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 NEW.created_at := OLD.created_at;
 IF (to_jsonb(NEW)-ARRAY['version','created_at','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','created_at','updated_at']) THEN
  NEW.version := OLD.version+1;NEW.updated_at := clock_timestamp();
 ELSE NEW.version:=OLD.version;NEW.updated_at:=OLD.updated_at;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fixture_resume_profile_version BEFORE UPDATE ON candidate_profiles FOR EACH ROW EXECUTE FUNCTION fixture_resume_profile_version();
