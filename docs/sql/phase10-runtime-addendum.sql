-- SEPARATE UNAPPROVED PROPOSAL: apply only after migration 012 and the pinned
-- Phase 9 runtime overlay. Requires new review/authorization; no activation.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
DO $$
DECLARE table_name text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['automation_schedule','automation_executions','automation_matches'] LOOP
  EXECUTE format('ALTER TABLE job_agent.%I OWNER TO job_agent_owner',table_name);
  EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('ALTER TABLE job_agent.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC, anon, authenticated, service_role',table_name);
  EXECUTE format('GRANT SELECT, INSERT, UPDATE ON job_agent.%I TO job_agent_runtime',table_name);
  EXECUTE format('CREATE POLICY job_agent_backend ON job_agent.%I FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true)',table_name);
 END LOOP;
END;
$$;
COMMIT;
