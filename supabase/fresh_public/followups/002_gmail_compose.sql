-- Separate owner approval required. Preserve the applied 001 bundle and history.
-- Only extend the application OAuth intent discriminator for the existing compose flow.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
DO $$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
   JOIN pg_namespace n ON n.oid=t.relnamespace
   WHERE n.nspname='public' AND t.relname='oauth_states'
     AND pg_get_userbyid(t.relowner)='job_agent_owner'
     AND c.conname='oauth_states_authorization_mode_check' AND c.convalidated
     AND pg_get_constraintdef(c.oid)=$expected$CHECK (((authorization_mode)::text = ANY ((ARRAY['metadata'::character varying, 'send'::character varying])::text[])))$expected$
 ) THEN
   RAISE EXCEPTION 'reviewed_oauth_mode_constraint_required_no_reapply';
 END IF;
END $$;
ALTER TABLE public.oauth_states
 DROP CONSTRAINT oauth_states_authorization_mode_check,
 ADD CONSTRAINT oauth_states_authorization_mode_check
 CHECK (authorization_mode IN ('metadata','send','compose'));
COMMIT;
