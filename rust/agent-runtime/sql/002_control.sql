-- Explicit additive migration. No existing application policy, quota or history is modified.
CREATE TABLE rust_agent_control (
    key text PRIMARY KEY CHECK (key='primary'),
    mode text NOT NULL CHECK (mode IN ('STOPPED','PAUSED','RUNNING')),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
    heartbeat_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO rust_agent_control(key,mode)VALUES('primary','STOPPED');
CREATE TABLE rust_agent_control_events (
    revision bigint PRIMARY KEY CHECK (revision>0),
    mode text NOT NULL CHECK (mode IN ('STOPPED','PAUSED','RUNNING')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO rust_agent_control_events(revision,mode)VALUES(1,'STOPPED');
ALTER TABLE rust_agent_events ADD COLUMN decision_calls integer NOT NULL DEFAULT 0;
ALTER TABLE rust_agent_runs ADD COLUMN question_checked_at timestamptz;
CREATE INDEX rust_agent_question_scan ON rust_agent_runs(question_checked_at NULLS FIRST,created_at,id)
WHERE run->>'state'='waiting_owner';
ALTER TABLE rust_agent_control ENABLE ROW LEVEL SECURITY;
ALTER TABLE rust_agent_control_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rust_agent_control FROM PUBLIC;
REVOKE ALL ON rust_agent_control_events FROM PUBLIC;
DO $block$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
            EXECUTE format('REVOKE ALL ON rust_agent_control FROM %I',client_role);
            EXECUTE format('REVOKE ALL ON rust_agent_control_events FROM %I',client_role);
        END IF;
    END LOOP;
END
$block$;
