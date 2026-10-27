-- REVIEW ONLY. No startup migration and no live DDL under this task.
-- This template uses job_agent for disposable tests. The approved live schema
-- is public; use the explicit schema renderer after owner migration approval.
BEGIN;
CREATE TABLE IF NOT EXISTS job_agent.gmail_read_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider varchar(30) NOT NULL DEFAULT 'gmail' CHECK (provider='gmail'),
    google_subject varchar(255) NOT NULL,
    account_email varchar(254) NOT NULL,
    encrypted_refresh_token text,
    encrypted_access_token text,
    encryption_key_id varchar(64),
    granted_scopes json NOT NULL DEFAULT '[]',
    status varchar(30) NOT NULL DEFAULT 'disconnected'
        CHECK (status IN ('connected','disconnected','reauthorization_required')),
    token_generation integer NOT NULL DEFAULT 1 CHECK (token_generation>0),
    token_expires_at timestamptz,
    connected_at timestamptz NOT NULL,
    last_verified_at timestamptz,
    last_refresh_at timestamptz,
    disconnected_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_gmail_read_email UNIQUE(provider,account_email),
    CONSTRAINT gmail_readonly_scopes CHECK (
        granted_scopes::jsonb <@ '["openid","https://www.googleapis.com/auth/userinfo.email","https://www.googleapis.com/auth/gmail.metadata","https://www.googleapis.com/auth/gmail.readonly"]'::jsonb
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_gmail_read_subject
    ON job_agent.gmail_read_accounts(provider,google_subject) WHERE google_subject<>'';
ALTER TABLE job_agent.gmail_read_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.gmail_read_accounts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON job_agent.gmail_read_accounts FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE job_agent.gmail_read_accounts OWNER TO job_agent_owner;
GRANT SELECT, INSERT, UPDATE ON job_agent.gmail_read_accounts TO job_agent_runtime;
DROP POLICY IF EXISTS job_agent_backend ON job_agent.gmail_read_accounts;
CREATE POLICY job_agent_backend ON job_agent.gmail_read_accounts FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
CREATE TABLE IF NOT EXISTS job_agent.gmail_read_oauth_states (
    state_hash varchar(64) PRIMARY KEY,
    provider varchar(30) NOT NULL DEFAULT 'gmail' CHECK (provider='gmail'),
    actor_id varchar(64) NOT NULL,
    browser_hash varchar(64) NOT NULL,
    expected_email varchar(254) NOT NULL,
    connection_generation integer NOT NULL,
    encrypted_verifier text,
    encryption_key_id varchar(64) NOT NULL,
    redirect_uri varchar(2048) NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    consumed_at timestamptz,
    authorization_mode varchar(20) NOT NULL CHECK (authorization_mode IN ('read_metadata','read_body')),
    expected_subject varchar(255)
);
CREATE INDEX IF NOT EXISTS ix_gmail_read_oauth_states_expires_at ON job_agent.gmail_read_oauth_states(expires_at);
ALTER TABLE job_agent.gmail_read_oauth_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.gmail_read_oauth_states FORCE ROW LEVEL SECURITY;
REVOKE ALL ON job_agent.gmail_read_oauth_states FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE job_agent.gmail_read_oauth_states OWNER TO job_agent_owner;
GRANT SELECT, INSERT, UPDATE ON job_agent.gmail_read_oauth_states TO job_agent_runtime;
DROP POLICY IF EXISTS job_agent_backend ON job_agent.gmail_read_oauth_states;
CREATE POLICY job_agent_backend ON job_agent.gmail_read_oauth_states FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
COMMIT;
