-- Additive local-reviewed scheduling foundation. Does not activate a worker.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
CREATE TABLE job_agent.automation_schedule (
 key varchar(20) PRIMARY KEY DEFAULT 'primary',
 enabled boolean NOT NULL DEFAULT false,
 version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
 configuration jsonb NOT NULL DEFAULT '{}',
 next_run_at timestamptz, last_run_at timestamptz, heartbeat_at timestamptz,
 CONSTRAINT ck_automation_primary CHECK (key = 'primary')
);
CREATE TABLE job_agent.automation_executions (
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
 discovery_run_id uuid REFERENCES job_agent.discovery_runs(id),
 CONSTRAINT uq_automation_request_source UNIQUE (request_key, source),
 CONSTRAINT ck_automation_state CHECK (state IN ('pending','claimed','running','completed','partial','failed','blocked')),
 CONSTRAINT ck_automation_trigger CHECK (trigger_type IN ('manual','scheduled'))
);
CREATE INDEX ix_automation_executions_state ON job_agent.automation_executions(state);
CREATE UNIQUE INDEX uq_automation_active_source ON job_agent.automation_executions(source)
 WHERE state IN ('pending','claimed','running');
CREATE TABLE job_agent.automation_matches (
 job_id uuid PRIMARY KEY REFERENCES job_agent.jobs(id),
 profile_id uuid NOT NULL, profile_version integer NOT NULL CHECK (profile_version >= 1),
 evidence_hash varchar(64) NOT NULL, result jsonb NOT NULL,
 scored_at timestamptz NOT NULL DEFAULT now()
);
DO $$
DECLARE table_name text; client_role text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['automation_schedule','automation_executions','automation_matches'] LOOP
  EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
    EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
   END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   EXECUTE format('GRANT SELECT,INSERT,UPDATE ON job_agent.%I TO service_role',table_name);
  END IF;
 END LOOP;
END;
$$;
COMMIT;
