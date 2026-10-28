-- REVIEW ONLY. Requires separate owner approval; never run at application startup.
-- Stop all Gmail connect/sync workers before using this empty-install rollback.
-- Keep the baseline schema, legacy OAuth grants, tokens and preference rows intact.
-- For a populated installation use a verified backup/recovery plan instead.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(350035, 1);
-- FORCE RLS must not make a populated table look empty to its nonlogin owner.
DO $$
BEGIN
    IF NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user) THEN
        RAISE EXCEPTION 'gmail_rollback_requires_approved_maintenance_identity';
    END IF;
END $$;
LOCK TABLE job_agent.gmail_read_accounts, job_agent.gmail_read_oauth_states IN ACCESS EXCLUSIVE MODE;
LOCK TABLE job_agent.owner_preferences IN SHARE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT FROM job_agent.gmail_read_accounts)
       OR EXISTS (SELECT FROM job_agent.gmail_read_oauth_states)
       OR EXISTS (SELECT FROM job_agent.owner_preferences
                  WHERE key LIKE 'gmail_sync:%' OR key LIKE 'gmail_msg:%'
                     OR key LIKE 'gmail_workspace_slot:%' OR key LIKE 'gmail_drafts:%'
                     OR key LIKE 'gmail_draft_oauth:%' OR key LIKE 'gmail_outreach_draft:%'
                     OR key LIKE 'gmail_draft:%'
                     OR key LIKE 'gmail_application:%') THEN
        RAISE EXCEPTION 'gmail_rollback_requires_empty_install_and_no_evidence';
    END IF;
END $$;
DROP TABLE job_agent.gmail_read_oauth_states RESTRICT;
DROP TABLE job_agent.gmail_read_accounts RESTRICT;
COMMIT;
