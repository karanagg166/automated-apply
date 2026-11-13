-- Apply explicitly to an owner-approved target only. The Rust process never auto-migrates.
-- This namespace is new: existing application/queue/receipt tables remain untouched.
CREATE TABLE rust_agent_runs (
    id uuid PRIMARY KEY,
    request_key uuid NOT NULL UNIQUE,
    owner text NOT NULL DEFAULT 'primary' CHECK (owner = 'primary'),
    run jsonb NOT NULL CHECK (jsonb_typeof(run) = 'object'),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    lease_token uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);
CREATE UNIQUE INDEX rust_agent_one_active_lease ON rust_agent_runs ((true)) WHERE lease_token IS NOT NULL;
CREATE INDEX rust_agent_runnable ON rust_agent_runs (created_at)
WHERE run->>'state' IN ('ready','model_running','tool_pending','tool_running');
CREATE TABLE rust_agent_events (
    run_id uuid NOT NULL REFERENCES rust_agent_runs(id),
    revision bigint NOT NULL,
    role text NOT NULL,
    state text NOT NULL,
    model_calls integer NOT NULL,
    tool_calls integer NOT NULL,
    reserved_tokens integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (run_id,revision)
);
-- Fail closed for Supabase/PostgREST clients. Backend role grants/policies require an
-- explicit target-specific deployment review; table owners/service roles may bypass RLS.
ALTER TABLE rust_agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rust_agent_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rust_agent_runs,rust_agent_events FROM PUBLIC;
DO $block$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
            EXECUTE format('REVOKE ALL ON rust_agent_runs,rust_agent_events FROM %I',client_role);
        END IF;
    END LOOP;
END
$block$;
