-- Phase 4A: additive backend-only foundation, after 001-005. Never applied at startup.
BEGIN;
CREATE TABLE IF NOT EXISTS job_agent.connected_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(30) NOT NULL CHECK(provider='gmail'),
    google_subject VARCHAR(255) NOT NULL,
    account_email VARCHAR(254) NOT NULL,
    encrypted_refresh_token TEXT,
    encrypted_access_token TEXT,
    encryption_key_id VARCHAR(64),
    granted_scopes JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(granted_scopes)='array'),
    status VARCHAR(30) NOT NULL DEFAULT 'disconnected'
        CHECK(status IN ('connected','disconnected','reauthorization_required')),
    token_generation INTEGER NOT NULL DEFAULT 1 CHECK(token_generation >= 1),
    token_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_verified_at TIMESTAMPTZ, last_refresh_at TIMESTAMPTZ, disconnected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_connected_provider UNIQUE(provider),
    CONSTRAINT ck_connected_credentials CHECK(status <> 'connected' OR
        (length(google_subject)>0 AND encrypted_refresh_token IS NOT NULL AND encryption_key_id IS NOT NULL)),
    CONSTRAINT ck_refresh_envelope CHECK(encrypted_refresh_token IS NULL OR
        encrypted_refresh_token ~ '^[A-Za-z0-9_-]{1,40}:[0-9a-f]{24}:gAAAA'),
    CONSTRAINT ck_access_envelope CHECK(encrypted_access_token IS NULL OR
        encrypted_access_token ~ '^[A-Za-z0-9_-]{1,40}:[0-9a-f]{24}:gAAAA')
);
CREATE TABLE IF NOT EXISTS job_agent.oauth_states (
    state_hash VARCHAR(64) PRIMARY KEY CHECK(state_hash ~ '^[0-9a-f]{64}$'),
    provider VARCHAR(30) NOT NULL DEFAULT 'gmail' CHECK(provider='gmail'),
    actor_id VARCHAR(64) NOT NULL CHECK(actor_id='owner'),
    browser_hash VARCHAR(64) NOT NULL CHECK(browser_hash ~ '^[0-9a-f]{64}$'),
    expected_email VARCHAR(254) NOT NULL,
    connection_generation INTEGER NOT NULL CHECK(connection_generation >= 1),
    encrypted_verifier TEXT,
    encryption_key_id VARCHAR(64) NOT NULL,
    redirect_uri VARCHAR(2048) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), consumed_at TIMESTAMPTZ,
    CHECK(expires_at > created_at AND expires_at <= created_at + interval '15 minutes')
);
CREATE INDEX IF NOT EXISTS idx_oauth_state_expiry ON job_agent.oauth_states(expires_at);
ALTER TABLE job_agent.outreach_logs
    ADD COLUMN IF NOT EXISTS connected_account_id UUID REFERENCES job_agent.connected_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS draft_revision INTEGER NOT NULL DEFAULT 1 CHECK(draft_revision >= 1),
    ADD COLUMN IF NOT EXISTS candidate_profile_version INTEGER,
    ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(254),
    ADD COLUMN IF NOT EXISTS evidence_snapshot JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS approval_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS approved_revision INTEGER,
    ADD COLUMN IF NOT EXISTS last_edited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) NOT NULL DEFAULT 'needs_review',
    ADD COLUMN IF NOT EXISTS generation_metadata JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS created_via VARCHAR(20) NOT NULL DEFAULT 'legacy'
        CHECK(created_via IN ('legacy','rest','mcp')),
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100),
    ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_idempotency ON job_agent.outreach_logs(idempotency_key);

-- Defense for direct backend writers: local drafts cannot fabricate provider delivery.
-- Historical sent rows are preserved byte-for-byte; no new send state is introduced.
CREATE OR REPLACE FUNCTION job_agent.phase4a_draft_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.approval_status = 'sent' OR NEW.sent_at IS NOT NULL OR
           NEW.gmail_draft_id IS NOT NULL OR NEW.gmail_message_id IS NOT NULL OR NEW.gmail_thread_id IS NOT NULL THEN
            RAISE EXCEPTION 'Phase 4A supports local drafts only';
        END IF;
    ELSE
        IF (NEW.sent_at,NEW.gmail_draft_id,NEW.gmail_message_id,NEW.gmail_thread_id) IS DISTINCT FROM
           (OLD.sent_at,OLD.gmail_draft_id,OLD.gmail_message_id,OLD.gmail_thread_id) OR
           (NEW.approval_status='sent' AND OLD.approval_status<>'sent') THEN
            RAISE EXCEPTION 'Phase 4A supports local drafts only';
        END IF;
        NEW.created_at := OLD.created_at;
        IF (to_jsonb(NEW)-ARRAY['draft_revision','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['draft_revision','updated_at']) THEN
            NEW.draft_revision := OLD.draft_revision+1;
            NEW.updated_at := clock_timestamp();
        ELSE
            NEW.draft_revision := OLD.draft_revision;
            NEW.updated_at := OLD.updated_at;
        END IF;
        IF (NEW.subject,NEW.body,NEW.recipient_email,NEW.evidence_hash,NEW.evidence_snapshot,NEW.contact_id,NEW.job_id,NEW.connected_account_id) IS DISTINCT FROM
           (OLD.subject,OLD.body,OLD.recipient_email,OLD.evidence_hash,OLD.evidence_snapshot,OLD.contact_id,OLD.job_id,OLD.connected_account_id) THEN
            NEW.approval_status := 'pending_approval'; NEW.approved_at := NULL;
            NEW.approval_hash := NULL; NEW.approved_revision := NULL;
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
CREATE OR REPLACE TRIGGER phase4a_draft_guard BEFORE INSERT OR UPDATE ON job_agent.outreach_logs
FOR EACH ROW EXECUTE FUNCTION job_agent.phase4a_draft_guard();

DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['connected_accounts','oauth_states','outreach_logs'] LOOP
        EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
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
