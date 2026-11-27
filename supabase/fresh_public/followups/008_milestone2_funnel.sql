-- Python v2 followup 008 (Milestone 2): post-apply mail funnel reconciliation.
--   * public.mail_events.kind widens from RECRUITER_REPLY | INTERVIEW | JOB_ALERT to also accept
--     CONFIRMATION (application receipt mail), OA_INVITE (online assessment) and REJECTED, so the
--     worker's read-only funnel reconciler can link those mails to an application.
--   * ix_mail_events_application: the proof receipt lists the mails linked to one application.
--
-- Requires followups 004 + 005. Additive and idempotent: the CHECK only ever widens (every row
-- valid before stays valid), no table, column or row is dropped. Ownership/ACL of mail_events is
-- unchanged (004). Never stores OTP codes, security codes or message bodies (snippet stays <= 500).

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $kinds$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.mail_events'::regclass AND conname = 'mail_events_kind_check'
          AND pg_get_constraintdef(oid) LIKE '%OA_INVITE%'
    ) THEN
        ALTER TABLE public.mail_events DROP CONSTRAINT IF EXISTS mail_events_kind_check;
        ALTER TABLE public.mail_events ADD CONSTRAINT mail_events_kind_check CHECK (
            kind IN ('RECRUITER_REPLY','INTERVIEW','JOB_ALERT','CONFIRMATION','OA_INVITE','REJECTED'));
    END IF;
END
$kinds$;

CREATE INDEX IF NOT EXISTS ix_mail_events_application
    ON public.mail_events (application_id, received_at) WHERE application_id IS NOT NULL;

COMMIT;
