-- PROPOSAL ONLY: jyzjgoniuwexvipbbpwa / postgres.
-- After backup/restore gates, 001-011, hardening, catalog checks and secure password provisioning.
-- Set the password using an authenticated administrative psql session's \password job_agent_runtime
-- prompt and save it only in the approved private backend secret store. No password in this file.
BEGIN;
ALTER ROLE job_agent_runtime LOGIN;
COMMIT;
