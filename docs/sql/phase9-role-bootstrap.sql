-- PROPOSAL ONLY: jyzjgoniuwexvipbbpwa / postgres. Owner approval and recovery gates required.
-- Operational role provisioning; not a historical schema migration.
-- Preconditions: job_agent and both role names absent; authenticated admin;
-- verified recovery artifact/rehearsal and approved bounded maintenance window.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
CREATE ROLE job_agent_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE job_agent_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3;
GRANT job_agent_owner TO postgres;
CREATE SCHEMA job_agent AUTHORIZATION job_agent_owner;
REVOKE ALL ON SCHEMA job_agent FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE job_agent_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER ROLE job_agent_runtime SET search_path = pg_catalog, job_agent;
ALTER ROLE job_agent_runtime SET statement_timeout = '30s';
ALTER ROLE job_agent_runtime SET lock_timeout = '2s';
ALTER ROLE job_agent_runtime SET idle_in_transaction_session_timeout = '30s';
COMMIT;
-- Keep runtime NOLOGIN until approved private password provisioning. Never put a password here.
