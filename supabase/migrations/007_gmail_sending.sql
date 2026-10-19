-- Phase 4B: backend-only consent and one permanent send reservation per draft.
-- Additive, replayable; no production/startup application hook. Never edits migration 006.
BEGIN;
ALTER TABLE job_agent.oauth_states
    ADD COLUMN IF NOT EXISTS authorization_mode VARCHAR(20) NOT NULL DEFAULT 'metadata'
        CHECK(authorization_mode IN ('metadata','send')),
    ADD COLUMN IF NOT EXISTS expected_subject VARCHAR(255);

CREATE TABLE IF NOT EXISTS job_agent.outreach_send_confirmations (
    token_hash VARCHAR(64) PRIMARY KEY CHECK(token_hash ~ '^[a-f0-9]{64}$'),
    draft_id UUID NOT NULL REFERENCES job_agent.outreach_logs(id),
    connected_account_id UUID NOT NULL REFERENCES job_agent.connected_accounts(id),
    actor_id VARCHAR(64) NOT NULL CHECK(actor_id='owner'),
    draft_revision INTEGER NOT NULL CHECK(draft_revision>=1),
    approval_hash VARCHAR(64) NOT NULL CHECK(approval_hash ~ '^[a-f0-9]{64}$'),
    recipient_email VARCHAR(254) NOT NULL,
    sender_email VARCHAR(254) NOT NULL,
    sender_binding VARCHAR(64) NOT NULL CHECK(sender_binding ~ '^[a-f0-9]{64}$'),
    content_digest VARCHAR(64) NOT NULL CHECK(content_digest ~ '^[a-f0-9]{64}$'),
    evidence_digest VARCHAR(64) NOT NULL CHECK(evidence_digest ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CHECK(expires_at > created_at AND expires_at <= created_at + interval '10 minutes')
);
CREATE INDEX IF NOT EXISTS idx_send_confirmation_expiry ON job_agent.outreach_send_confirmations(expires_at);
CREATE TABLE IF NOT EXISTS job_agent.outreach_send_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL UNIQUE REFERENCES job_agent.outreach_logs(id),
    connected_account_id UUID NOT NULL REFERENCES job_agent.connected_accounts(id),
    confirmation_hash VARCHAR(64) NOT NULL UNIQUE REFERENCES job_agent.outreach_send_confirmations(token_hash),
    actor_id VARCHAR(64) NOT NULL CHECK(actor_id='owner'),
    draft_revision INTEGER NOT NULL CHECK(draft_revision>=1),
    approval_hash VARCHAR(64) NOT NULL CHECK(approval_hash ~ '^[a-f0-9]{64}$'),
    recipient_email VARCHAR(254) NOT NULL,
    sender_email VARCHAR(254) NOT NULL,
    sender_binding VARCHAR(64) NOT NULL CHECK(sender_binding ~ '^[a-f0-9]{64}$'),
    subject TEXT NOT NULL, body TEXT NOT NULL,
    content_digest VARCHAR(64) NOT NULL CHECK(content_digest ~ '^[a-f0-9]{64}$'),
    evidence_digest VARCHAR(64) NOT NULL CHECK(evidence_digest ~ '^[a-f0-9]{64}$'),
    rfc_message_id VARCHAR(255) NOT NULL UNIQUE CHECK(rfc_message_id = '<outreach.' || replace(id::text,'-','') || '@automated-apply.invalid>'),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
    request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    status VARCHAR(30) NOT NULL DEFAULT 'prepared' CHECK(status IN
        ('prepared','attempting','accepted_by_gmail','failed_before_send','outcome_unknown','manually_reconciled')),
    gmail_message_id VARCHAR(255), gmail_thread_id VARCHAR(255),
    attempted_at TIMESTAMPTZ, accepted_at TIMESTAMPTZ,
    failure_category VARCHAR(64) CHECK(failure_category IS NULL OR failure_category IN
        ('connection_failed_before_send','transmission_outcome_unknown','invalid_gmail_response',
         'malformed_request','credential_rejected','scope_or_policy_denied','gmail_resource_missing',
         'gmail_quota_exceeded','gmail_server_or_unexpected_response','context_changed_before_transmission',
         'interrupted_attempt_requires_review')),
    reconciliation_required BOOLEAN NOT NULL DEFAULT false,
    reconciled_at TIMESTAMPTZ, reconciled_by VARCHAR(64), reconciliation_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK(gmail_message_id IS NULL OR gmail_message_id ~ '^[A-Za-z0-9_-]{1,255}$'),
    CHECK(gmail_thread_id IS NULL OR gmail_thread_id ~ '^[A-Za-z0-9_-]{1,255}$'),
    CHECK((status='accepted_by_gmail' AND gmail_message_id IS NOT NULL AND accepted_at IS NOT NULL AND attempted_at IS NOT NULL)
        OR status<>'accepted_by_gmail'),
    CHECK((gmail_message_id IS NULL AND gmail_thread_id IS NULL AND accepted_at IS NULL)
        OR status IN ('accepted_by_gmail','manually_reconciled')),
    CHECK(status NOT IN ('attempting','outcome_unknown') OR (attempted_at IS NOT NULL AND reconciliation_required)),
    CHECK(status NOT IN ('accepted_by_gmail','failed_before_send','manually_reconciled') OR NOT reconciliation_required),
    CHECK(status <> 'manually_reconciled' OR
        (reconciled_by='owner' AND reconciled_at IS NOT NULL AND length(reconciliation_note)>=20)),
    CHECK(accepted_at IS NULL OR gmail_message_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_outreach_send_created ON job_agent.outreach_send_attempts(created_at);

CREATE OR REPLACE FUNCTION job_agent.phase4b_confirmation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Send confirmations are audit records'; END IF;
    IF TG_OP='UPDATE' THEN
        IF OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL OR OLD.expires_at<=clock_timestamp()
           OR (to_jsonb(NEW)-'consumed_at') IS DISTINCT FROM (to_jsonb(OLD)-'consumed_at') THEN
            RAISE EXCEPTION 'Confirmation is immutable and single use';
        END IF;
    ELSIF NEW.consumed_at IS NOT NULL OR NOT EXISTS (
        SELECT 1 FROM job_agent.outreach_logs d JOIN job_agent.connected_accounts a ON a.id=NEW.connected_account_id
        WHERE d.id=NEW.draft_id AND d.approval_status='approved' AND d.draft_revision=NEW.draft_revision
          AND d.approved_revision=d.draft_revision AND d.approval_hash=NEW.approval_hash
          AND d.evidence_hash=NEW.evidence_digest AND d.recipient_email=NEW.recipient_email
          AND a.status='connected' AND a.account_email=NEW.sender_email
          AND a.granted_scopes ? 'https://www.googleapis.com/auth/gmail.send'
    ) THEN RAISE EXCEPTION 'Confirmation requires current approved context';
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER phase4b_confirmation_guard BEFORE INSERT OR UPDATE OR DELETE ON job_agent.outreach_send_confirmations
FOR EACH ROW EXECUTE FUNCTION job_agent.phase4b_confirmation_guard();

CREATE OR REPLACE FUNCTION job_agent.phase4b_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Send attempts are permanent audit records'; END IF;
    IF TG_OP='INSERT' THEN
        IF NEW.status<>'prepared' OR NEW.attempted_at IS NOT NULL OR NEW.gmail_message_id IS NOT NULL OR
           NEW.gmail_thread_id IS NOT NULL OR NEW.accepted_at IS NOT NULL OR NOT EXISTS (
            SELECT 1 FROM job_agent.outreach_send_confirmations c
            JOIN job_agent.outreach_logs d ON d.id=c.draft_id
            JOIN job_agent.connected_accounts a ON a.id=c.connected_account_id
            JOIN job_agent.contacts t ON t.id=d.contact_id
            WHERE c.token_hash=NEW.confirmation_hash AND c.consumed_at IS NOT NULL AND c.expires_at>clock_timestamp()
            AND (c.draft_id,c.connected_account_id,c.actor_id,c.draft_revision,c.approval_hash,c.recipient_email,c.sender_email,c.sender_binding,c.content_digest,c.evidence_digest)
              = (NEW.draft_id,NEW.connected_account_id,NEW.actor_id,NEW.draft_revision,NEW.approval_hash,NEW.recipient_email,NEW.sender_email,NEW.sender_binding,NEW.content_digest,NEW.evidence_digest)
            AND d.approval_status='approved' AND d.draft_revision=NEW.draft_revision AND d.approved_revision=d.draft_revision
            AND d.approval_hash=NEW.approval_hash AND d.evidence_hash=NEW.evidence_digest
            AND d.subject=NEW.subject AND d.body=NEW.body AND d.recipient_email=NEW.recipient_email
            AND d.sent_at IS NULL AND d.gmail_message_id IS NULL
            AND a.status='connected' AND a.account_email=NEW.sender_email AND a.granted_scopes ? 'https://www.googleapis.com/auth/gmail.send'
            AND NOT t.do_not_contact AND t.email_status='verified' AND t.email=NEW.recipient_email
        ) THEN RAISE EXCEPTION 'Send reservation requires consumed exact consent and current approval'; END IF;
    ELSE
        IF (to_jsonb(NEW)-ARRAY['status','gmail_message_id','gmail_thread_id','attempted_at','accepted_at','failure_category','reconciliation_required','updated_at','reconciled_at','reconciled_by','reconciliation_note']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['status','gmail_message_id','gmail_thread_id','attempted_at','accepted_at','failure_category','reconciliation_required','updated_at','reconciled_at','reconciled_by','reconciliation_note']) THEN
            RAISE EXCEPTION 'Send attempt identity is immutable';
        END IF;
        IF NOT ((OLD.status='prepared' AND NEW.status IN ('attempting','failed_before_send')) OR
                (OLD.status='attempting' AND NEW.status IN ('accepted_by_gmail','outcome_unknown','failed_before_send')) OR
                (OLD.status IN ('outcome_unknown','failed_before_send') AND NEW.status='manually_reconciled')) THEN
            RAISE EXCEPTION 'Illegal send transition; retries are forbidden';
        END IF;
        IF OLD.attempted_at IS NOT NULL AND NEW.attempted_at IS DISTINCT FROM OLD.attempted_at THEN
            RAISE EXCEPTION 'Attempt initiation is immutable';
        END IF;
        IF NEW.status<>'manually_reconciled' AND
           (NEW.reconciled_at IS NOT NULL OR NEW.reconciled_by IS NOT NULL OR NEW.reconciliation_note IS NOT NULL) THEN
            RAISE EXCEPTION 'Reconciliation requires explicit audited disposition';
        END IF;
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER phase4b_attempt_guard BEFORE INSERT OR UPDATE OR DELETE ON job_agent.outreach_send_attempts
FOR EACH ROW EXECUTE FUNCTION job_agent.phase4b_attempt_guard();

-- Supersede 006 in place. Keep its material edit invalidation and approval/revision checks.
-- Delivery metadata is permitted only when backed by a matching accepted, immutable attempt.
CREATE OR REPLACE FUNCTION job_agent.phase4a_draft_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.approval_status='sent' OR NEW.sent_at IS NOT NULL OR NEW.gmail_draft_id IS NOT NULL OR
           NEW.gmail_message_id IS NOT NULL OR NEW.gmail_thread_id IS NOT NULL THEN
            RAISE EXCEPTION 'New drafts cannot fabricate send history';
        END IF;
    ELSE
        NEW.created_at := OLD.created_at;
        IF NEW.gmail_draft_id IS DISTINCT FROM OLD.gmail_draft_id THEN RAISE EXCEPTION 'Gmail drafts are unsupported'; END IF;
        IF (NEW.sent_at,NEW.gmail_message_id,NEW.gmail_thread_id) IS DISTINCT FROM
           (OLD.sent_at,OLD.gmail_message_id,OLD.gmail_thread_id) OR (NEW.approval_status='sent' AND OLD.approval_status<>'sent') THEN
            IF NEW.approval_status='sent' OR NOT EXISTS (
                SELECT 1 FROM job_agent.outreach_send_attempts s WHERE s.draft_id=OLD.id AND s.status='accepted_by_gmail'
                AND (s.gmail_message_id,s.gmail_thread_id,s.accepted_at,s.draft_revision,s.subject,s.body,s.recipient_email)
                IS NOT DISTINCT FROM (NEW.gmail_message_id,NEW.gmail_thread_id,NEW.sent_at,OLD.draft_revision,NEW.subject,NEW.body,NEW.recipient_email)
            ) THEN RAISE EXCEPTION 'Delivery fields require a valid accepted send attempt'; END IF;
        END IF;
        IF (to_jsonb(NEW)-ARRAY['draft_revision','updated_at','gmail_message_id','gmail_thread_id','sent_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['draft_revision','updated_at','gmail_message_id','gmail_thread_id','sent_at']) THEN
            NEW.draft_revision := OLD.draft_revision+1; NEW.updated_at := clock_timestamp();
        ELSE NEW.draft_revision := OLD.draft_revision; NEW.updated_at := OLD.updated_at;
        END IF;
        IF (NEW.subject,NEW.body,NEW.recipient_email,NEW.evidence_hash,NEW.evidence_snapshot,NEW.contact_id,NEW.job_id,NEW.connected_account_id) IS DISTINCT FROM
           (OLD.subject,OLD.body,OLD.recipient_email,OLD.evidence_hash,OLD.evidence_snapshot,OLD.contact_id,OLD.job_id,OLD.connected_account_id) THEN
            NEW.approval_status := 'pending_approval'; NEW.approved_at := NULL; NEW.approval_hash := NULL; NEW.approved_revision := NULL;
            NEW.last_edited_at := clock_timestamp(); NEW.validation_status := 'requires_review';
        END IF;
    END IF;
    IF NEW.approval_status='approved' AND
       (NEW.approval_hash IS NULL OR NEW.approved_revision IS DISTINCT FROM NEW.draft_revision OR NEW.approved_at IS NULL) THEN
        RAISE EXCEPTION 'Approval must identify the current draft revision';
    END IF;
    RETURN NEW;
END;
$$;
DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['outreach_send_confirmations','outreach_send_attempts'] LOOP
        EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('REVOKE ALL ON job_agent.%I FROM service_role',table_name);
            EXECUTE format('GRANT SELECT,INSERT,UPDATE ON job_agent.%I TO service_role',table_name);
        END IF;
    END LOOP;
END;
$$;
COMMIT;
