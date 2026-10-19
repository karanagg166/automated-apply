-- Additive owner-only data. Apply only to an explicitly authorized target.
BEGIN;
CREATE TABLE IF NOT EXISTS job_agent.private_resumes (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), label VARCHAR(200) NOT NULL,
 ciphertext BYTEA NOT NULL, sha256 VARCHAR(64) NOT NULL,
 confirmed BOOLEAN NOT NULL DEFAULT false, resource_id UUID,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS job_agent.owner_notifications (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), dedup_key VARCHAR(200) UNIQUE NOT NULL,
 kind VARCHAR(50) NOT NULL, title VARCHAR(200) NOT NULL, body TEXT NOT NULL,
 href VARCHAR(200) NOT NULL, read_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS job_agent.owner_preferences (
 key VARCHAR(50) PRIMARY KEY, value JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS job_agent.notification_deliveries (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 notification_id UUID NOT NULL REFERENCES job_agent.owner_notifications(id) ON DELETE CASCADE,
 channel VARCHAR(30) NOT NULL, status VARCHAR(40) NOT NULL,
 attempt_count INTEGER NOT NULL DEFAULT 0, last_error VARCHAR(100), next_attempt_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT uq_notification_channel UNIQUE(notification_id,channel)
);
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['private_resumes','owner_notifications','owner_preferences','notification_deliveries'] LOOP
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
